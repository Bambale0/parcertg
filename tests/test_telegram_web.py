from app.telegram_web import (
    SeenMessageStore,
    extract_original_message_url,
    parse_browser_messages,
)


def test_browser_messages_use_dom_id_and_fallback_hash() -> None:
    messages = parse_browser_messages(
        [
            {
                "id": "123",
                "text": "Нужен разработчик Telegram-бота",
                "links": ["https://t.me/example/10"],
            },
            {
                "id": "",
                "text": "Нужен Python backend",
                "links": [],
            },
        ]
    )

    assert messages[0].key == "123"
    assert len(messages[1].key) == 64


def test_original_url_ignores_notification_bot_link() -> None:
    url = extract_original_message_url(
        (
            "https://t.me/telemetr_notif_bot",
            "https://t.me/freelance_chat/42",
        ),
        "telemetr_notif_bot",
    )

    assert url == "https://t.me/freelance_chat/42"


def test_seen_store_persists_and_limits_history(tmp_path) -> None:
    store = SeenMessageStore(tmp_path, limit=2)
    store.add("one")
    store.add("two")
    store.add("three")
    store.mark_initialized()
    store.save()

    restored = SeenMessageStore(tmp_path, limit=2)

    assert restored.initialized is True
    assert restored.contains("one") is False
    assert restored.contains("two") is True
    assert restored.contains("three") is True
