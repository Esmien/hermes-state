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
| litellm | ghcr.io/berriai/litellm:**v1.106.6** (pinned; `main-latest` is a rolling dev tag — why pinning, and how to bump: `references/updates.md`) | LLM gateway/proxy |
| litellm-redis | redis:7-alpine, `--requirepass` from `${LITELLM_REDIS_PASSWORD}`, `--maxmemory 256mb --maxmemory-policy noeviction`, no published port | LiteLLM state store (auth cache, rate-limit/token counters, router cooldowns) |
| open-webui | esmien/webui:local (built locally from `ai/webui-branding/`, derived from OWUI 0.13.3) | chat UI, rebranded «Esmien AI» |
| searxng | searxng/searxng:latest | web search |
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

- **Never put `/dev/null` as a destination** in a symlink/`install`/`ln -sfn` one-liner while cleaning up: it silently unlinks the device node host-wide (every service writing to `null` fails). Restore is `rm -f /dev/null && mknod -m 666 /dev/null c 1 3`; verify with `ls -l /dev/null` → `crw-rw-rw- 1 root root 1, 3`.
- **Git is the record:** `sudo -u ai_service env HOME=/home/ai_service git -C /home/ai_service/ai-stack …` (**no remote** — branch `master` is local-only, so nothing gets pushed and `git commit -a` sweeps unrelated working-tree edits into your commit: stage files by name); `ai/.env`, `backups/`, `backup-deploy/`, `*.bak*`, logs ignored on purpose; `ai/.env.example` holds the key names with `CHANGE_ME`. `runbook.md` is tracked and owner-facing — update it when a recovery procedure changes.
- **DB restore applies `backups/postgres/<db>_*.dump` — but the dumps are `.dump.enc`**, so an unchanged mask silently finds nothing and the deploy continues on an empty database.
- **UI from a foreign machine = SSH tunnel only** (`-L 8080:127.0.0.1:8080 -L 4000:127.0.0.1:4000`) → [references/operations.md](references/operations.md).
- **Docker events miss "Up+healthy, traffic dead"**: `litellm-watchdog.py` + `litellm-watchdog.{service,timer}` (60 s, alerts via Bot API) covers it → [references/backups-notifications.md](references/backups-notifications.md).
- **Misquoted facts** (aliases vs unique models, `edge-tts` orphan, «Failure» wall = scanners, empty `bot_db`) → [references/pitfalls.md](references/pitfalls.md).

## Deploy

```bash
cd /home/ai_service/ai-stack
sudo ./deploy.sh                 # full deploy
sudo ./deploy.sh --skip-restore  # containers/roles only, leave DBs
sudo ./deploy.sh --skip-tls      # stack only, leave nginx/certbot
sudo ./deploy.sh --force-stale   # allow dumps older than STALE_HOURS
```

## .env keys (values are secret — never print)

`LITELLM_MASTER_KEY`, `LITELLM_REDIS_PASSWORD` (generated `openssl rand -hex 32`, used by both the `litellm` and `litellm-redis` services), `LITELLM_DB_PASSWORD`, `WEBUI_DB_PASSWORD`, `WEBUI_SECRET_KEY`, `WEBUI_URL` (drives the compose `WEBUI_URL`; no hardcoded domain), `OPENROUTER_API_KEY`, `OPEN_TERMINAL_API_KEY`, `SEARXNG_SECRET_KEY`, `UI_USERNAME`, `UI_PASSWORD`, `GITHUB_KEY`, `ENABLE_ADMIN_CHAT_ACCESS`, `OPEN_TERMINAL_SANDBOX_API_KEY`, `ENABLE_DIRECT_INTEGRATIONS`.

Removed in the `vps-infra` migration and **not** to be reintroduced: `DOMAIN`, `BOT_DB_PASSWORD`, `POSTGRES_ADMIN_PASSWORD`.

`UI_PASSWORD` is the **LiteLLM** admin password. The Open WebUI admin password is separate — see `references/owui-admin-auth.md`. The Admin UI's «Environment-credential login is enabled» banner is a task, not a hole: prove the DB admin first, then `disable_env_credential_login: true`; never delete the pair — inert and the documented rollback → [references/litellm-admin-auth.md](references/litellm-admin-auth.md). Two bots carry Telegram notifications, neither implies the other — verify each with `getMe` → [references/backups-notifications.md](references/backups-notifications.md).

