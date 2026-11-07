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

LiteLLM / Open WebUI / SearXNG / open-terminal stack, with PostgreSQL 17 + pgvector on the host and Nginx+Certbot for TLS. The music bot (lyria) is a **separate** deployment on the same host — `references/music-bot-lyria.md`; it has its own containers, its own Postgres and is NOT covered by `deploy.sh` or the `postgres-backup` timers. **Its code is off-limits:** the owner allows state checks, test runs and commits/pushes of what is already in the tree — never rewriting the bot's logic. Report defects as a list; fix only on an explicit separate instruction.

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
    webui-branding/      Dockerfile for esmien/webui:local (ARG OPENWEBUI_BASE digest + rebrand sed) and the generated assets; RESTORE_WEBUI.md sits next to it
    backup-databases.sh  pg_dump → encrypt (dump-crypto) helper
  backups/               postgres dumps, nginx/certbot archives
    postgres/<db>_<ts>.dump.enc   AES-256 encrypted, key /etc/backup-crypto.key; retention: newest 3 per DB
  backup-deploy/         previous configs (.old, nginx/, caddy/)
```

## Services (docker compose project `ai`)

| Container | Image | Role |
|---|---|---|
| litellm | ghcr.io/berriai/litellm:**v1.106.6** (pinned; `main-latest` is a rolling dev tag — see below) | LLM gateway/proxy |
| litellm-redis | redis:7-alpine, `--requirepass` from `${LITELLM_REDIS_PASSWORD}`, `--maxmemory 256mb --maxmemory-policy noeviction`, no published port | LiteLLM state store (auth cache, rate-limit/token counters, router cooldowns) |
| open-webui | esmien/webui:local (built locally from `ai/webui-branding/`, derived from OWUI 0.13.0) | chat UI, rebranded «Esmien AI» |
| searxng | searxng/searxng:latest | web search |
| open-terminal | ghcr.io/open-webui/open-terminal:latest | web terminal |
| open-terminal-sandbox | esmien/open-terminal-arduino:local (built from `ai/arduino-sandbox/`) | не-root песочница для пользователей WebUI: shell, файлы, arduino-cli — `references/sandbox-terminal.md` |


> `cptr` (`ghcr.io/open-webui/computer`) was removed from the stack on the owner's instruction: container, image, `/home/ai_service/webui_data/computer`, compose block, `deploy.sh` references (`SITES` entry, `start_apps`, final report), nginx vhost + cert `term.esmien.qd.je`, and the boot-expected list. Nothing should reintroduce it.
> **open-terminal memory** (heap ratchets, 2g cap, nightly restart): `references/disk-and-memory.md`.

- **PostgreSQL 17 + pgvector runs on the HOST** (apt, pgdg repo) — not in compose.
- **Nginx** = TLS terminator (replaced caddy); **Certbot** issues/renews certs.
- Only 80/443 are deliberate ingress and the compose backends bind 127.0.0.1 — but **that is a per-service setting, not a host guarantee**. The HOST PostgreSQL 17 listens on `0.0.0.0:5432` (`listen_addresses='*'`) and nothing filtered it (`ufw` is `ENABLED=no`, `iptables INPUT` policy ACCEPT), so the port was open to the internet and being brute-forced (`grep -c 'no pg_hba.conf entry' /var/log/postgresql/postgresql-17-main.log` → 41k). It is now guarded by `/usr/local/bin/fw-guard-postgres.sh` + `fw-guard-postgres.service` (only 127.0.0.1 and 172.16.0.0/12 get in). **Never answer «что у нас наружу» from `docker ps` alone** — host services (Postgres, nginx, docker-proxy) are invisible there. Audit/closure procedure: `vps-network-exposure` skill.

## Facts that get misquoted in summaries

- `GET /model/info` returns **80 entries (aliases) over 43 unique upstream models** — say «80 записей/
  алиасов», never «80 маршрутов»: half of the entries point at the same deployment.
- **`edge-tts` is an orphan container.** It runs on `stack-net` with no published port, is not in the compose
  file and is not referenced by `litellm/config.yaml`; WebUI TTS is `audio.tts.engine=openai` with
  `audio.tts.model=tts.openrouter/gemini-3.8-flash-lite-tts` (through LiteLLM → OpenRouter). Do not describe
  edge-tts as the stack's TTS path; removal needs the owner's confirmation.
- **Красная стена «Failure» в UI LiteLLM — чаще всего не модели, а сканеры.** Прежде чем
  искать сбой, сгруппировать последние отказы по модели: строки с пустой моделью — это
  неаутентифицированные `401/429` на `/v1/models` (`SELECT model, count(*) FROM
  "LiteLLM_SpendLogs" WHERE status='failure' AND "startTime" > now() - interval '1 hour'
  GROUP BY 1`). Адрес источника виден в `/var/log/nginx/access.log` (там же `curl/8.x` UA и
  пути `/cohere`, `/vllm`, `/vertex_ai`); в `docker logs litellm` — только `172.18.0.1`, то есть
  docker-proxy, а не клиент. Лечение — джейл `nginx-llm-unauth` + лимит на `/v1/models`
  (скилл `vps-network-exposure`, раздел про fail2ban и rate limits) и чистка анонимных
  строк (`references/disk-and-memory.md`). Не перезапускать LiteLLM и не искать причину в ключах:
  0 успешных запросов с этих адресов = утечки нет, есть мусор.
- **`bot_db` is empty**: 0 tables in `public`, 0 backends; its 7.7 MB is template overhead. Leftover of the
  pre-lyria deployment — never list it as live data.
- Host dumps cover **`webui_db` + `litellm_db` only**; `lyria`'s own Postgres is deliberately unbacked and
  `bot_db` is not dumped either.

## Смотреть UI снаружи — только через SSH-туннель

`open-webui` (8080) и `litellm` (4000) публикуются на `127.0.0.1`, поэтому с чужой машины
(и на прогоне без TLS, где nginx вообще не ставится) браузер видит их так:

```bash
ssh -N -L 8080:127.0.0.1:8080 -L 4000:127.0.0.1:4000 root@<host>
# http://localhost:8080 — WebUI, http://localhost:4000/ui — LiteLLM
```

Логин LiteLLM — **юзер из БД** (`black.walf16@gmail.com`, роль `proxy_admin`), env-логин по `UI_USERNAME`/`UI_PASSWORD` и мастер-ключу на форме отключён флагом `disable_env_credential_login` (см. `references/litellm-admin-auth.md`). Мастер-ключ остаётся рабочим только как API-bearer — это break-glass. На восстановленной БД пользователи уже есть, а экран первичной регистрации WebUI означает пустую `webui_db` — и первый зарегистрированный станет админом.

## Domains → backend

The public names are moving from the `esmien.qd.je` zone (free DNS whose authoritatives fail — see `vpn-entry-stack` for the triage) to the owned **`esmien.ru`** zone on Cloudflare. Both sets are served in parallel until the owner moves the family, so an old and a new name point at the same backend:

```
ai.esmien.ru    -> 127.0.0.1:8080  (open-webui — единственный вход) | ai.esmien.qd.je
app.esmien.ru   -> 301 на ai.esmien.ru (не второй вход)          | —
llm.esmien.ru   -> 127.0.0.1:4000  (litellm)      | llm.esmien.qd.je
bot.esmien.ru   -> 127.0.0.1:8000  (music bot)    | bot.esmien.qd.je
mon.esmien.ru   -> 127.0.0.1:8090  (beszel hub)      | mon.esmien.qd.je
vpn.esmien.ru:8443 (VPN entry)                    | vpn.esmien.qd.je:8443
```

**Оранжевого облака в зоне больше нет: `ai` переведён в серый по указанию владельца** — CF отдавал
HTML-оболочку и не пропускал пачку подресурсов с адресов выходов VPN (диагностика и доказательства —
`references/cloudflare-proxy.md`, раздел про «через VPN не грузится»). Оба имени, `ai` и `app`, серые и ходят прямо на
origin, бэкенд один (`127.0.0.1:8080`). **`app.esmien.ru` — не второй вход, а редирект:** по указанию
владельца он отдаёт `301` на `ai` с сохранением пути и query, без проксирования и без лимитов
(два имени одного WebUI = две cookie-сессии, потому что cookie привязана к hostname). Не возвращать
`app` вторым проксирующим vhost'ом без прямой просьбы. Бэкап прежнего файла — `.bak-before-redirect`.
Проверка правки: `curl -s -o /dev/null -D- --resolve app.esmien.ru:443:127.0.0.1
'https://app.esmien.ru/c/x?y=1' | grep -iE '^HTTP|^location'` — ждать `301` и полный путь в `Location`.

**Правка вхоста и проверка после reload.** `write_file` отказывается писать в `/etc/nginx` (sensitive
system path): писать новый файл в scratch и класть через `cp` (бэкап — `cp -a <file> <file>.bak-<повод>`).
Сразу после `systemctl reload nginx` первый же `curl` может ответить по **старому** конфигу — прежний
worker ещё принимает соединения; повторять запрос, а не откатывать правку и не искать «конфиг не
применился» (симптом обманчив: только что отредактированный vhost отдаёт 200 с телом прежнего).

**Снятие оранжевого облака — два действия, а не одно.** Сначала убрать из вхост-файла гейт
`if ($deny_direct) { return 403; }` (он пропускает только запросы с `CF-Connecting-IP` и без CF режет
`403` вообще всё, включая владельца), потом `PATCH {"proxied":false}`. Порядок и проверка — в
`references/cloudflare-proxy.md`; не возвращать гейт, пока запись серая.

Adding a service name on a new zone — order matters:

1. Wait until the A record answers from two public resolvers. Under Cloudflare it must be **grey cloud (DNS only)**: with the orange proxy on, HTTP-01 validation comes back `530` and certbot fails before nginx is even involved. An orange record is only correct if the service is deliberately fronted by Cloudflare (then TLS terminates at the edge and the origin vhost needs no Let's Encrypt cert).
2. Issue the certificate through a **port-80 ACME stub** for the new name (`location /.well-known/acme-challenge/ { root /var/www/html; }`), `certbot certonly --webroot`. A full vhost cannot be written first — `nginx -t` refuses to load a config whose `ssl_certificate` path does not exist yet.
3. Then write the real vhost as a copy of the old one with the hostname substituted — same `listen 127.0.0.1:9443 proxy_protocol ssl http2`, same rate-limit zones, timeouts and `X-Forwarded-*`. A new name without its own vhost silently lands on the default server of that listener.
4. Drop the ACME stub once the real file carries the port-80 block (a copy of the site file already has it) and `nginx -t && systemctl reload nginx`.
5. Verify with `curl -o /dev/null -w '%{http_code} cert=%{ssl_verify_result}' https://<name>/` — want `200 cert=0`. Then confirm the old name still answers, because the family stays on it until the owner says otherwise.

