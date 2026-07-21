from __future__ import annotations

from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import Settings
from app.database import Database
from app.models import Lead, LeadStatus


class Notifier:
    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.database = database
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

    def _register_handlers(self) -> None:
        @self.router.message(Command("start"))
        async def start_handler(message: Message) -> None:
            if not self._is_admin(message.from_user.id if message.from_user else None):
                return
            await message.answer(
                "Lead Hunter запущен. Используйте /stats для статистики за сегодня."
            )

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
        reasons = "\n".join(f"• {escape(reason)}" for reason in lead.reasons.split("\n") if reason)
        text = (
            f"🔥 <b>ГОРЯЧИЙ ЛИД — {lead.score}/100</b>\n\n"
            f"{escape(lead.original_text[:3000])}\n\n"
            f"<b>Почему подходит:</b>\n{reasons or '• Совпадение по правилам'}\n\n"
            f"<b>Источник:</b> {escape(source.chat_title)}\n"
            f"<b>Автор:</b> {escape(lead.sender_name or 'неизвестно')} ({escape(username)})\n"
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
                        text="✅ Взял в работу", callback_data=f"lead:contacted:{lead.id}"
                    ),
                    InlineKeyboardButton(
                        text="🚫 Не подходит", callback_data=f"lead:skip:{lead.id}"
                    ),
                ],
                [InlineKeyboardButton(text="🗑 Спам", callback_data=f"lead:spam:{lead.id}")],
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
