# Backups and notifications

> Loaded from the `ai-stack` skill. Read this when backups, restore, timers, Telegram notifications.

## Offsite copy of WebUI user files (`webui_data`)

- **The DB dumps never contained uploads/generated images.** `webui_data/` (uploads 688 MB, generated_images 310 MB, cache 487 MB) is restored only from a bundle unless the weekly archive exists. Since 2026-10 there is one: `webui-data-backup.timer` (Sun 04:00 UTC) runs `/usr/local/bin/webui-data-backup.py`, which tars `uploads` + `generated_images` (**cache excluded — regenerable**), splits at `TG_DOC_LIMIT` and uploads ~55 parts / ~980 MB to the file bot, recording a registry set with `db="webui_data"`.
- Restore: `/usr/local/bin/webui-data-restore.py [--target DIR] [--force] [--registry URL]` (verified end-to-end: 55 parts, sha256 ok, 860 files, 997 MB). Bootstrap path: `install.py --from-bot` now fetches the set (`RESTORE_DBS` includes `webui_data`) and the new `data` step unpacks it into `WEBUI_DATA` — it skips a non-empty dir unless `--restore`.
- **Build the registry entry before deleting the split parts.** `backup_registry_entry` hashes every part; deleting them first raises `FileNotFoundError` after the upload already succeeded, leaving 55 orphan files in the chat and no registry.
- **`build_split_instruction` does not fit 55 parts** (Telegram caps a message at 4096 chars). The script sends the full instruction only for ≤10 parts and otherwise a compact `cat …part_* > …` + sha256 line.

## Offsite copies added 2026-11 (Hermes history, .env secrets)

- `hermes-history-backup.timer` (Sun 04:20 UTC) → `/usr/local/bin/hermes-history-backup.py`: consistent
  SQLite snapshots (`sqlite3 .backup`, WAL-safe) of `state.db` + `kanban.db` plus `sessions/`, ~28 MB
  tar.gz → 2 parts to the file bot, registry set `db="hermes_history"`, 2 local archives in
  `/var/lib/hermes-history-backup`. Reason: `hermes-state-backup.sh` ships config/memories/skills/cron/
  plugins but NOT conversation history — after a total loss the chats were gone.
- `secrets-offsite-backup.timer` (Sun 04:10 UTC) → `/usr/local/bin/secrets-offsite-backup.py`: collects
  `.env` files (ai-stack, notifications, `/root/.hermes/.env`, any under `deploy/music_bot`), writes a
  key-name-only inventory, encrypts the tar with AES-256-CBC/pbkdf2-300k using `/root/.secrets/offsite.key`
  (600, generated once), round-trip verifies (decrypt → sha256 → tar listing) and only then uploads the
  `.enc` + inventory to the file bot as `db="secrets_offsite"`. The passphrase is delivered ONCE to the
  notification chat (flag `/root/.secrets/offsite.key.sent`) and exists nowhere else — losing that Telegram
  message loses the archive. Never print it; to rotate, delete key+flag and re-run.
- Both are registered in `install.py` (`CORE_TIMERS` + `HOST_BIN_SCRIPTS`) and mirrored in
  `assets/host/{bin,systemd}` — keep those copies in step with `/usr/local/bin`.

## Which layer actually detects an offline host

- **The primary external watchdog is the GitHub Actions `uptime.yml` in the private `hermes-state` repo**, not
  `deadman-ping`. It probes `https://ai.esmien.ru/` and `https://llm.esmien.ru/health/liveliness` every
  15 min from a runner, keeps state in an open issue labeled `uptime`, and messages Telegram only on the
  up→down and down→up transitions. It depends on repo secrets `TG_TOKEN`/`TG_CHAT`.
