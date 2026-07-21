from __future__ import annotations

from functools import cached_property
from pathlib import Path
from urllib.parse import urljoin

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ALLOWED_SOURCE_PROVIDERS = frozenset(
    {"manual", "telegram_web", "telethon", "tgstat"}
)
LEGACY_TELEMETRIO_ALERT_BOTS = frozenset(
    {"telemetr_notif_bot", "telemetrio_alert_bot"}
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )

    bot_token: str
    admin_ids: str
    notify_chat_id: int | None = None

    # Cheap-by-default modes: manual forwarding or autonomous Telegram Web reader.
    source_providers: str = "manual"

    # Autonomous reader for Telemetrio monitoring alerts in Telegram Web.
    telegram_web_profile_dir: Path = Path("/data/telegram-web")
    telegram_web_target_chat: str = "TelemetrioAlertBot"
    telegram_web_url: str = "https://web.telegram.org/k/"
    telegram_web_poll_seconds: int = Field(default=15, ge=5, le=3600)
    telegram_web_login_timeout_seconds: int = Field(default=600, ge=60, le=3600)
    telegram_web_import_existing: bool = False

    # Optional MTProto/Telethon provider.
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_session: str | None = None
    chat_sources_file: Path | None = Path("config/sources.txt")
    chat_sources: str = ""

    # Optional TGStat Callback provider.
    tgstat_token: str | None = None
    tgstat_webhook_secret: str | None = None
    tgstat_verify_code: str | None = None
    tgstat_query_file: Path = Path("config/lead_query.tgstat")
    tgstat_subscription_id: int | None = None
    tgstat_queue_size: int = Field(default=1000, ge=10, le=100_000)
    public_base_url: str | None = None
    web_host: str = "0.0.0.0"
    web_port: int = Field(default=8080, ge=1, le=65_535)

    database_url: str = "sqlite+aiosqlite:///./parcertg.db"
    min_lead_score: int = Field(default=65, ge=0, le=100)
    dedup_window_hours: int = Field(default=48, ge=1, le=720)
    dedup_similarity: int = Field(default=92, ge=50, le=100)
    log_level: str = "INFO"

    @field_validator(
        "bot_token",
        "admin_ids",
        "telegram_api_hash",
        "telegram_session",
        "tgstat_token",
        "tgstat_webhook_secret",
        "tgstat_verify_code",
        "public_base_url",
        mode="before",
    )
    @classmethod
    def strip_optional_strings(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None

    @field_validator("bot_token", "admin_ids")
    @classmethod
    def required_strings_must_not_be_blank(cls, value: str | None) -> str:
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("telegram_web_target_chat")
    @classmethod
    def normalize_telegram_web_target_chat(cls, value: str) -> str:
        normalized = value.strip().removeprefix("@")
        if not normalized:
            raise ValueError("must not be blank")
        if normalized.casefold() in LEGACY_TELEMETRIO_ALERT_BOTS:
            return "TelemetrioAlertBot"
        return normalized

    @field_validator("telegram_web_url")
    @classmethod
    def validate_telegram_web_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("https://"):
            raise ValueError("must be an HTTPS URL")
        return normalized

    @model_validator(mode="after")
    def validate_provider_configuration(self) -> Settings:
        providers = self.parsed_source_providers
        unknown = providers - ALLOWED_SOURCE_PROVIDERS
        if unknown:
            raise ValueError(
                "Unknown SOURCE_PROVIDERS values: " + ", ".join(sorted(unknown))
            )
        if "telethon" in providers:
            missing = [
                name
                for name, value in (
                    ("TELEGRAM_API_ID", self.telegram_api_id),
                    ("TELEGRAM_API_HASH", self.telegram_api_hash),
                    ("TELEGRAM_SESSION", self.telegram_session),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "Telethon provider requires: " + ", ".join(missing)
                )
        if "tgstat" in providers and not self.tgstat_webhook_secret:
            raise ValueError("TGStat provider requires TGSTAT_WEBHOOK_SECRET")
        return self

    @cached_property
    def parsed_source_providers(self) -> frozenset[str]:
        providers = {
            item.strip().casefold()
            for item in self.source_providers.split(",")
            if item.strip()
        }
        return frozenset(providers or {"manual"})

    @cached_property
    def parsed_admin_ids(self) -> frozenset[int]:
        return frozenset(
            int(item.strip()) for item in self.admin_ids.split(",") if item.strip()
        )

    @staticmethod
    def _normalize_source(raw: str) -> str | int | None:
        value = raw.strip()
        if not value:
            return None

        normalized = value.removeprefix("https://t.me/").removeprefix("http://t.me/")
        normalized = normalized.removeprefix("@").rstrip("/")
        if not normalized:
            return None

        try:
            return int(normalized)
        except ValueError:
            return normalized

    def _file_source_values(self) -> list[str]:
        path = self.chat_sources_file
        if path is None or not path.exists():
            return []

        values: list[str] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", maxsplit=1)[0].strip()
            if not line:
                continue
            values.extend(part.strip() for part in line.split(",") if part.strip())
        return values

    @cached_property
    def parsed_chat_sources(self) -> tuple[str | int, ...]:
        raw_values = self._file_source_values()
        raw_values.extend(
            item.strip() for item in self.chat_sources.split(",") if item.strip()
        )

        sources: list[str | int] = []
        seen: set[tuple[str, str]] = set()
        for raw in raw_values:
            source = self._normalize_source(raw)
            if source is None:
                continue

            key = (
                ("id", str(source))
                if isinstance(source, int)
                else ("username", source.casefold())
            )
            if key in seen:
                continue

            seen.add(key)
            sources.append(source)

        if not sources:
            raise ValueError(
                "No Telegram sources configured. Fill CHAT_SOURCES or "
                "CHAT_SOURCES_FILE."
            )
        return tuple(sources)

    @cached_property
    def target_chat_id(self) -> int:
        if self.notify_chat_id is not None:
            return self.notify_chat_id
        return next(iter(self.parsed_admin_ids))

    @cached_property
    def tgstat_callback_path(self) -> str:
        if not self.tgstat_webhook_secret:
            raise ValueError("TGSTAT_WEBHOOK_SECRET is not configured")
        return f"/webhooks/tgstat/{self.tgstat_webhook_secret}"

    @cached_property
    def tgstat_callback_url(self) -> str:
        if not self.public_base_url:
            raise ValueError("PUBLIC_BASE_URL is not configured")
        base = self.public_base_url.rstrip("/") + "/"
        return urljoin(base, self.tgstat_callback_path.lstrip("/"))
