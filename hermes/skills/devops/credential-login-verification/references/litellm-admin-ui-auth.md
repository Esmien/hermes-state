# LiteLLM Admin UI auth — env credential login vs a real admin row

Depth for the `credential-login-verification` decision «which door is live». Everything here is
read from the pinned `ghcr.io/berriai/litellm` image itself; nothing is guessed from docs.

## Where the code lives (read it, don't guess)

The image is Alpine/BusyBox and ships LiteLLM in a venv, not under `/app/litellm`:

```bash
docker exec litellm python -c "import litellm,os;print(os.path.dirname(litellm.__file__))"
# -> /app/.venv/lib/python3.13/site-packages/litellm
docker exec litellm grep -rn disable_env_credential_login /app/.venv/lib/python3.13/site-packages/litellm
```

BusyBox `grep` has no `--include`; a plain `-rn PATTERN /app` with `| head` is the working form.
Relevant files: `proxy/auth/login_utils.py` (`_sign_in`, `_admin_credentials_match`,
`is_env_credential_login_enabled`), `proxy/config_resolvers/settings_store.py` (YAML vs DB merge),
`proxy/health_endpoints/_health_endpoints.py` (the banner flag on readiness).

## What `disable_env_credential_login` actually closes

- The **login form** only: the `UI_USERNAME`/`UI_PASSWORD` pair, and the master-key fallback used
  when `UI_PASSWORD` is unset. Gate: `general_settings.get("disable_env_credential_login") is True`.
- **Not** the master key as an API bearer token — that path never enters `authenticate_user`, so
  `/user/new`, `/user/update` (password reset), `/health/*` keep working. That is the break-glass:
  a locked-out operator fixes it over the API, no config edit.
- `disable_password_login_when_sso_enabled: true` (only when SSO is *fully* configured) closes
  username/password altogether, env credentials included.
- Rollback is deliberate and cheap: remove the flag, `docker restart litellm`.

## Where the flag belongs on this stack

`ai/litellm/config.yaml` → `general_settings.disable_env_credential_login: true`, committed to git,
then `docker restart litellm` — it is config, not env, so no compose recreate.

**DB merge does not eat it.** With `store_model_in_db: true` the proxy persists a `general_settings`
row in `LiteLLM_Config` (`select param_name, left(param_value::text,200) from "LiteLLM_Config"`), and
whoever saves a setting in the UI rewrites that row. Resolution is nevertheless **per key**
(`SettingsStore.resolve(yaml_value, db_value)`), so a YAML-only key is honoured even after the UI
writes its own subset. Verify by behaviour, not by reasoning (next section).

Do **not** delete `UI_USERNAME`/`UI_PASSWORD` from `.env` as part of this: with the flag on they are
rejected at the form anyway, deleting them buys nothing and costs a compose edit + recreate,
and keeping them keeps the documented one-line rollback.

## Verify the flag without touching any secret

Readiness details expose the banner decision (`show_env_credential_login_warning`), so the check needs
no password — only the master key, taken from the container's own env and never printed:

```bash
docker exec litellm python -c "
import json,os,urllib.request
r=urllib.request.Request('http://127.0.0.1:4000/health/readiness',headers={'Authorization':'Bearer '+os.environ['LITELLM_MASTER_KEY']})
print(json.load(urllib.request.urlopen(r,timeout=20)).get('details',{}).get('show_env_credential_login_warning'))"
# True = env login still live and the UI banner is showing; False = flag took effect
```

On this install readiness answers only `{db, status}` — no `details` object — so that field comes back
`None` and proves nothing. Fall back to the effect that cannot be missed: `POST /v2/login` with
`admin` / `user` plus the master key must answer **401**, while the DB admin still gets `200`. Two
refused logins settle the flag; reading the config back does not.

Order of operations is not optional: a working DB admin row must exist and be proven **before** the
flag. The owner sets that password himself in the UI (`Internal Users → + Invite User → proxy_admin →
open the invite link`); an agent resets it with `/user/update` + master key, never with a value typed
into chat.

## Handing the owner a login when he does not remember the password

The clean path is still the invite link (owner picks the password, agent never sees one). When the
row already exists and the password is lost, the agent resets it over the API with the master key —
no DB surgery, no container restart:

```python
POST /user/update   {"user_id": "<uuid>", "password": "<value>"}      # Authorization: Bearer <master key>
```

Three things bite here:

- **Policy rejects plain hex.** A generated 64-char hex string comes back `400 … must include an
  uppercase letter, include a special character`. Append a memorisable suffix (`A!`), keep the rest
  as the owner sent it, and state the effective string once («твоя строка + `A!`»). He cannot log in
  with the value he typed, and guessing that is a wasted round-trip.
- **The reset stamps `password_reset_required = true`.** The flag is what forces the reset screen on
  next login — HIBP is not involved (`last_breach_check_at` is only stamped by the login-time breach
  check, which fails open and never blocks). Leave the flag if the owner should choose his own
  password now; clear it when the ask is «let me into the dashboard»:
  `update "LiteLLM_UserTable" set password_reset_required=false where user_id='<uuid>'`.
- **Proof of a working handover is two-stage.** Run `/v2/login` (JSON) and expect `200`; then decode
  the returned JWT's claims to read `user_id`, `user_role`, `password_reset_required`, `exp`, and take
  `claims["key"]` — the session's virtual key. The JWT itself is **not** an API bearer (`401`), so use
  the inner `sk-…` for the probes: `/v1/models`, `/model/info`, `/key/list`, `/user/list`, and a
  `/key/generate` with an explicit two-model list, deleting that key afterwards. A `200` on login alone
  proves the password; only the inner-key probes prove the account is the full admin the owner expects.