- **«Сервер недоступен снаружи» is a claim about the probe, not automatically about the host.** The workflow
  kept probing the retired `esmien.qd.je` names long after that zone stopped resolving, so every run reported
  down while `ai`/`llm` answered 200 from the host. Before debugging the server, open the workflow, read the
  exact URLs it checks and `getent hosts` each one: a hostname without DNS is a permanent false alarm, and the
  fix is the URL in `hermes-state`, not anything on the VPS.
- **`deadman-ping.timer` is the SECOND contour and is not configured**: no `/etc/deadman-ping.url`, no
  `DEADMAN_URL=` key in `notifications/.env`, so the script exits without pinging anything. Since 2026-11 it
  writes one journal line per day (`DEADMAN_URL не задан`) instead of exiting silently. Wiring it needs the
  owner's healthchecks.io check URL — nothing the agent can generate.
- **`uptime-heartbeat.timer` is NOT uptime monitoring.** It is a monthly job (1st, 03:00) that commits to
  `vps-infra/maintainer/uptime-heartbeat.txt` so GitHub does not disable scheduled workflows on an inactive
  repo. Never quote it as «пинг наружу, видно падение хоста».

## External uptime watchdog (server offline)

- Local alerts die with the host, so `.github/workflows/uptime.yml` in the private `hermes-state` repo probes `https://ai.esmien.ru/` and `https://llm.esmien.ru/health/liveliness` every 15 min from a GitHub runner and writes to Telegram via `TG_TOKEN`/`TG_CHAT` repo secrets.
- **State is an open issue labelled `uptime`, not a repository variable** — `GITHUB_TOKEN` gets `403 Resource not accessible by integration` on `/actions/variables`, while `issues: write` works. The `uptime` label must exist or `gh issue create` fails.
- Grep `monitor.py` for `alerts` before claiming disk alerts are missing: `/etc/cron.d/server-monitor` already runs `monitor.py alerts` every 10 min with `DISK_WARN_PERCENT=85` (that is why 76% was silent), and `INODE_*` plus `MAX_BACKUP_AGE_HOURS` are checked there too.

## Dumps are encrypted (2026-11): at rest and in Telegram

- **Why:** `webui_db` holds every chat as plaintext JSON, and the dumps were leaving the host unencrypted (146 MB `PostgreSQL custom database` blobs, mode 644, straight into the file bot). Chat-level encryption inside OWUI does not exist and stock PostgreSQL has no TDE, so the dumps were the real exposure.
- **Scheme:** `/usr/local/bin/dump-crypto` (repo: `assets/host/bin/dump-crypto`) — `openssl enc -aes-256-cbc -pbkdf2 -iter 300000 -salt`, the same primitive and the same key as the offsite secrets archive. Key: `/etc/backup-crypto.key`, a 0440 `root:ai_service` copy of `/root/.secrets/offsite.key` (the timers run as `ai_service` and cannot read `/root`). One key, one recovery procedure.
- **Write path:** `backup-databases.sh` does `pg_dump` → `chmod 600` → `dump-crypto encrypt` (which deletes the plaintext) → retention counts `*.dump.enc`. If encryption fails the script exits 1 and deliberately leaves the plaintext for a human, logging it.
- **Read path:** `collect_backup_groups` globs `<BACKUP_PATTERN>` **and** `<pattern>.enc`; `_restore_into_temp_db` decrypts a `.enc` into its own temp dir before the usual split/re-join/`pg_restore`, so the verified artifact is exactly what the owner gets after `cat parts | decrypt`. Proven end-to-end on the real pair: webui 49 tables / 31.6 s, litellm 106 tables / 17.3 s.
- **Telegram side:** the sent parts are `.dump.enc`, and `build_split_instruction` appends the decrypt command (`openssl enc -d … -pass file:offsite.key`) plus the note that the file is encrypted; sha256 is still computed over the encrypted file, so integrity checks stay valid.
- **Recovery order:** restore `offsite.key` from the notification chat first, then `install -m 0440 -o root -g ai_service /root/.secrets/offsite.key /etc/backup-crypto.key` (or let `install.py` do it — it warns when the offsite key is missing). Without that copy `verify` reports a decrypt failure, not a corrupt dump.
- **`monitor.py verify` / `/backups` still must run as root** — decryption is fine as `ai_service`, but the restore branch needs passwordless `sudo -u postgres`.
- **Renaming or reshaping an on-disk artefact means finding every consumer, not the one you are looking at.** Three separate places in `monitor.py` enumerate dumps by glob: `collect_backup_groups`, the backup-age block inside the check that `alerts` runs every 10 min, and `verify_backup`. Changing the write path to `.dump.enc` while only fixing the first left the 10-minute alert shouting «Не найдены файлы бэкапа … по шаблону '*.dump'» against six intact dumps. They now share `backup_glob_patterns(pattern)`, which returns both `<pattern>` and `<pattern>.enc`. Procedure for any such change: `grep -n 'BACKUP_PATTERN\|\.dump' monitor.py` first, patch every hit, then actually run `monitor.py alerts` twice (first run clears the state, second must send nothing) and one `verify` — an unfixed consumer is silent in code review and loud in the owner's Telegram.

