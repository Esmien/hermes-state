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

The stack is versioned in git: run git as `ai_service` (root gets `dubious ownership`), know what must never be committed, and match the commit shape the owner expects — `references/repo-hygiene.md`.

LiteLLM / Open WebUI / SearXNG / open-terminal stack, with PostgreSQL 17 + pgvector on the host and Nginx+Certbot for TLS. The music bot (lyria) is a **separate** deployment on the same host — `references/music-bot-lyria.md`; it has its own containers, its own Postgres and is NOT covered by `deploy.sh` or the `postgres-backup` timers.

## Location — IMPORTANT

The stack lives at **`/home/ai_service/ai-stack`** on the host.

- The host root is mounted **directly as `/`** — this agent runs on the host root, NOT in a container with a `/mnt/host` bind. **`/mnt/host` does not exist on the host.** Never prefix host paths with `/mnt/host`; use them as-is (`/home/...`, `/etc/...`).
- **`/mnt/host` exists only inside `open-terminal`** (it mounts `/` there, `cwd=/mnt/host`, docker.sock passed through). An agent driving that web terminal reads `/mnt/host/home/ai_service/...` as valid, but the Docker daemon resolves bind sources on the HOST, where the path is absent — it auto-creates an empty directory there and the container mounts a directory over a file (`IsADirectoryError` crash loop). **Never recreate a stack container from open-terminal's shell or with `/mnt/host` paths**; recovery drill in `references/operations.md`.
- Owner: user `ai_service`.

## Layout

```
/home/ai_service/ai-stack/
  deploy.sh              one-command full deploy (bash, needs sudo)
  ai/
    docker-compose.yml   compose project "ai", network stack-net
    .env                 secrets (NEVER cat — grep keys only)
    litellm/config.yaml  gateway settings ONLY (drop_params: true, forward_client_headers, router_settings); model routing lives in litellm_db, not here
    searxng/             settings.yml, limiter.toml, engines/
    backup-databases.sh  pg_dump helper
  backups/               postgres dumps, nginx/certbot archives
    postgres/<db>_<ts>.dump   retention: newest 3 dumps per DB (backup-databases.sh)
  backup-deploy/         previous configs (.old, nginx/, caddy/)
```

## Services (docker compose project `ai`)

| Container | Image | Role |
|---|---|---|
| litellm | ghcr.io/berriai/litellm:**v1.105.1** (pinned; `main-latest` is a rolling dev tag — see below) | LLM gateway/proxy |
| litellm-redis | redis:7-alpine, `--requirepass` from `${LITELLM_REDIS_PASSWORD}`, `--maxmemory 256mb --maxmemory-policy noeviction`, no published port | LiteLLM state store (auth cache, rate-limit/token counters, router cooldowns) |
| open-webui | esmien/webui:local (built locally from `webui-branding/`, derived from OWUI 0.12.4) | chat UI, rebranded «Esmien AI» |
| searxng | searxng/searxng:latest | web search |
| open-terminal | ghcr.io/open-webui/open-terminal:latest | web terminal |


> `cptr` (`ghcr.io/open-webui/computer`) was removed from the stack on the owner's instruction: container, image, `/home/ai_service/webui_data/computer`, compose block, `deploy.sh` references (`SITES` entry, `start_apps`, final report), nginx vhost + cert `term.esmien.qd.je`, and the boot-expected list. Nothing should reintroduce it.
> **open-terminal memory** (heap ratchets, 2g cap, nightly restart): `references/disk-and-memory.md`.

- **PostgreSQL 17 + pgvector runs on the HOST** (apt, pgdg repo) — not in compose.
- **Nginx** = TLS terminator (replaced caddy); **Certbot** issues/renews certs.
- Only 80/443 are deliberate ingress and the compose backends bind 127.0.0.1 — but **that is a per-service setting, not a host guarantee**. The HOST PostgreSQL 17 listens on `0.0.0.0:5432` (`listen_addresses='*'`) and nothing filtered it (`ufw` is `ENABLED=no`, `iptables INPUT` policy ACCEPT), so the port was open to the internet and being brute-forced (`grep -c 'no pg_hba.conf entry' /var/log/postgresql/postgresql-17-main.log` → 41k). It is now guarded by `/usr/local/bin/fw-guard-postgres.sh` + `fw-guard-postgres.service` (only 127.0.0.1 and 172.16.0.0/12 get in). **Never answer «что у нас наружу» from `docker ps` alone** — host services (Postgres, nginx, docker-proxy) are invisible there. Audit/closure procedure: `vps-network-exposure` skill.

## Domains → backend

```
ai.esmien.qd.je   -> 127.0.0.1:8080  (open-webui)
llm.esmien.qd.je  -> 127.0.0.1:4000  (litellm)
bot.esmien.qd.je  -> 127.0.0.1:8000  (music bot, lyria-bot)
```

## Versioning

- **`/home/ai_service/ai-stack` is a git repo** (owner `ai_service`, local user `VPS Admin <admin@esmien.qd.je>`, no remote). Commit compose/config changes there instead of leaving them on disk; run git as `sudo -u ai_service env HOME=/home/ai_service git -C /home/ai_service/ai-stack …` so `.git` stays `ai_service`-owned. Ignored on purpose: `ai/.env` (secrets), `backups/` (dumps), `backup-deploy/` (historical copies, several files are `600 root` and unreadable by `ai_service`), `*.bak*`, logs. `ai/.env.example` lists the key names with `CHANGE_ME` values — keep it in sync when a new `.env` key appears. Tracked baseline: compose (160 lines), `litellm/config.yaml`, searxng files, `deploy.sh`, `backup-databases.sh`, and **`runbook.md`** — the owner-facing incident playbook (симптомы A–E: шлюз недоступен / всплеск отказов / легли оба маршрута Hermes / место и БД / потеря хоста). Update it whenever a recovery procedure changes; it is the durable «что делать в 3 часа ночи» artefact.

