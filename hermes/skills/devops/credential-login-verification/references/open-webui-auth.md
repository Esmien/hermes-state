# Open WebUI auth model (this VPS)

Operational facts for debugging Open WebUI signin failures and the signup-approver bot. Container `open-webui`, host Postgres `127.0.0.1:5432`, db `webui_db`, role `webui`.

## Tables

- **`auth`** — `id`, `email`, `password` (bcrypt, `$2b$12$…`, 60 chars), `active`. There is **no `created_at` column here**; ordering must come from `"user".created_at`.
- **`user`** — `id`, `name`, `email`, `role`, `created_at`. Roles seen: `admin`, `user`, `pending`.

```python
# read-only, argv list, password from ai/.env WEBUI_DB_PASSWORD, never printed
subprocess.run(["psql", "-h", "127.0.0.1", "-U", "webui", "-d", "webui_db",
                "-X", "-A", "-t", "-F", "|", "-c",
                'select email, role, created_at from "user" order by created_at;'],
               env={**os.environ, "PGPASSWORD": env["WEBUI_DB_PASSWORD"]})
```

## Admin identity — two different things

- The **signin email** is the first `user` row with `role = 'admin'` ordered by `created_at`. That is what the approver script resolves via `admin_email()`.
- **`UI_USERNAME` in `ai/.env` is not the signin email** — it can hold a bare handle, not an address. Never pass it as the `email` field; resolve the admin email from the DB.

## `UI_PASSWORD` is a LiteLLM credential, not the WebUI one

`vps-infra/install.py` labels the key «Пароль администратора LiteLLM» and states that the Open WebUI admin password is set at first signin in the UI. The two stores are independent, so the approver reusing `UI_PASSWORD` for `POST /api/v1/auths/signin` is a **cross-service coupling**: any install or rotation pass that regenerates `UI_PASSWORD` kills the approver while the WebUI login stays exactly as the owner left it. Say that plainly — the owner usually did not change anything, and telling him he did is wrong.

## Endpoints and status codes

- `POST /api/v1/auths/signin` → `200` + token, or **`400` for wrong credentials** (not 401).
- `POST /api/v1/auths/signup` → `200`, creates the row with `role = 'pending'` (no admin access until approved).
- `POST /api/v1/auths/update/timezone`, `GET /api/v1/auths/` → normal traffic, `200`.

## Verify a candidate password offline

The host `python3` has no `bcrypt`; the app container does. Compare the candidate against `auth.password` without touching the network or the login throttle:

```bash
docker exec open-webui python -c \
  'import bcrypt,sys; print("MATCH" if bcrypt.checkpw(sys.argv[2].encode(), sys.argv[1].encode()) else "NO-MATCH")' \
  "$HASH" "$CANDIDATE"
```

`NO-MATCH` between `UI_PASSWORD` and the admin hash is the definitive root cause for every `signin failed: HTTP 400` in the approver log.

## The signup approver bot

- Script `/usr/local/bin/owui-signup-approver.py`, service `owui-signup-approver.service`, config `/etc/owui-signup-approver.env`-style file holding `TG_TOKEN`/`TG_OWNER`/`OWUI_BASE`, log `/var/log/owui-signup-approver.log` (rotated daily).
- Loop: every ~2 min it scans `role = 'pending'` rows → sends a Telegram card with approve/reject buttons → handles callbacks.
- **Approve** is a direct DB role update (no API token needed). **Reject** calls the Open WebUI delete-user API, which requires an admin token → `admin_token()` → password signin → the drift shows up here as `action r2 … failed: signin failed: HTTP 400` while approve still works.
- Symptom shape: `scan: N pending, 1 new` then repeated `action r2 … failed: signin failed: HTTP 400`, one per confirm tap. The pending row is left untouched, so the spam signup keeps being offered.
- **Date the breakage from the last successful *reject*, not the last approve.** `grep -hE 'approved|rejected' /var/log/owui-signup-approver.log*` — an approve landing yesterday evening proves only that the direct-SQL path works; the API path may have been dead for days. When the owner says «вечером аппрув работал», that is consistent with auth being broken the whole time.

## Dating the drift (no secrets printed)

The owner's «я ничего не менял» is usually true — prove which side moved instead of arguing:

- **`.env` snapshots.** `/home/ai_service/ai-stack/backups/env.bak-*` holds older copies. Compare key by key, printing only `len()` and equality: `print(f"{k:28} {len(old):>4} {len(new):>4} {'CHANGED' if old != new else 'same'}")`. One `CHANGED` row with every other secret `same` means a targeted rotation, not a rewrite.
- **Old value vs stored hash.** Run the offline bcrypt check on the *backup* value. `MATCH` on the backup and `NO-MATCH` on the live `.env` is the entire root cause in one command, and it yields a working credential without ever printing it.
- **Prove the account hash never moved.** The `auth` row is inside the pg dumps, extractable without restoring:
  ```bash
  pg_restore -a -t auth -f - /home/ai_service/ai-stack/backups/postgres/webui_db_<ts>.dump
  ```
  Parse the `COPY public.auth (…) FROM stdin;` block up to the `\.` terminator, match the admin email, compare hash tails. Identical tails across every dump plus the live row prove the owner's password was never touched and the `.env` is the drifted side.
- **Container env narrows the window.** `docker exec litellm printenv UI_PASSWORD`, hashed, never printed. If it equals the current file value, the file was already at that value when that container started — so the rotation happened *before* that start time, and later `.env` mtimes are unrelated edits.

## Fixing the drift

Prefer the option that mutates nothing:

1. **Decouple (preferred).** Give the approver its own key: add `OWUI_ADMIN_PASSWORD` to the approver's own config file, read it first and fall back to `UI_PASSWORD`. Copy the working value out of the `.env` backup programmatically. Nothing in `.env` or the DB changes, the owner keeps his web login, and the next `install.py` run cannot break it again.
2. Owner supplies the current admin password → update `UI_PASSWORD` in `ai/.env` with `sed -i` (never read the file back). Side effect: that key is also the LiteLLM admin password.
3. Reset the admin password to the `.env` value — `.env` stays intact, but the owner's web login changes.

After any of them, restart `owui-signup-approver.service` (the script caches the token in-process) and clear the stuck `pending` row. Verify with a real signin through the script's own credential source — HTTP `200`, not just a hash comparison.