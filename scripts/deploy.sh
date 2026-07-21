#!/usr/bin/env bash
set -Eeuo pipefail

EXPECTED_SHA="${1:-}"
APP_DIR="${DEPLOY_PATH:-$(pwd)}"
LOCK_FILE="${DEPLOY_LOCK_FILE:-/tmp/parcertg-deploy.lock}"

log() {
  printf '[deploy] %s\n' "$*"
}

fail() {
  printf '[deploy] ERROR: %s\n' "$*" >&2
  exit 1
}

command -v git >/dev/null 2>&1 || fail "git is not installed"
command -v docker >/dev/null 2>&1 || fail "docker is not installed"
command -v flock >/dev/null 2>&1 || fail "flock is not installed"

docker compose version >/dev/null 2>&1 || fail "docker compose plugin is unavailable"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  fail "another deployment is already running"
fi

cd "$APP_DIR"
[ -d .git ] || fail "$APP_DIR is not a Git repository"
[ -f docker-compose.yml ] || fail "docker-compose.yml is missing"
[ -f .env ] || fail ".env is missing; deployment will not create or overwrite secrets"

log "fetching origin/main"
git fetch --prune origin main
ORIGIN_SHA="$(git rev-parse origin/main)"

if [ -n "$EXPECTED_SHA" ] && [ "$ORIGIN_SHA" != "$EXPECTED_SHA" ]; then
  log "deployment skipped: tested SHA $EXPECTED_SHA was superseded by $ORIGIN_SHA"
  exit 0
fi

CURRENT_BRANCH="$(git branch --show-current)"
[ "$CURRENT_BRANCH" = "main" ] || fail "repository must be on main, found: $CURRENT_BRANCH"

if ! git diff --quiet || ! git diff --cached --quiet; then
  fail "working tree has tracked local changes; refusing to overwrite them"
fi

log "updating main with fast-forward only"
git pull --ff-only origin main
DEPLOYED_SHA="$(git rev-parse HEAD)"

if [ -n "$EXPECTED_SHA" ] && [ "$DEPLOYED_SHA" != "$EXPECTED_SHA" ]; then
  fail "checked out SHA $DEPLOYED_SHA does not match tested SHA $EXPECTED_SHA"
fi

log "validating Compose configuration"
docker compose config --quiet

log "building application image"
docker compose build --pull app

log "starting services"
docker compose up -d --remove-orphans

log "waiting for containers"
sleep 15

APP_CONTAINER="$(docker compose ps -q app)"
DB_CONTAINER="$(docker compose ps -q db)"
[ -n "$APP_CONTAINER" ] || fail "app container was not created"
[ -n "$DB_CONTAINER" ] || fail "db container was not created"

APP_STATUS="$(docker inspect --format '{{.State.Status}}' "$APP_CONTAINER")"
DB_STATUS="$(docker inspect --format '{{.State.Status}}' "$DB_CONTAINER")"

if [ "$APP_STATUS" != "running" ]; then
  docker compose logs --tail=200 app >&2 || true
  fail "app container status is $APP_STATUS"
fi

if [ "$DB_STATUS" != "running" ]; then
  docker compose logs --tail=200 db >&2 || true
  fail "db container status is $DB_STATUS"
fi

log "checking application configuration inside the running container"
docker compose exec -T app python -c \
  'from app.config import Settings; print(sorted(Settings().parsed_source_providers))'

log "deployment completed: $DEPLOYED_SHA"
docker compose ps