## Answering the owner

A question like «подходит ли эта модель под задачу», «какой уровень достаточен», «стоит ли брать X» wants a **verdict first**: what fits, what does not, and the one trade-off that decides it. Do not open the stack to answer it — no probes, no log digging, no spend queries. Measure only when the ask is explicitly «проверь», «прогони», «сравни».

- «почему медленно» → measure first (per-URI `rt` from nginx, then `docker stats`/`load`); two standing causes (LiteLLM admin bundle, one WebUI worker + avatar burst); never propose trimming the model list → [references/ui-latency.md](references/ui-latency.md).
- «поиск получше» → page fetching, not the model; engines never chain → [references/web-search-architecture.md](references/web-search-architecture.md).
- **«сделай нормально, костыли мне не надо»** — не предлагать второй вход на высоком порту, отдельное имя, ручной обход или «пока попробуй так»: владелец считает это костылём и злится сильнее, чем на нерешённую задачу. Работающая ветка — замер (лог → пакеты) и устранение причины; он готов сам потыкать, пока идёт capture, поэтому просить именно воспроизведение, а не тесты.
- **Не предлагать «запатчим апстрим» или «форкнем» как ответ на чужое узкое место** — «ты предлагаешь патчить чужой недокументированный код, так себе план». Порядок ответа: родная ручка апстрима (env/конфиг/флаг) → измерение → и только по его слову дериватив образа (тот самый `webui-branding/Dockerfile`, который мы уже собираем ради брендинга). Лицензия — тоже аргумент: у Open WebUI BSD-3 с пунктом о брендинге (не больше 50 юзеров за 30 дней без разрешения), поэтому наш ребрендинг легален пока нас 8, а «станет продуктом» — уже разговор с ними.
- «защищён / бэкапы / восстановлю за 30 минут» → verdict + evidence per claim, skill `vps-posture-assessment`; restore proof is `/backups` and `monitor.py verify`, not the digest, and secrets do have an offsite copy → [references/backups-notifications.md](references/backups-notifications.md).

## References (read on demand)

