from __future__ import annotations

import asyncio
from time import monotonic

from aiogram import Bot
from aiogram.types import BufferedInputFile
from playwright.async_api import async_playwright

from app.config import Settings
from app.telegram_web import (
    capture_telegram_web_login_image,
    launch_telegram_web_context,
    telegram_web_is_logged_in,
)


async def main_async() -> None:
    settings = Settings()  # type: ignore[call-arg]
    bot = Bot(settings.bot_token)
    playwright = await async_playwright().start()
    context = await launch_telegram_web_context(settings, playwright)
    page = context.pages[0] if context.pages else await context.new_page()

    try:
        await page.goto(
            settings.telegram_web_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        await page.wait_for_timeout(3000)
        if await telegram_web_is_logged_in(page):
            await bot.send_message(
                settings.target_chat_id,
                "✅ Telegram Web уже авторизован. Можно запускать ParcerTG.",
            )
            print("Telegram Web is already authorized.")
            return

        deadline = monotonic() + settings.telegram_web_login_timeout_seconds
        last_qr_sent = 0.0
        while monotonic() < deadline:
            if await telegram_web_is_logged_in(page):
                await bot.send_message(
                    settings.target_chat_id,
                    "✅ Telegram Web успешно авторизован. Запускайте ParcerTG.",
                )
                print("Telegram Web authorization completed.")
                return

            now = monotonic()
            if now - last_qr_sent >= 50:
                image = await capture_telegram_web_login_image(page)
                await bot.send_photo(
                    chat_id=settings.target_chat_id,
                    photo=BufferedInputFile(image, filename="telegram-web-login.png"),
                    caption=(
                        "🔐 <b>Вход в Telegram Web</b>\n\n"
                        "Откройте Telegram на телефоне:\n"
                        "Настройки → Устройства → Подключить устройство, "
                        "затем отсканируйте QR-код.\n\n"
                        "Код обновляется автоматически примерно раз в минуту."
                    ),
                )
                last_qr_sent = now
                print("A fresh login image was sent to the notification bot.")

            await asyncio.sleep(2)

        await bot.send_message(
            settings.target_chat_id,
            (
                "❌ Время ожидания входа Telegram Web истекло. "
                "Запустите команду ещё раз."
            ),
        )
        raise TimeoutError("Telegram Web login timed out")
    finally:
        await context.close()
        await playwright.stop()
        await bot.session.close()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
