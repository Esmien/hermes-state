---
name: ai-stack
description: "Use when working with the AI service stack on this VPS."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [devops, ai-stack, litellm, open-webui, searxng, postgres, docker, deploy]
---

# AI Stack (this VPS)

## When to Use

Load this skill whenever the task touches the AI service stack on this VPS — LiteLLM, Open WebUI, SearXNG, open-terminal, **the music bot (lyria)**, the host PostgreSQL, Nginx/Certbot TLS, `deploy.sh`, or the `backups/` dumps. It tells you where the stack lives and how to operate it.

LiteLLM / Open WebUI / SearXNG / open-terminal on PostgreSQL 17 + pgvector (host) behind Nginx+Certbot. **The music bot (lyria) is a separate deployment** — own containers, own Postgres, not covered by `deploy.sh` or the `postgres-backup` timers → [references/music-bot-lyria.md](references/music-bot-lyria.md). **Its code is off-limits:** state checks, test runs and commits/pushes of what is already in the tree only; report defects as a list, fix on an explicit separate instruction. Git as `ai_service` → [references/repo-hygiene.md](references/repo-hygiene.md).

## Location — IMPORTANT

The stack lives at **`/home/ai_service/ai-stack`** on the host. Owner: user `ai_service`.

- The host root is mounted **directly as `/`** — this agent runs on the host root, NOT in a container with a bind. **`/mnt/host` does not exist on the host**; never prefix host paths with it.
- **`/mnt/host` exists only inside `open-terminal`**, and recreating a stack container from that shell with `/mnt/host` paths mounts an auto-created empty directory over a file (`IsADirectoryError` loop) → [references/operations.md](references/operations.md).

## Layout

```
/home/ai_service/ai-stack/
  deploy.sh              one-command full deploy (bash, needs sudo)
  ai/
    docker-compose.yml   compose project "ai", network stack-net
    .env                 secrets (NEVER cat — grep keys only)
    litellm/config.yaml  gateway settings ONLY (drop_params: true, forward_client_headers, router_settings); model routing lives in litellm_db, not here
    searxng/             settings.yml, limiter.toml, engines/
    webui-branding/      Dockerfile for esmien/webui:local (ARG OPENWEBUI_BASE digest + rebrand sed) and the generated assets; RESTORE_WEBUI.md sits next to it
    backup-databases.sh  pg_dump → encrypt (dump-crypto) helper
  backups/               postgres dumps, nginx/certbot archives
    postgres/<db>_<ts>.dump.enc   AES-256 encrypted, key /etc/backup-crypto.key; retention: newest 3 per DB
  backup-deploy/         previous configs (.old, nginx/, caddy/)
```

## Services (docker compose project `ai`)

| Container | Image | Role |
|---|---|---|
| litellm | ghcr.io/berriai/litellm:**v1.108.8** — LTS line (`:lts` resolves here; bumped from 1.106.6 on 2026-11-14, rollback image `:rollback-1.106.6`) — why pinning, channels and how to bump: `references/updates.md` | LLM gateway/proxy |
| litellm-redis | redis:7-alpine, `--requirepass` from `${LITELLM_REDIS_PASSWORD}`, `--maxmemory 256mb --maxmemory-policy noeviction`, no published port | LiteLLM state store (auth cache, rate-limit/token counters, router cooldowns) |
| open-webui | esmien/webui:local (built locally from `ai/webui-branding/`, derived from OWUI 0.13.3) | chat UI, rebranded «Esmien AI» |
| searxng | searxng/searxng:latest | web search |
| playwright | mcr.microsoft.com/playwright:**v1.60.0-noble** (`npx playwright@1.60.0 run-server --port 3000`, `ipc: host`, только `stack-net`) | headless Chromium для загрузки страниц: WebUI рендерит JS вместо «пустая страница». Версия образа обязана совпадать с python-пакетом `playwright` в образе WebUI — проверять `docker exec open-webui python -c "import importlib.metadata as m; print(m.version('playwright'))"` перед бампом |
| open-terminal | ghcr.io/open-webui/open-terminal:latest | web terminal |
| — (удалена 2026-11-09) | — | Общая песочница `open-terminal-sandbox` удалена вместе с образом, томами и `sandbox_files`; ядро с тулчейном отменено. Каждый пользователь получает свой контейнер `ot-u-<slug>` (шаблон + provisioner + таймер). `references/sandbox-terminal.md`: действующая схема в начале, ниже — история решений и грабель |

> `cptr` (`ghcr.io/open-webui/computer`) was removed on the owner's instruction — container, image, data dir, compose block, `deploy.sh`, nginx vhost + cert, boot list. Nothing should reintroduce it → [references/operations.md](references/operations.md).
> **open-terminal memory** (heap ratchets, 2g cap, nightly restart): `references/disk-and-memory.md`.
> **beszel** (`mon.esmien.ru:8090`) is a SEPARATE compose — live at `/home/ai_service/beszel` (hub + agent, `network_mode: host`, own `.env` with `TOKEN`/`KEY` that never enters git); the tracked copy of its compose lives in `ai/beszel/`. Not covered by `deploy.sh`.

