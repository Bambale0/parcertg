from __future__ import annotations

import os

from telethon.sessions import StringSession
from telethon.sync import TelegramClient


def main() -> None:
    api_id = int(os.getenv("TELEGRAM_API_ID") or input("TELEGRAM_API_ID: ").strip())
    api_hash = os.getenv("TELEGRAM_API_HASH") or input("TELEGRAM_API_HASH: ").strip()

    print("Telegram отправит код подтверждения в приложение или по SMS.")
    with TelegramClient(StringSession(), api_id, api_hash) as client:
        print("\nСкопируйте строку ниже в TELEGRAM_SESSION и храните как пароль:\n")
        print(client.session.save())


if __name__ == "__main__":
    main()
