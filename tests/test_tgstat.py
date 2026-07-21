from datetime import UTC, datetime

from app.tgstat import parse_tgstat_event


def test_parse_tgstat_chat_event() -> None:
    payload = {
        "event_id": 848132,
        "event_type": "new_post",
        "post": {
            "id": 13_884_852_683,
            "date": 1_603_693_772,
            "link": "t.me/example_chat/439029",
            "channel_id": 2321,
            "user_id": 991,
            "text": "Нужен Python разработчик для Telegram-бота. Бюджет 80 000 руб.",
        },
        "channels": [
            {
                "id": 2321,
                "username": "@example_chat",
                "title": "Example chat",
            }
        ],
        "users": [
            {
                "id": 991,
                "username": "@customer",
                "first_name": "Ivan",
            }
        ],
    }

    incoming = parse_tgstat_event(payload)

    assert incoming is not None
    assert incoming.provider == "tgstat"
    assert incoming.source_title == "Example chat"
    assert incoming.source_username == "example_chat"
    assert incoming.sender_username == "customer"
    assert incoming.message_url == "https://t.me/example_chat/439029"
    assert incoming.published_at == datetime.fromtimestamp(1_603_693_772, tz=UTC)


def test_non_new_post_event_is_ignored() -> None:
    assert parse_tgstat_event({"event_type": "edit_post"}) is None