**Orange-clouding an already-issued name** (putting Cloudflare in front for its bot/WAF layer) is a different procedure from first issuance and has an ordering trap: restore the real client IP *before* flipping the record. Origin topology here is a `stream` block on 443 (`ssl_preread`) that forwards with `proxy_protocol` to the `127.0.0.1:9443` vhosts, and `00-proxy-realip.conf` resolves `$remote_addr` from that hop — once the record is proxied, `$remote_addr` becomes a Cloudflare edge IP and every `limit_req`/`limit_conn` bucket collapses onto one key, i.e. all users share one limit and get 429s together. Procedure, token scopes, free-plan limits and rollback: `references/cloudflare-proxy.md`.

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

DB restore always applies the newest matching dump (`pg_restore --clean --if-exists`), found by mask `backups/postgres/<db>_*.dump` then `backups/<db>_*.dump`. **The dumps on disk are `.dump.enc` now**, so check this step before trusting a `deploy.sh` restore: either feed it a file produced by `dump-crypto decrypt <x.dump.enc> <x.dump>` or extend the mask — an unchanged mask silently finds nothing and the deploy continues on an empty database.

## .env keys (values are secret — never print)

`LITELLM_MASTER_KEY`, `LITELLM_REDIS_PASSWORD` (generated `openssl rand -hex 32`, used by both the `litellm` and `litellm-redis` services), `LITELLM_DB_PASSWORD`, `WEBUI_DB_PASSWORD`, `WEBUI_SECRET_KEY`, `WEBUI_URL` (drives the compose `WEBUI_URL`; no hardcoded domain), `OPENROUTER_API_KEY`, `OPEN_TERMINAL_API_KEY`, `SEARXNG_SECRET_KEY`, `UI_USERNAME`, `UI_PASSWORD`, `GITHUB_KEY`, `ENABLE_ADMIN_CHAT_ACCESS`, `OPEN_TERMINAL_SANDBOX_API_KEY`, `ENABLE_DIRECT_INTEGRATIONS`.

