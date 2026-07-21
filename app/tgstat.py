from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.ingestion import IncomingLead


def _telegram_url(raw: object) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip()
    if value.startswith("https://") or value.startswith("http://"):
        return value
    return "https://" + value.lstrip("/")


def _find_by_id(items: object, expected_id: object) -> dict[str, Any] | None:
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and str(item.get("id")) == str(expected_id):
            return item
    return next((item for item in items if isinstance(item, dict)), None)


def _sender_name(user: dict[str, Any] | None) -> str | None:
    if not user:
        return None
    parts = [
        user.get("first_name"),
        user.get("last_name"),
    ]
    name = " ".join(str(part).strip() for part in parts if part).strip()
    if name:
        return name
    fallback = user.get("name") or user.get("title")
    return str(fallback).strip() if fallback else None


def parse_tgstat_event(payload: dict[str, Any]) -> IncomingLead | None:
    if payload.get("event_type") != "new_post":
        return None

    post = payload.get("post")
    if not isinstance(post, dict):
        return None
    text = post.get("text")
    if not isinstance(text, str) or not text.strip():
        return None

    channel_id = post.get("channel_id")
    channel = _find_by_id(payload.get("channels"), channel_id)
    user_id = post.get("user_id")
    user = _find_by_id(payload.get("users"), user_id)

    timestamp = post.get("date")
    try:
        published_at = datetime.fromtimestamp(int(timestamp), tz=UTC)
    except (TypeError, ValueError, OSError):
        published_at = datetime.now(UTC)

    source_title = (
        str(channel.get("title")).strip()
        if channel and channel.get("title")
        else str(channel_id or "TGStat source")
    )
    source_username = None
    if channel and channel.get("username"):
        source_username = str(channel["username"]).removeprefix("@")

    sender_username = None
    if user and user.get("username"):
        sender_username = str(user["username"]).removeprefix("@")

    try:
        sender_id = int(user_id) if user_id is not None else None
    except (TypeError, ValueError):
        sender_id = None

    return IncomingLead(
        text=text,
        provider="tgstat",
        source_id=str(channel_id or source_username or source_title),
        source_title=source_title,
        source_username=source_username,
        message_id=str(post.get("id") or payload.get("event_id") or timestamp),
        message_url=_telegram_url(post.get("link")),
        published_at=published_at,
        sender_id=sender_id,
        sender_username=sender_username,
        sender_name=_sender_name(user),
    )
