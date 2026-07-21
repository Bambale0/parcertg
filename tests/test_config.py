from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "bot_token": "token",
        "admin_ids": "123",
        "source_providers": "manual",
        "chat_sources": "",
        "chat_sources_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_manual_mode_does_not_require_mtproto_credentials() -> None:
    settings = make_settings()

    assert settings.parsed_source_providers == frozenset({"manual"})
    assert settings.telegram_api_id is None


def test_telethon_mode_requires_mtproto_credentials() -> None:
    with pytest.raises(ValidationError, match="TELEGRAM_API_ID"):
        make_settings(source_providers="telethon")


def test_tgstat_mode_requires_webhook_secret() -> None:
    with pytest.raises(ValidationError, match="TGSTAT_WEBHOOK_SECRET"):
        make_settings(source_providers="manual,tgstat")


def test_tgstat_callback_url_is_built_from_public_base_url() -> None:
    settings = make_settings(
        source_providers="manual,tgstat",
        tgstat_webhook_secret="secret-value",
        public_base_url="https://leads.example.com/base/",
    )

    assert (
        settings.tgstat_callback_url
        == "https://leads.example.com/base/webhooks/tgstat/secret-value"
    )


def test_default_catalog_contains_100_unique_sources() -> None:
    settings = make_settings(chat_sources_file=Path("config/sources.txt"))

    sources = settings.parsed_chat_sources

    assert len(sources) == 100
    assert len({str(source).casefold() for source in sources}) == 100


def test_file_and_env_sources_are_merged_and_deduplicated(tmp_path: Path) -> None:
    source_file = tmp_path / "sources.txt"
    source_file.write_text(
        "# comment\n@Alpha\nhttps://t.me/beta/\nalpha\n-100123\n",
        encoding="utf-8",
    )
    settings = make_settings(
        chat_sources_file=source_file,
        chat_sources="BETA,gamma",
    )

    assert settings.parsed_chat_sources == ("Alpha", "beta", -100123, "gamma")
