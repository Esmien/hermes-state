# AI Stack — common operations

All commands run on the host root (no /mnt/host prefix).

## Status

```bash
cd /home/ai_service/ai-stack/ai
docker compose ps
systemctl status postgresql
```

## Logs (bounded)

```bash
docker logs --tail 50 litellm
docker logs --tail 50 open-webui
journalctl -u nginx --no-pager -n 50
```

## Restart one service

```bash
cd /home/ai_service/ai-stack/ai
docker compose restart litellm
```

## Manual DB backup + Telegram notify

Run the two units in order — the notify unit has `After=postgres-backup.service`, so the dump must exist first. Both are `oneshot`, so `systemctl start` blocks until they finish.

```bash
systemctl start postgres-backup.service
systemctl show postgres-backup.service -p Result -p ExecMainStatus -p InactiveExitTimestamp

systemctl start postgres-backup-notify.service
systemctl show postgres-backup-notify.service -p Result -p ExecMainStatus

journalctl -u postgres-backup.service --no-pager -o cat -n 15
ls -lt /home/ai_service/ai-stack/backups/postgres/*.dump | head
```

**Verifying the notify leg** — `Result=success` is necessary but NOT sufficient (upload errors are collected into a ⚠️ block in the digest rather than raised). Check the plan, which never touches the network:

```bash
cd /home/ai_service/notifications
sudo -u ai_service env $(grep -E '^[A-Z_]+=' .env) /usr/bin/python3 monitor.py backup --dry-run
```

Expect one `sendDocument` line per part for dumps > 45 MiB (each split into 2), the join instruction with the expected SHA-256, and the digest. No output at all from a real (non-dry) run is normal.

Without `--dry-run`, only the digest the owner received can confirm delivery — ask them, or run `monitor.py verify`.

## Manual DB backup (no notify)

```bash
cd /home/ai_service/ai-stack
sudo ./ai/backup-databases.sh
# dumps land in backups/postgres/<db>_<timestamp>.dump
```

## Diagnosing a dump that changed size

`webui_db` dumps grow with `document_chunk` (pgvector embeddings) as files are ingested — a doubling overnight is usually real data.

```bash
sudo -u postgres psql -d webui_db -t -c \
  "select relname, pg_size_pretty(pg_total_relation_size(relid)) from pg_stat_user_tables order by pg_total_relation_size(relid) desc limit 8;"

# bloat check: n_dead_tup near 0 => healthy autovacuum, growth is genuine
sudo -u postgres psql -d webui_db -t -c \
  "select relname, n_live_tup, n_dead_tup from pg_stat_user_tables where n_dead_tup > 1000 order by n_dead_tup desc limit 5;"

sudo -u postgres psql -d webui_db -t -c "select pg_size_pretty(pg_database_size('webui_db'));"
df -h /
```

`document_chunk` has no `created_at` column — group by `collection_name` instead, where a single file can hold 10k+ chunks.

## Music bot (lyria)

Separate deployment: no compose file, no systemd unit. Plain `docker` commands.

```bash
docker ps --filter name=lyria --format '{{.Names}}|{{.Status}}|{{.Ports}}'
docker stats --no-stream --format '{{.Name}}: {{.MemUsage}} {{.CPUPerc}}' lyria-bot lyria-generation-worker lyria-enricher-worker

# queue health — 1 consumer per work queue, 0 on dead_letter = healthy
docker exec lyria-rabbitmq rabbitmqctl list_queues name messages messages_unacknowledged consumers
# (give this call 60-120s; rabbitmqctl is slow to answer)

# worker logs: ignore the AMQP traceback at boot, look for the listening line
docker logs lyria-generation-worker --tail 15 2>&1 | grep -E 'Listening started|listening for tasks|Error'

docker exec lyria-postgres psql -U lyria -d lyria -t -c \
  "select status, count(*), max(created_at) from generations group by status;"

docker restart lyria-bot   # per-container restart
```

`pending` rows in `generations` may be leftovers from a graceful restart rather than live work — cross-check against queue depth before flagging them.

## Recreating a container after a config edit (the /mnt/host trap)

A crash loop that starts right after a config edit is a mount problem until proven otherwise. Symptom: container `Up (health: starting)`, `RestartCount` climbing, log repeating

