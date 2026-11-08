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
   - `proxy/auth/login_utils.py` → `_sign_in()`: `_admin_credentials_match()` (env
     `UI_USERNAME`/`UI_PASSWORD`, master key as fallback) or a `LiteLLM_UserTable` row by
     `user_email` + scrypt password; `disable_env_credential_login: true` removes the env path,
     `disable_password_login_when_sso_enabled` removes both. Вызовы и флаги —
     [references/litellm-admin-ui-auth.md](references/litellm-admin-ui-auth.md).
2. **Find the endpoint the UI actually uses — do not guess.** Grep the service log for real traffic:
   ```bash
   docker logs litellm --since 30m 2>&1 | grep -E 'POST /(v[0-9]+/)?login'
   ```
   On LiteLLM the endpoint to test is **`POST /v2/login`** with a **JSON** body. Legacy `POST /login` reads `request.form()`, so a JSON body reaches it as `username="None"` and the answer is a `401` «invalid credentials» **however correct the password is** — a body-format mismatch that reads exactly like a wrong secret. If `/login` must be used, send form-encoded `data={"username":…, "password":…}`, never `json=`.

3. **Parse the right response shape.** v2 returns a `(scheme, token)` pair, so `{"login": true, "token": ...}` does not exist and a naive parser reports failure on success. Judge by HTTP 200 + presence of `token`, not by a `login` field.

   That `token` is a **UI session JWT**, not an API key: sending it as `Authorization: Bearer` answers `401`, and so does the `token=…` cookie on a direct API call. The session's virtual key is inside the claims — base64url-decode the middle JWT segment and use `claims["key"]` (an `sk-…` value) to test what the session can actually do. Claims also give `user_role`, `user_email`, `exp` and `password_reset_required`, which settles «did login succeed as the right principal» without any further probing.

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
- **Verify a policy flag by its observable effect, not by reading files back.** The env-login banner decision is exposed on `/health/readiness` as `details.show_env_credential_login_warning`; one call with the master key settles it without handling any password. Look for such an effect endpoint before reaching for a login attempt — trying the disabled credential to «see if it fails» burns the throttle and proves less.
- **Не объявлять credential мёртвым по тексту ошибки.** Сообщение вида «Credential <name>» в UI/логе называет креденшел, **которым пытались маршрутизировать запрос**, а не подтверждает, что он протух: тот же текст появляется при неверном имени модели и при лимитах апстрима. Перед вердиктом воспроизвести вызов через живой гейтвей и прочитать HTTP-код вместе с телом: `400 Invalid model name passed in model=<X>` — неверное имя группы (не существует как `model_name`), `400 … integer_below_min_value … Expected a value >= 16` — тестовый `max_tokens` ниже минимума апстрима, и только `401`/`403` с текстом про ключ указывает на креды. Проверять на модели, которая точно принадлежит этому креденшелу, и с валидными параметрами; вывод «ключ мёртв» без успешного/неуспешного живого запроса — ложный след, который уводит в перевыпуск рабочих ключей.
- **Editing `.env` without recreating the container changes nothing.** Compare `.env` mtime against `State.StartedAt`; if the file is newer, the running process still holds the old value.
- **The reverse trap:** if the password was ever changed through the UI, it lives in the DB and the `.env` value becomes dead. Rotating `.env` then restarting produces a confusing state where the operator believes they changed the password but still logs in with the old one. Prove it, do not assume it: verify the `.env` candidate against the stored hash (step 5). A `NO-MATCH` settles which side of the drift is stale in one command.
- **Open WebUI answers `400`, not `401`, to a bad signin.** Do not map HTTP status to meaning by habit across services: a `401` on Open WebUI means a blocked or missing route, while the wrong-password signal is `POST /api/v1/auths/signin → 400`.
- **Never print secrets into tool output.** Report length, `sha256[:8]`, character classes, entropy. Real values leak into logs, scrollback and transcripts. This holds when the owner asks directly («выведи пароль как есть»): decline in one line without a lecture, then hand him the one-line command to read it himself (`grep '^KEY=' <file>`) — he owns the file, the transcript is the leak.
- **Do not burn the throttle during verification.** Failed attempts count against the source address; a careless brute-force check can lock the owner out for the cooldown window. Use a throwaway username and a handful of tries.
- **A second admin row is easy to forget.** `select user_email, user_role from "LiteLLM_UserTable"` — an old `proxy_admin` with its own scrypt hash is a full door regardless of how strong the env credential is.
- **`user_id = 'default_user_id'` with `user_email IS NULL` and `password IS NULL` is NOT a door.** It is LiteLLM's internal default-user row. An empty `password` looks alarming in a `psql` listing and invites a pointless cleanup; it cannot authenticate because there is no hash to verify against. Filter it out mentally (or `where user_email is not null`) instead of reporting it as a finding.
- **`updated_at` is the timestamp witness for a DB-side rotation.** It moves on every write, so after the owner says «пароль поменял» this is the cheapest proof that the change landed in the store the login path actually reads — and it works without ever handling the secret. Pair it with a format check (`^scrypt:[A-Za-z0-9+/=]+$`, base64 part a multiple of 4) to catch a half-written row.
- **A very strong env password makes nginx basic auth unnecessary.** Say it plainly when true — it saves the owner a fragile change. 238 bits + throttling on `/v2/login` is an adequate gate for a home server.
- **A generated hex secret fails LiteLLM's password policy, and an admin-set password is *meant* to force a reset.** `POST /user/update {user_id, password}` rejects a hex string with `400 … must include an uppercase letter, include a special character`; append a fixed suffix (e.g. `A!`) and then tell the owner the **effective** string once, in one line — «твоя строка + `A!`» — because he cannot log in with what he sent. The same call silently stamps `password_reset_required = true` on the row, so the next login lands on the forced-reset screen instead of the dashboard; that flag, not HIBP, is the usual cause (`last_breach_check_at` is only stamped by the login-time breach check, which fails open and does not block). If the goal is a straight dashboard check, clear it: `update "LiteLLM_UserTable" set password_reset_required=false where user_id='<id>'` — otherwise leave it and let the owner pick his own password.
- **Секрет, вставленный в чат (особенно в групповой), уже сгорел** — не повторяй его в
  ответе, диффе или переписанном файле; одной строкой скажи, что делать: сменить пароль в
  UI и отозвать всё, что пришло вместе с ним, назвав зависимых клиентов. Разбор —
  [references/login-failure-triage.md](references/login-failure-triage.md).


