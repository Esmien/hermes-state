---
name: vps-posture-assessment
description: "Use when grading the host: security, backups, RTO."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [devops, audit, verdict, backups, resilience, rto, owner-facing]
---

# VPS posture assessment (this host)

## When to Use

«Опиши наш сервер», «получается, у меня защищённый/отказоустойчивый сервер?», «бэкапы нормальные?»,
«восстановим всё с нуля за 30 минут?» — any request to characterise the machine or to grade it. Also load it
when the answer will contain the words защищённость / отказоустойчивость / RPO / RTO.

Companion skills: `ai-stack` (what is inside the AI stack, and the backup verification paths),
`vps-network-exposure` (what is reachable from the internet), `vps-infra-installer` (the rebuild path).

## Procedure

1. **Inventory first, one batched pass** (read-only, nothing needs approval):
   `hostnamectl`, `lscpu | grep -E "Model name|^CPU\(s\)"`, `free -h`, `swapon --show`, `df -hT | grep -vE "tmpfs|overlay"`,
   `uptime`, `docker ps --format ...` + `docker stats --no-stream`, `docker system df`,
   `ss -tulpnH`, `systemctl list-unit-files --state=enabled`, `systemctl list-timers`,
   nginx vhost names — they live in `/etc/nginx/conf.d/*.conf` on this host and `sites-enabled/` is empty, so listing it alone reads as «сайтов нет»; grep `server_name|listen|proxy_pass` there, `certbot certificates | grep -E "Domains|Expiry"`,
   `sudo -u postgres psql -Atc "select datname, pg_database_size(...)"`, `du -sh /* /home/* /var/lib/docker`.
   Private addresses and DB sizes are fine to print; `.env` values, tokens and keys never are.
2. **Map every claim to its own evidence.** Защита = порты + аутентификация + файрвол/стражи + что за периметром.
   Наблюдаемость = какие таймеры реально идут (`list-timers`, не `list-unit-files`). Бэкапы = что покрыто,
   что нет, куда уезжает, кто это проверяет. Восстановление = путь из репозиториев + дампов + время на каждый шаг.
3. **Verdict first, then the breakdown.** One line answering the actual question («три пункта с оговорками,
   один неверен по терминологии»), then per claim: что подтвердилось → что осталось. Numbers before adjectives.
4. **Offer concrete closures, not a lecture.** 1–4 items with effort estimates; wait for confirmation before
   any change (standing rule: любое изменение — отдельно подтверждается).
5. **Documents for a third party are redacted.** «Полный обзор, покажи другу» = a `.md` file, not a chat dump:
   no IPs, domains, paths, container names or tokens; keep counts, timings and design decisions. Write it with
   `owner-facing-docs` and offer an internal version separately if he needs it.

## Verdict rules (the part that gets it wrong)

- **A single VM is never «отказоустойчивый».** Say «наблюдаемая и саморемонтируемая»: docker-autorecover,
  litellm-watchdog, deadman-ping, uptime-heartbeat, self-heal timers, Beszel graphs. One disk / one hypervisor /
  one provider = отказ железа кладёт всё. Do not let the owner rename self-healing into HA unchallenged —
  but present it as терминология, not as недостаток.
- **Separate периметр from за-периметром.** Perimeter (ports, keys-only SSH, fail2ban, DB guards) can be genuinely
  strong while one password inside still equals root. Say both in the same answer, in that order.
- **Never grade backups from a directory listing.** A dump directory proves files exist, not that they restore.
  Grep for the verification path (`pg_restore`, `verify_restore_`, `_restore_into_temp_db`) across
  `/usr/local/bin`, `/home/ai_service/notifications/monitor.py` and the stack before saying «не проверялось».
  On this host the dumps ARE restored into a throwaway DB before/after being sent to Telegram — see the
  `ai-stack` skill, file `references/backups-notifications.md`. Getting this wrong is the worst failure of this task class:
  it tells the owner his working backups are hope.
- **RPO and RTO are different answers.** RPO here: 24 h for the two host DBs, 7 days for WebUI files, git for
  configs/harness. RTO: see `references/recovery-rto.md`, ~35–50 min for the AI stack — «30 минут» is optimistic,
  not a lie; say which scenario it applies to (AI stack without lyria).
- **The longest step in a total loss is not data — it is access.** Secrets stay out of git, but there IS an
  offsite encrypted copy now (`secrets-offsite-backup.timer`, weekly, AES-256, file bot) — check it before
  calling access a gap. What remains is narrower: the archive's passphrase was delivered once into Telegram and
  exists nowhere else, and the list of where DNS/tokens/accounts come from still lives in the owner's head.

- **A timer that runs is not a timer that does something.** `systemctl list-timers` proves scheduling only.
  Read `ExecStart`, then the script's config sources: `deadman-ping` ran every 5 min for weeks with no
  `DEADMAN_URL` anywhere and pinged nobody; `uptime-heartbeat` is a monthly GitHub-actions keepalive, not an
  uptime probe. Before grading the monitoring layer, open the script and its env. The `LAST` column carries the
  other half: `-` means the timer has never fired on schedule, even when a manual run succeeded and left
  artefacts on disk — report «настроен, по расписанию ещё не запускался», not «работает».