Removed in the `vps-infra` migration and **not** to be reintroduced: `DOMAIN`, `BOT_DB_PASSWORD`, `POSTGRES_ADMIN_PASSWORD`.

`UI_PASSWORD` is the **LiteLLM** admin password. The Open WebUI admin password is separate — see `references/owui-admin-auth.md`.

It is also the shared *env credential* the Admin UI warns about («Environment-credential login is enabled»). That banner is not a finding to report as a hole on a one-user box — it is a request to replace the static pair with a real `proxy_admin` row and then set `general_settings.disable_env_credential_login: true`. Order (prove the DB admin first), verification by effect (`/health/readiness` → `details.show_env_credential_login_warning`), the `LiteLLM_Config` merge rule, and the phantom «the new admin can pick only All Proxy Models» symptom: skill `credential-login-verification`, file `litellm-admin-ui-auth.md` under its references/. Do not delete `UI_USERNAME`/`UI_PASSWORD` from `.env` for this — with the flag on they are inert, and they are the documented rollback.

**Two different bots carry the Telegram notifications, and neither implies the other works.** Hermes sends its own messages with `TELEGRAM_BOT_TOKEN` from `/root/.hermes/.env` (`@esmien_vps_admin_bot`); `monitor.py` uses `BOT_TOKEN` / `FILE_BOT_TOKEN` from `/home/ai_service/notifications/.env` (`@esmien_vps_notificator_bot`, `@esmien_ai_backups_bot`). "Уведомления приходят" therefore proves only the Hermes bot. Verify each token on its own with `getMe` (username only, never print the value) before telling the owner a bot is dead — and after editing `notifications/.env`, restart every unit that reads it: the token is copied into the process memory at start, so a service restarted before the edit keeps polling 404 until the next restart (`journalctl -u server-monitor-bot` shows `getUpdates HTTP 404` every 5 s).