- **PostgreSQL 17 + pgvector runs on the HOST** (apt, pgdg repo) — not in compose.
- **Nginx** = TLS terminator (replaced caddy); **Certbot** issues/renews certs.
- Only 80/443 are deliberate ingress and the compose backends bind 127.0.0.1 — but **that is a per-service setting, not a host guarantee**: host PostgreSQL 17 listens on `0.0.0.0:5432`, now guarded by `/usr/local/bin/fw-guard-postgres.sh` + `fw-guard-postgres.service`. **Never answer «что у нас наружу» from `docker ps` alone** → [references/operations.md](references/operations.md), skill `vps-network-exposure`.

## Domains → backend

Both zones run in parallel until the owner moves the family, so old and new names point at one backend (`esmien.qd.je` = free DNS with failing authoritatives, see `vpn-entry-stack`; `esmien.ru` = owned, on Cloudflare). **Read the actual state off disk before trusting this:** on 2026-11-09 `grep -rl qd.je /etc/nginx/{sites-enabled,conf.d}` returned nothing and `deploy.sh` targeted `.ru` only, i.e. the `qd.je` half was already dead there:

```
ai.esmien.ru    -> 127.0.0.1:8080  (open-webui — единственный вход) | ai.esmien.qd.je
app.esmien.ru   -> 301 на ai.esmien.ru (не второй вход)          | —
llm.esmien.ru   -> 127.0.0.1:4000  (litellm)      | llm.esmien.qd.je
bot.esmien.ru   -> 127.0.0.1:8000  (music bot)    | bot.esmien.qd.je
mon.esmien.ru   -> 127.0.0.1:8090  (beszel hub)      | mon.esmien.qd.je
vpn.esmien.ru:8443 (VPN entry)                    | vpn.esmien.qd.je:8443
```

- **`app.esmien.ru` is not a second entry, it is a `301`** to `ai` (path + query kept, no proxying, no limits) — two names for one WebUI = two cookie sessions.
- **The orange cloud is a two-sided switch — read its state from the zone, never from this file** (последнее состояние: `ai`/`app` серые — оранжевый эксперимент прямой путь не починил и снят по просьбе владельца, разбор идёт пакетным замером). Grey fixes the tunnel path but leaves the owner's ISP to reach the origin on 443 itself, so «вебуи не открывается БЕЗ впн» arrives within days; orange fixes the direct path but the edge can challenge our own exits. Read the zone (`proxied` + `modified_on`) and the request sequence in `access.log` (a reload loop = flaky path, not a broken app) **before** touching nginx. Never add a WAF skip «на всякий случай»: measure first — dial the host from a socks client built on the `p15`/`p17` outbounds, and `200` through the edge means no rule is needed. Un-oranging is **two** actions — drop the `if ($deny_direct) { return 403; }` gate first, then `PATCH {"proxied":false}` → [references/cloudflare-proxy.md](references/cloudflare-proxy.md).
- Vhost edits: `write_file` refuses `/etc/nginx` (stage in scratch, `cp`); after `systemctl reload nginx` the first `curl` may still hit the old worker — repeat it, don't roll back.
- New name: grey A record answering from two resolvers (orange ⇒ HTTP-01 `530`), cert via port-80 ACME stub + `certbot certonly --webroot`, then a vhost copied from an existing one, verify `200 cert=0`. Procedures and rollback → [references/cloudflare-proxy.md](references/cloudflare-proxy.md).

## Cross-cutting rules and the expensive traps

Full text → [references/cross-cutting-rules.md](references/cross-cutting-rules.md)

## Deploy

```bash
cd /home/ai_service/ai-stack
sudo ./deploy.sh                 # full deploy
sudo ./deploy.sh --skip-restore  # containers/roles only, leave DBs
sudo ./deploy.sh --skip-tls      # stack only, leave nginx/certbot
sudo ./deploy.sh --force-stale   # allow dumps older than STALE_HOURS
```

## .env keys (values are secret — never print)

`LITELLM_MASTER_KEY`, `LITELLM_REDIS_PASSWORD` (generated `openssl rand -hex 32`, used by both the `litellm` and `litellm-redis` services), `LITELLM_DB_PASSWORD`, `WEBUI_DB_PASSWORD`, `WEBUI_SECRET_KEY`, `WEBUI_URL` (drives the compose `WEBUI_URL`; no hardcoded domain), `OPENROUTER_API_KEY`, `OPEN_TERMINAL_API_KEY`, `SEARXNG_SECRET_KEY`, `UI_USERNAME`, `UI_PASSWORD`, `GITHUB_KEY`, `ENABLE_ADMIN_CHAT_ACCESS`, `ENABLE_DIRECT_INTEGRATIONS`.

Removed in the `vps-infra` migration and **not** to be reintroduced: `DOMAIN`, `BOT_DB_PASSWORD`, `POSTGRES_ADMIN_PASSWORD`. Gone with the deleted sandbox (2026-11-09): `OPEN_TERMINAL_SANDBOX_API_KEY` — do not add it back expecting a reader. Live set is **14 names**; check the list against `grep -oE '^[A-Z_]+=' ai/.env` (names only, never values).