Полный разбор остальных ловушек — семантика `400`/`401`/`403` и CSRF, дрейф автоматизаций,
гигиена секретов, доступ к `litellm_db` и `general_settings` —
[references/login-failure-triage.md](references/login-failure-triage.md) и
[references/litellm-admin-ui-auth.md](references/litellm-admin-ui-auth.md).

## Verification after rotation

1. New password → `200` + `token` on the live endpoint.
2. Old/incorrect password → `401` with a credentials error, not a different failure mode.
3. Burst of failures → `429` still appears.
4. `.env` hash == container hash, and container started *after* the file edit.
- Every remaining admin row accounted for — check `updated_at` moved, or the row was downgraded/removed.
- For a handover («reset it so I can log in»): `/v2/login` with the delivered password answers `200`, the JWT claims show the right `user_id`/`user_role`, `password_reset_required` is the intended value, and the inner session key returns the full `/v1/models` + `/model/info` lists and a `200` on `/key/generate` with an explicit model list (probe key deleted afterwards). That is the evidence set for «аккаунт полноценный»; a login alone is not.
- `default_user_id` (NULL email, NULL password) explicitly dismissed as the internal row, not a door.

## References

- `references/open-webui-auth.md` — Open WebUI auth model, status codes, offline bcrypt check.
- `references/litellm-admin-ui-auth.md` — **LiteLLM Admin UI**: env credential login vs a DB admin row, disabling the env path in this stack, verifying the flag by effect, and the phantom «admin can't select models» symptom.
- `scripts/probe-litellm-admin-view.py` — probe what a given LiteLLM `user_id` actually sees (`/model/info`, `/v1/models`, key generation), minting and deleting its own probe key; run inside the `litellm` container.
- `scripts/reset-litellm-admin-password.py` — reset a DB admin's password over the API (secret via env, never argv), then prove the account is a full `proxy_admin`: `/v2/login` → JWT claims → inner session key → `/v1/models`, `/model/info`, `/key/list`, `/user/list`, throwaway `/key/generate` + delete. Run when the owner says «пароль не помню, сбрось».
