from datetime import UTC, datetime

from app.config import Settings
from app.database import Database
from app.ingestion import IncomingLead, LeadProcessor, ProcessingStatus


def make_settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        bot_token="token",
        admin_ids="123",
        source_providers="manual",
        chat_sources_file=None,
        database_url=database_url,
    )


async def test_processor_accepts_and_deduplicates_cross_provider_lead(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'leads.db'}"
    database = Database(database_url)
    await database.create_schema()
    processor = LeadProcessor(make_settings(database_url), database)
    text = (
        "Срочно нужен Python разработчик. Нужно разработать Telegram-бота, "
        "подключить CRM и API. Бюджет 100 000 руб. Пишите @customer"
    )

    first = await processor.process(
        IncomingLead(
            text=text,
            provider="telemetr",
            source_id="telemetr-alerts",
            source_title="Telemetr alerts",
            message_id="1",
            published_at=datetime.now(UTC),
        )
    )
    second = await processor.process(
        IncomingLead(
            text=text,
            provider="tgstat",
            source_id="123",
            source_title="Original chat",
            message_id="99999999999",
            published_at=datetime.now(UTC),
        )
    )

    assert first.status is ProcessingStatus.ACCEPTED
    assert first.lead is not None
    assert second.status is ProcessingStatus.DUPLICATE
    assert second.lead is not None
    assert second.lead.id == first.lead.id

    await database.close()
