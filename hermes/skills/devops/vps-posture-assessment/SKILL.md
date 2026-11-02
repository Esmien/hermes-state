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
   nginx vhost names in `/etc/nginx/sites-enabled/` + grep `server_name|listen|proxy_pass`, `certbot certificates | grep -E "Domains|Expiry"`,
   `sudo -u postgres psql -Atc "select datname, pg_database_size(...)"`, `du -sh /* /home/* /var/lib/docker`.
   Private addresses and DB sizes are fine to print; `.env` values, tokens and keys never are.
2. **Map every claim to its own evidence.** Защита = порты + аутентификация + файрвол/стражи + что за периметром.
   Наблюдаемость = какие таймеры реально идут (`list-timers`, не `list-unit-files`). Бэкапы = что покрыто,
   что нет, куда уезжает, кто это проверяет. Восстановление = путь из репозиториев + дампов + время на каждый шаг.
3. **Verdict first, then the breakdown.** One line answering the actual question («три пункта с оговорками,
   один неверен по терминологии»), then per claim: что подтвердилось → что осталось. Numbers before adjectives.
4. **Offer concrete closures, not a lecture.** 1–4 items with effort estimates; wait for confirmation before
   any change (standing rule: любое изменение — отдельно подтверждается).

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
- **The longest step in a total loss is not data — it is access.** Secrets are deliberately out of git; if there is
  no offsite encrypted copy of `.env` files and no written list of where DNS/tokens come from, that is the real
  remaining gap and worth exactly one recommendation.

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

When the owner corrects one of these, accept it in one line, strike it from the list, and continue — do not
re-argue it in the same answer.

## References

- `references/recovery-rto.md` — measured restore-time budget (полоса, образы, сборки, дампы), what `install.py`
  and `deploy.sh` cover, and what has to be done by hand.
