from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from urllib.parse import quote

import structlog
from playwright.async_api import Locator, Page, async_playwright

from app.config import Settings
from app.ingestion import IncomingLead, LeadProcessor, ProcessingStatus
from app.notifier import Notifier
from app.telegram_web import (
    SeenMessageStore,
    TelegramWebMessage,
    extract_original_message_url,
    launch_telegram_web_context,
    parse_browser_messages,
)

logger = structlog.get_logger(__name__)

_LOGIN_SELECTORS = (
    "#auth-pages",
    ".auth-pages",
    ".qr-container",
    "[class*='qr-container']",
    "input[type='tel']",
)
_QR_SELECTORS = (
    "[class*='qr'] canvas",
    "[class*='qr'] svg",
    ".qr-container canvas",
    ".qr-container svg",
    "canvas",
)
_HEADER_SELECTORS = (
    "#column-center .chat-info",
    "#column-center .peer-title",
    "#column-center header",
    "#column-center [class*='chat-info']",
)
_SEARCH_INPUT_SELECTORS = (
    "#column-left input.input-search-input",
    "#column-left .input-search input",
    "#column-left input[placeholder*='Search' i]",
    "#column-left input[placeholder*='Поиск' i]",
    "#column-left input[type='search']",
)
_SEARCH_RESULT_SELECTORS = (
    "#column-left .search-group .row",
    "#column-left .chatlist-chat",
    "#column-left [data-peer-id]",
    "#column-left .row",
)
_EXTRACT_MESSAGES_SCRIPT = r"""
() => {
  const center = document.querySelector('#column-center') || document;
  const selectors = [
    '.bubbles-group .bubble', '.bubbles .bubble', '.bubble[data-mid]',
    '.bubble', '[data-mid]', '[data-message-id]', '.message-list-item'
  ];
  const roots = [];
  const seen = new Set();
  for (const selector of selectors) {
    for (const node of center.querySelectorAll(selector)) {
      const root = node.closest(
        '.bubble, [data-mid], [data-message-id], .message-list-item'
      ) || node;
      if (seen.has(root)) continue;
      seen.add(root);
      roots.push(root);
    }
    if (roots.length) break;
  }
  const messages = [];
  for (const root of roots) {
    const textNode = root.querySelector(
      '.translatable-message, .text-content, .formatted-text, ' +
      '[class*="message-text"], .bubble-content, .message'
    ) || root;
    const text = (textNode.innerText || root.innerText || '').trim();
    if (!text) continue;
    const links = Array.from(root.querySelectorAll('a[href]'))
      .map((anchor) => anchor.href)
      .filter(Boolean);
    for (const match of text.matchAll(
      /(?:https?:\/\/)?t\.me\/[A-Za-z0-9_+\-/=]+/gi
    )) {
      const value = match[0].startsWith('http')
        ? match[0]
        : `https://${match[0]}`;
      if (!links.includes(value)) links.push(value);
    }
    const idNode = root.matches('[data-mid], [data-message-id]')
      ? root
      : root.querySelector('[data-mid], [data-message-id]');
    const id = idNode?.getAttribute('data-mid') ||
      idNode?.getAttribute('data-message-id') || root.id || '';
    messages.push({id, text, links});
  }
  return messages.slice(-100);
}
"""


@dataclass(frozen=True, slots=True)
class TelegramWebPageState:
    url: str
    title: str
    logged_in: bool
    chat_header: str
    message_count: int


class LoginRequiredError(RuntimeError):
    pass


class TargetChatOpenError(RuntimeError):
    pass


async def _visible(locator: Locator) -> bool:
    try:
        return await locator.count() > 0 and await locator.first.is_visible()
    except Exception:
        return False


async def telegram_web_is_logged_in(page: Page) -> bool:
    for selector in _LOGIN_SELECTORS:
        if await _visible(page.locator(selector)):
            return False
    return await _visible(page.locator("#column-left"))


