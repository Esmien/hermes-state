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
   - Turning the env door off (`disable_env_credential_login`), what it does and does not close, where the flag belongs in this stack, and the trap that follows the switch: `references/litellm-admin-ui-auth.md`.

**Before advising the owner to disable the env login path**, walk the order in that reference: prove a working DB `proxy_admin` row first (he sets the password via the invite link, never in chat), then the flag, then verify by effect — not by re-reading the config.

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

- **A UI-created `proxy_admin` that «can't pick models for keys, only All Proxy Models» has full rights — it is a stale session, not RBAC.** The key form builds its dropdown as `[All Proxy Models]` + the names `/v1/models` returns for the logged-in session key; when that request fails or the cookie expired (`LITELLM_UI_SESSION_DURATION`), only the sentinel option is left. Prove rights from the API by minting a key bound to that `user_id` with the master key (`scripts/probe-litellm-admin-view.py`) — `/model/info` and `/v1/models` come back complete — and cure the symptom with a fresh login. Never «fix» it by editing `user_role`, teams or `LiteLLM_UserTable.models`. `models = {all-proxy-models}` is the *unrestricted* sentinel; it also renders as a red badge in the key list and looks like a fault.
- **Disabling a login path safely means disabling only that path.** `disable_env_credential_login: true` gates the login form; the master key as an API `Bearer` never enters `authenticate_user`, so it stays a working break-glass (`/user/update` resets a password, `/user/new` recreates an admin) and rollback is «remove the flag, restart». Guard against the opposite mistake too: `disable_password_login_when_sso_enabled` closes username/password *entirely*, so never set it while password login is the only proven door.
- **LiteLLM keeps `general_settings` in `LiteLLM_Config` but resolves it per key** (`SettingsStore.resolve(yaml_value, db_value)`), so a flag that lives only in `config.yaml` survives the UI rewriting its own DB subset — and an env-var change needs a container recreate while a config.yaml change needs only `docker restart litellm`. Confirm by behaviour, never by reasoning about the merge.
- **Verify a policy flag by its observable effect, not by reading files back.** The env-login banner decision is exposed on `/health/readiness` as `details.show_env_credential_login_warning`; one call with the master key settles it without handling any password. Look for such an effect endpoint before reaching for a login attempt — trying the disabled credential to «see if it fails» burns the throttle and proves less.
- **Не объявлять credential мёртвым по тексту ошибки.** Сообщение вида «Credential <name>» в UI/логе называет креденшел, **которым пытались маршрутизировать запрос**, а не подтверждает, что он протух: тот же текст появляется при неверном имени модели и при лимитах апстрима. Перед вердиктом воспроизвести вызов через живой гейтвей и прочитать HTTP-код вместе с телом: `400 Invalid model name passed in model=<X>` — неверное имя группы (не существует как `model_name`), `400 … integer_below_min_value … Expected a value >= 16` — тестовый `max_tokens` ниже минимума апстрима, и только `401`/`403` с текстом про ключ указывает на креды. Проверять на модели, которая точно принадлежит этому креденшелу, и с валидными параметрами; вывод «ключ мёртв» без успешного/неуспешного живого запроса — ложный след, который уводит в перевыпуск рабочих ключей.
- **A `403` on `POST /login` is CSRF, not a wrong password.** Go panels (3x-ui 3.x, and most cookie-session UIs) embed `<meta name="csrf-token" content="…">` in the login page and require that value in an `X-CSRF-Token` header alongside the session cookie. Fetch the page first, extract the token, then post — a bare post answers 403 with an empty body however correct the password is. Behind a proxy the same 403 appears when the panel's origin check sees a mismatched host: pass `Host $http_host` (port included) and `X-Forwarded-Proto $scheme` from nginx, because `Host $host` drops the port while the browser's `Origin` keeps it. The 3x-ui case, with rotation and a working verification sequence, is written up in the `vpn-entry-stack` skill (its `xui-panel` reference).
- **A `401` is not proof the password is wrong.** Wrong endpoint, wrong body schema, or a dead legacy route all return `401`. Establish the endpoint from logs first.
- **`login: None` in a JSON response is not a failed login** if `token` is present — v2 changed the shape. Check the raw body before concluding.
- **Editing `.env` without recreating the container changes nothing.** Compare `.env` mtime against `State.StartedAt`; if the file is newer, the running process still holds the old value.
- **The reverse trap:** if the password was ever changed through the UI, it lives in the DB and the `.env` value becomes dead. Rotating `.env` then restarting produces a confusing state where the operator believes they changed the password but still logs in with the old one. Prove it, do not assume it: verify the `.env` candidate against the stored hash (step 5). A `NO-MATCH` settles which side of the drift is stale in one command.
- **A failing automation is the earliest drift detector — and its error text names the emitter.** `signin failed: HTTP 400` from a bot means the credential *that script* reads has drifted; it says nothing about whether the web UI login is broken. `grep -rl "signin failed" /usr/local/bin /home/ai_service` locates the emitter; read its credential loader (`stack_secret(...)`, `admin_email()`) to learn exactly which email and which `.env` key it uses. Prefer the fix that mutates nothing: give the automation its own credential key in its own config and fall back to the shared one. The emitter is usually a **cross-service coupling** — a bot reads `UI_PASSWORD` to sign into a service where that key is not the real password (it is the *other* service's admin credential), so it breaks on the next install pass that regenerates the key while the owner's actual login stays untouched. Only if decoupling does not fit, present the two mutating options as a choice — sync `.env` to the live password (ask the owner for it) or reset the account to the `.env` value.
- **Open WebUI answers `400`, not `401`, to a bad signin.** Do not map HTTP status to meaning by habit across services: a `401` on Open WebUI means a blocked or missing route, while the wrong-password signal is `POST /api/v1/auths/signin → 400`.
- **SQL composed inline in a shell string silently loses `"` quoting.** `psql -c 'select … from "user"'` spliced into a double-quoted shell command arrives as `from user` → `relation "user" does not exist` / `column "email" does not exist`. Pass the statement as its own `argv` element from a Python `subprocess` list, never interpolated into a shell command string.
- **Never print secrets into tool output.** Report length, `sha256[:8]`, character classes, entropy. Real values leak into logs, scrollback and transcripts. This holds when the owner asks directly («выведи пароль как есть»): decline in one line without a lecture, then hand him the one-line command to read it himself (`grep '^KEY=' <file>`) — he owns the file, the transcript is the leak.
- **When the owner pastes a config or log containing a live key, that key is already burned.** Do not echo it back in the reply, the diff or a rewritten file — refer to it as «твой ключ» and edit around it. Finish with two concrete actions: revoke/rotate it in the issuing UI, and move it out of the config into env or the client's auth store. Config files travel into backups and git; a key in one is a key in every copy.
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
- Every remaining admin row accounted for — check `updated_at` moved, or the row was downgraded/removed.
- `default_user_id` (NULL email, NULL password) explicitly dismissed as the internal row, not a door.

## References

- `references/open-webui-auth.md` — Open WebUI auth model, status codes, offline bcrypt check.
- `references/litellm-admin-ui-auth.md` — **LiteLLM Admin UI**: env credential login vs a DB admin row, disabling the env path in this stack, verifying the flag by effect, and the phantom «admin can't select models» symptom.
- `scripts/probe-litellm-admin-view.py` — probe what a given LiteLLM `user_id` actually sees (`/model/info`, `/v1/models`, key generation), minting and deleting its own probe key; run inside the `litellm` container.
