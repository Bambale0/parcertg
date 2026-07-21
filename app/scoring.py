from __future__ import annotations

import re
from dataclasses import dataclass

SPACE_RE = re.compile(r"\s+")
URL_RE = re.compile(r"https?://\S+|t\.me/\S+", re.IGNORECASE)
PUNCT_RE = re.compile(r"[^\w\sа-яё+#]", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    points: int
    patterns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScoreResult:
    score: int
    reasons: tuple[str, ...]
    normalized_text: str


POSITIVE_RULES: tuple[Rule, ...] = (
    Rule(
        "Явно ищет исполнителя",
        30,
        (
            r"\bищ(?:у|ем)\s+(?:разработчика|программиста|исполнителя|специалиста|подрядчика)",
            r"\bнуж(?:ен|на|ны)\s+(?:разработчик|программист|исполнитель|специалист|подрядчик)",
            r"\bкто\s+(?:может|сможет|возьм[её]тся)\s+(?:сделать|разработать|реализовать|написать)",
            r"\bесть\s+(?:задача|заказ|проект)\b",
        ),
    ),
    Rule(
        "Нужна разработка или автоматизация",
        18,
        (
            r"\bнужн[оаы]\s+(?:сделать|разработать|реализовать|написать|доработать|интегрировать)",
            r"\bавтоматизац(?:ия|ию|ировать)\b",
            r"\bинтеграц(?:ия|ию|ировать)\b",
            r"\bразработк(?:а|у|ой)\b",
        ),
    ),
    Rule(
        "Совпадает с целевым стеком",
        20,
        (
            r"\bpython\b",
            r"\bfastapi\b",
            r"\baiogram\b",
            r"\btelegram[- ]?(?:бот|bot|mini\s*app)\b",
            r"\b(?:бот|бота|ботом)\s+(?:для|в|на)\s+telegram\b",
            r"\bopenai\b|\bclaude\b|\bllm\b|\brag\b|\bии[- ]?(?:агент|ассистент|бот)\b",
            r"\bcrm\b|\bapi\b|\bwebhook\b|\bвебхук\b",
            r"\bpostgres(?:ql)?\b|\bredis\b|\bdocker\b",
            r"\bпарсер\b|\bbackend\b|\bбэкенд\b",
        ),
    ),
    Rule(
        "Описана конкретная задача",
        12,
        (
            r"\b(?:тз|техническое задание|функционал|требования)\b",
            r"\b(?:должен|должна|должно|требуется)\b",
            r"\b(?:принимать|отправлять|считать|подключить|настроить|обрабатывать|хранить)\b",
        ),
    ),
    Rule(
        "Есть бюджет или готовность платить",
        15,
        (
            r"\bбюджет\b",
            r"\bоплат(?:а|ить|им|ой)\b",
            r"\b\d[\d\s]{2,}\s*(?:₽|руб|р\.?|usd|\$|евро|€)\b",
            r"\bстоимость\s+(?:обсуждается|договорная)\b",
        ),
    ),
    Rule(
        "Есть срочность",
        10,
        (
            r"\bсрочно\b",
            r"\bкак\s+можно\s+скорее\b",
            r"\bна\s+этой\s+неделе\b",
            r"\bсегодня\b|\bзавтра\b",
            r"\bбыстрый\s+старт\b",
        ),
    ),
    Rule(
        "Есть контакт для связи",
        5,
        (
            r"@[a-z0-9_]{5,}",
            r"\b(?:лс|личк[ауе]|директ)\b",
            r"\bпишите\b|\bсвяжитесь\b",
        ),
    ),
)

NEGATIVE_RULES: tuple[Rule, ...] = (
    Rule(
        "Исполнитель ищет работу",
        -45,
        (
            r"\bищу\s+(?:работу|вакансию|заказы|проект)\b",
            r"\bрассматриваю\s+(?:вакансии|предложения)\b",
            r"\bмо[её]\s+резюме\b|\bрезюме\s*[:—-]",
            r"\bготов\s+(?:взяться|подключиться|рассмотреть)\b",
        ),
    ),
    Rule(
        "Реклама услуг или обучения",
        -35,
        (
            r"\bоказываю\s+услуги\b|\bпредлагаю\s+услуги\b",
            r"\bкурс\b|\bобучение\b|\bмарафон\b|\bвебинар\b",
            r"\bнабираю\s+(?:учеников|наставляемых)\b",
        ),
    ),
    Rule(
        "Неподходящие условия",
        -25,
        (
            r"\bза\s+(?:долю|процент|идею)\b",
            r"\bоплата\s+после\s+(?:прибыли|запуска|результата)\b",
            r"\bбартер\b|\bбез\s+оплаты\b|\bбесплатн(?:о|ая|ый)\b",
        ),
    ),
    Rule(
        "Только офис",
        -20,
        (
            r"\bтолько\s+(?:офис|офлайн)\b",
            r"\bработа\s+в\s+офисе\b",
            r"\bрелокац(?:ия|ию)\b",
        ),
    ),
)


def normalize_text(text: str) -> str:
    value = text.lower().replace("ё", "е")
    value = URL_RE.sub(" ", value)
    value = PUNCT_RE.sub(" ", value)
    return SPACE_RE.sub(" ", value).strip()


def _matches(rule: Rule, text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in rule.patterns)


def score_message(text: str) -> ScoreResult:
    normalized = normalize_text(text)
    score = 0
    reasons: list[str] = []

    for rule in (*POSITIVE_RULES, *NEGATIVE_RULES):
        if _matches(rule, normalized):
            score += rule.points
            sign = "+" if rule.points > 0 else ""
            reasons.append(f"{sign}{rule.points}: {rule.name}")

    if len(normalized) < 25:
        score -= 15
        reasons.append("-15: Слишком мало контекста")
    elif len(normalized) >= 120:
        score += 5
        reasons.append("+5: Подробное описание")

    return ScoreResult(
        score=max(0, min(100, score)),
        reasons=tuple(reasons),
        normalized_text=normalized,
    )
