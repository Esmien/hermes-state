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

Order of operations is not optional: a working DB admin row must exist and be proven **before** the
flag. The owner sets that password himself in the UI (`Internal Users → + Invite User → proxy_admin →
open the invite link`); an agent resets it with `/user/update` + master key, never with a value typed
into chat.

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
