---
name: credential-login-verification
description: "Use when verifying that credentials actually work and which login path is live (rotated secrets, exposed admin panels)."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [devops, auth, credentials, secrets, rotation, litellm, admin-ui, login, exposure, verification]
    related_skills: [vps-network-exposure, ai-stack]
---

# Credential & login-path verification

## When to Use

The owner says any of: «со слабым паролем торчит», «я поменял пароль», «это суперадмин, он в env», «порт закрыл» about an auth gate rather than a socket, or asks for a post-rotation check. Also before claiming an admin panel is protected: a strong password on one login path means nothing if a second path exists.

Core insight: **«пароль поменян» and «дверь закрыта» are different claims.** A service can have several independent authentication paths, each with its own credential store. Rotating one leaves the others exactly as they were.

The same drift bites automations. Any bot that signs in with a password from `.env` — the Open WebUI signup approver is one — starts failing the moment that password is changed through the UI. Open WebUI auth model, status codes and the offline bcrypt check: `references/open-webui-auth.md`.

## Answer shape (owner preference)

**Verdict first**, then the evidence that decided it, then the gated fix. «Вход по новому паролю работает, старая дверь в БД осталась» before any command output. Never open with the investigation.

## Procedure

`scripts/login-path-audit.sh` runs steps 2–7 read-only in one pass and prints no secret values; run it first, then drill into whatever it flags. It auto-detects the `/mnt/host` prefix when executed from inside a container, and resolves the LiteLLM DB password from either a literal `DATABASE_URL` or `LITELLM_DB_PASSWORD` (compose builds the URL itself, so the literal is often absent).

1. **Enumerate authentication paths before testing anything.** Do not assume one. For LiteLLM read the code, it is the only honest source:
   - `proxy/auth/login_utils.py` → `_sign_in()` decides between `_admin_credentials_match()` (env `UI_USERNAME`/`UI_PASSWORD`, with master key as fallback when `UI_PASSWORD` is unset) and a `LiteLLM_UserTable` row lookup by `user_email` + scrypt password.
   - `disable_env_credential_login: true` in `general_settings` removes the env path entirely; `disable_password_login_when_sso_enabled` removes both.
   - Consequence: env credentials and DB password are **independent doors**. Rotating one does not touch the other.

2. **Find the endpoint the UI actually uses — do not guess.** Grep the service log for real traffic:
   ```bash
   docker logs litellm --since 30m 2>&1 | grep -E 'POST /(v[0-9]+/)?login'
   ```
   On LiteLLM 1.105.x the live endpoint is **`POST /v2/login`**; legacy `POST /login` answers `401` **even for correct credentials**. Testing `/login` proves nothing.

3. **Parse the right response shape.** v2 returns a `(scheme, token)` pair, so `{"login": true, "token": ...}` does not exist and a naive parser reports failure on success. Judge by HTTP 200 + presence of `token`, not by a `login` field.

4. **Confirm the credential the container actually holds is the one you think.** File and process drift apart silently:
   ```bash
   # hash, never the value
   sha256(file value) vs sha256(docker inspect --format '{{json .Config.Env}}')
   # and ordering: a .env edit newer than container start is NOT applied
   stat -c %y .env ; docker inspect litellm --format '{{.State.StartedAt}}'
   ```
   Compose maps `${UI_PASSWORD}` from the project `.env` into `environment:`, so editing the file requires `docker compose up -d litellm` (recreate), not `restart`.

5. **Check whether the DB password still opens a door.** Compare the stored scrypt hash against a candidate locally — no network, no lockout risk:
   ```python
   raw = base64.b64decode(stored.split(':', 1)[1] + '=')   # 48 bytes
   salt, digest = raw[:16], raw[16:]
   ok = hashlib.scrypt(candidate.encode(), salt=salt, n=16384, r=8, p=1, dklen=32) == digest
   ```
   Open WebUI instead stores a plain `$2b$12$` bcrypt hash in `auth.password`; verify it the same way, offline, with `bcrypt.checkpw`. See `references/open-webui-auth.md` for the exact command and the admin-identity rules.

6. **Grade strength without printing the secret.** Length, character classes, Shannon entropy per char × length. A 64-char hex string ≈ 238 bits — call it a key, not a password, and say so.

7. **Confirm throttling is live** — it is often the only thing standing between an exposed panel and brute force. Send a short burst of *wrong* credentials to a throwaway username and look for `429`.

8. **Report** which paths are open, which are closed, and what remains.

## Pitfalls

