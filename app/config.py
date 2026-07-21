from __future__ import annotations

from functools import cached_property

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
    chat_sources: str

    database_url: str = "sqlite+aiosqlite:///./parcertg.db"
    min_lead_score: int = Field(default=65, ge=0, le=100)
    dedup_window_hours: int = Field(default=48, ge=1, le=720)
    dedup_similarity: int = Field(default=92, ge=50, le=100)
    log_level: str = "INFO"

    @field_validator(
        "telegram_api_hash", "telegram_session", "bot_token", "admin_ids", "chat_sources"
    )
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @cached_property
    def parsed_admin_ids(self) -> frozenset[int]:
        return frozenset(int(item.strip()) for item in self.admin_ids.split(",") if item.strip())

    @cached_property
    def parsed_chat_sources(self) -> tuple[str | int, ...]:
        sources: list[str | int] = []
        for raw in self.chat_sources.split(","):
            value = raw.strip()
            if not value:
                continue
            normalized = value.removeprefix("https://t.me/").removeprefix("http://t.me/")
            normalized = normalized.removeprefix("@").rstrip("/")
            try:
                sources.append(int(normalized))
            except ValueError:
                sources.append(normalized)
        return tuple(sources)

    @cached_property
    def target_chat_id(self) -> int:
        if self.notify_chat_id is not None:
            return self.notify_chat_id
        return next(iter(self.parsed_admin_ids))
