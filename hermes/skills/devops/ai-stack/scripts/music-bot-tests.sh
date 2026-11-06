#!/usr/bin/env bash
# Полный прогон тестов музыкального бота (lyria) в изоляции — прод не трогается.
#
# Зачем так: на хосте python 3.14 и нет poetry/pipx, а проект целится в 3.12, поэтому
# `poetry run pytest` на хосте не заводится. Здесь поднимается временная docker-сеть
# со своими postgres/redis/rabbitmq, репозиторий монтируется READ-ONLY и копируется
# внутрь контейнера, так что рабочее дерево и .venv в нём не появляются.
#
# Повторяет CI (.github/workflows/ci.yml): ruff check, ruff format --check,
# alembic upgrade head, pytest в polling-режиме и в webhook-режиме.
#
#   bash music-bot-tests.sh              # полный прогон
#   REPO=/path/to/bot bash music-bot-tests.sh
#   KEEP=1 bash music-bot-tests.sh       # не удалять тестовые контейнеры (разбор)
set -uo pipefail

REPO="${REPO:-/root/deploy/music_bot}"
NET="mbtest-$$"
PREFIX="mbtest-$$"

cleanup() {
  if [ "${KEEP:-0}" = "1" ]; then
    echo "KEEP=1: контейнеры ${PREFIX}-* и сеть $NET оставлены"
    return
  fi
  docker rm -f "${PREFIX}-pg" "${PREFIX}-redis" "${PREFIX}-rabbit" >/dev/null 2>&1
  docker network rm "$NET" >/dev/null 2>&1
}
trap cleanup EXIT

docker network create "$NET" >/dev/null || { echo "не смог создать сеть $NET"; exit 1; }
docker run -d --name "${PREFIX}-pg" --network "$NET" \
  -e POSTGRES_USER=ci_user -e POSTGRES_PASSWORD=ci_password -e POSTGRES_DB=ci_test_db \
  postgres:17-alpine >/dev/null
docker run -d --name "${PREFIX}-redis" --network "$NET" redis:7-alpine >/dev/null
docker run -d --name "${PREFIX}-rabbit" --network "$NET" rabbitmq:3-management-alpine >/dev/null

ok=0
for _ in $(seq 1 30); do
  ok=0
  docker exec "${PREFIX}-pg" pg_isready -U ci_user -d ci_test_db >/dev/null 2>&1 && ok=$((ok+1))
  docker exec "${PREFIX}-redis" redis-cli ping >/dev/null 2>&1 && ok=$((ok+1))
  docker exec "${PREFIX}-rabbit" rabbitmq-diagnostics -q ping >/dev/null 2>&1 && ok=$((ok+1))
  [ "$ok" = 3 ] && break
  sleep 2
done
echo "сервисы: $ok/3"
# rabbitmq-diagnostics часто не успевает за 60 c и всё равно "ok" — тесты сами ждут брокер.

docker run --rm --network "$NET" -v "$REPO":/src:ro \
  -e BOT_TOKEN="1:test-token" -e OPENROUTER_API_KEY="test-key" -e BOT_ACCESS_KEY="key" \
  -e SONG_PRICE="1" -e BOT_OWNER_ID="0" -e MODEL_ID="google/lyria-3-pro-preview" -e MOCK_MODE="1" \
  -e REDIS_HOST="${PREFIX}-redis" -e REDIS_PORT=6379 -e REDIS_VAULT=0 \
  -e RABBITMQ_URL="amqp://guest:guest@${PREFIX}-rabbit:5672/" -e RABBITMQ_PREFETCH=10 \
  -e RABBITMQ_QUEUE_PREFIX=ci \
  -e POSTGRES_USER=ci_user -e POSTGRES_PASSWORD=ci_password -e POSTGRES_HOST="${PREFIX}-pg" \
  -e POSTGRES_PORT=5432 -e POSTGRES_DB=ci_test_db \
  -e WEBHOOK_BASE_URL="https://example.test" -e WEBHOOK_SECRET="ci-webhook-secret" \
  -e ENRICH_URL="" -e ENRICH_TOKEN="" -e ENRICH_MODEL="" \
  python:3.12-slim bash -c '
    set -e
    mkdir -p /work && cd /src
    tar --exclude=.git --exclude=__pycache__ --exclude=.venv -cf - . | (cd /work && tar xf -)
    pip install -q --disable-pip-version-check poetry
    cd /work && poetry config virtualenvs.create false
    poetry install --no-interaction --no-ansi 2>&1 | tail -2
    echo "=== ruff check";        poetry run ruff check . 2>&1 | tail -5
    echo "=== ruff format";       poetry run ruff format --check . 2>&1 | tail -3
    echo "=== alembic";           poetry run alembic upgrade head 2>&1 | tail -3
    echo "=== pytest polling";    WEBHOOK_MODE=0 poetry run pytest -q 2>&1 | tail -6
    echo "=== pytest webhook";    WEBHOOK_MODE=1 poetry run pytest -q 2>&1 | tail -6
  '
rc=$?
echo "=== тесты завершились с кодом $rc"
exit "$rc"
