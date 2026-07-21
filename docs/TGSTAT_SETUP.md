# TGStat Callback

TGStat Callback отправляет события на FastAPI webhook ParcerTG. Проект использует одну keyword-подписку с расширенным запросом из `config/lead_query.tgstat` и `peer_types=all`, то есть ищет одновременно по каналам и чатам.

## Требования

- тариф TGStat с доступом к API Callback;
- персональный API-токен;
- публичный HTTPS URL;
- открытый порт приложения или reverse proxy на `WEB_PORT`.

## Переменные окружения

```env
SOURCE_PROVIDERS=manual,tgstat
TGSTAT_TOKEN=...
TGSTAT_WEBHOOK_SECRET=...
TGSTAT_VERIFY_CODE=
TGSTAT_QUERY_FILE=config/lead_query.tgstat
TGSTAT_SUBSCRIPTION_ID=
PUBLIC_BASE_URL=https://leads.example.com
WEB_PORT=8080
```

Создать секрет:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Итоговый callback URL формируется автоматически:

```text
https://leads.example.com/webhooks/tgstat/<TGSTAT_WEBHOOK_SECRET>
```

## Установка callback URL

Первый вызов нужен для получения `verify_code`:

```bash
docker compose run --rm app python -m scripts.tgstat_setup set-url
```

TGStat вернёт код. Добавьте его в `.env`:

```env
TGSTAT_VERIFY_CODE=TGSTAT_VERIFY_CODE_...
```

Перезапустите приложение и повторите команду:

```bash
docker compose up -d --build
docker compose run --rm app python -m scripts.tgstat_setup set-url
```

## Создание подписки

```bash
docker compose run --rm app python -m scripts.tgstat_setup subscribe
```

Сохраните возвращённый ID:

```env
TGSTAT_SUBSCRIPTION_ID=1234
```

При повторном `subscribe` существующая подписка будет отредактирована, а не продублирована.

## Диагностика

```bash
docker compose run --rm app python -m scripts.tgstat_setup status
curl https://leads.example.com/health
```

Webhook сначала кладёт событие в локальную очередь и сразу отвечает HTTP 202. Скоринг, запись в БД и отправка карточки выполняются фоновым worker-процессом. При переполнении очереди сервер отвечает 503, чтобы TGStat повторил доставку.

## Настройка запроса

Запрос хранится в `config/lead_query.tgstat`. Он использует расширенный синтаксис: группы, оператор ИЛИ, точные фразы и исключения. Перед боевым запуском его полезно проверить в поиске публикаций TGStat с включённым расширенным языком.