- **Run distro python tools with `env -u PYTHONPATH`.** The agent's shell exports PYTHONPATH into Hermes's own
  venv (cryptography 50), which shadows the system packages: `certbot certificates` dies with
  `AttributeError: module 'lib' has no attribute 'GEN_EMAIL'` while the same binary works from a clean
  environment and from `certbot.timer`. Unset the variable before declaring a system tool broken.
- **The external eye does exist — check it before saying «мониторинга снаружи нет».** `.github/workflows/uptime.yml`
  in the private `hermes-state` repo (live clone at `/var/lib/hermes-state/repo`, not `/root/hermes-state`) probes ai/llm every 15 min from a GitHub runner and messages Telegram on
  up→down / down→up transitions (state in an open `uptime` issue). `deadman-ping` (healthchecks.io) is the
  unconfigured second contour, and wiring it needs the owner's account URL.
- **Quote swap in use, not `free`'s «available».** `free -h` shows a comfortable 4.5 GiB available because page cache counts as reclaimable, while the swap file holds ~1.9 GB of 4 — the swap figure is the honest statement of the memory margin and the number that belongs in a document. Name it as a thin margin, not as an outage to fix.
- **`docker system df`: read the `RECLAIMABLE` column, not TOTAL.** 13.89 GB of build cache with 43 MB
  reclaimable is not «17 GB можно освободить без потерь» — pruning costs a full rebuild of `esmien/webui`
  and the arduino sandbox (6–10 min of the RTO).
- **`/model/info` entries ≠ routes.** 80 entries over 43 unique upstream models — count both before quoting.
- **Check DBs for content, not just size.** `bot_db` is 7.7 MB of template with 0 tables; quoting it as live
  data is how a summary loses credibility.
- **Harness backup scope:** `hermes-state` carries config/memories/skills/cron/plugins — NOT
  `state.db`/`sessions`. Those now go weekly to the file bot via `hermes-history-backup.timer`.

- **Targeted attack is out of scope by design**: an unadvertised family service, no marketing, no public signup funnel worth attacking. Do not model APT-style scenarios and do not sell countermeasures against them.
- **One VM is a budget constraint, not an oversight**: no money and no point in a cluster for a low-user service with negative ROI. Mitigation he relies on: migration in ~1h with full backup restore, worst case 1 day of data (RPO 24h). Grading a single-VM setup as «нет отказоустойчивости» and leaving it there is nagging — state the terminology once, then the RTO numbers.
- **Family-account phishing is bounded**: those accounts are ordinary users; the ceiling is the token spend of normal chat usage, and there are no per-key limits by his decision. When he asks whether a user JWT reaches the API: it **does** — `POST /api/chat/completions` (and `/api/v1/chat/completions`) authenticates with a plain user JWT, so a stolen token can loop chats from a script for the token's whole lifetime. Admin endpoints stay closed (`/api/v1/users/all`, `/api/v1/configs/export` → 401). Answer that honestly, once, without turning it into a project.
- **JWT facts to quote instead of guessing**: `JWT_EXPIRES_IN=4w`, no refresh token — expiry means a plain re-login, nothing renews silently; sessions can be revoked wholesale (jti/iat against `revoked_at`, admin action reports `sessions_revoked`).

## Accepted risks — do NOT list these as holes

The owner has decided these; re-flagging them wastes the session and reads as nagging:

- `open-terminal` with `/` bind **and** `docker.sock`, reachable from WebUI — single-user contour, signup gated by
  the Telegram approver, only he has access. It is a scope boundary, not a defect.
- **Lyria (music bot) DB is not backed up** and does not need to be: its DB holds nothing valuable by application
  design. Do not propose dumping it again.
- No HA / no failover VM / no replication; `ufw` off with per-service guards instead; Prometheus off (Beszel only).
- No fallbacks between model routes, no key limits — conscious product choices.
- No full-host restore drill yet: accepted, because the recovery plan is «manual install → monitoring shows errors →
  fix → update the deploy script», and the two things that must not be lost (DBs + harness) are already offsite.
  When this comes up, say the procedure is written and ready (Multipass VM + `install.py --secrets-from-bot`,
  `vps-infra-installer` → `references/restore-drill.md`) but has not been run end-to-end yet — never claim «отрепетировано».
- `deadman-ping` without `DEADMAN_URL` (healthchecks.io needs the owner's account). The primary external check is
  the GitHub Actions workflow; note it as «второй контур не подключён», never as a fresh hole.
- `edge-tts` kept as a spare although nothing consumes it; `bot_db` left in place with 0 tables. Removing either
  is destructive and needs a separate explicit go-ahead.

When the owner corrects one of these, accept it in one line, strike it from the list, and continue — do not
re-argue it in the same answer.

## References

- `references/recovery-rto.md` — measured restore-time budget (полоса, образы, сборки, дампы), what `install.py`
  and `deploy.sh` cover, and what has to be done by hand.
