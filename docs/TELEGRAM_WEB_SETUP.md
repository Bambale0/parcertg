# Автономный бесплатный режим через Telegram Web

Этот режим читает новые уведомления `@telemetr_notif_bot` из сохранённой
Telegram Web-сессии и передаёт их в общий `LeadProcessor`. Ручная пересылка,
`api_id`, `api_hash` и платный Callback API не нужны.

## Ограничения

- требуется один раз авторизовать собственный Telegram-аккаунт по QR-коду;
- профиль браузера хранит активную сессию и должен считаться секретом;
- интеграция зависит от интерфейса Telegram Web и после крупных обновлений
  интерфейса может потребовать корректировки селекторов;
- бесплатный лимит найденных упоминаний задаётся тарифом Telemetr;
- ParcerTG ничего не пишет в отслеживаемые чаты и не отвечает заказчикам сам.

## 1. Настройте мониторинг Telemetr

1. Создайте одно отслеживание на сайте Telemetr.
2. Используйте ключи из `config/telemetr_keywords.txt`.
3. Используйте исключения из `config/telemetr_minus_words.txt`.
4. В разделе мониторинга нажмите «Подключить» и прикрепите
   `@telemetr_notif_bot` к своему Telemetr-аккаунту.
5. Убедитесь, что тестовое уведомление появляется в этом диалоге.

## 2. Обновите `.env`

```env
SOURCE_PROVIDERS=telegram_web

TELEGRAM_WEB_PROFILE_DIR=/data/telegram-web
TELEGRAM_WEB_TARGET_CHAT=telemetr_notif_bot
TELEGRAM_WEB_URL=https://web.telegram.org/k/
TELEGRAM_WEB_POLL_SECONDS=15
TELEGRAM_WEB_LOGIN_TIMEOUT_SECONDS=600
TELEGRAM_WEB_IMPORT_EXISTING=false
```

`TELEGRAM_WEB_IMPORT_EXISTING=false` означает, что при первом подключении
текущая история будет отмечена как прочитанная. Обрабатываться будут только
новые уведомления. Это защищает от шквала старых лидов.

## 3. Пересоберите образ

```bash
git pull
docker compose build --pull app
```

Образ основан на официальном Playwright Python image и содержит Chromium.
Профиль браузера сохраняется в volume `telegram_web_data`.

## 4. Авторизуйте Telegram Web

Остановите основной контейнер, чтобы браузерный профиль не был заблокирован:

```bash
docker compose stop app
docker compose run --rm app python -m scripts.telegram_web_login
```

ParcerTG отправит свежий QR-код в чат уведомлений, заданный в
`NOTIFY_CHAT_ID`. На телефоне откройте:

```text
Telegram → Настройки → Устройства → Подключить устройство
```

Отсканируйте QR-код. После сообщения об успешном входе запустите сервис:

```bash
docker compose up -d app
docker compose logs -f app
```

## 5. Проверьте состояние

В боте выполните:

```text
/providers
```

Должен отображаться провайдер `telegram_web`.

В логах при успешном запуске появятся события:

```text
telegram_web_collector_started
telegram_web_history_baselined
```

После появления нового уведомления Telemetr:

```text
telegram_web_alert_processed
```

Горячий лид придёт обычной карточкой ParcerTG. Сообщения ниже
`MIN_LEAD_SCORE` сохраняться не будут.

## Повторная авторизация

Если Telegram завершил сессию, бот пришлёт инструкцию. Повторите:

```bash
docker compose stop app
docker compose run --rm app python -m scripts.telegram_web_login
docker compose up -d app
```

Не удаляйте volume `telegram_web_data`, иначе авторизация и список уже
прочитанных уведомлений будут потеряны.

## Сброс сессии

Только когда требуется полностью войти заново:

```bash
docker compose down
docker volume rm parcertg_telegram_web_data
docker compose up -d db
docker compose run --rm app python -m scripts.telegram_web_login
docker compose up -d app
```

Название volume может отличаться, если каталог проекта или Compose project
имеет другое имя. Проверьте его через `docker volume ls`.