## Backups & notifications

- **`Requires=` in a timer's `[Unit]` makes the timer START its service — including at every boot.** Both backup timers originally carried `Requires=postgres-backup.service` / `Requires=postgres-backup-notify.service`; because `timers.target` starts the timers at boot, systemd pulled the services in too, so every reboot produced a full pg_dump pair (~150 MB, ~13 s CPU) plus a Telegram digest. `Persistent=true` was NOT the cause (stamps were current). Activation is already handled by the implicit `Unit=` (`foo.timer` → `foo.service`); the `Requires=` lines were removed. Symptom to recognise: `journalctl -b | grep postgres-backup` shows `Started postgres-backup.timer` immediately followed by `Starting postgres-backup.service` seconds after boot. Verify a fix with `systemctl show <timer> -p Requires` (must not list the service) and by restarting the timer — the service must stay `inactive`.
- `postgres-backup.timer` (02:30 UTC / 05:30 MSK) runs `ai/backup-databases.sh`: pg_dump of `webui_db` + `litellm_db`, then keeps only the newest `RETENTION_COUNT` (default 3) dumps **per database** and deletes the rest — count-based, not date-based, so several backups made on the same day still collapse to the last 3. DB names are derived from the dump filenames; ordering is by mtime.
- `postgres-backup-notify.timer` (03:00 UTC / 06:00 MSK) runs `notifications/monitor.py backup`: sends the newest dump of each DB to the **file bot** (`FILE_BOT_TOKEN`, `@esmien_ai_backups_bot`) and a digest to the **message bot** (`BOT_TOKEN`, `@esmien_vps_notificator_bot`). Dumps are split adaptively: `split_part_count(size) = ceil(size / TG_DOC_LIMIT)` with `TG_DOC_LIMIT = 18 MiB` — **the limit is the download one, not the upload one.** `sendDocument` takes 50 MB, but `getFile` returns at most 20 MB, so a 45 MiB part sits in the chat and can never be pulled back for a restore (measured: `webui_db` 113 MB → 7×16.2 MiB, `litellm_db` 28.5 MB → 2×14.3 MiB). The join command names all parts and is phrased via `plural_ru(count, ...)` so the wording is right for 3+ parts.
- **A bot cannot read its own chat history — the only handle for restore is `file_id`.** Every part's `file_id`/`message_id` is written to `<BACKUP_DIR>/.tg-registry.json` (newest 3 sets per DB) by `record_backup_registry`, and that file is shipped to the private `hermes-state` repo as `host/backups/tg-registry.json`, from where `install.py --from-bot` downloads the parts and checks `sha256`. Losing the registry does not lose the files but breaks the automatic path: the fallback is the owner forwarding the parts to the bot and `getUpdates` picking them up. Uploaded files of the pre-18-MiB era are unrecoverable regardless.
- Notifications live in **`/home/ai_service/notifications/`** (sibling of `ai-stack`, NOT inside it): `monitor.py`, `README.md`, `.env` (mode 640 root:ai_service). `.env` holds `BOT_TOKEN`, `FILE_BOT_TOKEN`, `BOT_OWNER=214062001`, `BACKUP_DIR`, `BACKUP_PATTERN=*.dump`, `DISK/INODE_WARN|CRIT_PERCENT`, `MAX_BACKUP_AGE_HOURS`, `MONITOR_*_STATE_FILE`. Never print it.
- **The upload digest must say what the recipient is looking at.** Nine part-files in the chat mean nothing to the owner without a mapping, and «в отчёте их нет» is the predictable complaint. `build_backup_digest` therefore ends with a «В файл-боте (реестр file_id)» block fed from `.tg-registry.json` via `registry_sent_parts()`: per DB — part count, average part size, delivery state, and the first 12 hex of the dump's `sha256`. Keep that block in sync with whatever the splitter actually sends; a digest that lists only dump names is an upload receipt that hides the transport.
- **The nightly `backup` digest stays fast and does NOT restore** — it is an upload receipt, so never read its «Сохранены бэкапы» list as proof of restorability; the restore proof is the 03:15 `verify` report. Do not "improve" this by wiring verification into `notify_backup`: that unit runs as `ai_service`, which has no passwordless `sudo -u postgres` (see below), so the restore would fail with a false ❌.
- **Prove delivery with the Bot API's own receipt.** `send_telegram` now prints `monitor: sent message_id=<id> chat=<id> chars=<n>` on every successful send, so `journalctl -u <unit> -n 5` shows delivery instead of leaving it to the exit code. For an offline check, wrap `monitor.urlopen` and assert `result.message_id`. The owner's "уведомление не пришло" is a delivery question, never a code question — answer it from a real `message_id`, not from `rc=0`.
- `/etc/cron.d/server-monitor` runs only `alerts` every 10 min. Docker container events (start/die/stop/restart/oom/create) are watched by `server-monitor-events.service` (root, `monitor.py events`, long-running, `Restart=on-failure`) — the old 3-min `containers` polling cron was replaced by this Events API watcher. It batches events in `MONITOR_EVENT_WINDOW_SECONDS` (default 60 s, which doubles as the send throttle) and reconnects with tenacity exponential backoff (tenacity comes from apt `python3-tenacity`, NOT pip — the cron/systemd interpreter is `/usr/bin/python3` and has no pip). Server metrics are on-demand via the bot command `/health` (snapshot taken at request time).
- `server-monitor-bot.service` (root, `monitor.py bot`) long-polls `getUpdates` and answers BOT_OWNER only: `/health`, `/healthcheck`, `/docker_ps`, `/backups`, `/help`, `/start`. `/healthcheck` is a liveness probe for the bot itself — it replies the fixed `200. Статус: ок` (delivery through the Bot API proves the poll loop is alive); external systems (Docker healthcheck, uptime monitors) use it as an OK signal. Poll offset lives in `/var/lib/server-monitor/bot_state.json`; `flock` blocks a second instance. Code change needs `systemctl restart server-monitor-bot`.
- `/backups` also proves validity: the newest dump of each DB is restored into a throwaway DB (`verify_restore_<db>_<pid>_<ts>`, `pg_restore --no-owner --no-privileges` as `sudo -u postgres`) and the temp DB is dropped in `finally`. **Any** dump bigger than `TG_DOC_LIMIT` is re-split with the same adaptive count and re-joined first (`split = size > TG_DOC_LIMIT`, not a per-DB allowlist — the allowlist silently verified `litellm_db` as one file while the recipient got 2 parts), so the verified bytes are exactly what the recipient gets. ~35 s for a 113 MB + 28 MB pair; the bot sends a «⏳ Проверяю…» ack first.
- **`monitor.py verify` (the nightly 03:15 report) also restores now** — it calls `_restore_into_temp_db` for the newest dump of each DB and prints a «Восстановление (во временную БД)» block; a failed restore lands in «Проблемы» and the closing line reads «✅ Всё в порядке: дампы на месте и восстановлены во временную БД». The nightly `monitor.py backup` digest stays fast and does NOT restore — it is only an upload receipt, so never read its «Сохранены бэкапы» list as proof of restorability.
- **The verify cron must run as root, not `sudo -u ai_service`.** The restore branch needs `sudo -u postgres`; as `ai_service` it dies with `sudo: a password is required` and the report shows a false ❌. The Hermes cron job «Проверка ночного бэкапа PostgreSQL» therefore runs `monitor.py verify` as root (root reads the 640 root:ai_service `.env` fine).
- **Never let the cron LLM agent launch `monitor.py verify` itself — the owner gets duplicate reports.** `verify` sends its message straight from inside the script, so every extra invocation is a duplicate in Telegram. Observed: one cron run produced two sequential `verify` runs (two `verify_restore_*` DB sets, two reports, restore times differing by ~1 s) because the agent ran the same tool command twice in one execution. Fix in place: the job carries the pre-run `script: backup-verify.sh` (`~/.hermes/scripts/backup-verify.sh`, run via bash), which does the actual `verify` once under `flock` and logs to `/var/log/hermes-backup-verify.log`; its stdout is injected into the prompt, and the prompt forbids re-running any backup check. Consequence to respect: the report is sent by the scheduler's pre-run script, not by the agent — so when editing that job, keep the script (or accept the agent sends it and instruct it to run exactly once).
- **Count the runs, not the exit code.** To test any change to the verify path, check the number of distinct `verify_restore_<db>_<pid>` name sets in `journalctl --since '-3min' | grep -o 'verify_restore_[a-z_]*_[0-9]*' | sort -u` — one pid means one report. A single `systemctl`/`hermes cron runs` status cannot reveal the duplicate.
- `monitor.py backup --dry-run` prints the send plan without calling Telegram. `monitor.py verify` checks the last run and sends a report to the message bot; `monitor.py send "text"` sends arbitrary text.
- **A split long HTML message must keep its tags balanced per chunk.** `send_long_message` used to cut every 3900 chars blindly, so a crash/OOM alert whose `<pre>` block with docker logs exceeded the limit produced a chunk with an unclosed `<pre>` and Telegram rejected the whole alert: `HTTP 400: can't parse entities: Can't find end tag corresponding to start tag "pre"`. It now closes the tags left open in a chunk and reopens them in the next (`_open_tags` / `_balance_html_chunks`), and never cuts inside a tag. When adding a new long HTML message, reuse `send_long_message` — hand-rolled slicing silently loses alerts.
- **Reading the verify history:** `/var/log/hermes-backup-verify.log` is one line per night — `verify exit=0` means the restore check ran AND the report was delivered; `verify exit=1` + `monitor: Telegram API HTTP 404` means the check ran but the message died on an invalid/placeholder `BOT_TOKEN`. That single file distinguishes "backups are bad" from "the bot is dead", which look identical in the chat (nothing arrives either way).
- **Token hygiene:** Bot API tokens always look like `<digits>:<35 chars>`; a secret that does not match `^\d{6,12}:[A-Za-z0-9_-]{30,}$` is a placeholder, not a rotated token. `install.json` deliberately stores the mask `__stored_in_notifications_env__`, so never copy a token back from config into `.env`; validate with `getMe` and re-issue via BotFather if it fails — the value cannot be recovered from logs or git.
- **`Result=success` on the notify unit now means the files actually arrived.** `notify_backup` still collects per-file failures into `upload_errors` and renders them as a «⚠️ Не удалось отправить файлы» block inside the digest, but it then **raises `MonitorError`**, which `main()` maps to exit 1 — a lost upload surfaces as `Result=failed`, not a healthy-looking success. Do not remove that raise: it is the only thing keeping the unit honest.
- **`monitor.py backup` prints nothing on success** — only `--dry-run` and error paths emit output. An empty journal for `postgres-backup-notify.service` is the expected healthy case, not a silent failure. Judge it by `Result`/`ExecMainStatus` plus a dry-run, never by the absence of log lines.
- To run a subcommand as the service user: `cd /home/ai_service/notifications && sudo -u ai_service env $(grep -E '^[A-Z_]+=' .env) /usr/bin/python3 monitor.py backup --dry-run`. Never `cat`/print the `.env` contents in the process.
- `monitor.py backup` can be triggered manually to send fresh dumps after a one-off `backup-databases.sh` run; run backup first, notify second, never the reverse (the notify unit has `After=postgres-backup.service`).
- A Hermes cron job (daily 03:15 UTC / 06:15 MSK, id `3378eb7271b7`) runs the pre-run script `backup-verify.sh`, which runs `monitor.py verify` once and reports to the message bot; the agent only analyses the injected output.
- Metrics come from `/proc` + stdlib (meminfo/stat/uptime, `os.getloadavg`, `shutil.disk_usage`), with `psutil` only for per-process top-5 and core counts — prefer `/proc` for stability; fall back to `psutil` only if `/proc` is unreadable.

