from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from app.config import Settings
from app.ingestion import IncomingLead, LeadProcessor, ProcessingStatus

if TYPE_CHECKING:
    from app.notifier import Notifier

logger = structlog.get_logger(__name__)

_READY_SELECTORS = (
    "#column-left",
    ".chatlist",
    ".chat-list",
    "[class*='chatlist']",
    "[class*='chat-list']",
)
_QR_SELECTORS = (
    "[class*='qr'] canvas",
    "[class*='qr'] svg",
    "canvas",
    "svg[class*='qr']",
)
_LOGIN_TEXT_MARKERS = (
    "log in to telegram",
    "scan this code",
    "qr code",
    "войти в telegram",
    "отсканируйте код",
)
_EXTRACT_MESSAGES_SCRIPT = """
() => {
  const selectors = [
    '.bubbles-group .bubble',
    '.bubble[data-mid]',
    '.bubble',
    '[data-mid].message'
  ];
  let nodes = [];
  for (const selector of selectors) {
    nodes = Array.from(document.querySelectorAll(selector));
    if (nodes.length) break;
  }
  const unique = [];
  const roots = new Set();
  for (const node of nodes) {
    const root = node.closest('.bubble') || node;
    if (roots.has(root)) continue;
    roots.add(root);
    const textNode = root.querySelector(
      '.text-content, .formatted-text, .bubble-content, .message'
    ) || root;
    const text = (textNode.innerText || root.innerText || '').trim();
    if (!text) continue;
    const links = Array.from(root.querySelectorAll('a[href]'))
      .map((anchor) => anchor.href)
      .filter(Boolean);
    const id = root.getAttribute('data-mid') ||
      root.getAttribute('data-message-id') || root.id || '';
    unique.push({id, text, links});
  }
  return unique.slice(-100);
}
"""


@dataclass(frozen=True, slots=True)
class TelegramWebMessage:
    key: str
    text: str
    links: tuple[str, ...]


class LoginRequiredError(RuntimeError):
    pass


class SeenMessageStore:
    def __init__(self, profile_dir: Path, limit: int = 5000) -> None:
        self.path = profile_dir / "parcertg-seen.json"
        self.limit = limit
        self.initialized = False
        self._keys: list[str] = []
        self._key_set: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            logger.warning("telegram_web_state_invalid", path=str(self.path))
            return
        keys = payload.get("seen", []) if isinstance(payload, dict) else []
        if not isinstance(keys, list):
            return
        self.initialized = bool(payload.get("initialized"))
        self._keys = [str(value) for value in keys[-self.limit :]]
        self._key_set = set(self._keys)

    def contains(self, key: str) -> bool:
        return key in self._key_set

    def add(self, key: str) -> None:
        if key in self._key_set:
            return
        self._keys.append(key)
        self._key_set.add(key)
        overflow = len(self._keys) - self.limit
        if overflow > 0:
            removed = self._keys[:overflow]
            self._keys = self._keys[overflow:]
            self._key_set.difference_update(removed)

    def mark_initialized(self) -> None:
        self.initialized = True

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        payload = {"initialized": self.initialized, "seen": self._keys}
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.path)


def _message_key(raw_id: str, text: str, links: tuple[str, ...]) -> str:
    if raw_id.strip():
        return raw_id.strip()
    raw = "\x1f".join((text, *links)).encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


def parse_browser_messages(raw_messages: list[dict[str, Any]]) -> list[TelegramWebMessage]:
    parsed: list[TelegramWebMessage] = []
    for raw in raw_messages:
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        raw_links = raw.get("links") or []
        links = tuple(
            str(value).strip()
            for value in raw_links
            if isinstance(value, str) and value.strip()
        )
        key = _message_key(str(raw.get("id") or ""), text, links)
        parsed.append(TelegramWebMessage(key=key, text=text, links=links))
    return parsed


def extract_original_message_url(
    links: tuple[str, ...],
    target_chat: str,
) -> str | None:
    ignored = target_chat.casefold().removeprefix("@")
    for link in links:
        lowered = link.casefold()
        if "t.me/" not in lowered:
            continue
        if f"t.me/{ignored}" in lowered:
            continue
        return link
    return None


async def launch_telegram_web_context(
    settings: Settings,
    playwright: Playwright,
) -> BrowserContext:
    settings.telegram_web_profile_dir.mkdir(parents=True, exist_ok=True)
    return await playwright.chromium.launch_persistent_context(
        user_data_dir=str(settings.telegram_web_profile_dir),
        headless=True,
        viewport={"width": 1280, "height": 900},
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )


async def telegram_web_is_logged_in(page: Page) -> bool:
    for selector in _READY_SELECTORS:
        try:
            if await page.locator(selector).count() > 0:
                return True
        except Exception:
            continue
    try:
        body_text = (await page.locator("body").inner_text()).casefold()
    except Exception:
        return False
    return not any(marker in body_text for marker in _LOGIN_TEXT_MARKERS)


