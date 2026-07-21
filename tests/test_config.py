from pathlib import Path

from app.config import Settings


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "telegram_api_id": 1,
        "telegram_api_hash": "hash",
        "telegram_session": "session",
        "bot_token": "token",
        "admin_ids": "123",
        "chat_sources": "",
        "chat_sources_file": None,
    }
    values.update(overrides)
    return Settings(**values)


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