## Gateway watchdog (independent of LiteLLM) — moved from SKILL.md

- **Docker events already cover `die`/`restart`/`oom`, but not "container Up+healthy, traffic dead".** That gap is closed by `/usr/local/bin/litellm-watchdog.py` + `litellm-watchdog.{service,timer}` (root, oneshot every 60 s, `Requires=sysinit.target` only — never add a `Requires=` naming the service, that makes the timer start it at boot). It probes `http://127.0.0.1:4000/health/liveliness` (`FAIL_THRESHOLD=2` consecutive misses ⇒ DOWN alert, plus a recovery alert), reports the container state in the message, and runs a second check over `LiteLLM_SpendLogs`: last 15 min, ≥10 calls and ≥50 % failures (excluding `/v1/models` and `pass_through_endpoint`) ⇒ «всплеск отказов» alert, throttled 30 min. Alerts go straight to the Bot API (BOT_TOKEN/BOT_OWNER from `/home/ai_service/notifications/.env`), so they arrive while the gateway is dead; state `/var/lib/server-monitor/litellm_watchdog_state.json`, log `/var/log/litellm-watchdog.log`. Test with `--test` (real delivery, returns `message_id`), `--no-send` (prints the alert body), or `LITELLM_WATCHDOG_URL=http://127.0.0.1:4999/...` (fake dead endpoint — fires on the 2nd run).

## Two notification bots — neither implies the other

**Two different bots carry the Telegram notifications, and neither implies the other works.** Hermes sends its own messages with `TELEGRAM_BOT_TOKEN` from `/root/.hermes/.env` (`@esmien_vps_admin_bot`); `monitor.py` uses `BOT_TOKEN` / `FILE_BOT_TOKEN` from `/home/ai_service/notifications/.env` (`@esmien_vps_notificator_bot`, `@esmien_ai_backups_bot`). "Уведомления приходят" therefore proves only the Hermes bot. Verify each token on its own with `getMe` (username only, never print the value) before telling the owner a bot is dead — and after editing `notifications/.env`, restart every unit that reads it: the token is copied into the process memory at start, so a service restarted before the edit keeps polling 404 until the next restart (`journalctl -u server-monitor-bot` shows `getUpdates HTTP 404` every 5 s).

## Answering «сервер защищён / отказоустойчив / бэкапы / восстановлю за 30 минут»

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

## Scripts / index entry (moved from SKILL.md)

- `scripts/check-notification-bots.py` — **Telegram notification health** (each bot token via `getMe`, usernames only; plus the `file_id` restore registry with part sizes and age). Run first when the owner says a message never arrived.