async def capture_telegram_web_login_image(page: Page) -> bytes:
    for selector in _QR_SELECTORS:
        locator = page.locator(selector)
        try:
            count = await locator.count()
            if count:
                return await locator.last.screenshot(type="png")
        except Exception:
            continue
    return await page.screenshot(type="png", full_page=True)


class TelegramWebCollector:
    def __init__(
        self,
        settings: Settings,
        processor: LeadProcessor,
        notifier: Notifier,
    ) -> None:
        self.settings = settings
        self.processor = processor
        self.notifier = notifier
        self.store = SeenMessageStore(settings.telegram_web_profile_dir)
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._login_notice_sent = False

    async def _notify_login_required(self) -> None:
        if self._login_notice_sent:
            return
        self._login_notice_sent = True
        await self.notifier.bot.send_message(
            chat_id=self.settings.target_chat_id,
            text=(
                "⚠️ <b>Telegram Web не авторизован</b>\n\n"
                "На сервере выполните:\n"
                "<code>docker compose stop app</code>\n"
                "<code>docker compose run --rm app "
                "python -m scripts.telegram_web_login</code>\n"
                "<code>docker compose up -d app</code>"
            ),
        )

    async def _start_browser(self) -> Page:
        self._playwright = await async_playwright().start()
        self._context = await launch_telegram_web_context(
            self.settings,
            self._playwright,
        )
        page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        await page.goto(
            self.settings.telegram_web_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        await page.wait_for_timeout(3000)
        if not await telegram_web_is_logged_in(page):
            raise LoginRequiredError("Telegram Web profile is not authorized")
        target = self.settings.telegram_web_target_chat
        await page.goto(
            f"https://web.telegram.org/k/#@{target}",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        await page.wait_for_timeout(7000)
        if not await telegram_web_is_logged_in(page):
            raise LoginRequiredError("Telegram Web session expired")
        self._login_notice_sent = False
        return page

    async def _read_messages(self, page: Page) -> list[TelegramWebMessage]:
        raw = await page.evaluate(_EXTRACT_MESSAGES_SCRIPT)
        if not isinstance(raw, list):
            return []
        return parse_browser_messages(raw)

    async def _bootstrap(self, messages: list[TelegramWebMessage]) -> None:
        if self.store.initialized:
            return
        if self.settings.telegram_web_import_existing:
            self.store.mark_initialized()
            self.store.save()
            return
        for message in messages:
            self.store.add(message.key)
        self.store.mark_initialized()
        self.store.save()
        logger.info("telegram_web_history_baselined", messages=len(messages))
        await self.notifier.bot.send_message(
            chat_id=self.settings.target_chat_id,
            text=(
                "✅ <b>Telegram Web подключён</b>\n"
                "Старая история пропущена. Новые уведомления Telemetr "
                "будут обрабатываться автоматически."
            ),
        )

    async def _process_message(self, message: TelegramWebMessage) -> None:
        incoming = IncomingLead(
            text=message.text,
            provider="telemetr",
            source_id=f"telegram-web:{self.settings.telegram_web_target_chat}",
            source_title=f"@{self.settings.telegram_web_target_chat}",
            message_id=message.key,
            message_url=extract_original_message_url(
                message.links,
                self.settings.telegram_web_target_chat,
            ),
            published_at=datetime.now(UTC),
        )
        result = await self.processor.process(incoming)
        if result.status is ProcessingStatus.ACCEPTED and result.lead is not None:
            await self.notifier.send_lead(result.lead)
        logger.info(
            "telegram_web_alert_processed",
            status=result.status.value,
            score=result.score.score,
            message_key=message.key,
        )

    async def _poll(self, page: Page) -> None:
        messages = await self._read_messages(page)
        await self._bootstrap(messages)
        changed = False
        for message in messages:
            if self.store.contains(message.key):
                continue
            self.store.add(message.key)
            changed = True
            await self._process_message(message)
        if changed:
            self.store.save()

    async def _run_browser_session(self) -> None:
        page = await self._start_browser()
        logger.info(
            "telegram_web_collector_started",
            target=self.settings.telegram_web_target_chat,
            poll_seconds=self.settings.telegram_web_poll_seconds,
        )
        while True:
            await self._poll(page)
            await asyncio.sleep(self.settings.telegram_web_poll_seconds)

    async def run(self) -> None:
        while True:
            try:
                await self._run_browser_session()
            except asyncio.CancelledError:
                raise
            except LoginRequiredError:
                logger.warning("telegram_web_login_required")
                await self.close_browser()
                await self._notify_login_required()
                await asyncio.sleep(60)
            except Exception:
                logger.exception("telegram_web_collector_error")
                await self.close_browser()
                await asyncio.sleep(30)

    async def close_browser(self) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                logger.exception("telegram_web_context_close_failed")
            self._context = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                logger.exception("telegram_web_playwright_stop_failed")
            self._playwright = None

    async def close(self) -> None:
        self.store.save()
        await self.close_browser()
