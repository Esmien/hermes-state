# Hermes agent state (private)

Automatic snapshot of everything that differs from a stock Hermes install on the VPS.
Written by `/usr/local/bin/hermes-state-backup.sh` (systemd timer `hermes-state-backup.timer`,
daily at 02:30 UTC together with the PostgreSQL backup), committed only when something changed.

## Layout

| path | content |
|---|---|
| `hermes/config.yaml` | agent configuration (secrets referenced via `${ENV_VAR}`, not inline) |
| `hermes/SOUL.md` | persona / operating instructions |
| `hermes/memories/` | `MEMORY.md` (agent notes) and `USER.md` (user profile) |
| `hermes/skills/` | authored/curated skills (hub clone and caches excluded) |
| `hermes/cron/jobs.json` | scheduled cron job definitions |
| `hermes/plugins/`, `hermes/hooks/`, `hermes/scripts/` | extensions and helper scripts |
| `host/bin/` | ops scripts from `/usr/local/bin` (incident detector, watchdogs, retention…) |
| `host/systemd/` | unit files from `/etc/systemd/system` |
| `host/etc/` | `docker-autorecover.conf`, expected-containers list, logrotate rule |
| `host/ai-stack/` | DB backup script of the AI stack |
| `MANIFEST.sha256` | checksums of every snapshot file |

## Not included (by design)

`/root/.hermes/.env`, `/home/ai_service/ai-stack/ai/.env`, `state.db`, `sessions/`,
`logs/`, `cache/`, `installs/`, `hermes-agent/` (the install itself), `.hermes/skills/.hub`.
API keys, tokens and session history never leave the host through this repo.

## Restore (sketch)

1. Install Hermes, stop the gateway (`systemctl --user stop hermes-gateway`).
2. Copy `hermes/*` over `/root/.hermes/`, `host/bin/*` to `/usr/local/bin`,
   `host/systemd/*` to `/etc/systemd/system`, `host/etc/*` to `/etc/`, then
   `systemctl daemon-reload && systemctl --user daemon-reload`.
3. Re-create `.hermes/.env` / `ai-stack/ai/.env` with the real secrets, then
   `systemctl --user restart hermes-gateway`.
