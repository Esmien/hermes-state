# Installer pitfalls

- `curl | bash` takes stdin: bootstrap uses `exec </dev/tty` before interactive prompts. Test opening a tty in a subshell `( exec 3</dev/tty )` to avoid aborting without a tty.
- `write_file` must be binary-safe: branding assets include PNGs. Compose reads `ai/.env`; `WEBUI_URL` comes from there, not a hardcoded domain. Skip a test `pg_dump` when a backup is under one hour old.
- Compose validation can use `docker compose config -q` with dummy secrets. Never write a masked token placeholder back into `.env`: the installer cleans `__stored_in_notifications_env__` and prefers existing `.env` values. A placeholder persisted as a Telegram token caused HTTP 404.
- `notifications/.env` must be `0640 root:ai_service` for `postgres-backup-notify.service`; check the service and its filtered journal after any change.
- The watcher syncs `assets/` host → repo and can overwrite repository-only asset changes. Coordinate changes to live assets and repository with appropriate approval; review the live watcher before editing.
- `--only fetch` on an empty target needs the installer fallback for `GITHUB_KEY` from the live stack. Otherwise registry lookup fails and fallback `getUpdates` has no result.
- `inotifywait` fails on nonexistent paths. Watch the backup directory rather than a not-yet-created `.tg-registry.json`; exclude dump files and backup logs.
- Verified backup drill: `monitor.py backup` → chunked dumps + registry in hermes-state → `install.py --only fetch --from-bot` → matching SHA256 and `pg_restore --list`. Repeat only in an isolated target directory, never against live data.
- Installer runs can overwrite the set of keys in `ai/.env`; before a live run ensure an existing private backup is available and compare securely without printing secrets. The old `UI_PASSWORD` incident and secret handling rules are in the main skill.
