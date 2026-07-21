from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings

API_BASE = "https://api.tgstat.ru"


def _read_query(path: Path) -> str:
    parts: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", maxsplit=1)[0].strip()
        if line:
            parts.append(line)
    query = " ".join(parts).strip()
    if not query:
        raise ValueError(f"TGStat query file is empty: {path}")
    return query


async def _request(
    client: httpx.AsyncClient,
    method: str,
    endpoint: str,
    *,
    token: str,
    data: dict[str, object] | None = None,
) -> dict[str, Any]:
    payload = {"token": token, **(data or {})}
    response = await client.request(
        method,
        f"{API_BASE}{endpoint}",
        data=payload if method == "POST" else None,
        params=payload if method == "GET" else None,
    )
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise RuntimeError("TGStat returned a non-object response")
    return result


async def set_callback_url(
    client: httpx.AsyncClient,
    settings: Settings,
    callback_url: str | None,
) -> None:
    url = callback_url or settings.tgstat_callback_url
    result = await _request(
        client,
        "POST",
        "/callback/set-callback-url",
        token=settings.tgstat_token or "",
        data={"callback_url": url},
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    verify_code = result.get("verify_code")
    if verify_code:
        print(
            "\nДобавьте в .env строку:\n"
            f"TGSTAT_VERIFY_CODE={verify_code}\n"
            "Перезапустите контейнер и повторите команду set-url."
        )


async def subscribe(
    client: httpx.AsyncClient,
    settings: Settings,
    query_file: Path | None,
    subscription_id: int | None,
) -> None:
    query = _read_query(query_file or settings.tgstat_query_file)
    data: dict[str, object] = {
        "q": query,
        "event_types": "new_post",
        "strong_search": 0,
        "extended_syntax": 1,
        "peer_types": "all",
    }
    active_subscription_id = subscription_id or settings.tgstat_subscription_id
    if active_subscription_id is not None:
        data["subscription_id"] = active_subscription_id

    result = await _request(
        client,
        "POST",
        "/callback/subscribe-word",
        token=settings.tgstat_token or "",
        data=data,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    response = result.get("response")
    if isinstance(response, dict) and response.get("subscription_id"):
        print(
            "\nСохраните ID подписки в .env:\n"
            f"TGSTAT_SUBSCRIPTION_ID={response['subscription_id']}"
        )


async def status(client: httpx.AsyncClient, settings: Settings) -> None:
    callback_info = await _request(
        client,
        "GET",
        "/callback/get-callback-info",
        token=settings.tgstat_token or "",
    )
    subscriptions = await _request(
        client,
        "GET",
        "/callback/subscriptions-list",
        token=settings.tgstat_token or "",
    )
    print(
        json.dumps(
            {
                "callback": callback_info,
                "subscriptions": subscriptions,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


async def async_main() -> None:
    parser = argparse.ArgumentParser(description="Configure TGStat Callback for ParcerTG")
    subparsers = parser.add_subparsers(dest="command", required=True)

    set_url_parser = subparsers.add_parser("set-url")
    set_url_parser.add_argument("--callback-url")

    subscribe_parser = subparsers.add_parser("subscribe")
    subscribe_parser.add_argument("--query-file", type=Path)
    subscribe_parser.add_argument("--subscription-id", type=int)

    subparsers.add_parser("status")
    args = parser.parse_args()

    settings = Settings()  # type: ignore[call-arg]
    if not settings.tgstat_token:
        raise SystemExit("TGSTAT_TOKEN is required")

    async with httpx.AsyncClient(timeout=20.0) as client:
        if args.command == "set-url":
            await set_callback_url(client, settings, args.callback_url)
        elif args.command == "subscribe":
            await subscribe(
                client,
                settings,
                args.query_file,
                args.subscription_id,
            )
        elif args.command == "status":
            await status(client, settings)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
