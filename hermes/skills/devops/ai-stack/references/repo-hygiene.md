# Repo hygiene: /home/ai_service/ai-stack

The stack is versioned in git (local repo, **no remote**). A sloppy commit is permanent, so the rules below are gates, not style notes.

## Run git as the repo owner

The working tree belongs to `ai_service`. As root, git aborts with `detected dubious ownership in repository`. Use the service account — its identity is already configured (`VPS Admin <admin@esmien.qd.je>`):

```bash
cd /home/ai_service/ai-stack
sudo -u ai_service git status --porcelain
sudo -u ai_service git add -A
sudo -u ai_service git commit -F - <<'MSG' ... MSG
```

Adding `safe.directory` for root also works but hides that the files are owned by someone else; prefer the account that owns them.

## What never goes into the commit

`.gitignore` already covers `.env` / `**/.env` / `*secrets*` / `*.pem` / `*.key`, `backups/`, `*.dump*`, `*.sql.gz`, `*.bak*`, `*.log`, `__pycache__`. Two entries are easy to miss and both were added after checking the actual files:

- `ai/webui-branding/_state_snapshot/` — `compose.resolved.before.yml` is `docker compose config` output, i.e. **resolved values** of `LITELLM_MASTER_KEY`, `OPENROUTER_API_KEY`, `WEBUI_SECRET_KEY`, DB/Redis passwords. Keep it on disk as rollback evidence; never in git.
- `ai/webui-branding/out/` — generated inside the Dockerfile build stage from `logo_light.png` / `logo_dark.png`; committing the binaries lets them drift from `generate_assets.py`.

Before `git add -A`, read `git status --porcelain` and check that no new filename looks like a secret or a build artifact. `.dockerignore` and `.gitignore` answer different questions — a file excluded from the image can still leak through git.

## `.env` and `.env.example` parity

The example is a contract, not a sample: same **key set in the same order** as the real `.env`. Verify mechanically, never by eye:

```bash
diff <(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' ai/.env) \
     <(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' ai/.env.example) && echo KEYS-IDENTICAL
```

Every key in the example carries a comment: which component reads it, what breaks on rotation, whether containers must be recreated after changing it, and a generation hint (`openssl rand -hex 32`). Mark the ones `deploy.sh` preflight enforces as `[обязательна]` — take that list from `deploy.sh` itself. If the real `.env` is ordered illogically, reorder its lines (values untouched) instead of writing an illogical document.

Ready checker (key names only, never values): `bash scripts/check-env-parity.sh [stack_dir]` — key order diff, preflight keys present and non-empty, plus a dead-key candidate scan that skips backups, `backup-deploy/` and `_state_snapshot/`.

## Dead keys: prove it, then delete

1. `grep -rl --exclude='.env' --exclude='.env.example' KEY .` — discount `backups/`, `backup-deploy/`, `ai/webui-branding/_state_snapshot/`: historical copies are not consumers.
2. Look outside the repo: `/usr/local/bin/*`, `/etc/systemd/system/*`, timers/cron.
3. Check the DB side for credentials — `sudo -u postgres psql -tAc "select rolname from pg_roles where rolcanlogin"` plus `pg_database` owners. A role with a password but no consumer is a dead credential, not a live key (`bot_db` was empty: 0 tables).
4. Read `deploy.sh` preflight; never delete a key it greps for.

Dead keys already removed: `DOMAIN` (domains live as literals in deploy.sh's `SITES`), `POSTGRES_ADMIN_PASSWORD` (deploy uses peer auth through `sudo -u postgres psql`), `BOT_DB_PASSWORD` (role `bot` owns an empty `bot_db`). Report the list with the reason for each before deleting, and report leftover databases/roles separately — dropping them needs the owner's explicit go-ahead.

## Editing `.env` safely

- Back up **outside** the repo: `/var/backups/ai-stack/env.pre-cleanup.<ts>` — a `.bak` beside `.env` is exactly the junk the owner wants gone.
- Never print values; extract key names only (`grep -oE '^[A-Z_]+='`), delete by key (`sed -i '/^KEY=/d' .env`) or reorder lines in python.
- After any rewrite prove nothing was lost: hash the sorted set of non-comment lines before and after, check the key count, and confirm mode/owner stayed `640 root:ai_service`.
- Nothing changes at runtime until containers are recreated, so an unused key can be removed without touching the stack — verify the endpoints anyway (`runbook-containers.md` §5).

## Junk backups

Git replaced timestamped copies as the rollback mechanism: `*.bak.<ts>` files beside configs are junk and get deleted after the change is committed, not left to accumulate. Exceptions worth keeping: `backups/env.bak-*` (the only snapshot of real `.env` secrets) and everything under `backups/postgres/` (the actual DB backup chain) — never touch those.

## Commit shape the owner expects

One commit per coherent change. Russian subject line, then bullets that say **what changed and why it matters**, including deliberate non-changes ("`mem_limit` остались только у litellm — осознанное решение") and consequences (recreate needed, brief downtime). No process narrative, no command replay.

Order of work around a commit:

1. `docker compose config -q` — a config that will not parse must not reach the commit.
2. Consistency pass over parameters *before* committing: "приведи к консистентности" means the whole file follows one convention with exceptions commented in place.
3. Commit.
4. Then make the running state match the repo (recreate the affected services with the incident detector paused), verify, and only afterwards delete the junk copies.