async def capture_telegram_web_login_image(page: Page) -> bytes:
    for selector in _QR_SELECTORS:
        locator = page.locator(selector)
        if not await _visible(locator):
            continue
        try:
            return await locator.last.screenshot(type="png")
        except Exception:
            continue
    return await page.screenshot(type="png", full_page=True)


def reset_telegram_web_browser_profile(profile_dir: Path) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    for child in profile_dir.iterdir():
        if child.name in {"parcertg-seen.json", "diagnostics"}:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)


def telegram_web_chat_url(base_url: str, target_chat: str) -> str:
    target = target_chat.strip().removeprefix("@")
    address = quote(f"tg://resolve?domain={target}", safe="")
    return f"{base_url.rstrip('/')}/#?tgaddr={address}"


def _normalized(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _matches_target(value: str, target_chat: str) -> bool:
    value_normalized = _normalized(value)
    target_normalized = _normalized(target_chat.removeprefix("@"))
    without_bot = target_normalized.removesuffix("bot")
    return bool(
        target_normalized in value_normalized
        or without_bot in value_normalized
        or (
            target_normalized.startswith("telemetrio")
            and "telemetrio" in value_normalized
        )
    )


async def _chat_header(page: Page) -> str:
    for selector in _HEADER_SELECTORS:
        locator = page.locator(selector)
        if not await _visible(locator):
            continue
        try:
            value = (await locator.first.inner_text()).strip()
        except Exception:
            continue
        if value:
            return value
    return ""


async def extract_browser_messages(page: Page) -> list[TelegramWebMessage]:
    raw = await page.evaluate(_EXTRACT_MESSAGES_SCRIPT)
    return parse_browser_messages(raw) if isinstance(raw, list) else []


async def _search_target(page: Page, target_chat: str) -> bool:
    search_input: Locator | None = None
    for selector in _SEARCH_INPUT_SELECTORS:
        locator = page.locator(selector)
        if await _visible(locator):
            search_input = locator.first
            break
    if search_input is None:
        return False

    await search_input.click()
    await search_input.fill("@" + target_chat.removeprefix("@"))
    await page.wait_for_timeout(2500)
    for selector in _SEARCH_RESULT_SELECTORS:
        results = page.locator(selector)
        try:
            count = min(await results.count(), 30)
        except Exception:
            continue
        for index in range(count):
            result = results.nth(index)
            try:
                text = (await result.inner_text()).strip()
            except Exception:
                continue
            if _matches_target(text, target_chat):
                await result.click()
                await page.wait_for_timeout(5000)
                return True

    await search_input.press("Enter")
    await page.wait_for_timeout(5000)
    return _matches_target(await _chat_header(page), target_chat)


async def open_target_chat(page: Page, settings: Settings) -> None:
    target = settings.telegram_web_target_chat
    await page.goto(
        telegram_web_chat_url(settings.telegram_web_url, target),
        wait_until="domcontentloaded",
        timeout=60_000,
    )
    await page.wait_for_timeout(7000)
    if not await telegram_web_is_logged_in(page):
        raise LoginRequiredError("Telegram Web profile is not authorized")
    if _matches_target(await _chat_header(page), target):
        return
    if await extract_browser_messages(page):
        return
    if await _search_target(page, target):
        return
    raise TargetChatOpenError(f"Unable to open @{target}")


async def page_state(page: Page) -> TelegramWebPageState:
    return TelegramWebPageState(
        url=page.url,
        title=await page.title(),
        logged_in=await telegram_web_is_logged_in(page),
        chat_header=await _chat_header(page),
        message_count=len(await extract_browser_messages(page)),
    )


async def save_diagnostics(page: Page, profile_dir: Path) -> tuple[Path, Path]:
    directory = profile_dir / "diagnostics"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    screenshot = directory / f"telegram-web-{stamp}.png"
    state_file = directory / f"telegram-web-{stamp}.json"
    state = await page_state(page)
    await page.screenshot(path=str(screenshot), type="png", full_page=True)
    state_file.write_text(
        json.dumps(asdict(state), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return screenshot, state_file


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
        self._playwright = None
        self._context = None
        self._empty_polls = 0
        self._last_diagnostic_at = 0.0

    async def _start_browser(self) -> Page:
        self._playwright = await async_playwright().start()
        self._context = await launch_telegram_web_context(
            self.settings,
            self._playwright,
        )
        page = (
            self._context.pages[0]
            if self._context.pages
            else await self._context.new_page()
        )
        await page.goto(
            self.settings.telegram_web_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        await page.wait_for_timeout(5000)
        if not await telegram_web_is_logged_in(page):
            raise LoginRequiredError("Telegram Web profile is not authorized")
        await open_target_chat(page, self.settings)
        return page

    async def _bootstrap(self, messages: list[TelegramWebMessage]) -> bool:
        if self.store.initialized:
            return True
        if not messages:
            logger.warning("telegram_web_bootstrap_waiting_for_messages")
            return False
        if not self.settings.telegram_web_import_existing:
            for message in messages:
                self.store.add(message.key)
        self.store.mark_initialized()
        self.store.save()
        await self.notifier.bot.send_message(
            self.settings.target_chat_id,
            (
                "✅ <b>Telegram Web подключён</b>\n"
                "Диалог @TelemetrioAlertBot открыт. Новые уведомления "
                "будут обрабатываться автоматически."
            ),
        )
        return True

    async def _process(self, message: TelegramWebMessage) -> None:
        result = await self.processor.process(
            IncomingLead(
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
        )
        if result.status is ProcessingStatus.ACCEPTED and result.lead is not None:
            await self.notifier.send_lead(result.lead)
        logger.info(
            "telegram_web_alert_processed",
            status=result.status.value,
            score=result.score.score,
            message_key=message.key,
        )

    async def _poll(self, page: Page) -> None:
        messages = await extract_browser_messages(page)
        if not messages:
            self._empty_polls += 1
            if self._empty_polls == 1:
                state = await page_state(page)
                logger.warning("telegram_web_no_messages", **asdict(state))
            if self._empty_polls % 4 == 0:
                await open_target_chat(page, self.settings)
            should_save_diagnostics = (
                self._empty_polls >= 8
                and monotonic() - self._last_diagnostic_at > 300
            )
            if should_save_diagnostics:
                screenshot, state_file = await save_diagnostics(
                    page,
                    self.settings.telegram_web_profile_dir,
                )
                self._last_diagnostic_at = monotonic()
                logger.error(
                    "telegram_web_diagnostics_saved",
                    screenshot=str(screenshot),
                    state=str(state_file),
                )
            return

        self._empty_polls = 0
        if not await self._bootstrap(messages):
            return
        changed = False
        for message in messages:
            if self.store.contains(message.key):
                continue
            self.store.add(message.key)
            changed = True
            await self._process(message)
        if changed:
            self.store.save()

    async def _session(self) -> None:
        page = await self._start_browser()
        logger.info(
            "telegram_web_collector_started",
            target=self.settings.telegram_web_target_chat,
            **asdict(await page_state(page)),
        )
        while True:
            await self._poll(page)
            await asyncio.sleep(self.settings.telegram_web_poll_seconds)

    async def run(self) -> None:
        while True:
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except LoginRequiredError:
                logger.warning("telegram_web_login_required")
                await self.close_browser()
                await self.notifier.bot.send_message(
                    self.settings.target_chat_id,
                    (
                        "⚠️ Telegram Web не авторизован. Запустите:\n"
                        "<code>docker compose stop app</code>\n"
                        "<code>docker compose run --rm app python -m "
                        "scripts.telegram_web_login --reset</code>\n"
                        "<code>docker compose up -d app</code>"
                    ),
                )
                await asyncio.sleep(60)
            except Exception:
                logger.exception("telegram_web_collector_error")
                await self.close_browser()
                await asyncio.sleep(30)

    async def close_browser(self) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def close(self) -> None:
        self.store.save()
        await self.close_browser()
