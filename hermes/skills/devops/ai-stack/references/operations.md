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
- Nginx vhosts: `/etc/nginx/sites-*` (backups in `backup-deploy/nginx/`).