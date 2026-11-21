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
  **Coverage is an explicit pattern list, not «все секреты»:** `SOURCE_PATTERNS` in
  `/usr/local/bin/secrets-offsite-backup.py` is a glob list and the archive holds only what matches it.
  Current state: the `.env` files, `/etc/turnstile-gate.env`, `/root/.config/owui-signup-approver/env` and
  `/root/.secrets/*.ini` (both Cloudflare tokens). Still outside: `/root/.secrets/*.key|*.json|*.txt` — the
  reality key, the Hysteria users/keys, the subscription share pages. `offsite.key` is excluded deliberately:
  the passphrase must not travel inside its own archive. Read the list, then name the classes covered and not —
  quoting the timer as «секреты уезжают» overstates it.
  Judge a timer by its **effective** schedule, never by elapsed time: read `systemctl cat <unit>.timer`
  **including the `*.timer.d` drop-ins** (an override here rewrites `OnCalendar` from 04:10 to 00:25) and take
  `NEXT` from `list-timers`. A weekly Sunday job whose `LAST` is six days old is on schedule; calling it stale is
  a false alarm the owner should not have to hear. Overdue means `NEXT` is in the past or absent, or `LAST` is
  older than one period **after** the effective calendar was read.

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
  in the private `hermes-state` repo (live clone at `/var/lib/hermes-state/repo`, not `/root/hermes-state`) probes
  `https://ai.esmien.ru/` and `https://llm.esmien.ru/health/liveliness` every 15 min from a GitHub runner and
  messages Telegram on up→down / down→up transitions (state in an open `uptime` issue). `deadman-ping`
  (healthchecks.io) is the unconfigured second contour, and wiring it needs the owner's account URL.
  **Judge the watchdog by its target, not by its verdict:** when it reports «сервер недоступен снаружи», read the
  URLs inside the workflow and `getent hosts` each one before touching the host — the check spent months probing
  retired `esmien.qd.je` names that no longer resolve, so it cried «down» while every service answered 200.
- **Name only the components the inventory actually printed.** A summary is read as fact, so a
  familiar-sounding service filled in from general knowledge becomes a lie in the owner's head:
  an overview once called the ingress «Traefik» on a host where `systemctl` lists `nginx.service`
  and no Traefik exists anywhere. Every daemon, proxy and database named in the answer must trace
  back to a line of this session's `systemctl` / `docker ps` / `ss` output; ingress on this host is
  **nginx (system package, never a container)**.
- **Quote swap in use, not `free`'s «available».** `free -h` shows a comfortable 4.5 GiB available because page cache counts as reclaimable, while the swap file holds ~1.9 GB of 4 — the swap figure is the honest statement of the memory margin and the number that belongs in a document. Name it as a thin margin, not as an outage to fix.
- **`docker system df`: read the `RECLAIMABLE` column, not TOTAL.** 13.89 GB of build cache with 43 MB
  reclaimable is not «17 GB можно освободить без потерь» — pruning costs a full rebuild of `esmien/webui`
  and the arduino sandbox (6–10 min of the RTO).
- **`/model/info` entries ≠ routes.** 80 entries over 43 unique upstream models — count both before quoting.
- **Check DBs for content, not just size.** `bot_db` is 7.7 MB of template with 0 tables; quoting it as live
  data is how a summary loses credibility.
- **Harness backup scope:** `hermes-state` carries config/memories/skills/cron/plugins — NOT
  `state.db`/`sessions`. Those now go weekly to the file bot via `hermes-history-backup.timer`.
- **Prompt injection is not a posture item you can grade as «закрыто».** The model is not a security boundary;
  grade the deterministic layer instead (egress, tool-call hooks, secret isolation, reader isolation) and say
  outright that instructions in a system prompt are not protection. Ranking, what is theatre, and what exists on
  this host — `references/prompt-injection-defense.md`. Never let an LLM-judge or a "prompt that forbids
  following pages" be counted as a control.

## Secret-leak audit («а токен не закоммичен?»)

A standing question with two different answers that must not be merged: **утекло** (value is in a repo, worktree
or history) vs **потеряемо** (value exists only on the host).