`UI_PASSWORD` is the **LiteLLM** admin password. The Open WebUI admin password is separate — see `references/owui-admin-auth.md`. The Admin UI's «Environment-credential login is enabled» banner is a task, not a hole: prove the DB admin first, then `disable_env_credential_login: true`; never delete the pair — inert and the documented rollback → [references/litellm-admin-auth.md](references/litellm-admin-auth.md). Two bots carry Telegram notifications, neither implies the other — verify each with `getMe` → [references/backups-notifications.md](references/backups-notifications.md).

## Answering the owner

Full text → [references/answering-the-owner.md](references/answering-the-owner.md)

## The traps that cost the most

Verbatim from `references/cross-cutting-rules.md` — the full list of rules and traps lives there.

- **Начало согласованной работы — действие, а не отчёт о проверке.** Выполняй разрешённые шаги и проверки до завершения оговорённого этапа; останавливайся только на реальном блокере или отдельном гейте владельца. Проверка сама по себе не равна реализации. Если владелец просит сохранить прогресс перед продолжением, сначала запиши актуальное состояние, проверенные результаты, незавершённые проверки и точку отката в план, а затем продолжай работу. Для визуальной приёмки WebUI владелец предпочитает Chromium, реальную тестовую учётную запись и проверку скриншота зрением; разрешённая им JWT-инъекция проверяет авторизованный интерфейс, но не парольный вход. До отправки сообщения сверь выбранный пресет с разрешённой моделью, чтобы случайно не расходовать дорогой маршрут → `references/owui-internals.md`.
- **Ключи не перевыпускать и не ротировать — никогда, в том числе ради теста.** У одного OWUI-ключа (`webui_db.api_key`, одна строка на юзера) несколько потребителей сразу: кастом-провайдер Hermes (`HERMES_CUSTOM_127_0_0_1_8080_API_KEY` в `/root/.hermes/.env`) и обогатитель музыкального бота (`ENRICH_TOKEN` в `/root/deploy/music_bot/.env`). `POST /api/v1/auths/api_key` не «показывает» ключ, а перевыпускает его и аннулирует старый — после этого Hermes и бот получают `401`, и владелец справедливо считает это поломкой. Для тестов достаточно прочитать ключ из БД; если ротация всё-таки случилась — записать новый в оба файла, пересоздать `bot`/`enricher-worker` и перезапустить Hermes. Детали и порядок восстановления — `references/owui-internals.md`.
- **Docker events miss "Up+healthy, traffic dead"**: `litellm-watchdog.py` + `litellm-watchdog.{service,timer}` (60 s, alerts via Bot API) covers it → [references/backups-notifications.md](references/backups-notifications.md).
- **Права OWUI: группы перекрывают дефолт.** `config.user.permissions` — только база; действующие права даёт `group.permissions`. Проверять все группы (`select name, permissions::jsonb->'chat' from "group"`): в этом стеке у группы «Ограничения» `chat.system_prompt` стоял `true`, то есть поле было доступно, хотя дефолт `false`. Изменённые права видны после перелогина — они кэшируются в сессии.
- **Бэкап строк БД от имени postgres не пишется в `/var/backups`** (0700 root): снимать откат через `sudo -u postgres psql -XA -tA -c "select json_agg(…)" > файл` от root и сразу `chmod 600`.
- **Never put `/dev/null` as a destination** in a symlink/`install`/`ln -sfn` one-liner while cleaning up: it silently unlinks the device node host-wide (every service writing to `null` fails). Restore is `rm -f /dev/null && mknod -m 666 /dev/null c 1 3`; verify with `ls -l /dev/null` → `crw-rw-rw- 1 root root 1, 3`.

## References (read on demand)

One topic per file, all in `references/`. The annotated index (what each answers, in what order to read them) is → [references/index.md](references/index.md).

- **Routes / models:** `updates.md`, `upstream-release-review.md`, `model-provenance.md`, `model-route-benchmark.md`, `chatgpt-subscription.md`, `litellm-model-db.md`, `litellm-admin-auth.md`
- **Open WebUI:** `owui-admin-auth.md`, `owui-internals.md`, `owui-chat-forensics.md`, `owui-data-purge.md`, `owui-task-models.md`, `ui-latency.md`, `signup-approval.md`, `branding.md`
- **Search / media / bots:** `searxng.md`, `web-search-architecture.md`, `media-pipeline.md`, `music-bot-lyria.md`, `enricher-system.md`, `enricher-system-legacy.md`, `sandbox-terminal.md`
- **Host hygiene:** `operations.md`, `disk-and-memory.md`, `memory-troubleshooting.md`, `repo-hygiene.md`, `coupling-hermes.md`, `backups-notifications.md`, `cloudflare-proxy.md`, `kb-sync.md`, `pitfalls.md`
- **Working with the owner:** `answering-the-owner.md`, `cross-cutting-rules.md`
