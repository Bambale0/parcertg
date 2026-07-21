from app.dedup import fingerprint, similarity


def test_fingerprint_ignores_case_links_and_punctuation() -> None:
    left = "Нужен Telegram-бот! https://example.com"
    right = "нужен telegram бот"
    assert fingerprint(left) == fingerprint(right)


def test_similar_reposts_are_detected() -> None:
    left = "Ищем разработчика: нужен Telegram бот с CRM и оплатой. Бюджет обсуждается."
    right = "Ищем разработчика. Нужен Telegram-бот с CRM и оплатой, бюджет обсуждается"
    assert similarity(left, right) >= 90