## Answering the owner about models

A question like «подходит ли эта модель под задачу», «какой уровень достаточен», «стоит ли брать X»
wants a **verdict first**: what fits, what does not, and the one trade-off that decides it. Do not
open the stack to answer it — no probes, no log digging, no spend queries. Run measurements only when
the ask is explicitly «проверь», «прогони», «сравни»; stack work started on a conceptual question gets
interrupted, and rightly so.

## Answering the owner «почему медленно»

Жалоба на скорость — это измерение, а не гипотезы: `rt` по URI из лога nginx (у `llm.esmien.ru`
своего `rt` нет — только счётчики), потом `docker stats`/`load`, и только потом вывод. На этом
хосте два штатных виновника: вес/кэш админки LiteLLM и один воркер Open WebUI в связке с пачкой
запросов аватарок. Три правила ответа: **не предлагать сокращать подобранный вручную список
моделей** (множитель — всплеск запросов, не ассортимент), **не складывать параллельные задержки
в «итого секунд»** (124×300 мс параллельно — это 1–2 с, а не 37), и **не занимать `litellm-redis`
под WebUI-воркеры** (он выделенный, 256 MB `noeviction`). Процедура, профиль по слоям (открытие длинного чата: ядро 44 мс против 1099 КБ ответа), готовые
локации nginx и ловушка вставки не в тот `server`-блок — `references/ui-latency.md`. Патчи в
бизнес-логику OWUI не предлагать даже когда выигрыш посчитан: только края (nginx/env/образ), иначе
это лотерея без тестов.

## Answering the owner about web search

OWUI's built-in `searxng` path keeps only SERP `title/link/snippet` — it never opens the results, so
answer quality is capped by ~200-char teasers. Engines do not chain: when a custom/external search
fails, OWUI logs and returns `[]` and the model answers with no context. So «поиск получше» is a
page-fetching problem, not a model problem, and any «SearXNG как фоллбэк» must live INSIDE the
replacement service. Contract, hot-path budget, Hermes's role and the trust-zone caveat:
`references/web-search-architecture.md`.

## Answering the owner «сервер защищён / отказоустойчив / бэкапы / восстановлю за 30 минут»

A yes/no posture question wants a verdict, evidence per claim, and a short list of what is actually
left — not a re-inventory essay. Procedure and the accepted-risk list: `vps-posture-assessment` skill.
Two hard rules from this stack:

