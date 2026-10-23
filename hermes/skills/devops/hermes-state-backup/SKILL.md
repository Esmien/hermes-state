---
name: hermes-state-backup
description: Use when restoring or auditing Hermes' own state backup.
version: 1.0.0
author: Hermes VPS Agent
license: MIT
metadata:
  hermes:
    tags: [backup, git, restore, hermes-state]
    related_skills: [ai-stack, container-incident-response]
---

# Hermes state backup (config + skills + runbooks → private git)

## When to Use

- The user asks where the agent's own settings/skills/runbooks are backed up, or wants a restore drill.
- `hermes-state-backup.timer` failed, the GitHub repo is stale, or the secret guard aborted a commit.
- A new runbook/unit/systemd script must be pulled into the daily snapshot.

## What exists

| item | path |
|---|---|
| snapshot script | `/usr/local/bin/hermes-state-backup.sh` |
| units | `hermes-state-backup.service` / `.timer` (daily **02:30 UTC**, same schedule as `postgres-backup.timer`, `Persistent=true`) |
| working git repo | `/var/lib/hermes-state/repo` (root, 0700) |
| remote | `https://github.com/Esmien/hermes-state` (private, auto-created via API on first run) |
| credentials | `GITHUB_KEY` in `/home/ai_service/ai-stack/ai/.env` → git asks via `GIT_ASKPASS=/var/lib/hermes-state/git-askpass.sh`, so the token never lands in `.git/config` or argv |
| log | `/var/log/hermes-state-backup.log` (logrotate weekly, 4 kept) |
| failure alert | Telegram via `hermes send -t telegram` (works without the gateway running) |

Snapshot layout inside the repo: `hermes/{config.yaml,SOUL.md,memories/,skills/,cron/jobs.json,plugins/,hooks/,scripts/}`,
`host/{bin,systemd,etc,ai-stack}/`, `MANIFEST.sha256`, `README.md`.

## Deliberately excluded

`.hermes/.env`, `ai-stack/ai/.env`, `state.db`, `sessions/`, `logs/`, `cache/`, `installs/`,
`hermes-agent/` (the install), `skills/.hub` (51 MB hub clone), `.curator_ledger.jsonl`, `.usage.json`.
Secrets inside `config.yaml` are `${ENV_VAR}` references only — that is why the file is safe to commit.

## Rules that keep it safe

- The script aborts the commit if a secret-like string appears in the snapshot tree
  (`ghp_`, `sk-`, `AKIA`, bot tokens, PEM private keys), ignoring obvious placeholders
  (`xxx`, `...`, `YOUR_`, `REDACTED`). If it fires, fix the offending file — do not weaken the regex.
- Commit only when the tree actually changed (`git diff --cached --quiet`), so quiet days create no noise.
- Deletions propagate: skills/scripts are synced with `rsync --delete`, so removing a skill locally also removes it from the repo.

## Verify / operate

```bash
systemctl start hermes-state-backup.service          # run now
systemctl list-timers hermes-state-backup.timer      # schedule
tail -n 20 /var/log/hermes-state-backup.log          # outcome
systemctl status hermes-state-backup.service         # exit code of the last run
```
Expected idle output: `no changes since last snapshot — nothing to commit`.

## Adding a new runbook/script to the backup

Append the filename to `HOST_BIN`, `HOST_UNITS` or `HOST_ETC` in the script. Missing files are skipped
silently (`[[ -f ... ]] && ...`), so the arrays can list units that do not exist on every host.

## Gotchas

- `write_file` refuses paths under `/etc`; stage the unit in `/root/.hermes/cache/scratch/` and
  `install -m 644` it into place, then `systemctl daemon-reload`.
- The script must run as **root** (`User=root` in the unit) — `/root/.hermes` and the units are root-owned.
- Restore order: copy `hermes/*` → `/root/.hermes/`, `host/bin/*` → `/usr/local/bin`,
  `host/systemd/*` → `/etc/systemd/system`, `host/etc/*` → `/etc/`; then `daemon-reload`, re-create the
  `.env` files with real secrets, restart the gateway user service.
- `postgres-backup.service` runs as `ai_service` and cannot reach `/root/.hermes`, which is why the state
  snapshot is a separate root unit on the same `OnCalendar` instead of an `ExecStartPost` hook.