- **A `401` is not proof the password is wrong.** Wrong endpoint, wrong body schema, or a dead legacy route all return `401`. Establish the endpoint from logs first.
- **`login: None` in a JSON response is not a failed login** if `token` is present — v2 changed the shape. Check the raw body before concluding.
- **Editing `.env` without recreating the container changes nothing.** Compare `.env` mtime against `State.StartedAt`; if the file is newer, the running process still holds the old value.
- **The reverse trap:** if the password was ever changed through the UI, it lives in the DB and the `.env` value becomes dead. Rotating `.env` then restarting produces a confusing state where the operator believes they changed the password but still logs in with the old one. Prove it, do not assume it: verify the `.env` candidate against the stored hash (step 5). A `NO-MATCH` settles which side of the drift is stale in one command.
- **A failing automation is the earliest drift detector — and its error text names the emitter.** `signin failed: HTTP 400` from a bot means the credential *that script* reads has drifted; it says nothing about whether the web UI login is broken. `grep -rl "signin failed" /usr/local/bin /home/ai_service` locates the emitter; read its credential loader (`stack_secret(...)`, `admin_email()`) to learn exactly which email and which `.env` key it uses. Then present the two fixes as a choice — sync `.env` to the live password (ask the owner for it) or reset the account to the `.env` value — because both mutate a credential and neither is safe to pick silently.
- **Open WebUI answers `400`, not `401`, to a bad signin.** Do not map HTTP status to meaning by habit across services: a `401` on Open WebUI means a blocked or missing route, while the wrong-password signal is `POST /api/v1/auths/signin → 400`.
- **SQL composed inline in a shell string silently loses `"` quoting.** `psql -c 'select … from "user"'` spliced into a double-quoted shell command arrives as `from user` → `relation "user" does not exist` / `column "email" does not exist`. Pass the statement as its own `argv` element from a Python `subprocess` list, never interpolated into a shell command string.
- **Never print secrets into tool output.** Report length, `sha256[:8]`, character classes, entropy. Real values leak into logs, scrollback and transcripts.
- **Do not burn the throttle during verification.** Failed attempts count against the source address; a careless brute-force check can lock the owner out for the cooldown window. Use a throwaway username and a handful of tries.
- **`trusted_proxy_ranges` unset breaks per-IP throttling.** Behind nginx every request arrives from the proxy address (`172.18.0.1`), so the limiter sees one client for the whole internet:
  `WARNING: login_throttle.py: trusted_proxy_ranges is not set ... limited per source address and username only`.
  Set it to the proxy ranges so limits apply to the real client IP.
- **A second admin row is easy to forget.** `select user_email, user_role from "LiteLLM_UserTable"` — an old `proxy_admin` with its own scrypt hash is a full door regardless of how strong the env credential is.
- **`user_id = 'default_user_id'` with `user_email IS NULL` and `password IS NULL` is NOT a door.** It is LiteLLM's internal default-user row. An empty `password` looks alarming in a `psql` listing and invites a pointless cleanup; it cannot authenticate because there is no hash to verify against. Filter it out mentally (or `where user_email is not null`) instead of reporting it as a finding.
- **`updated_at` is the timestamp witness for a DB-side rotation.** It moves on every write, so after the owner says «пароль поменял» this is the cheapest proof that the change landed in the store the login path actually reads — and it works without ever handling the secret. Pair it with a format check (`^scrypt:[A-Za-z0-9+/=]+$`, base64 part a multiple of 4) to catch a half-written row.
- **`LiteLLM_UserTable.password` is the only password column in the schema** — worth confirming once with `information_schema.columns where column_name in ('password','password_hash')` so there is no third door hiding in a table nobody looks at.
- **Reading this DB from the stack's own containers rarely works.** The `litellm` venv has no `psycopg2`, and `lyria-postgres` serves a *different* database (`litellm_db does not exist`). Use a throwaway client on the host network so `127.0.0.1:5432` is the real host Postgres:
  ```bash
  docker run --rm --net=host -e PGPASSWORD="$PASS" postgres:17-alpine \
    psql -h 127.0.0.1 -U litellm -d litellm_db -At -c "<query>"
  ```
  Also note compose often builds `DATABASE_URL` from `${LITELLM_DB_PASSWORD}`, so a literal `DATABASE_URL=` line is absent from `.env` and naive parsing silently yields an empty password.
- **`basic auth` in front of an API is not a fix.** OpenAI-style clients send `Authorization: Bearer`, not HTTP Basic; and ACME renewal (`authenticator = nginx`) breaks unless `/.well-known/acme-challenge/` stays open. Basic auth only on `/ui/` + `/login`, with the ACME location untouched, is the shape that works.
- **A very strong env password makes nginx basic auth unnecessary.** Say it plainly when true — it saves the owner a fragile change. 238 bits + throttling on `/v2/login` is an adequate gate for a home server.

## Verification after rotation

1. New password → `200` + `token` on the live endpoint.
2. Old/incorrect password → `401` with a credentials error, not a different failure mode.
3. Burst of failures → `429` still appears.
4. `.env` hash == container hash, and container started *after* the file edit.
5. Every remaining admin row accounted for — check `updated_at` moved, or the row was downgraded/removed.
6. `default_user_id` (NULL email, NULL password) explicitly dismissed as the internal row, not a door.