- **Never claim the dumps are unverified or unrestorable without reading `references/backups-notifications.md`.**
  Restore verification exists on two paths: the bot command `/backups` restores the newest dump of each DB
  into a throwaway `verify_restore_*` database and drops it, and the nightly `monitor.py verify` report does
  the same at 03:15. What is NOT proof is the nightly `backup` digest («Сохранены бэкапы») — it is an upload
  receipt only. Answer «прогонялся ли restore» from the verify path, not from `ls backups/` and not from the digest.
- **Secrets DO have an offsite copy — say it, with the caveat.** `ai/.env` is git-ignored by design, but
  `secrets-offsite-backup.timer` (Sunday 04:10 UTC) tars every `.env` on the host, encrypts it AES-256-CBC
  (pbkdf2, key `/root/.secrets/offsite.key`), round-trip verifies decrypt → sha256 → tar listing, and uploads
  the `.enc` plus a key-name-only inventory to the file bot as `db="secrets_offsite"`. The residual risk is not
  the archive but its passphrase: it was delivered once into Telegram and exists nowhere else. Never repeat the
  old line «секреты нигде не лежат» — it is wrong and it scares the owner for nothing.

## References (read on demand)

- `references/coupling-hermes.md` — **Hermes ↔ AI stack coupling**. Read when any change touching Hermes config, LiteLLM groups/fallback, the gateway or the emergency route.
- `references/pitfalls.md` — **Pitfalls (AI stack)**. Read when something behaves in a way the docs do not explain.
- `references/disk-and-memory.md` — **Memory, disk headroom and DB growth**. Read when disk fills up, RAM climbs, dumps/logs/images grow; open-terminal heap floor.
- `references/backups-notifications.md` — **Backups and notifications**. Read when backups, restore, timers, Telegram notifications.
- `references/litellm-model-db.md` — **Модели/группы в `litellm_db`**. Read when a model flaps, a group returns 400 from one deployment, or a DB edit (extra_headers, aliases) has to be applied and verified.
- `references/litellm-admin-auth.md` — **LiteLLM: ownership в `litellm_db`** (ключи/spend/мемберства/авторство моделей переписываются на реального админа; «Created By = Unknown»; вес и кэш админки). Auth-путь (env-дверь, `/v2/login`, сброс пароля) — в skill `credential-login-verification`, его файл `litellm-admin-ui-auth.md`.
- `references/ui-latency.md` — **«Медленно грузится»: латентность UI/API**. Read when the owner says a page or the chat UI is slow: per-URI `rt` from nginx logs (websockets out of the stats, `.js.map` = devtools open), the two standing causes (LiteLLM admin bundle, single-worker WebUI + avatar burst), the nginx cache locations and the wrong-server-block trap, plus the «what would a second worker give» answer, per-layer profiling of a long chat open, and why a chat cache is not worth patching into the app.
- `references/model-provenance.md` — **Model provenance and cleanup in Open WebUI**. Read when ghost models, dead/disabled presets, model ids that 400 or vanish.
- `references/media-pipeline.md` — **Media pipeline (images / TTS through LiteLLM)**. Read when image generation, TTS, `cptr`, model routing for media.
- `references/music-bot-lyria.md` — **Music bot (lyria)**. Read when the separate lyria deployment (its own Postgres/Redis/RabbitMQ).
- `references/chatgpt-subscription.md` — **ChatGPT/Codex subscription as a LiteLLM route**. Read when asked to expose a ChatGPT Plus/Pro subscription as an API or to add `chatgpt/*` models into Open WebUI.
- `references/updates.md` — **Updating stack containers**. Read when upgrading one container, rolling tags, LiteLLM upgrade.
- `references/branding.md` — **Branding (Esmien AI)**. Read when brand assets, image/logo, screenshots.
- `references/signup-approval.md` — **Signup approval, user administration and WebUI auth hardening**. Read when pending signups, the Telegram approver, user roles via the API — and whenever signup/login protection is in play (Turnstile gate, fail2ban jail, rate limits, security headers, MFA, admin API keys and their rotation trap).
- `references/searxng.md` — **SearXNG (web search backend)**. Read when web search returns junk, engines get banned, or the image is upgraded.
- `references/cloudflare-proxy.md` — **Cloudflare in front of one of our names**. Read before proxying a vhost, adding WAF/bot rules, when rate limits suddenly apply to everyone at once, when an outside monitor reports the site as down/403 while it is healthy, or when traffic breaks after the client's egress IP changed (per-IP reputation of VPN exits). Also read when a browser shows `ERR_TIMED_OUT` while `curl` from several vantages gets `200` — Alt-Svc/h3 through a tunnel, section «HTTP/3 (Alt-Svc)».
- `references/web-search-architecture.md` — **Web search end to end: OWUI `external` contract, shim plan, Hermes's role**. Read when the owner wants search better than SearXNG, or search/answer quality comes up.
- `references/memory-troubleshooting.md` — **Container memory attribution**. Read when asked "what is eating the RAM" — numbers before causes.
- `references/upstream-release-review.md` — **Reviewing an upstream release**. Read before applying any version bump; never update unprompted.
- `references/kb-sync.md` — **git → база знаний Open WebUI**: `kb-sync.py`, таймер раз в 2 часа, протокол `sync/diff` и грабли (общий манифест, дубли контента, пустые файлы).
- `references/operations.md` — **Operations drills** (recreating a container after a config edit, routine checks).
- `references/repo-hygiene.md` — **Git hygiene for `ai-stack`** (what must never be committed, commit shape).
- `references/owui-admin-auth.md` — **Open WebUI admin auth** (`UI_PASSWORD` is LiteLLM's, not WebUI's).
- `references/owui-data-purge.md` — **Удаление чатов/файлов Open WebUI по дате или юзеру** (`webui_db`: `chat` + `chat_message` + `chat_file`, восстановление маппинга файлов из дампа, пути `file.path` → `webui_data/uploads`, что нельзя трогать). Read before any «снеси диалоги» / «почисти файлы» request.
- `references/owui-task-models.md` — **Фоновые задачи Open WebUI (заголовки чатов, теги, follow-up)**. Read when заголовки/теги не генерируются или заголовок выглядит как дословное первое сообщение, и перед любой правкой `task.*`: личный флаг `title.auto`, контракт шаблона (`{{prompt}}` + JSON), почему правка в БД не требует перезапуска.
- `references/sandbox-terminal.md` — **Песочница `open-terminal-sandbox` для пользователей WebUI** (не-root, read-only, arduino-cli; подключение через `terminal_server.connections` + access_grants; привязка модели через `meta.terminalId`; ловушки `cap_setgid`, root-овский `.arduino15` и heredoc). Готовый системный промпт MCU-ассистента: `templates/mcu-assistant-system-prompt.md`.
- `references/model-route-benchmark.md` — **Model / route A/B benchmarking**. Read when the owner says a model underperforms, or before switching a LiteLLM group: hidden-prompt probe (injected system prompts show up as thousands of `prompt_tokens` on a one-line request), discriminating task set, cost per success. Run `scripts/model-route-bench.py [model ...]`.
- `scripts/probe-owui-terminal.py` — **end-to-end terminal probe** (admin login → feature flags → real `run_command` → `/execute` evidence in open-terminal logs, cleans up its chat). Run after any Open WebUI update.
- `scripts/lyria-enricher-router-pipe.py` — **живой OWUI-Pipe `enricher`** (decider → poem/idea → Argon → JSON). Держать синхронно с функцией в OWUI.
- `scripts/lyria-enricher-pipe.py` — **исходник OWUI-Pipe `lyria_enricher`** (songwriter + critic + санитайзер, выключен). Держать синхронно с живой функцией: правка в OWUI без копии здесь теряется вместе с БД.
- `scripts/check-notification-bots.py` — **Telegram notification health** (each bot token via `getMe`, usernames only; plus the `file_id` restore registry with part sizes and age). Run first when the owner says a message never arrived.
- `scripts/lyria-e2e.py` — **E2E прогон музыкального бота по всем юзер-стори** (форж webhook-апдейтов, FSM-сидинг для кнопок, проверки по БД/логам, сбор mp3). Run when asked «проверь бота / прогони сценарии»; детали и грабли — `references/music-bot-lyria.md`.
- `scripts/music-bot-tests.sh` — **юнит/интеграционные тесты music_bot в изоляции** (свои pg/redis/rabbitmq, репо read-only, CI-паритет: ruff + alembic + pytest в polling и webhook). Run when asked «прогони тесты» — никогда не на хосте, там python 3.14 без poetry. Baseline и границы — `references/music-bot-lyria.md`.
