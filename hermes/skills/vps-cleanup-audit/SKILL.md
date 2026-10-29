---
name: vps-cleanup-audit
description: "Use when cleaning up a VPS or resetting it near stock."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [devops, cleanup, audit, ssh, recon, snap, journald, postgres, 3x-ui]
---

# VPS cleanup audit (a host that is not this VPS)

## When to Use

«почистить сервер друга», «убрать всё лишнее, не уронив систему и ssh», «привести к стоковому состоянию», «что тут можно удалить». Any server reached over SSH that is **not** the box this agent lives on. For this VPS's own disk pressure use `vps-disk-reclamation`; for its ports use `vps-network-exposure`.

## Answer shape (owner preference)

**Advice-only mode first.** «здесь делать не надо ничего, нужен совет» = answer with options and tradeoffs, no commands at all. Do not connect until told to.

**«Стоковое состояние» has one honest answer:** руками не достигается, только переустановкой образа или откатом чистого снапшота. Say that in the first line, then rank the options:
1. rebuild из панели хостера (тот же IP, 5–15 мин) — единственный настоящий сток;
2. откат снапшота, снятого сразу после установки;
3. зачистка «прикладного слоя» руками — ~90% эффекта, мусор в `/etc`, пакетах и логах остаётся;
4. ручной `rm -rf /` / `dd` образа — не советовать: риск незагружаемой машины без выигрыша.
Then list what even a manual wipe leaves behind (machine-id, host keys, netplan, `/etc`-остатки, cloud-init кэш, swap/fstab, snap-ревизии, pip/npm-пакеты).

**On-host report shape** (same discipline as the exposure skill):
1. one-line verdict + box facts (OS, vCPU/RAM, disk used/free, uptime);
2. «что есть» — one line per real service with its port and data dir;
3. **tier A — мусор, удаляю без риска**: bullet per item with size + one clause why it is safe;
4. **tier B — решение владельца**: things that are recent installs, unused-but-intentional, or need a product decision (fresh agent install, an unused DB, geo-bases);
5. **tier C — не трогаю**: the service binaries/config/db, TLS renewal, firewall/brute-force defence, sshd, network;
6. totals («~1 ГБ без Hermes, ~3.9 ГБ с ним»), then one-line ask: «скажи делай A или делай A + …».

Every tier-A item needs a number. A cleanup proposal without sizes is not a proposal.

## Procedure

1. **Access.** Password SSH from the agent host needs `sshpass` (`apt-get install -y -qq sshpass`). Wrap it in one scratch script driven by env vars (`$RHOST`, `$RPS`) so every call gets the same `StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=12` and the password never lands in a file. Remove the wrapper when done.
2. **Read-only recon, batched.** 3–4 calls, each grouping independent commands — never one call per question. Exact batches and what each line means: `references/recon-commands.md`.
3. **Classify before judging sizes.** Map every listening socket to a PID → unit → data dir. `ss` shows the product; the disk shows the junk. A big directory belonging to a live listener is tier C, not tier A.
4. **Back up the small load-bearing state before any delete**: copy the panel/app DB (`/etc/x-ui/x-ui.db`) and `pg_dump` the app database into `/root/preclean-<date>/`. ~12 MB buys the owner a rollback and makes «делай» easy to say.
5. **Execute tier by tier, only after confirmation.** Reversible-first: `journalctl --vacuum-size`, `truncate -s 0` on log files, `snap remove`, `apt clean`, `systemctl reset-failed`. Never mix a service restart into the cleanup batch — if something breaks you must know which step did it.
6. **Verify**: `df -h /`, `systemctl is-active <service>`, `ss -tulpn | grep <port>`, and one real request against the service (panel HTTP code) — then report the new free-space number.

## Pitfalls

- **The listening process is the product; its data is not junk.** On a panel/proxy box (3x-ui, xray) the biggest dirs are `/usr/local/x-ui` (binaries + geo bases) and the DB behind it — a 260 MB directory next to an 861 MB journal is load-bearing, the journal is not. Decide from `ss -tulpn` + `systemctl cat`, never from `du` alone.
- **A Postgres database can be the app's backend even when the app also has a sqlite file.** Check tables (`psql -c "\dt"`) before proposing a drop: a schema full of `clients`/`hosts`/`api_tokens` is the panel's live store, not a leftover pet project. A random-looking owner name is normal.
- **journald has no size cap by default** — `journalctl --disk-usage` is usually the single biggest safe win on any long-lived box (861 MB seen on a host with 7 GB used). `--vacuum-size=200M` keeps recent history; say so.
- **`/var/log/btmp*` is the failed-login ledger, not app noise.** On a password-auth host it grows to tens of MB and its size is a **security signal** — report it as «сюда ломятся» in the same breath as the disk number. Truncating is safe (fail2ban keeps its own log).
- **`snap list --all`: rows marked `disabled` are superseded revisions of a live snap** — `snap remove <name> --revision=<rev>` drops the old one only; check `snap connections <name>` and `systemctl is-active snap.<name>.*` before removing the whole snap. A test-only snap (`speedtest`) is a separate, safe call.
- **A failed transient unit has no file to delete.** `/run/systemd/transient/*.service` exists only in RAM: `systemctl reset-failed` and move on; do not hunt `/etc/systemd/system` for it and do not report a reboot as the fix.
- **`apt-get -s autoremove` first.** On a maintained host it answers `0 to remove` — do not promise package cleanup you cannot deliver; the reclaimable apt volume is `/var/cache` (`apt clean`).
- **Extra `geoip_*.dat` / `geosite_*.dat` in an xray bin dir are only safe if the *generated* config does not reference them.** Grep the runtime config (`"geoip:ru"`, `"geosite:ir"`), not the panel's sqlite DB — it is binary and `grep` on it returns nothing useful. Removal is cheap to undo: the panel re-downloads.
- **`acme.sh` + its root crontab + `/root/cert` are load-bearing for TLS**, and deleting them breaks nothing *today* — only at renewal, silently, ~60 days out. Check `openssl x509 -enddate` and keep them in tier C.
- **Root password login on a foreign box is often `PermitRootLogin yes`** — it is also the path you are using. Report it as a risk with the btmp evidence; never tighten sshd as part of «уборка» without a separate confirmation, and remember sshd drops-ins are first-match-wins (`50-cloud-init.conf` beats `60-cloudimg-settings.conf`), so a `99-*.conf` may not take effect — verify with `sshd -T`.
- **A fresh agent/AI install in `/root` is the largest reclaimable item and still not tier A.** Show its parts (tools/, cache/, installs/, plus `~/.npm`, `~/.local/share/uv`) so the owner can choose «целиком» vs «только cache», and say whether the box can carry it (1 vCPU / 1 GB RAM next to a panel + Postgres cannot).
- **Check `who` for other root sessions before deleting anything.** An unfamiliar foreign IP logged in at that moment is a red flag to raise, not a detail to skip.
- **Never echo credentials, `.env`, certs or DB rows into the report**; sizes, table names and expiry dates are enough.
- **SQL through the single-quoted remote command mangles escapes** (`\x27` inside `psql -tAc` becomes a syntax error). Use `psql -c "\dt"` / a plain double-quoted statement, or pipe a heredoc through `bash -s`.

## Related

- Disk consumers and safe-reclaim sets on *this* host: `vps-disk-reclamation`.
- Port/firewall verdict shape and iptables guards: `vps-network-exposure`.
- Rebuilding a box from scratch afterwards: `vps-infra-installer`.
