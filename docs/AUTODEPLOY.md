# CI и автодеплой ParcerTG

После настройки каждый push в `main` проходит:

1. Ruff.
2. Компиляцию Python-модулей.
3. Pytest.
4. Проверку `scripts/deploy.sh`.
5. Проверку Docker Compose.
6. Сборку production Docker image.
7. Автоматический деплой на сервер по SSH.

Pull request запускает проверки кода, но не получает production-секреты и не
выполняет деплой.

## Как устроен деплой

Workflow `.github/workflows/deploy.yml` запускается только после успешного
workflow `CI` для push в ветку `main`.

На сервере выполняется `scripts/deploy.sh`, который:

- блокирует параллельный деплой через `flock`;
- проверяет, что разворачивается именно протестированный commit SHA;
- не перезаписывает `.env`;
- отказывается работать при локальных изменениях tracked-файлов;
- обновляет `main` только через `git pull --ff-only`;
- проверяет Docker Compose;
- пересобирает приложение;
- запускает контейнеры;
- проверяет, что `app` и `db` находятся в состоянии `running`;
- проверяет загрузку конфигурации внутри контейнера.

Если новый push появился раньше завершения предыдущего CI, устаревший деплой
увидит другой SHA в `origin/main` и завершится без развёртывания непроверенного
кода.

## 1. Подготовьте SSH-ключ для GitHub Actions

На сервере под пользователем, который будет выполнять деплой:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh

ssh-keygen \
  -t ed25519 \
  -f ~/.ssh/github_actions_parcertg \
  -N '' \
  -C 'github-actions-parcertg'

cat ~/.ssh/github_actions_parcertg.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Покажите приватный ключ и скопируйте всё содержимое, включая заголовок и конец:

```bash
cat ~/.ssh/github_actions_parcertg
```

После добавления ключа в GitHub приватный файл можно удалить с сервера. Для
входа серверу нужен только public key в `authorized_keys`:

```bash
rm ~/.ssh/github_actions_parcertg
```

Не удаляйте `github_actions_parcertg.pub` до завершения настройки, чтобы можно
было сверить ключ. Никогда не коммитьте приватный ключ.

## 2. Получите запись known_hosts

На сервере задайте публичный IP или DNS-имя, по которому GitHub будет
подключаться:

```bash
DEPLOY_HOST='SERVER_IP_OR_DOMAIN'
DEPLOY_PORT='22'
```

Для стандартного порта 22:

```bash
awk -v host="$DEPLOY_HOST" \
  '{print host " " $1 " " $2}' \
  /etc/ssh/ssh_host_ed25519_key.pub
```

Для нестандартного порта:

```bash
awk -v host="[$DEPLOY_HOST]:$DEPLOY_PORT" \
  '{print host " " $1 " " $2}' \
  /etc/ssh/ssh_host_ed25519_key.pub
```

Скопируйте получившуюся строку целиком. Workflow использует
`StrictHostKeyChecking=yes` и не доверяет неизвестному серверу автоматически.

## 3. Создайте GitHub Environment

В репозитории откройте:

```text
Settings → Environments → New environment → production
```

В environment `production` добавьте secrets:

| Secret | Значение |
|---|---|
| `DEPLOY_HOST` | публичный IP или DNS сервера |
| `DEPLOY_SSH_PRIVATE_KEY` | приватный ключ из предыдущего шага |
| `DEPLOY_KNOWN_HOSTS` | строка host key из предыдущего шага |

Добавьте variables:

| Variable | Пример |
|---|---|
| `DEPLOY_USER` | `root` |
| `DEPLOY_PORT` | `22` |
| `DEPLOY_PATH` | `/root/parcertg` |

Workflow имеет рабочие значения по умолчанию для пользователя, порта и пути,
но лучше задать их явно.

## 4. Проверьте серверный репозиторий

```bash
cd /root/parcertg
git checkout main
git pull --ff-only origin main
test -f .env
docker compose config --quiet
```

Локальные правки в tracked-файлах блокируют деплой. Все серверные секреты
должны находиться только в `.env`, который исключён из Git.

Проверьте права пользователя деплоя:

```bash
git status --short
docker compose version
docker ps
```

Если используется не `root`, пользователь должен владеть каталогом проекта и
иметь право запускать Docker.

## 5. Первый запуск

После добавления secrets можно запустить деплой вручную:

```text
GitHub → Actions → Deploy production → Run workflow
```

Далее деплой будет выполняться автоматически после каждого успешного CI в
`main`.

## 6. Рекомендуемая защита main

В `Settings → Branches` создайте правило для `main`:

- Require a pull request before merging.
- Require status checks to pass before merging.
- Выберите проверку `Test and lint`.
- Do not allow force pushes.
- Do not allow deletions.

Production environment можно дополнительно ограничить веткой `main`. Ручное
подтверждение деплоя включайте только если нужен контроль перед каждым
обновлением; без required reviewers деплой полностью автоматический.

## Диагностика

Локальная проверка серверного скрипта без обновления кода:

```bash
bash -n scripts/deploy.sh
```

Ручной деплой конкретного текущего SHA:

```bash
cd /root/parcertg
bash scripts/deploy.sh "$(git rev-parse origin/main)"
```

Логи приложения:

```bash
docker compose logs -f --tail=200 app
```

Состояние контейнеров:

```bash
docker compose ps
```

При ошибке workflow выводит последние 200 строк логов проблемного контейнера.
