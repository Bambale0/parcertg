from __future__ import annotations

from datetime import UTC

import structlog
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from app.config import Settings
from app.ingestion import IncomingLead, LeadProcessor, ProcessingStatus
from app.notifier import Notifier

logger = structlog.get_logger(__name__)


class LeadCollector:
    def __init__(
        self,
        settings: Settings,
        processor: LeadProcessor,
        notifier: Notifier,
    ) -> None:
        self.settings = settings
        self.processor = processor
        self.notifier = notifier
        if not (
            settings.telegram_api_id
            and settings.telegram_api_hash
            and settings.telegram_session
        ):
            raise ValueError("Telethon credentials are not configured")
        self.client = TelegramClient(
            StringSession(settings.telegram_session),
            settings.telegram_api_id,
            settings.telegram_api_hash,
        )

    @staticmethod
    def _message_url(
        chat_id: int,
        chat_username: str | None,
        message_id: int,
    ) -> str | None:
        if chat_username:
            return f"https://t.me/{chat_username}/{message_id}"
        raw = str(chat_id)
        if raw.startswith("-100"):
            return f"https://t.me/c/{raw[4:]}/{message_id}"
        return None

    async def _handle_message(self, event: events.NewMessage.Event) -> None:
        if event.out or not event.raw_text:
            return

        chat = await event.get_chat()
        sender = await event.get_sender()
        chat_id = int(event.chat_id)
        chat_title = (
            getattr(chat, "title", None)
            or getattr(chat, "username", None)
            or str(chat_id)
        )
        chat_username = getattr(chat, "username", None)
        sender_username = getattr(sender, "username", None)
        sender_name = " ".join(
            value
            for value in (
                getattr(sender, "first_name", None),
                getattr(sender, "last_name", None),
            )
            if value
        ).strip() or None

        result = await self.processor.process(
            IncomingLead(
                text=event.raw_text,
                provider="telethon",
                source_id=str(chat_id),
                source_title=chat_title,
                source_username=chat_username,
                message_id=str(event.message.id),
                message_url=self._message_url(
                    chat_id,
                    chat_username,
                    event.message.id,
                ),
                published_at=event.message.date.astimezone(UTC),
                sender_id=getattr(sender, "id", None),
                sender_username=sender_username,
                sender_name=sender_name,
            )
        )
        if result.status is ProcessingStatus.ACCEPTED and result.lead is not None:
            await self.notifier.send_lead(result.lead)

    async def run(self) -> None:
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise RuntimeError(
                "TELEGRAM_SESSION is invalid or expired. "
                "Run scripts.generate_session again."
            )

        configured_sources = self.settings.parsed_chat_sources
        resolved_chats = []
        unavailable_sources: list[str | int] = []
        for source in configured_sources:
            try:
                resolved_chats.append(await self.client.get_input_entity(source))
            except Exception:
                unavailable_sources.append(source)
                logger.exception("chat_source_unavailable", source=source)

        if not resolved_chats:
            raise RuntimeError(
                "No Telegram sources could be resolved by the Telegram account"
            )

        self.client.add_event_handler(
            self._handle_message,
            events.NewMessage(chats=resolved_chats, incoming=True),
        )
        logger.info(
            "collector_started",
            configured=len(configured_sources),
            resolved=len(resolved_chats),
            unavailable=len(unavailable_sources),
        )
        await self.client.run_until_disconnected()

    async def close(self) -> None:
        await self.client.disconnect()
