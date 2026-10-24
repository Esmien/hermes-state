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
- `hermes-state-watch.service` is dead, the GitHub repo is stale, or the secret guard aborted a commit.
- A new runbook/unit/systemd script must be pulled into the snapshot.

## What exists

| item | path |
|---|---|
| snapshot script | `/usr/local/bin/hermes-state-backup.sh` |
| **trigger: inotify watcher** | `/usr/local/bin/hermes-state-watch.sh` + `hermes-state-watch.service` (inotify, debounce 90 s, max delay 15 min) |
| run-on-demand unit | `hermes-state-backup.service` (oneshot, used by the watcher and manually) |
| legacy timer (**disabled**) | `hermes-state-backup.timer` — kept on disk only as a fallback, must stay disabled |
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

## Change-driven, not scheduled (owner's rule since 2026-10-24)

Backups fire **when the state changes**, not on a clock. `hermes-state-watch.service` runs `inotifywait -r -t 15` over the snapshot inputs (`/root/.hermes/{skills,memories,plugins,hooks,scripts,cron,config.yaml,SOUL.md}`, `/usr/local/bin`, `/etc/systemd/system`, the runbook and the stack backup script), waits for `QUIET=90` seconds without events (`MAXDELAY=900` if changes never stop), then calls the snapshot script. The script itself already no-ops when the tree is unchanged, so a burst of edits produces exactly one commit.

- `inotify-tools` is required (`inotifywait 3.22` present). systemd `.path` units are **not** recursive — they would miss `skills/<name>/SKILL.md`.
- The watcher also runs one snapshot at service start, which covers edits made while it was down (host rebooted, unit stopped).
- A `flock` on `/var/lib/hermes-state/.snapshot.lock` (fd 9, `-w 900`) serialises the watcher and manual runs; without it a manual `systemctl start` during a debounce window produced interleaved commits.
- **Every path in `WATCH` must also be snapshotted.** Watching a file that no `install`/`rsync` line copies produces runs that commit nothing — that is how `runbook-containers.md` was watched but absent from the repo until it was added to the snapshot loop. Add both sides in the same edit.
- Watch files, not whole directories, when the directory carries runtime churn: `cron/` contains `deliveries.db-wal` that is written continuously and reset the debounce forever (no snapshot ever fired). The watcher therefore watches `cron/jobs.json` and excludes `-wal$|-shm$|\.db$|\.usage\.json`.
- After editing the watcher itself: `systemctl restart hermes-state-watch` — that restart triggers a catch-up snapshot, which is the fastest self-test.

## Verify / operate

```bash
systemctl is-active hermes-state-watch.service        # должно быть active (running)
systemctl start hermes-state-backup.service          # принудительный снапшот сейчас
tail -n 20 /var/log/hermes-state-watch.log           # watcher: старт, «changes detected», результат
tail -n 20 /var/log/hermes-state-backup.log          # сам снапшот: commit + push
git -C /var/lib/hermes-state/repo log --oneline -3    # что уже уехало
```
Expected idle output in the backup log: `no changes since last snapshot — nothing to commit`.

## Adding a new runbook/script to the backup

Append the filename to `HOST_BIN`, `HOST_UNITS` or `HOST_ETC` in the script (the stack runbooks are copied by a loop into `host/ai-stack/`). Missing files are skipped silently (`[[ -f ... ]] && ...`), so the arrays can list units that do not exist on every host. Foreign files that live outside those arrays (e.g. `/etc/hosts`, nginx configs) are **not** backed up — say so instead of promising a full-host snapshot.

## Retry after a failed push

A push that fails (GitHub unreachable, token revoked) leaves the commit on the host only. Three mechanisms close that hole:

- the snapshot script compares `git ls-remote origin refs/heads/main` with the local HEAD on **every** run and pushes when they differ (catch-up), so a commit stranded by an outage goes up with the next tick;
- the watcher retries a failed snapshot with exponential backoff (`RETRY_MIN=60` → `RETRY_MAX=300`) instead of waiting for the next edit;
- push failures alert through `hermes send`, throttled to **one message per 30 minutes** (stamp `/var/lib/hermes-state/.last-push-alert`): with retries every 60-300 s an unthrottled alert means a dozen identical messages per outage.

Drills, from cheap to conclusive — `references/push-outage-drill.md`:

- stub: `BACKUP=/tmp/failing.sh WATCH_LOG=/tmp/watch.log QUIET=5 RETRY_MIN=3 RETRY_MAX=6 /usr/local/bin/hermes-state-watch.sh` (the watcher reads those overrides from the environment) — proves backoff only;
- sandbox: copy the repo plus a local bare remote — proves the catch-up branch without touching GitHub;
- live: block `github.com` in `/etc/hosts` (leave `api.github.com` reachable) — proves the whole chain on the real remote; the owner asks for this level of proof.

## Gotchas

- **Do not re-enable `hermes-state-backup.timer`.** The owner replaced the schedule with change-triggered snapshots on 2026-10-24; a timer means duplicate commits and a second source of truth. The unit stays on disk only as a manual fallback.
- `Conflicts=` pointing at the unit itself is dropped by systemd with a warning (`Dependency Conflicts=… is dropped`) — do not “guard” a singleton service that way.
- `write_file` refuses paths under `/etc`; stage the unit in `/root/.hermes/cache/scratch/` and
  `install -m 644` it into place, then `systemctl daemon-reload`.
- The script must run as **root** (`User=root` in the unit) — `/root/.hermes` and the units are root-owned.
- Restore order: copy `hermes/*` → `/root/.hermes/`, `host/bin/*` → `/usr/local/bin`,
  `host/systemd/*` → `/etc/systemd/system`, `host/etc/*` → `/etc/`; then `daemon-reload`, re-create the
  `.env` files with real secrets, restart the gateway user service.
- `postgres-backup.service` runs as `ai_service` and cannot reach `/root/.hermes`, which is why the state
  snapshot is a separate root unit rather than an `ExecStartPost` hook of the DB backup.
- Related watcher for search quality (different subsystem, same principle of not trusting healthchecks): the SearXNG section of the `ai-stack` skill.