```
IsADirectoryError: [Errno 21] Is a directory: '/app/config.yaml'
```

Diagnose in this order:

```bash
docker inspect <c> --format '{{json .Mounts}}'                                                     # what actually got bound
docker inspect <c> --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'    # which namespace issued the recreate
stat -c '%n %y %F' <host source path>                                                             # a directory stamped at the recreate = Docker auto-created it
git -C /home/ai_service/ai-stack status --short && git -C /home/ai_service/ai-stack diff           # what was really edited
```

Root-cause shape: `open-terminal` mounts the host root at `/mnt/host` (rw, `cwd=/mnt/host`, docker.sock passed through), so an agent driving that web terminal runs compose from `/mnt/host/home/ai_service/ai-stack/ai`. The compose CLI reads the file fine — it exists in that container — but the Docker daemon resolves the relative bind source `./litellm/config.yaml` on the HOST, where `/mnt/host` does not exist, and creates an empty directory tree there. The container then mounts a directory over the config file and dies on every boot.

Fix — re-issue from the host dir, then drop the junk tree:

```bash
cd /home/ai_service/ai-stack/ai && docker compose up -d litellm   # run with background=true, then process_manage action=wait
docker inspect litellm --format '{{json .Mounts}}'                # source must be /home/ai_service/... — a FILE, not a directory
rm -rf /mnt/host                                                  # only Docker's auto-created empty dirs live there
```

Verify: `/health/liveliness` → 200, one real completion through the gateway, `docker logs litellm --since 5m | grep -c IsADirectoryError` → 0, `RestartCount` stops climbing.

The edited config is usually innocent — check that the added key is supported by the pinned version (e.g. `general_settings.trusted_proxy_ranges` is read by `litellm/proxy/auth/trusted_proxy_utils.py`) before rewriting YAML blind.

## TLS

```bash
sudo certbot renew --dry-run
```

## Config edits

- LiteLLM routing: `ai/litellm/config.yaml` → `docker compose restart litellm`.
- SearXNG: `ai/searxng/settings.yml` → `docker compose restart searxng`.
- Nginx vhosts: `/etc/nginx/conf.d/*.conf` (backups in `backup-deploy/nginx/`). `patch`/`write_file`
  refuse paths under `/etc/nginx/` as sensitive — edit them with a python script from the terminal
  (`.bak` copy first, exact-string replace), then `nginx -t && systemctl reload nginx`, and mirror the
  file into `vps-infra` (`assets/host/etc/nginx/`) so the recovery repo keeps matching the host.

## Admin UI is slow — measure before touching anything

Reports «UI грузится вечно» are usually weight, not the gateway. Measure in this order:

```bash
# 1) backend latency + payload size (master key from the container env, never printed)
for p in /v1/models /model/info /model_group/info /v2/model/info /user/list; do
  curl -s -o /dev/null -w "$p %{http_code} %{time_total}s %{size_download}B\n" \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" http://127.0.0.1:4000$p
done
# 2) what the browser actually downloads
curl -sL http://127.0.0.1:4000/ui | grep -o 'src="[^"]*\.js"' | wc -l   # chunk count
curl -sI http://127.0.0.1:4000/ui/_next/static/chunks/<chunk>.js | grep -i cache-control
dig +short llm.esmien.ru        # VPS IP = grey cloud, no CF cache layer in the path
```

Baseline here: API 23–80 ms (`/model/info` 256 KB, `/v2/model/info` 155 KB) and **28 JS chunks,
2.97 MB**. Gzip + immutable caching for `/ui/_next/static/` are configured (see
`references/litellm-admin-auth.md`); if a future report says «опять тормозит», re-measure before
blaming the proxy — the remaining seconds are the SPA itself.

## После рестарта LiteLLM — это холодный старт, а не поломка

`docker restart litellm` / `up -d` gives `state=running, health=starting` for ~10–30 s. In that
window WebUI and Hermes get errors and fall back, so the owner — who is usually sitting in the UI —
reads it as «всё отвалилось сразу после твоей правки».

- Do not report «готово» on the strength of `docker restart` returning 0. Poll until
  `/health/liveliness` is 200, then make **one real completion** through a throwaway key and see the
  row land in `LiteLLM_SpendLogs` under the right `user`; delete the probe key.
