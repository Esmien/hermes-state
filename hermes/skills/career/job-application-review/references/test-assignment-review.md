# Take-home review — run the stack, don't grade the README

For a test assignment (ТЗ + repo) the verdict must rest on real execution. The plan below is the one that worked on a FastAPI + Postgres + RabbitMQ service; adapt names, keep the order.

## 1. Static pass (fast, before any container)

```bash
cd /root/.hermes/cache/scratch && git clone --branch <branch> --depth 1 <url> review
find . -path ./.git -prune -o -type f -print | head -60
```

Read only: models, outbox/relay, consumer, broker topology, docker-compose, migration, README, pyproject. Map every ТЗ requirement onto a file and note where it is missing — that list becomes the «чего не хватает» section.

Check the classic tells while reading: unique index on the idempotency column, `FOR UPDATE SKIP LOCKED` in the relay, `FOR UPDATE`/state guard in the consumer, DLX/DLQ args + binding routing key matching `x-dead-letter-routing-key`, healthchecks that hardcode credentials from elsewhere in the compose file, missing outbox retention/index, README examples that were sanitised into non-working form.

## 2. Isolate the stack on the VPS

Production already owns 5432/5672/8000. Override every published port through the compose file's own env vars and use a separate project name:

```bash
cd <repo> && cp .env.example .env   # then edit: creds, API_PORT=8005,
                                     # POSTGRES_HOST_PORT=55432,
                                     # RABBITMQ_HOST_PORT=5673,
                                     # RABBITMQ_MANAGEMENT_PORT=15673
touch /var/lib/docker-autorecover/pause          # detector must ignore test containers
docker compose -p paytest up -d --build
docker network inspect paytest_default --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}'
```

Write `.env` with write_file, never `cat` it, never echo the values.

## 3. Webhook receiver

A throwaway HTTP server on the host that accepts both outcomes (200 on `/hook`, 500 on `/fail`) and appends bodies to a log file; run it with `background=true`, probe with one curl before trusting it. Containers must call it at the **bridge gateway** IP from step 2 (`http://172.20.0.1:9099/hook`), not `127.0.0.1`.

## 4. Contract probes

```bash
# create
curl -s -X POST http://127.0.0.1:8005/api/v1/payments \
  -H 'X-API-Key: <key>' -H 'Content-Type: application/json' -H 'Idempotency-Key: order-1' \
  -d '{"amount":"100.00","currency":"RUB","description":"Order 1","metadata":{"order_id":"1"},"webhook_url":"http://172.20.0.1:9099/hook"}'
# poll GET until pending -> final; then check the receiver log
```

Then: replay same body (same id, 202), replay different body (409), no `Idempotency-Key` (422), no `X-API-Key` (401), oversized header (expect 422 — a 500 is a real bug worth naming), and a failing webhook URL followed by `rabbitmqctl list_queues name type messages_ready` after ~30 s.

Concurrency probe — one row or five?

```bash
seq 1 5 | xargs -P5 -I@ curl -s -o /dev/null -w '@:%{http_code} ' -X POST <url> ... \
  -d '{"amount":"7.00","currency":"USD","description":"race","metadata":{},"webhook_url":"..."}'
docker compose -p paytest exec -T postgres psql -U <user> -d <db> -tAc \
  "select count(*) from payments where idempotency_key='race-4';"
```

**`-I@`, never the default `-I{}`**: xargs substitutes `{}` inside the JSON body (`"metadata":{}` → `"metadata":2`) and every request comes back 422, which looks like a service bug for a minute. Same trap applies to any payload containing braces.

## 5. Run their own tests

No `uv` on the host — use a throwaway container on the **project network**, so the DB is reachable by service name:

```bash
docker run --rm --network paytest_default -v "$PWD":/app -w /app \
  -e TEST_DATABASE_URL='postgresql+asyncpg://<user>:<pw>@postgres:5432/<db>_test' \
  python:3.12-slim bash -c "pip install -q uv && uv sync --frozen && uv run pytest -q -rs 2>&1 | tail -15"
```

Same pattern for `uv run ruff check` and `uv run mypy src tests`. Report the counts (`113 passed`, `All checks passed`, `no issues found in N files`).

**Read the skip lines.** `-rs` is mandatory: `N passed, M skipped` with «PostgreSQL is not available» means the DB tests never ran, and a compose file that publishes on `127.0.0.1` cannot be reached through the bridge gateway — use the service name and rerun before claiming the suite passes.

## 6. Teardown

```bash
docker compose -p paytest down -v
rm -f /var/lib/docker-autorecover/pause
# stop the probe server (pkill -f hook_server.py kills its own wrapper — verify the port is free instead)
```

Leaving a `-p paytest` stack or the pause marker behind turns the next incident review into noise.

## 7. Reading the result like an interviewer

Classify each finding, because the weight differs:

- **Proven working** — say what you ran and what came back; that is the strongest paragraph in the review.
- **Outright bug** — reproducible status code, one-line fix (missing header length limit → 500 on insert is the archetype).
- **Design hole** — name the failure mode and the question it invites: crash between gateway call and commit → double charge; webhook lost after 3 attempts → «как доставить через сутки?»; outbox table grows forever; relay inside the consumer process; no row lock when consumers are scaled.
- **Doc decay** — broken curl examples, port numbers contradicting `.env.example`, healthchecks hardcoding credentials. Cheap to fix, and reviewers notice.
- **Over-engineering** — 2k LOC of Protocols/UoW for two endpoints is a real remark, phrase it as a trade-off, not a defect.

Verdict wording follows the umbrella's rule: «крепко, но…» with the ranked holes, or «отправлять нельзя» if the top bug is on the happy path. Close with an offer to open a PR for the top one or two fixes.
