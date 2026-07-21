# ParcerTG — охотник за горячими лидами в Telegram

ParcerTG принимает заявки из нескольких источников, локально оценивает их по прозрачным правилам, удаляет дубли и отправляет только подходящие лиды в личного Telegram-бота.

Проект теперь запускается **без `api_id` и `api_hash`**. Самый дешёвый старт — бесплатный мониторинг Telemetrio и пересылка найденных уведомлений в ParcerTG. Когда качество лидов подтвердится, можно включить TGStat Callback или Telethon.

## Источники

| Провайдер | Стоимость старта | Как работает |
|---|---:|---|
| `manual` | 0 | Пересылка уведомлений Telemetrio/TGStat в бота или команда `/lead` |
| `tgstat` | по тарифу API Callback | TGStat отправляет новые совпадения на FastAPI webhook |
| `telethon` | 0 | Отдельный Telegram-аккаунт напрямую слушает каталог из 100 источников |

Провайдеры можно комбинировать: `SOURCE_PROVIDERS=manual,tgstat`.

## Возможности

- rule-based scoring от 0 до 100 без передачи сообщений в LLM;
- приоритет Python, FastAPI, Telegram-ботов, AI-интеграций, CRM, API и автоматизации;
- фильтрация резюме, рекламы услуг, обучения, бартера и работы «за процент»;
- точная и fuzzy-дедупликация между разными провайдерами;
- карточка лида с причинами оценки и ссылкой на оригинал;
- кнопки «Взял в работу», «Не подходит» и «Спам»;
- PostgreSQL в Docker и SQLite для локальной разработки;
- неблокирующая очередь TGStat webhook: сервер отвечает до обработки лида;
- готовый составной запрос TGStat, который занимает одну отслеживаемую тему;
- каталог из 100 Telegram-чатов и каналов для опционального Telethon-режима.

## Самый дешёвый запуск

### 1. Создайте бота

Создайте бота через `@BotFather`, откройте с ним диалог и узнайте свой numeric Telegram ID.

### 2. Заполните окружение

```bash
cp .env.example .env
```

Для бесплатного режима достаточно:

```env
BOT_TOKEN=...
ADMIN_IDS=123456789
NOTIFY_CHAT_ID=123456789
SOURCE_PROVIDERS=manual
```

### 3. Запустите

```bash
docker compose up -d --build
docker compose logs -f app
```

### 4. Настройте Telemetrio

Используйте готовые списки:

- `config/telemetr_keywords.txt`;
- `config/telemetr_minus_words.txt`;
- инструкция: [`docs/TELEMETR_SETUP.md`](docs/TELEMETR_SETUP.md).

Перешлите найденное уведомление из бота Telemetrio в ParcerTG. Сообщение будет оценено, сохранено и дедуплицировано. Низкий балл вернётся как диагностический ответ, а горячий лид — как полноценная карточка.

## Команды бота

```text
/start       справка
/check TEXT  только оценить текст
/lead TEXT   оценить и сохранить
/lead        в ответ на сообщение — обработать его
/stats       статистика за сегодня
/providers   активные провайдеры
```

Также можно просто переслать сообщение в бота — отдельная команда не нужна.

## TGStat Callback

TGStat Callback нужен только после проверки качества лидов. Он позволяет получать события из каналов и чатов на собственный URL.

1. Откройте внешний HTTPS-доступ к порту `8080`.
2. Добавьте в `.env`:

```env
SOURCE_PROVIDERS=manual,tgstat
TGSTAT_TOKEN=...
TGSTAT_WEBHOOK_SECRET=длинная_случайная_строка
PUBLIC_BASE_URL=https://leads.example.com
```

3. Перезапустите контейнер.
4. Получите код подтверждения callback:

```bash
docker compose run --rm app python -m scripts.tgstat_setup set-url
```

5. Добавьте показанный `TGSTAT_VERIFY_CODE` в `.env`, перезапустите и повторите `set-url`.
6. Создайте одну подписку по готовому составному запросу:

```bash
docker compose run --rm app python -m scripts.tgstat_setup subscribe
```

7. Проверьте состояние:

```bash
docker compose run --rm app python -m scripts.tgstat_setup status
```

Подробности: [`docs/TGSTAT_SETUP.md`](docs/TGSTAT_SETUP.md).

## Telethon — необязательный резерв

Telethon не требуется для бесплатного ручного режима и TGStat. Включайте его только если получите собственные MTProto-реквизиты:

```env
SOURCE_PROVIDERS=manual,telethon
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
TELEGRAM_SESSION=...
CHAT_SOURCES_FILE=config/sources.txt
```

Создание сессии:

```bash
docker compose run --rm app python -m scripts.generate_session
```

Аккаунт должен состоять в нужных группах. Недоступные источники логируются и не останавливают остальные.

## Скоринг

По умолчанию уведомление приходит при `MIN_LEAD_SCORE=65`.

- +30 — явно ищет разработчика или исполнителя;
- +20 — совпадение с целевым стеком;
- +18 — требуется разработка, интеграция или автоматизация;
- +15 — указан бюджет или готовность платить;
- +10 — есть срочность;
- отрицательные баллы — резюме, реклама услуг, курсы, бартер, работа за долю или только в офисе.

Правила находятся в `app/scoring.py`.

## Архитектура

```text
Telemetrio alert ──forward──┐
TGStat Callback ──webhook───┼──> LeadProcessor ──> scoring ──> dedup ──> PostgreSQL
Telethon chats ──MTProto────┘                                      │
                                                                    └──> aiogram bot
```

Все источники проходят через единый `LeadProcessor`, поэтому дубли между Telemetrio, TGStat и Telethon объединяются.

## Локальная разработка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
ruff check .
```

Для SQLite:

```env
DATABASE_URL=sqlite+aiosqlite:///./parcertg.db
```

## Безопасность

- сервис не пишет заказчикам автоматически;
- webhook защищён длинным секретом в URL;
- не публикуйте `.env`, `TGSTAT_TOKEN`, `TELEGRAM_SESSION` и `api_hash`;
- не используйте один `StringSession` одновременно в нескольких экземплярах;
- соблюдайте правила групп, условия поставщиков данных и требования к персональным данным.
