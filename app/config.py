from __future__ import annotations

from functools import cached_property
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    telegram_api_id: int
    telegram_api_hash: str
    telegram_session: str
    bot_token: str
    admin_ids: str
    notify_chat_id: int | None = None

    # Sources from the file are loaded first. CHAT_SOURCES can append custom values.
    chat_sources_file: Path | None = Path("config/sources.txt")
    chat_sources: str = ""

    database_url: str = "sqlite+aiosqlite:///./parcertg.db"
    min_lead_score: int = Field(default=65, ge=0, le=100)
    dedup_window_hours: int = Field(default=48, ge=1, le=720)
    dedup_similarity: int = Field(default=92, ge=50, le=100)
    log_level: str = "INFO"

    @field_validator("telegram_api_hash", "telegram_session", "bot_token", "admin_ids")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @cached_property
    def parsed_admin_ids(self) -> frozenset[int]:
        return frozenset(
            int(item.strip()) for item in self.admin_ids.split(",") if item.strip()
        )

    @staticmethod
    def _normalize_source(raw: str) -> str | int | None:
        value = raw.strip()
        if not value:
            return None

        normalized = value.removeprefix("https://t.me/").removeprefix("http://t.me/")
        normalized = normalized.removeprefix("@").rstrip("/")
        if not normalized:
            return None

        try:
            return int(normalized)
        except ValueError:
            return normalized

    def _file_source_values(self) -> list[str]:
        path = self.chat_sources_file
        if path is None or not path.exists():
            return []

        values: list[str] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", maxsplit=1)[0].strip()
            if not line:
                continue
            values.extend(part.strip() for part in line.split(",") if part.strip())
        return values

    @cached_property
    def parsed_chat_sources(self) -> tuple[str | int, ...]:
        raw_values = self._file_source_values()
        raw_values.extend(
            item.strip() for item in self.chat_sources.split(",") if item.strip()
        )

        sources: list[str | int] = []
        seen: set[tuple[str, str]] = set()
        for raw in raw_values:
            source = self._normalize_source(raw)
            if source is None:
                continue

            key = (
                ("id", str(source))
                if isinstance(source, int)
                else ("username", source.casefold())
            )
            if key in seen:
                continue

            seen.add(key)
            sources.append(source)

        if not sources:
            raise ValueError(
                "No Telegram sources configured. Fill CHAT_SOURCES or "
                "CHAT_SOURCES_FILE."
            )
        return tuple(sources)

    @cached_property
    def target_chat_id(self) -> int:
        if self.notify_chat_id is not None:
            return self.notify_chat_id
        return next(iter(self.parsed_admin_ids))
