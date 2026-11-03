# Recovery time budget (this host)

Use when the owner asks «за сколько поднимем с нуля» or when a rebuild has to be estimated honestly.
Numbers below were measured on the host, not assumed.

## Bandwidth is the floor

- Egress measured with a 100 MB Hetzner pull: **≈29.5 MB/s (~236 Mbit/s)**. Re-measure before quoting if the
  provider or the plan changed: `curl -o /dev/null -m 10 -w "%{speed_download} B/s\n" https://ash-speed.hetzner.com/100MB.bin`
  (Cloudflare's `speed.cloudflare.com` endpoint may return a 1-byte body here — do not read that as a dead link).
- Docker images on this host total **≈21 GB** → ≈12 min of download alone at that rate.
- There is **no registry mirror** in `/etc/docker/daemon.json`; pulls go straight to ghcr/docker hub.

## Step costs

| Step | Cost | Note |
|---|---|---|
| apt base + PostgreSQL 17 + pgvector + roles/DBs | 3–4 min | `install.py` step sequence |
| Pull ≈21 GB of images | ~12 min | unpack on 4 vCPU adds 5–8 min |
| **Build** `esmien/webui:local` and `esmien/open-terminal-arduino:local` | 6–10 min | these are NOT pulls — local Dockerfiles (`ai/webui-branding/`, `ai/arduino-sandbox/`); forgetting this breaks every estimate |
| Restore `webui_db` (120 MB) + `litellm_db` (34 MB) | 2–3 min | `pg_restore`, newest dump auto-applied by `deploy.sh` |
| `webui_data` (1.5 GB, 55 Telegram parts) | 5–8 min | `webui-data-restore.py`, weekly archive |
| Certbot + nginx vhosts | 1–2 min | needs DNS already pointing at the new IP |

Total for a live AI stack with data: **35–50 min**. Machine-time floor is ~25 min, so «30 минут» is the
optimistic end of the range, not a fabrication — quote it as «около часа, если канал не просядет».

## What the rebuild path actually covers

- `install.py` (from the `vps-infra` repo): PostgreSQL + roles/DBs, TLS/nginx, the `ai` stack, Beszel,
  VPN assets incl. the xray config, notify/autorecover units, Hermes from the `hermes-state` repo.
  Useful flags: `--restore`, `--restore-hermes`, `--from-bot` (fetches DB and webui_data sets from Telegram),
  and `--secrets-from-bot --secrets-key <passphrase file>` which downloads the encrypted `.env` archive and
  lays all four files back into place with the right owners/modes.
- `deploy.sh` inside `/home/ai_service/ai-stack`: containers + restore of the newest local dump.
- **Not covered, by hand every time**: lyria (its own compose lives in `/root/deploy/music_bot/infra`, outside the
  installer and outside backups — owner's decision, so treat its loss as accepted), stale project checkouts
  (e.g. a `payment-service` tree that is not deployed), Beszel history, DNS records.
- The single durable artefact for «3 часа ночи» is `runbook.md` in the stack repo (симптомы A–E). Keep it in
  sync when a recovery procedure changes.

## The real bottleneck in a total loss

Images and dumps are mechanically reproducible; **access used to be the gap, and it is now mostly closed.**
`.env` files are git-ignored on purpose, but since the weekly offsite job exists they are not lost with the disk:
`secrets-offsite-backup.timer` (Sun 04:10 UTC) tar+gzips every `.env` (ai-stack, notifications, `/root/.hermes`,
`music_bot`), encrypts with AES-256-CBC/pbkdf2-300k using `/root/.secrets/offsite.key` (600), round-trip verifies,
and uploads the `.enc` plus a key-names-only inventory to the file bot under `db="secrets_offsite"`.

So do **not** repeat the old line «offsite copies of secrets do not exist» — that was true before this job and is
now wrong. The remaining single point of failure is the **passphrase**: it was delivered to Telegram exactly once
(flag `/root/.secrets/offsite.key.sent`) and exists nowhere else. If the owner cannot find that message, the archive
is unreadable after a total loss — say that instead, and recommend he put it in a password manager.

A restore from the archive was verified end-to-end into a throwaway root (`VPS_INFRA_SECRETS_ROOT=/tmp/x`): four
files, perms `640 root:ai_service` (`600` under `/root`), sha256 of each identical to the inventory.

Still manual after a total loss: DNS records and the passphrase itself.