1. **Never take the value through argv or chat.** Read it from the file inside the scanning process; the script
   does this for you: `scripts/secret-leak-scan.py --source /root/.secrets/cf.ini` (or
   `--source /etc/hysteria/config.yaml --key cloudflare_api_token`). It prints lengths, repo names, counts and
   redacted context only, and exits 1 on a hit.
2. **History matters as much as the worktree.** `git grep -F` proves the current tree is clean; only
   `git log --all -S <value>` proves the value never travelled. A hit in history means rotate **and** decide about
   the commit — do not force-push a recovery repo to hide it.
3. **Audit every repo, including the harness snapshot.** Recovery repos and the hermes-state live clone
   `/var/lib/hermes-state/repo` (not `/root/.hermes`, which is *not* a git repo). Plaintext placeholders
   (`__CLOUDFLARE_API_TOKEN__`) in templates are the expected shape, not a finding.
4. **Hunt the materialised copy too.** Installers substitute a placeholder from a secrets file into a live config
   (`/etc/hysteria/config.yaml` is written once by `install-hysteria.sh` and keeps the token). That copy is in
   neither recovery repo — good for git, and the second place a host loss takes with it. Say both.
5. **Verify which secret a service actually got, by value.** Skills document the canonical file; the running
   service may hold a different token from a second file. Two Cloudflare tokens coexist here and the prefix tells
   the scope apart: `cfut_…` = user token, zone-scoped, `/root/.secrets/cf.ini` (DNS-01 for `*.esmien.ru`);
   `cfat_…` = account token with full access, `/root/.secrets/cf-esmien-com.ini`, and that is the value
   `install-hysteria.sh` substitutes into `/etc/hysteria/config.yaml`. Comparing values inside the scanning
   process beats trusting the documentation.
6. **A coverage gap is closed with one glob, then proven by the inventory.** Add the pattern to
   `SOURCE_PATTERNS`, run the script with `--dry-run` and read the generated `secrets_<stamp>.inventory.txt`:
   it lists paths, sha256 and key names, never values, so it is safe to grep and is the proof of inclusion.
   Then run it for real instead of waiting for the weekly tick (the owner wants the secret offsite now), and sync
   the host copy in `vps-infra/assets/host/bin/` so the recovery repo still matches the host.

## Scope decisions (same rule: do not re-argue)

- **Targeted attack is out of scope by design**: an unadvertised family service, no marketing, no public signup funnel worth attacking. Do not model APT-style scenarios and do not sell countermeasures against them.
- **One VM is a budget constraint, not an oversight**: no money and no point in a cluster for a low-user service with negative ROI. Mitigation he relies on: migration in ~1h with full backup restore, worst case 1 day of data (RPO 24h). Grading a single-VM setup as «нет отказоустойчивости» and leaving it there is nagging — state the terminology once, then the RTO numbers.
- **Family-account phishing is bounded**: those accounts are ordinary users; the ceiling is the token spend of normal chat usage, and there are no per-key limits by his decision. When he asks whether a user JWT reaches the API: it **does** — `POST /api/chat/completions` (and `/api/v1/chat/completions`) authenticates with a plain user JWT, so a stolen token can loop chats from a script for the token's whole lifetime. Admin endpoints stay closed (`/api/v1/users/all`, `/api/v1/configs/export` → 401). Answer that honestly, once, without turning it into a project.
- **JWT stays at 4 weeks — do not propose shortening it.** A short expiry forces frequent re-login and the annoyance hits the family accounts, not just him; a 256-bit admin password plus the approval gate is the intended trade. Damage control is detection and the revoke-all action, not session lifetime. Quote the facts instead of guessing: `JWT_EXPIRES_IN=4w`, no refresh token — expiry means a plain re-login, nothing renews silently; sessions can be revoked wholesale (jti/iat vs `revoked_at`, admin action reports `sessions_revoked`).

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

- `scripts/secret-leak-scan.py` — checks a secret value against every recovery repo's worktree **and** history,
  then lists secret-shaped literals on recently added lines (redacted). Use it instead of hand-written greps.
- `references/prompt-injection-defense.md` — threat surface, the controls that actually hold (egress allowlist,
  pattern hooks, secret isolation, reader profile), what is theatre, and the honest ceiling with root +
  `docker.sock`.
- `references/recovery-rto.md` — measured restore-time budget (полоса, образы, сборки, дампы), what `install.py`
  and `deploy.sh` cover, and what has to be done by hand.