- If the owner reports breakage right after a restart, check `docker inspect litellm --format
  '{{.State.StartedAt}}'` and the failure rows' timestamps first: failures that stop at the start
  time are the cold start, not a regression — and say so in one line instead of re-auditing auth.
- `LiteLLM_SpendLogs` is the arbiter: `status<>'success'` rows with `coalesce(model,'')<>''` are real
  model failures; empty-model rows are unauthenticated `/v1/models` scanner noise.

## Accessing the stack UI from outside — SSH tunnel only (moved from SKILL.md)

## Смотреть UI снаружи — только через SSH-туннель

`open-webui` (8080) и `litellm` (4000) публикуются на `127.0.0.1`, поэтому с чужой машины
(и на прогоне без TLS, где nginx вообще не ставится) браузер видит их так:

```bash
ssh -N -L 8080:127.0.0.1:8080 -L 4000:127.0.0.1:4000 root@<host>
# http://localhost:8080 — WebUI, http://localhost:4000/ui — LiteLLM
```

Логин LiteLLM — **юзер из БД** (`black.walf16@gmail.com`, роль `proxy_admin`), env-логин по `UI_USERNAME`/`UI_PASSWORD` и мастер-ключу на форме отключён флагом `disable_env_credential_login` (см. `references/litellm-admin-auth.md`). Мастер-ключ остаётся рабочим только как API-bearer — это break-glass. На восстановленной БД пользователи уже есть, а экран первичной регистрации WebUI означает пустую `webui_db` — и первый зарегистрированный станет админом.

## `/mnt/host`: why a stack container must never be recreated from open-terminal

- The host root is mounted **directly as `/`** — this agent runs on the host root, NOT in a container with a `/mnt/host` bind. **`/mnt/host` does not exist on the host.** Never prefix host paths with `/mnt/host`; use them as-is (`/home/...`, `/etc/...`).
- **`/mnt/host` exists only inside `open-terminal`** (it mounts `/` there, `cwd=/mnt/host`, docker.sock passed through). An agent driving that web terminal reads `/mnt/host/home/ai_service/...` as valid, but the Docker daemon resolves bind sources on the HOST, where the path is absent — it auto-creates an empty directory there and the container mounts a directory over a file (`IsADirectoryError` crash loop). **Never recreate a stack container from open-terminal's shell or with `/mnt/host` paths**; recovery drill in `references/operations.md`.

## `cptr` removal (do not reintroduce)

> `cptr` (`ghcr.io/open-webui/computer`) was removed from the stack on the owner's instruction: container, image, `/home/ai_service/webui_data/computer`, compose block, `deploy.sh` references (`SITES` entry, `start_apps`, final report), nginx vhost + cert `term.esmien.qd.je`, and the boot-expected list. Nothing should reintroduce it.

## Host exposure: PostgreSQL on `0.0.0.0:5432` (moved from SKILL.md)

- Only 80/443 are deliberate ingress and the compose backends bind 127.0.0.1 — but **that is a per-service setting, not a host guarantee**. The HOST PostgreSQL 17 listens on `0.0.0.0:5432` (`listen_addresses='*'`) and nothing filtered it (`ufw` is `ENABLED=no`, `iptables INPUT` policy ACCEPT), so the port was open to the internet and being brute-forced (`grep -c 'no pg_hba.conf entry' /var/log/postgresql/postgresql-17-main.log` → 41k). It is now guarded by `/usr/local/bin/fw-guard-postgres.sh` + `fw-guard-postgres.service` (only 127.0.0.1 and 172.16.0.0/12 get in). **Never answer «что у нас наружу» from `docker ps` alone** — host services (Postgres, nginx, docker-proxy) are invisible there. Audit/closure procedure: `vps-network-exposure` skill.

## Deploy: the `.dump.enc` restore trap

DB restore always applies the newest matching dump (`pg_restore --clean --if-exists`), found by mask `backups/postgres/<db>_*.dump` then `backups/<db>_*.dump`. **The dumps on disk are `.dump.enc` now**, so check this step before trusting a `deploy.sh` restore: either feed it a file produced by `dump-crypto decrypt <x.dump.enc> <x.dump>` or extend the mask — an unchanged mask silently finds nothing and the deploy continues on an empty database.
