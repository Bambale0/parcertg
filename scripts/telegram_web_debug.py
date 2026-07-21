from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from playwright.async_api import async_playwright

from app.config import Settings
from app.telegram_web import launch_telegram_web_context
from app.telegram_web_v2 import (
    open_target_chat,
    page_state,
    save_diagnostics,
)


async def main_async() -> None:
    settings = Settings()  # type: ignore[call-arg]
    playwright = await async_playwright().start()
    context = await launch_telegram_web_context(settings, playwright)
    page = context.pages[0] if context.pages else await context.new_page()

    try:
        await page.goto(
            settings.telegram_web_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        await page.wait_for_timeout(5000)
        initial = await page_state(page)
        print("Initial state:")
        print(json.dumps(asdict(initial), ensure_ascii=False, indent=2))

        if initial.logged_in:
            await open_target_chat(page, settings)
            await page.wait_for_timeout(3000)

        final = await page_state(page)
        screenshot, state_file = await save_diagnostics(
            page,
            settings.telegram_web_profile_dir,
        )
        print("Final state:")
        print(json.dumps(asdict(final), ensure_ascii=False, indent=2))
        print(f"Screenshot: {screenshot}")
        print(f"State file: {state_file}")
    finally:
        await context.close()
        await playwright.stop()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
