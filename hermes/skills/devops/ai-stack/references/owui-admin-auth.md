# Open WebUI admin auth (and why `UI_PASSWORD` is the wrong secret)

## Two different admin passwords — keep them apart

- `UI_PASSWORD` in `/home/ai_service/ai-stack/ai/.env` is the **LiteLLM** admin
  password (docker-compose injects it into the `litellm` service).
- The **Open WebUI** admin password is chosen by the owner at first UI login and
  is written nowhere in the stack repo. On this box it is duplicated into
  `OWUI_ADMIN_PASSWORD` in `/root/.config/owui-signup-approver/env` (600 root).
- The two are unrelated and are not guaranteed to match. `install.py` from
  `vps-infra` can silently regenerate `UI_PASSWORD` (it prompts with a
  `secrets.token_urlsafe(...)` default) without touching the WebUI account.

## Symptom of mixing them up

`POST /api/v1/auths/signin` with `{email: <admin email>, password: UI_PASSWORD}`
returns **HTTP 400** and the app log shows only
`open_webui.models.auths:authenticate_user: <email>` + `400`. Open WebUI answers
400 (not 401) for bad credentials, so it looks like a malformed request or a
missing account — it is just a wrong password.

Anything that authenticates to Open WebUI must use `OWUI_ADMIN_PASSWORD`:
`owui-signup-approver.py`, approval-guardian probes, screenshot scripts.

## How to prove a candidate password is the right one

The bcrypt hash is in `webui_db.auth.password`:

```
select email, left(password,7), length(password) from auth;   -- $2b$12$, 60
select password from auth where email='<admin email>';
```

Check a candidate without printing it, using the container's bcrypt:

```
docker exec -i open-webui python -c "import bcrypt,sys;print(bcrypt.checkpw(sys.argv[2].encode(),sys.argv[1].encode()))" '<hash>' "$PASSWORD"
```

A live signin is the final word: `curl -s -o /dev/null -w '%{http_code}' -X POST
http://127.0.0.1:8080/api/v1/auths/signin -H 'Content-Type: application/json' -d
'{"email":"...","password":"..."}'` → `200`.

## Where the working value can be recovered from

`ai-stack/backups/env.bak-*` (older `.env` copies) and `backups/postgres/
webui_db_*.dump` (the auth table is unchanged across dumps — compare the hash
tail to see whether the *account* or the *env var* moved). Extract without
restoring a database:

```
pg_restore -a -t auth -f - webui_db_YYYYMMDD.dump | sed -n '/COPY public.auth/,/^\\\./p'
```

## Approver facts

- `approve` = direct SQL (`UPDATE "user" SET role='user'`) — needs no token, so
  it keeps working while signin is broken. Only `reject` (`DELETE /api/v1/users/
  <id>`) needs the admin token. A silent approver is therefore not a sign of
  health: check reject after any `.env` rotation.
- `admin_token()` caches the JWT in memory; a stale token surfaces as 401 and
  the code retries once with `force=True` → fresh signin.
- Failure text now names the variable to fix:
  `signin failed: HTTP 400 (admin <email>; check OWUI_ADMIN_PASSWORD in <cfg>)`.
