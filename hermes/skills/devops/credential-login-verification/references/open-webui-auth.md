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

## Fixing the drift

Two options, both change a credential — present them and let the owner choose:

1. Owner supplies the current admin password → update `UI_PASSWORD` in `ai/.env` with `sed -i` (never read the file back).
2. Reset the admin password to the `.env` value — `.env` stays intact, but the owner's web login changes.

After either, restart `owui-signup-approver.service` (the script caches the token in-process) and clear the stuck `pending` row.