Report it as a handover, not as a log: what the password is (one line, no commentary), what was
verified and with what counts, and that the account keeps `proxy_admin` rights. If the owner pasted the
password or the master key in chat, say in the same reply that it is now in the thread history and
propose changing it in the UI plus rotating the key — without repeating either value.

## Phantom permissions: «admin created in the UI can't choose models for keys»

Symptom to expect after switching: the key-creation form's model dropdown offers only
**All Proxy Models**. It is a UI rendering artefact, not RBAC. Do not edit roles, teams or
`LiteLLM_UserTable.models` over it.

Mechanism:

- The form's option list is built as `[All Proxy Models]` + the names returned by `/v1/models`
  **fetched with the logged-in session key**. If that XHR fails or the cookie has expired
  (`LITELLM_UI_SESSION_DURATION`), the list is empty and only the sentinel option remains.
- Cure: fresh login / hard refresh. Nothing else.
- `models = {all-proxy-models}` on a user row is the **unrestricted** sentinel, not a downgrade. It
  also renders as a red `All Proxy Models` badge in the key list — looks like a fault, is not one.

Prove the rights from the API instead of trusting the UI, without the admin's password — mint a key
*bound to their user_id* with the master key, probe, delete:

```bash
# inside the litellm container; see scripts/probe-litellm-admin-view.py
python /tmp/probe-litellm-admin-view.py <user_id>
```

Expected on a healthy `proxy_admin`: `/model/info` returns every alias, `/v1/models` (and the
`/v1/models?user_id=<id>&user_role=<role>` impersonation form) returns the full model-name list, and
`/key/generate` with an explicit `models` list answers `200`. A UI-created `proxy_admin` with
`models = {all-proxy-models}` therefore loses nothing versus env login.

Distinguish the two logins where it matters: env-login sessions are minted as
`user_id = default_user_id` on team `litellm-dashboard`; a DB-user session carries the real user_id, so
spend and audit attribute to the person and deleting the row revokes access.

## Audit facts quick-reference

```sql
select user_id, user_email, user_role, models from "LiteLLM_UserTable" order by created_at;
```

- `default_user_id`, NULL email, NULL password = LiteLLM's internal row, **not** a door.
- Any other `proxy_admin` row with a password hash is a full door regardless of how strong the env
  password is — that is the point of the banner, and it is also why disabling the env path is safe
  once that row is proven.


## Code paths of the LiteLLM sign-in (verbatim detail)

   - `proxy/auth/login_utils.py` → `_sign_in()` decides between `_admin_credentials_match()` (env `UI_USERNAME`/`UI_PASSWORD`, with master key as fallback when `UI_PASSWORD` is unset) and a `LiteLLM_UserTable` row lookup by `user_email` + scrypt password.
   - `disable_env_credential_login: true` in `general_settings` removes the env path entirely; `disable_password_login_when_sso_enabled` removes both.
   - Consequence: env credentials and DB password are **independent doors**. Rotating one does not touch the other.
   - Turning the env door off (`disable_env_credential_login`), what it does and does not close, where the flag belongs in this stack, and the trap that follows the switch: `references/litellm-admin-ui-auth.md`.

**Before advising the owner to disable the env login path**, walk the order in that reference: prove a working DB `proxy_admin` row first (he sets the password via the invite link, never in chat), then the flag, then verify by effect — not by re-reading the config.


## general_settings: DB subset vs config.yaml

- **LiteLLM keeps `general_settings` in `LiteLLM_Config` but resolves it per key** (`SettingsStore.resolve(yaml_value, db_value)`), so a flag that lives only in `config.yaml` survives the UI rewriting its own DB subset — and an env-var change needs a container recreate while a config.yaml change needs only `docker restart litellm`. Confirm by behaviour, never by reasoning about the merge.


## psql quoting from a shell string

- **SQL composed inline in a shell string silently loses `"` quoting.** `psql -c 'select … from "user"'` spliced into a double-quoted shell command arrives as `from user` → `relation "user" does not exist` / `column "email" does not exist`. Pass the statement as its own `argv` element from a Python `subprocess` list, never interpolated into a shell command string.


## Login throttling behind the proxy: trusted_proxy_ranges

- **`trusted_proxy_ranges` unset breaks per-IP throttling.** Behind nginx every request arrives from the proxy address (`172.18.0.1`), so the limiter sees one client for the whole internet:
  `WARNING: login_throttle.py: trusted_proxy_ranges is not set ... limited per source address and username only`.
  Set it to the proxy ranges so limits apply to the real client IP.


## Schema: the only password column

- **`LiteLLM_UserTable.password` is the only password column in the schema** — worth confirming once with `information_schema.columns where column_name in ('password','password_hash')` so there is no third door hiding in a table nobody looks at.


## Reading litellm_db from the host, not from a container

- **Reading this DB from the stack's own containers rarely works.** The `litellm` venv has no `psycopg2`, and `lyria-postgres` serves a *different* database (`litellm_db does not exist`). Use a throwaway client on the host network so `127.0.0.1:5432` is the real host Postgres:
  ```bash
  docker run --rm --net=host -e PGPASSWORD="$PASS" postgres:17-alpine \
    psql -h 127.0.0.1 -U litellm -d litellm_db -At -c "<query>"
  ```
  Also note compose often builds `DATABASE_URL` from `${LITELLM_DB_PASSWORD}`, so a literal `DATABASE_URL=` line is absent from `.env` and naive parsing silently yields an empty password.
