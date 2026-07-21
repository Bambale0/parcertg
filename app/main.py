from __future__ import annotations

import asyncio
import logging
import sys

import structlog

from app.collector import LeadCollector
from app.config import Settings
from app.database import Database
from app.ingestion import LeadProcessor
from app.notifier import Notifier
from app.telegram_web import TelegramWebCollector
from app.web import TGStatWebhookServer


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        stream=sys.stdout,
    )
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
    )


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(settings.log_level)

    database = Database(settings.database_url)
    await database.create_schema()
    processor = LeadProcessor(settings, database)
    notifier = Notifier(settings, database, processor)

    collector: LeadCollector | None = None
    telegram_web_collector: TelegramWebCollector | None = None
    tgstat_server: TGStatWebhookServer | None = None
    tasks = [asyncio.create_task(notifier.run(), name="notification-bot")]

    if "telegram_web" in settings.parsed_source_providers:
        telegram_web_collector = TelegramWebCollector(
            settings,
            processor,
            notifier,
        )
        tasks.append(
            asyncio.create_task(
                telegram_web_collector.run(),
                name="telegram-web-collector",
            )
        )

    if "telethon" in settings.parsed_source_providers:
        collector = LeadCollector(settings, processor, notifier)
        tasks.append(
            asyncio.create_task(collector.run(), name="telegram-collector")
        )

    if "tgstat" in settings.parsed_source_providers:
        tgstat_server = TGStatWebhookServer(settings, processor, notifier)
        tasks.append(
            asyncio.create_task(tgstat_server.run(), name="tgstat-webhook")
        )

    try:
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_EXCEPTION,
        )
        for task in done:
            exception = task.exception()
            if exception:
                raise exception
        for task in pending:
            task.cancel()
    finally:
        if tgstat_server is not None:
            await tgstat_server.close()
        if telegram_web_collector is not None:
            await telegram_web_collector.close()
        if collector is not None:
            await collector.close()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await notifier.close()
        await database.close()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
