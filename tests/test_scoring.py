from app.scoring import normalize_text, score_message


def test_hot_target_lead_scores_above_threshold() -> None:
    text = (
        "Срочно ищем разработчика. Нужно сделать Telegram-бота на Python, "
        "подключить CRM и OpenAI API. Есть ТЗ, бюджет 150 000 руб., начать на этой неделе."
    )
    result = score_message(text)
    assert result.score >= 80
    assert any("Явно ищет исполнителя" in reason for reason in result.reasons)
    assert any("целевым стеком" in reason for reason in result.reasons)


def test_resume_is_rejected() -> None:
    text = "Ищу работу Python-разработчиком. Рассматриваю вакансии, вот мое резюме."
    assert score_message(text).score < 30


def test_normalization_removes_links_and_noise() -> None:
    assert normalize_text("Привет!!! https://example.com  Нужен БОТ") == "привет нужен бот"
