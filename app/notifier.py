from __future__ import annotations

import re
from datetime import UTC, datetime
from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import Settings
from app.database import Database
from app.ingestion import IncomingLead, LeadProcessor, ProcessingResult, ProcessingStatus
from app.models import Lead, LeadStatus
from app.scoring import ScoreResult, score_message

TELEGRAM_URL_RE = re.compile(r"(?:https?://)?t\.me/[A-Za-z0-9_+\-/=]+", re.IGNORECASE)


class Notifier:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        processor: LeadProcessor,
    ) -> None:
        self.settings = settings
        self.database = database
        self.processor = processor
        self.bot = Bot(
            settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self.dispatcher = Dispatcher()
        self.router = Router(name="lead-controls")
        self._register_handlers()
        self.dispatcher.include_router(self.router)

    def _is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.settings.parsed_admin_ids

    @staticmethod
    def _message_text(message: Message | None) -> str:
        if message is None:
            return ""
        return (message.text or message.caption or "").strip()

    @staticmethod
    def _command_argument(message: Message) -> str:
        text = message.text or ""
        _, separator, argument = text.partition(" ")
        return argument.strip() if separator else ""

    @staticmethod
    def _extract_url(message: Message, text: str) -> str | None:
        entities = [*(message.entities or []), *(message.caption_entities or [])]
        for entity in entities:
            url = getattr(entity, "url", None)
            if isinstance(url, str) and "t.me/" in url:
                return url
        match = TELEGRAM_URL_RE.search(text)
        if not match:
            return None
        url = match.group(0)
        return url if url.startswith("http") else "https://" + url

    @staticmethod
    def _format_score(score: ScoreResult) -> str:
        reasons = "\n".join(f"• {escape(reason)}" for reason in score.reasons)
        return (
            f"<b>Оценка: {score.score}/100</b>\n"
            f"{reasons or '• Правила не сработали'}"
        )

    def _incoming_from_forward(self, message: Message) -> IncomingLead | None:
        text = self._message_text(message)
        origin = message.forward_origin
        if not text or origin is None:
            return None

        origin_chat = getattr(origin, "chat", None) or getattr(
            origin, "sender_chat", None
        )
        origin_user = getattr(origin, "sender_user", None)
        hidden_name = getattr(origin, "sender_user_name", None)

        username = getattr(origin_chat, "username", None) or getattr(
            origin_user, "username", None
        )
        source_id = str(
            getattr(origin_chat, "id", None)
            or getattr(origin_user, "id", None)
            or hidden_name
            or f"forward:{message.chat.id}"
        )
        source_title = (
            getattr(origin_chat, "title", None)
            or getattr(origin_user, "full_name", None)
            or hidden_name
            or "Пересланное сообщение"
        )
        normalized_username = str(username or "").removeprefix("@").casefold()
        if "telemetr" in normalized_username:
            provider = "telemetr"
        elif "tgalerts" in normalized_username or "tgstat" in normalized_username:
            provider = "tgstat"
        else:
            provider = "manual"

        origin_message_id = getattr(origin, "message_id", None) or message.message_id
        published_at = getattr(origin, "date", None)
        if not isinstance(published_at, datetime):
            published_at = datetime.now(UTC)

        sender_name = None
        sender_id = None
        sender_username = None
        if origin_user is not None:
            sender_id = getattr(origin_user, "id", None)
            sender_username = getattr(origin_user, "username", None)
            sender_name = getattr(origin_user, "full_name", None)
        elif hidden_name:
            sender_name = str(hidden_name)

        return IncomingLead(
            text=text,
            provider=provider,
            source_id=source_id,
            source_title=str(source_title),
            source_username=str(username).removeprefix("@") if username else None,
            message_id=str(origin_message_id),
            message_url=self._extract_url(message, text),
            published_at=published_at,
            sender_id=sender_id,
            sender_username=sender_username,
            sender_name=sender_name,
        )

    async def _answer_processing_result(
        self,
        message: Message,
        result: ProcessingResult,
    ) -> None:
        if result.status is ProcessingStatus.BELOW_THRESHOLD:
            await message.answer(
                "🟡 <b>Не дотянул до порога горячего лида</b>\n\n"
                + self._format_score(result.score)
            )
            return
        if result.status is ProcessingStatus.DUPLICATE:
            lead_id = result.lead.id if result.lead else "?"
            await message.answer(f"♻️ Такой лид уже сохранён: #{lead_id}")
            return
        if result.lead is None:
            await message.answer("Не удалось сохранить лид")
            return

        await self.send_lead(result.lead)
        if message.chat.id != self.settings.target_chat_id:
            await message.answer(f"🔥 Лид сохранён и отправлен: #{result.lead.id}")

    def _register_handlers(self) -> None:
        @self.router.message(Command("start", "help"))
        async def start_handler(message: Message) -> None:
            if not self._is_admin(message.from_user.id if message.from_user else None):
                return
            providers = ", ".join(sorted(self.settings.parsed_source_providers))
            if "telegram_web" in self.settings.parsed_source_providers:
                mode_text = (
                    "Автопоиск включён: сохранённая Telegram Web-сессия читает "
                    f"новые уведомления @{self.settings.telegram_web_target_chat}."
                )
            else:
                mode_text = (
                    "Ручной режим: перешлите уведомление Telemetr — бот оценит, "
                    "удалит дубль и сохранит горячий лид."
                )
            await message.answer(
                "<b>ParcerTG запущен</b>\n\n"
                f"{mode_text}\n\n"
                "Команды:\n"
                "• /check текст — только оценить\n"
                "• /lead текст — сохранить и обработать\n"
                "• /lead в ответ на сообщение — обработать сообщение\n"
                "• /stats — статистика\n"
                "• /providers — активные источники\n\n"
                f"Активные источники: <code>{escape(providers)}</code>"
            )

        @self.router.message(Command("providers"))
        async def providers_handler(message: Message) -> None:
            if not self._is_admin(message.from_user.id if message.from_user else None):
                return
            providers = "\n".join(
                f"• <code>{escape(provider)}</code>"
                for provider in sorted(self.settings.parsed_source_providers)
            )
            await message.answer(f"<b>Активные источники</b>\n{providers}")

        @self.router.message(Command("check"))
        async def check_handler(message: Message) -> None:
            if not self._is_admin(message.from_user.id if message.from_user else None):
                return
            text = self._command_argument(message) or self._message_text(
                message.reply_to_message
            )
            if not text:
                await message.answer("Использование: <code>/check текст заявки</code>")
                return
            await message.answer(self._format_score(score_message(text)))

        @self.router.message(Command("lead"))
        async def lead_handler(message: Message) -> None:
            if not self._is_admin(message.from_user.id if message.from_user else None):
                return
            text = self._command_argument(message)
            reply = message.reply_to_message
            if not text:
                text = self._message_text(reply)
            if not text:
                await message.answer(
                    "Использование: <code>/lead текст заявки</code> или ответьте "
                    "командой /lead на сообщение."
                )
                return

            incoming = (
                self._incoming_from_forward(reply)
                if reply and reply.forward_origin
                else None
            )
            if incoming is None:
                incoming = IncomingLead(
                    text=text,
                    provider="manual",
                    source_id=f"manual:{message.chat.id}",
                    source_title="Ручной ввод",
                    message_id=str(reply.message_id if reply else message.message_id),
                    message_url=self._extract_url(reply or message, text),
                    published_at=datetime.now(UTC),
                    sender_id=message.from_user.id if message.from_user else None,
                    sender_username=(
                        message.from_user.username if message.from_user else None
                    ),
                    sender_name=(
                        message.from_user.full_name if message.from_user else None
                    ),
                )
            result = await self.processor.process(incoming)
            await self._answer_processing_result(message, result)

        @self.router.message(Command("stats"))
        async def stats_handler(message: Message) -> None:
            if not self._is_admin(message.from_user.id if message.from_user else None):
                return
            stats = await self.database.stats_today()
            await message.answer(
                "<b>Статистика за сегодня</b>\n\n"
                f"🔥 Найдено лидов: <b>{stats['total']}</b>\n"
                f"✅ Взято в работу: <b>{stats['contacted']}</b>\n"
                f"🚫 Отклонено: <b>{stats['rejected']}</b>"
            )

        @self.router.message(F.forward_origin)
        async def forwarded_lead_handler(message: Message) -> None:
            if not self._is_admin(message.from_user.id if message.from_user else None):
                return
            incoming = self._incoming_from_forward(message)
            if incoming is None:
                await message.answer("В пересланном сообщении нет текста")
                return
            result = await self.processor.process(incoming)
            await self._answer_processing_result(message, result)

        @self.router.callback_query(F.data.startswith("lead:"))
        async def lead_action_handler(callback: CallbackQuery) -> None:
            if not self._is_admin(callback.from_user.id):
                await callback.answer("Нет доступа", show_alert=True)
                return

            _, action, raw_lead_id = callback.data.split(":", maxsplit=2)
            lead_id = int(raw_lead_id)
            status_map = {
                "contacted": LeadStatus.CONTACTED,
                "skip": LeadStatus.NOT_RELEVANT,
                "spam": LeadStatus.SPAM,
            }
            status = status_map.get(action)
            if status is None:
                await callback.answer("Неизвестное действие", show_alert=True)
                return

            updated = await self.database.set_status(lead_id, status)
            if not updated:
                await callback.answer("Лид не найден", show_alert=True)
                return

            labels = {
                LeadStatus.CONTACTED: "✅ Взято в работу",
                LeadStatus.NOT_RELEVANT: "🚫 Не подходит",
                LeadStatus.SPAM: "🗑 Спам",
            }
            await callback.answer(labels[status])
            if callback.message:
                await callback.message.edit_reply_markup(reply_markup=None)
                await callback.message.answer(f"{labels[status]} · лид #{lead_id}")

    async def send_lead(self, lead: Lead) -> None:
        source = lead.sources[0]
        username = f"@{lead.sender_username}" if lead.sender_username else "нет username"
        reasons = "\n".join(
            f"• {escape(reason)}" for reason in lead.reasons.split("\n") if reason
        )
        text = (
            f"🔥 <b>ГОРЯЧИЙ ЛИД — {lead.score}/100</b>\n\n"
            f"{escape(lead.original_text[:3000])}\n\n"
            f"<b>Почему подходит:</b>\n{reasons or '• Совпадение по правилам'}\n\n"
            f"<b>Источник:</b> {escape(source.chat_title)}\n"
            f"<b>Автор:</b> {escape(lead.sender_name or 'неизвестно')} "
            f"({escape(username)})\n"
            f"<b>Лид:</b> #{lead.id}"
        )

        buttons: list[list[InlineKeyboardButton]] = []
        if source.message_url:
            buttons.append(
                [InlineKeyboardButton(text="Открыть сообщение", url=source.message_url)]
            )
        buttons.extend(
            [
                [
                    InlineKeyboardButton(
                        text="✅ Взял в работу",
                        callback_data=f"lead:contacted:{lead.id}",
                    ),
                    InlineKeyboardButton(
                        text="🚫 Не подходит",
                        callback_data=f"lead:skip:{lead.id}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="🗑 Спам",
                        callback_data=f"lead:spam:{lead.id}",
                    )
                ],
            ]
        )
        await self.bot.send_message(
            chat_id=self.settings.target_chat_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            disable_web_page_preview=True,
        )

    async def run(self) -> None:
        await self.dispatcher.start_polling(
            self.bot,
            allowed_updates=self.dispatcher.resolve_used_update_types(),
            handle_signals=False,
        )

    async def close(self) -> None:
        if self.dispatcher._running_lock.locked():
            await self.dispatcher.stop_polling()
        await self.bot.session.close()
