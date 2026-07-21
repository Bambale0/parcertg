from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.database import Database
from app.dedup import fingerprint
from app.models import Lead, LeadSource
from app.scoring import ScoreResult, score_message

logger = structlog.get_logger(__name__)

_PROVIDER_LABELS = {
    "manual": "Ручной импорт",
    "telemetr": "Telemetr",
    "tgstat": "TGStat",
    "telethon": "Telegram",
}


@dataclass(frozen=True, slots=True)
class IncomingLead:
    text: str
    provider: str
    source_id: str
    source_title: str
    message_id: str
    message_url: str | None = None
    published_at: datetime | None = None
    source_username: str | None = None
    sender_id: int | None = None
    sender_username: str | None = None
    sender_name: str | None = None


class ProcessingStatus(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    BELOW_THRESHOLD = "below_threshold"


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    status: ProcessingStatus
    score: ScoreResult
    lead: Lead | None = None


def _stable_integer(*parts: str, bits: int) -> int:
    raw = "\x1f".join(parts).encode("utf-8", errors="replace")
    digest = hashlib.sha256(raw).digest()
    value = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return value & ((1 << bits) - 1)


def _source_title(provider: str, title: str) -> str:
    provider_label = _PROVIDER_LABELS.get(provider.casefold(), provider)
    clean_title = title.strip() or "Неизвестный источник"
    return f"{provider_label} · {clean_title}"[:255]


class LeadProcessor:
    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.database = database

    async def process(self, incoming: IncomingLead) -> ProcessingResult:
        score = score_message(incoming.text)
        if score.score < self.settings.min_lead_score:
            return ProcessingResult(
                status=ProcessingStatus.BELOW_THRESHOLD,
                score=score,
            )

        provider = incoming.provider.casefold().strip() or "manual"
        source = LeadSource(
            chat_id=_stable_integer(provider, incoming.source_id, bits=63),
            chat_title=_source_title(provider, incoming.source_title),
            chat_username=(incoming.source_username or "").removeprefix("@") or None,
            message_id=_stable_integer(
                provider,
                incoming.source_id,
                incoming.message_id,
                bits=31,
            ),
            message_url=incoming.message_url,
            published_at=incoming.published_at or datetime.now(UTC),
        )
        message_fingerprint = fingerprint(score.normalized_text)
        duplicate = await self.database.find_duplicate(
            fingerprint=message_fingerprint,
            normalized_text=score.normalized_text,
            window_hours=self.settings.dedup_window_hours,
            minimum_similarity=self.settings.dedup_similarity,
        )
        if duplicate is not None:
            try:
                added = await self.database.add_source(duplicate.id, source)
            except IntegrityError:
                added = False
            logger.info(
                "lead_duplicate",
                lead_id=duplicate.id,
                provider=provider,
                source_added=added,
            )
            return ProcessingResult(
                status=ProcessingStatus.DUPLICATE,
                score=score,
                lead=duplicate,
            )

        lead = Lead(
            fingerprint=message_fingerprint,
            normalized_text=score.normalized_text,
            original_text=incoming.text,
            score=score.score,
            reasons="\n".join(score.reasons),
            sender_id=incoming.sender_id,
            sender_username=incoming.sender_username,
            sender_name=incoming.sender_name,
        )
        try:
            lead = await self.database.create_lead(lead, source)
        except IntegrityError:
            duplicate = await self.database.find_duplicate(
                fingerprint=message_fingerprint,
                normalized_text=score.normalized_text,
                window_hours=self.settings.dedup_window_hours,
                minimum_similarity=self.settings.dedup_similarity,
            )
            return ProcessingResult(
                status=ProcessingStatus.DUPLICATE,
                score=score,
                lead=duplicate,
            )

        logger.info(
            "lead_accepted",
            lead_id=lead.id,
            provider=provider,
            score=lead.score,
        )
        return ProcessingResult(
            status=ProcessingStatus.ACCEPTED,
            score=score,
            lead=lead,
        )