## Gateway watchdog (independent of LiteLLM)

- **Docker events already cover `die`/`restart`/`oom`, but not "container Up+healthy, traffic dead".** That gap is closed by `/usr/local/bin/litellm-watchdog.py` + `litellm-watchdog.{service,timer}` (root, oneshot every 60 s, `Requires=sysinit.target` only — never add a `Requires=` naming the service, that makes the timer start it at boot). It probes `http://127.0.0.1:4000/health/liveliness` (`FAIL_THRESHOLD=2` consecutive misses ⇒ DOWN alert, plus a recovery alert), reports the container state in the message, and runs a second check over `LiteLLM_SpendLogs`: last 15 min, ≥10 calls and ≥50 % failures (excluding `/v1/models` and `pass_through_endpoint`) ⇒ «всплеск отказов» alert, throttled 30 min. Alerts go straight to the Bot API (BOT_TOKEN/BOT_OWNER from `/home/ai_service/notifications/.env`), so they arrive while the gateway is dead; state `/var/lib/server-monitor/litellm_watchdog_state.json`, log `/var/log/litellm-watchdog.log`. Test with `--test` (real delivery, returns `message_id`), `--no-send` (prints the alert body), or `LITELLM_WATCHDOG_URL=http://127.0.0.1:4999/...` (fake dead endpoint — fires on the 2nd run).

## Deploy

```bash
cd /home/ai_service/ai-stack
sudo ./deploy.sh                 # full deploy
sudo ./deploy.sh --skip-restore  # containers/roles only, leave DBs
sudo ./deploy.sh --skip-tls      # stack only, leave nginx/certbot
sudo ./deploy.sh --force-stale   # allow dumps older than STALE_HOURS
```

DB restore always applies the newest matching dump (`pg_restore --clean --if-exists`), found by mask `backups/postgres/<db>_*.dump` then `backups/<db>_*.dump`.

## .env keys (values are secret — never print)

`LITELLM_MASTER_KEY`, `LITELLM_REDIS_PASSWORD` (generated `openssl rand -hex 32`, used by both the `litellm` and `litellm-redis` services), `LITELLM_DB_PASSWORD`, `WEBUI_DB_PASSWORD`, `WEBUI_SECRET_KEY`, `WEBUI_URL` (drives the compose `WEBUI_URL`; no hardcoded domain), `OPENROUTER_API_KEY`, `OPEN_TERMINAL_API_KEY`, `SEARXNG_SECRET_KEY`, `UI_USERNAME`, `UI_PASSWORD`, `GITHUB_KEY`, `ENABLE_ADMIN_CHAT_ACCESS`.

Removed in the `vps-infra` migration and **not** to be reintroduced: `DOMAIN`, `BOT_DB_PASSWORD`, `POSTGRES_ADMIN_PASSWORD`.

`UI_PASSWORD` is the **LiteLLM** admin password. The Open WebUI admin password is separate — see `references/owui-admin-auth.md`.

## References (read on demand)

- `references/coupling-hermes.md` — **Hermes ↔ AI stack coupling**. Read when any change touching Hermes config, LiteLLM groups/fallback, the gateway or the emergency route.
- `references/pitfalls.md` — **Pitfalls (AI stack)**. Read when something behaves in a way the docs do not explain.
- `references/disk-and-memory.md` — **Memory, disk headroom and DB growth**. Read when disk fills up, RAM climbs, dumps/logs/images grow; open-terminal heap floor.
- `references/backups-notifications.md` — **Backups and notifications**. Read when backups, restore, timers, Telegram notifications.
- `references/model-provenance.md` — **Model provenance and cleanup in Open WebUI**. Read when ghost models, dead/disabled presets, model ids that 400 or vanish.
- `references/media-pipeline.md` — **Media pipeline (images / TTS through LiteLLM)**. Read when image generation, TTS, `cptr`, model routing for media.
- `references/music-bot-lyria.md` — **Music bot (lyria)**. Read when the separate lyria deployment (its own Postgres/Redis/RabbitMQ).
- `references/updates.md` — **Updating stack containers**. Read when upgrading one container, rolling tags, LiteLLM upgrade.
- `references/branding.md` — **Branding (Esmien AI)**. Read when brand assets, image/logo, screenshots.
- `references/signup-approval.md` — **Signup approval and user administration**. Read when pending signups, the Telegram approver, user roles via the API.
- `references/searxng.md` — **SearXNG (web search backend)**. Read when web search returns junk, engines get banned, or the image is upgraded.
- `references/memory-troubleshooting.md` — **Container memory attribution**. Read when asked "what is eating the RAM" — numbers before causes.
- `references/upstream-release-review.md` — **Reviewing an upstream release**. Read before applying any version bump; never update unprompted.
- `references/operations.md` — **Operations drills** (recreating a container after a config edit, routine checks).
- `references/repo-hygiene.md` — **Git hygiene for `ai-stack`** (what must never be committed, commit shape).
- `references/owui-admin-auth.md` — **Open WebUI admin auth** (`UI_PASSWORD` is LiteLLM's, not WebUI's).
- `scripts/probe-owui-terminal.py` — **end-to-end terminal probe** (admin login → feature flags → real `run_command` → `/execute` evidence in open-terminal logs, cleans up its chat). Run after any Open WebUI update.
