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

## 8. Re-reviewing his fixes (PR against the dev branch)

A follow-up PR is not a reading task either: the fix can pass review and still break the upgrade path. Same isolation, same probes, plus three checks the first pass does not need.

### Get the PR without a merge base

```bash
git fetch origin 'refs/pull/<n>/head:pr<n>' --depth 5
git fetch origin dev --depth 20
git diff --stat origin/dev pr<n>        # two explicit refs
```

A shallow clone has no merge base, so `git diff dev...pr<n>` dies with «no merge base» — diff the two refs directly. Read the diff of `src/` and `migrations/`, not the new tree; confirm each promised fix landed and nothing on the old happy path regressed.

### The migration must be proven as an upgrade

```bash
# old branch, real row in the DB
git checkout origin/dev && docker compose -p <proj> up -d --build
curl ... POST /payments            # leave data behind
docker compose -p <proj> down      # NO -v: keep the volume
git checkout pr<n> && docker compose -p <proj> up -d --build
docker compose -p <proj> logs api | grep -i alembic   # upgrade lines, not just create_all
docker compose -p <proj> exec -T api alembic current
docker compose -p <proj> exec -T postgres psql -U <u> -d <db> -tAc \
  "select indexname from pg_indexes where tablename in ('outbox','payments') order by 1"
```

Then GET the pre-existing row: it must still deserialise. A migration proven only on an empty database is the most common regression in these PRs. Look for dropped indexes recreated elsewhere, and for **`NOT NULL ... server_default` columns added to a populated table** — old rows silently get a value nobody chose (e.g. «webhook delivered» rows come back as `pending`), which is a review remark with a one-line `UPDATE` fix, not a blocker.

### Background job / retention probe

Insert synthetic rows instead of waiting days, then recreate the consumer with a short interval inline (shell env beats `.env` for interpolation):

```sql
insert into outbox (id,event_type,payload,status,created_at,processed_at) values
 (gen_random_uuid(),'payment.created','{}','processed', now()-interval '10 days', now()-interval '10 days'),
 (gen_random_uuid(),'payment.created','{}','processed', now(), now()),
 (gen_random_uuid(),'payment.created','{}','pending',   now()-interval '10 days', null);
```

```bash
OUTBOX_RETENTION_INTERVAL_SECONDS=5 docker compose -p <proj> up -d --force-recreate consumer
```

Expect: old processed gone, fresh processed kept, pending never deleted. Note the honest caveat — retention keyed on `created_at` deletes an old backlog immediately after it is published, which is safe but looks surprising in the log.

### New endpoint under concurrency

```bash
seq 1 3 | xargs -P3 -I@ curl -s -o /dev/null -w '@:%{http_code} ' \
  -X POST http://127.0.0.1:<port>/api/v1/payments/<id>/webhook/replay -H 'X-API-Key: <key>'
```

Expect exactly one `200`, the rest `409`, and **one** extra delivery in the receiver log. Three `200`s mean the advertised `FOR UPDATE` is decorative. Same for state-machine endpoints: unknown id → 404, wrong current state → 409, upstream failure → 502 with the attempt counter incremented.

### What to critique in round 2

- **External HTTP inside the transaction that holds `SELECT ... FOR UPDATE`.** The row lock and a pooled connection stay held for the whole backoff (attempts × timeout + waits), serialising replays and starving the pool. Correct shape: short read+check transaction → HTTP outside → short write with a state guard (`WHERE webhook_status='failed'`).
- **Swallowed status-write errors.** Logging and continuing is defensible, but check the resulting state is repairable: a payment left `pending` while the endpoint refuses replay for `pending` is a dead end — needs a retry or a broader replay guard.
- **Unbounded `DELETE`** in a retention job — batch it (`WHERE id IN (SELECT ... LIMIT n)`), otherwise one long statement locks a growing table.
- **README examples removed rather than fixed.** The ТЗ asks for examples; a Swagger link is not a replacement, and the original examples being sanitised (`***`, unbalanced quote) is not a reason to ship none.
- State plainly when a PR closes 4 of 5 findings: the merge verdict should name what was verified live, then the remaining ranked question. Do not re-litigate the first review.
