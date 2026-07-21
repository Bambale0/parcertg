# ParcerTG — охотник за горячими лидами в Telegram

ParcerTG принимает заявки из нескольких источников, локально оценивает их по
прозрачным правилам, удаляет дубли и отправляет только подходящие лиды в личного
Telegram-бота.

Проект запускается без `api_id` и `api_hash`. Основной бесплатный режим теперь
полностью автономный: Telemetr ищет упоминания, `@telemetr_notif_bot` присылает
уведомления, а сохранённая Telegram Web-сессия сама забирает их в ParcerTG.
Ручная пересылка не требуется.

## Источники

| Провайдер | Стоимость старта | Как работает |
|---|---:|---|
| `telegram_web` | 0 | Chromium читает новые уведомления `@telemetr_notif_bot` |
| `manual` | 0 | Ручная пересылка уведомлений или команда `/lead` |
| `tgstat` | по тарифу Callback API | TGStat отправляет совпадения на FastAPI webhook |
| `telethon` | 0 | Telegram-аккаунт напрямую слушает каталог из 100 источников |

Провайдеры можно комбинировать, например:

```env
SOURCE_PROVIDERS=telegram_web,manual
```

## Возможности

- автономный бесплатный сбор уведомлений Telemetr через Telegram Web;
- rule-based scoring от 0 до 100 без передачи сообщений в LLM;
- приоритет Python, FastAPI, Telegram-ботов, AI-интеграций, CRM, API и
  автоматизации;
- фильтрация резюме, рекламы услуг, обучения, бартера и работы «за процент»;
- точная и fuzzy-дедупликация между разными провайдерами;
- карточка лида с причинами оценки и ссылкой на оригинал;
- кнопки «Взял в работу», «Не подходит» и «Спам»;
- PostgreSQL в Docker и SQLite для локальной разработки;
- сохранение Telegram Web-сессии и списка уже обработанных уведомлений;
- TGStat Callback и Telethon как дополнительные провайдеры.

## Бесплатный автономный запуск

### 1. Создайте бота уведомлений

Создайте бота через `@BotFather`, откройте с ним диалог и узнайте свой numeric
Telegram ID.

### 2. Настройте мониторинг Telemetr

Создайте одно отслеживание и подключите уведомления к
`@telemetr_notif_bot`. Используйте готовые файлы:

- `config/telemetr_keywords.txt`;
- `config/telemetr_minus_words.txt`;
- [`docs/TELEMETR_SETUP.md`](docs/TELEMETR_SETUP.md).

Бесплатный Public API Telemetr не используется в основном потоке: тестовый
аккаунт читает только верифицированные источники, а нужные фриланс-чаты обычно
не верифицированы. Telegram Web читает уже готовую ленту мониторинга из одного
диалога и не расходует API-квоту Telemetr.

### 3. Подготовьте `.env`

```bash
cp .env.example .env
nano .env
```

Минимальная конфигурация:

```env
BOT_TOKEN=...
ADMIN_IDS=123456789
NOTIFY_CHAT_ID=123456789

SOURCE_PROVIDERS=telegram_web
TELEGRAM_WEB_PROFILE_DIR=/data/telegram-web
TELEGRAM_WEB_TARGET_CHAT=telemetr_notif_bot
TELEGRAM_WEB_POLL_SECONDS=15
TELEGRAM_WEB_IMPORT_EXISTING=false

DATABASE_URL=postgresql+asyncpg://parcertg:parcertg@db:5432/parcertg
MIN_LEAD_SCORE=65
```

### 4. Соберите образ

```bash
docker compose build --pull app
```

### 5. Один раз авторизуйте Telegram Web

Основной контейнер должен быть остановлен, чтобы браузерный профиль не был
занят:

```bash
docker compose stop app
docker compose run --rm app python -m scripts.telegram_web_login
```

QR-код придёт в вашего бота. На телефоне откройте:

```text
Telegram → Настройки → Устройства → Подключить устройство
```

Отсканируйте QR-код. После подтверждения запустите сервис:

```bash
docker compose up -d app
docker compose logs -f app
```

Полная инструкция:
[`docs/TELEGRAM_WEB_SETUP.md`](docs/TELEGRAM_WEB_SETUP.md).

### 6. Проверка

В боте:

```text
/providers
```

Ожидаемый источник:

```text
telegram_web
```

При первом запуске старая история уведомлений отмечается как прочитанная. Новые
уведомления Telemetr автоматически проходят через скоринг и дедупликацию.

## Команды бота

```text
/start       справка
/check TEXT  только оценить текст
/lead TEXT   оценить и сохранить
/lead        в ответ на сообщение — обработать его
/stats       статистика за сегодня
/providers   активные провайдеры
```

Ручная пересылка остаётся запасным способом, даже когда включён
`telegram_web`.

## TGStat Callback

TGStat Callback нужен после проверки качества лидов, когда потребуется более
стабильный официальный webhook.

```env
SOURCE_PROVIDERS=telegram_web,tgstat
TGSTAT_TOKEN=...
TGSTAT_WEBHOOK_SECRET=длинная_случайная_строка
PUBLIC_BASE_URL=https://leads.example.com
```

Настройка:

```bash
docker compose run --rm app python -m scripts.tgstat_setup set-url
docker compose run --rm app python -m scripts.tgstat_setup subscribe
docker compose run --rm app python -m scripts.tgstat_setup status
```

Подробности: [`docs/TGSTAT_SETUP.md`](docs/TGSTAT_SETUP.md).

## Telethon — необязательный резерв

Telethon включается только после получения собственных MTProto-реквизитов:

```env
SOURCE_PROVIDERS=telegram_web,telethon
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
TELEGRAM_SESSION=...
CHAT_SOURCES_FILE=config/sources.txt
```

Создание сессии:

```bash
docker compose run --rm app python -m scripts.generate_session
```

## Скоринг

По умолчанию уведомление приходит при `MIN_LEAD_SCORE=65`.

- +30 — явно ищет разработчика или исполнителя;
- +20 — совпадение с целевым стеком;
- +18 — требуется разработка, интеграция или автоматизация;
- +15 — указан бюджет или готовность платить;
- +10 — есть срочность;
- отрицательные баллы — резюме, реклама услуг, курсы, бартер, работа за долю
  или только в офисе.

Правила находятся в `app/scoring.py`.

## Архитектура

```text
Telemetr monitoring
        ↓
@telemetr_notif_bot
        ↓ Telegram Web + persistent Chromium profile
TelegramWebCollector
        ↓
LeadProcessor → scoring → dedup → PostgreSQL → aiogram bot

TGStat Callback ──webhook──┐
Telethon chats ──MTProto───┴──> тот же LeadProcessor
```

## Локальная разработка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
ruff check .
```

Для локального запуска Chromium вне Docker дополнительно выполните:

```bash
python -m playwright install chromium
```

## Безопасность

- сервис не пишет заказчикам автоматически;
- volume `telegram_web_data` содержит активную пользовательскую сессию;
- не публикуйте `.env`, browser profile, `TGSTAT_TOKEN`, `TELEGRAM_SESSION` и
  `api_hash`;
- не запускайте одновременно два Chromium-процесса с одним profile directory;
- Telegram Web-интеграция зависит от интерфейса сайта и может потребовать
  обновления селекторов после крупных изменений;
- соблюдайте правила групп, условия поставщиков данных и требования к
  персональным данным.