- `references/coupling-hermes.md` — **Hermes ↔ AI stack coupling** (Hermes config, LiteLLM groups/fallback, emergency route).
- `references/pitfalls.md` — **Pitfalls (AI stack)**. Read when something behaves in a way the docs do not explain.
- `references/disk-and-memory.md` — **Memory, disk headroom, DB growth** (disk full, RAM climb, open-terminal heap floor).
- `references/backups-notifications.md` — **Backups, restore, timers, Telegram notifications**.
- `references/litellm-model-db.md` — **Модели/группы в `litellm_db`**. Read when a model flaps, a group returns 400 from one deployment, or a DB edit (extra_headers, aliases) has to be applied and verified.
- `references/litellm-admin-auth.md` — **LiteLLM: ownership в `litellm_db`** (ключи/spend/мемберства, «Created By = Unknown», вес и кэш админки). Auth-путь — в skill `credential-login-verification`.
- `references/ui-latency.md` — **«Медленно грузится»: латентность UI/API** (per-URI `rt`, два штатных виновника, кэш nginx, профиль длинного чата).
- `references/model-provenance.md` — **Model provenance / cleanup in Open WebUI** (ghost models, dead presets).
- `references/media-pipeline.md` — **Media pipeline (images / TTS through LiteLLM)**.
- `references/enricher-system.md` — **System-промпт модели `enricher`** (актуальный). Read before touching it.
- `references/enricher-system-legacy.md` — **Старый system-промпт `enricher`** (откат на claude-haiku-5.5).
- `references/music-bot-lyria.md` — **Music bot (lyria)**. Read when the separate lyria deployment (its own Postgres/Redis/RabbitMQ).
- `references/chatgpt-subscription.md` — **ChatGPT/Codex subscription as a LiteLLM route** (`chatgpt/*` models in WebUI).
- `references/updates.md` — **Updating stack containers** (one container, rolling tags, LiteLLM).
- `references/branding.md` — **Branding (Esmien AI)** (assets, image/logo, screenshots).
- `references/signup-approval.md` — **Signup approval, user administration, WebUI auth hardening** (Turnstile, fail2ban, лимиты, MFA, admin keys).
- `references/searxng.md` — **SearXNG (web search backend)**: junk results, banned engines, image upgrade.
- `references/cloudflare-proxy.md` — **Cloudflare in front of one of our names** (прокси, WAF, лимиты на всех сразу, ложный down, h3/Alt-Svc).
- `references/web-search-architecture.md` — **Web search end to end: OWUI `external` contract, shim plan, Hermes's role**. Read when the owner wants search better than SearXNG, or search/answer quality comes up.
- `references/memory-troubleshooting.md` — **Container memory attribution** («what is eating the RAM»).
- `references/upstream-release-review.md` — **Reviewing an upstream release**; never update unprompted.
- `references/kb-sync.md` — **git → база знаний Open WebUI**: `kb-sync.py`, таймер раз в 2 часа, `sync/diff`.
- `references/operations.md` — **Operations drills** (recreating a container after a config edit, routine checks).
- `references/repo-hygiene.md` — **Git hygiene for `ai-stack`** (what must never be committed, commit shape).
- `references/owui-admin-auth.md` — **Open WebUI admin auth** (`UI_PASSWORD` is LiteLLM's, not WebUI's).
- `references/owui-data-purge.md` — **Удаление чатов/файлов Open WebUI** по дате или юзеру (`chat` / `chat_message` / `chat_file`).
- `references/owui-task-models.md` — **Фоновые задачи Open WebUI** (заголовки чатов, теги, follow-up; `task.*`).
- `references/owui-internals.md` — **Внутренности Open WebUI**: где живёт состояние (`config`, `tool.content`/`valves`, `chat`), почему нель­зя выбирать значения целиком (base64 в `ui.default_interface_settings`), как безопасно править workspace-тул в БД, почему выбор терминала — клиентский. Read before any DB edit or bundle grep.
- `references/sandbox-terminal.md` — **Песочницы на пользователя (действующая схема)**: `template.compose.yml` + `/usr/local/bin/sandbox-provisioner.py` + 60-секундный таймер, лимиты 1.5 ГБ/1 CPU, квота 2 ГБ с LRU, `HOME=/home/user/workspace` и `OPEN_TERMINAL_FILE_BROWSER_ROOT=/home/user` (юзер видит одну папку `workspace`), установка пакетов без root, access_grants и `meta.terminalId`, **отсутствие HTTP-раздачи файлов** (ссылки на файлы не работают), грабли LRU/compose-интерполяции; ниже — история (общая песочница, отвергнутый `OPEN_TERMINAL_MULTI_USER`, EXDEV). Промпт MCU — `templates/mcu-assistant-system-prompt.md`.
- `references/model-route-benchmark.md` — **Model / route A/B benchmarking**; `scripts/model-route-bench.py`.
- `scripts/probe-owui-terminal.py` — **end-to-end terminal probe** (login → flags → real `run_command` → `/execute` evidence). Run after any WebUI update.
- `scripts/lyria-enricher-router-pipe.py` — **живой OWUI-Pipe `enricher`** (decider → poem/idea → Argon → JSON). Держать синхронно с функцией в OWUI.
- `scripts/lyria-enricher-pipe.py` — **исходник OWUI-Pipe `lyria_enricher`** (songwriter + critic + санитайзер, выключен).
- `scripts/check-notification-bots.py` — **Telegram notification health** (each token via `getMe`; `file_id` registry). Run first when a message never arrived.
- `scripts/lyria-e2e.py` — **E2E прогон музыкального бота по всем юзер-стори** («проверь бота / прогони сценарии»).
- `scripts/` также: `audit-dead-models.py`, `check-env-parity.sh`, `compact-webui-images.py`, `model-route-bench.py`, `probe-approval-guardian.py`, `probe-media-endpoints.py`.
- `scripts/music-bot-tests.sh` — **тесты music_bot в изоляции** (свои pg/redis/rabbitmq, CI-паритет: ruff + alembic + pytest). Никогда не на хосте.
