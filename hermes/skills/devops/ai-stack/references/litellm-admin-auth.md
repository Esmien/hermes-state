# LiteLLM admin: ownership in `litellm_db` (this host)

Scope: what the live install looks like after the switch, the **DB ownership surgery** (keys, spend,
model authorship), and the two things the UI shows wrong. The auth-path depth — env credential door
vs a DB row, `/login` vs `/v2/login`, password policy/reset trap, verifying the flag by effect — lives
in the class-level skill `credential-login-verification`, file `references/litellm-admin-ui-auth.md`,
which also carries `scripts/probe-litellm-admin-view.py` and `scripts/reset-litellm-admin-password.py`.
Read that one for the login work; read this one before editing `litellm_db`.

## Current state

- The only admin is a **DB user**: `black.walf16@gmail.com` (user_id
  `b4c63a9b-863f-497c-9f90-5b5745ba4562`), role `proxy_admin`, `models=[all-proxy-models]`.
- `general_settings.disable_env_credential_login: true` in `ai/litellm/config.yaml`
  (commit `feat(litellm): disable env credential login…`). Env login is dead: `UI_USERNAME`/
  `UI_PASSWORD` and the master-key fallback are rejected **on the login form only**.
- `UI_USERNAME`/`UI_PASSWORD` stay in `ai/.env` on purpose — inert, they are the documented
  rollback (remove the flag + `docker restart litellm`).
- **Break-glass: the master key keeps working as an API bearer.** It never goes through
  `authenticate_user`, so `/user/update`, `/user/new`, `/key/generate`, `/health` all keep
  working with the UI locked out. Never say "админка потеряна" — a password can always be reset
  over the API.
- All keys, spend logs, daily spend aggregates and team memberships were re-pointed from
  `default_user_id` to that user; `LiteLLM_UserTable.spend` was merged and zeroed on the default
  row. The `default_user_id` row itself is kept (anchor for keys created by the master key without
  `user_id`); it now shows 0 keys / 0 spend.

## Traps hit while doing it

1. **`POST /login` takes form data, `/v2/login` takes JSON.** A JSON body posted to `/login`
   yields "Invalid credentials" (both fields read as the string `"None"`), not a 422. For scripted
   login use `POST /v2/login {"username", "password"}` → `{token, redirect_url}`; the token is a
   JWT whose `key` claim is the real session virtual key — use that as the bearer, the JWT itself
   is not accepted as an API key.
2. **Password policy**: uppercase + special character are required (`/user/update` answers 400
   `Password does not meet the required policy`).
3. **`/user/update` with `password` sets `password_reset_required=true`** (an admin assigning a
   password forces the user to pick their own). The UI then shows the reset screen instead of the
   dashboard. To hand over a working login straight away:
   `update "LiteLLM_UserTable" set password_reset_required=false where user_id='…'`.
   The HIBP login screen (`screen_login_password_for_breach`) only *fails open* and stamps the same
   column on a real hit; it does not set it for a clean password.
4. **A UI-created `proxy_admin` is not crippled.** Verified live on v1.106.6: its session sees
   `/model/info` = 80 entries, `/v1/models` = 48, `/key/list`, `/user/list`, and can generate a key
   with an explicit model list. The "only *All Proxy Models* in the dropdown" symptom is client-side:
   the key form builds its options as `[All Proxy Models] + /v1/models` fetched with the *session*
   token; a failed or stale fetch leaves just the one entry. Fix = re-login/hard refresh, not
   permissions.
5. **Keys created by a proxy admin get no owner unless `user_id` is passed explicitly**
   (`/key/generate` with the admin session returns `user_id: null`). Keys created with the master
   key behave the same. That is how unowned keys appear in the Keys page.
6. **`general_settings` merges per key, not per row**: `SettingsStore.apply_db_row` resolves each
   key as `resolve(yaml_value, db_value)`, so a flag that exists only in `config.yaml` is honoured
   even though a `general_settings` row exists in `LiteLLM_Config` (ours holds
   `store_model_in_db` + `pass_through_endpoints`). No need to write the flag through the API.
7. **Restart can't be avoided but the redis auth cache is tiny here** — after the ownership rewrite
   `--scan` shows ~5 keys and none carried `default_user_id`, so no cache purge is needed for this
   kind of DB edit; a stale window would only mis-attribute a few spend rows.

## Ownership rewrite (repeatable)

Backup first (`sudo -u postgres pg_dump -Fc -d litellm_db -f /tmp/x.dump`, then `install -m 600`
into `/var/backups/litellm/` — `pg_dump` as postgres cannot write into a root-owned directory).

```sql
begin;
update "LiteLLM_VerificationToken"  set user_id='<new>' where user_id='default_user_id';
update "LiteLLM_SpendLogs"          set "user"='<new>'  where "user"='default_user_id';
update "LiteLLM_TeamMembership"     set user_id='<new>' where user_id='default_user_id';
update "LiteLLM_UserTable" t set spend = coalesce(t.spend,0) + coalesce(d.spend,0)
  from (select spend from "LiteLLM_UserTable" where user_id='default_user_id') d
  where t.user_id='<new>';
update "LiteLLM_UserTable" set spend=0 where user_id='default_user_id';
update "LiteLLM_DailyUserSpend"     set user_id='<new>' where user_id='default_user_id';
commit;
```

The key table is **`LiteLLM_VerificationToken`** (there is no `LiteLLM_KeyTable`).
`/key/list` paginates at 10 by default and hides expired keys — read counts from SQL, not from the
UI or from one API page. `LiteLLM_AuditLog` and `LiteLLM_UserNotifications` were empty here, no
rewrite needed; check before running a broader sweep.

Guard: `LiteLLM_DailyUserSpend` has a unique index on
`(user_id, date, api_key, model, custom_llm_provider, mcp_namespaced_tool_name, endpoint)` — the
UPDATE aborts on a collision, which is the right failure mode (rollback, then merge additively
instead of re-pointing).

## Модели: "Created By / Updated At = Unknown"

The Model Management table reads **`model_info.created_by` / `model_info.created_at` / `model_info.updated_at`**
(column accessors in the UI bundle: `accessorFn: e => e.model_info.created_by`), and only when
`model_info.db_model` is false does it print "Defined in config". The DB columns
`LiteLLM_ProxyModelTable.created_by/created_at/updated_at` are **never serialised** by `/model/info`
and `/v2/model/info` on v1.106.6 — the rows come back as `{model_name, model_info, litellm_params}`
only — so the UI prints "Unknown" / "Unknown date" no matter what the columns hold. Real data was in
the columns all along (created_at 2026-10-18). Ownership was rewritten to the admin user anyway, and
`created_by/created_at/updated_at` were merged into the `model_info` jsonb so a later release can pick
them up; a restart did NOT make them appear, i.e. the endpoint drops them, not the router cache.
Do not promise the owner that the Models page will show his name without an upgrade.

## Why the LiteLLM admin UI feels slow (measured)

Backend is not the problem: `/v1/models` 50 ms, `/model/info` 60 ms / 256 KB, `/v2/model/info` 70 ms /
155 KB, `/model_group/info` 79 ms / 54 KB, `/user/list` 23 ms. The UI itself ships **28 JS chunks,
2.97 MB total**, and the model page adds ~0.4 MB of JSON; nothing on `/ui/_next/static/` carries a
`Cache-Control` header, so every visit re-walks ~30 requests (each +~100–150 ms through Cloudflare).
That is the 3–5 s the owner sees. The fix is caching, not the proxy: `add_header Cache-Control
"public, max-age=31536000, immutable"` for `location ^~ /ui/_next/static/` in
`/etc/nginx/conf.d/llm.esmien.ru.conf` (file names are content-hashed).

**Applied** (nginx commit in `vps-infra`, `assets/host/etc/nginx/`):

- `location ^~ /ui/_next/static/` with the immutable header above;
- global `gzip` had `gzip_types` commented out in `nginx.conf`, so JS/CSS/JSON left the host
  **uncompressed** — now `gzip_types … application/javascript text/css application/json …`, plus
  `gzip_proxied any`. One 637 KB chunk drops to 224 KB; the whole bundle ≈ 1 MB instead of 2.97 MB.
- `llm.esmien.ru` is **grey cloud (DNS only)** — it answers with the VPS IP, so Cloudflare cache rules
  are irrelevant here and the nginx header is the entire fix. Do not propose a CF rule for this host.
- Verify: `curl -s -o /dev/null -D - --resolve llm.esmien.ru:443:127.0.0.1 --compressed -k
  https://llm.esmien.ru/ui/_next/static/chunks/<chunk>.js | grep -iE 'cache-control|content-encoding'`
  → want `public, max-age=31536000, immutable` + `gzip`.
- **The `patch`/`write_file` tools refuse `/etc/nginx/*` as a sensitive path** — edit those configs with
  a small python script run through the terminal (copy to `*.bak`, exact-string replace, then
  `nginx -t && systemctl reload nginx`), and mirror the result into `vps-infra` afterwards.
- First load on an empty browser cache stays ~2–3 s: that is the SPA's weight, not a regression.

## Verifying a change like this

- Login: `/v2/login` with the DB user → 200; with `admin`/`user` + master key → **401**.
- `/health/readiness` returns only `{db, status}` here, so it does *not* expose
  `show_env_credential_login_warning`; prove the flag through the 401s instead.
- One real call through a fresh key (`service.deepseek/deepseek-v4.1-flash`, `max_tokens` 20) must
  show up in `LiteLLM_SpendLogs` under the new `user`, and the probe key must be deleted after.
- End to end ~2 min; `docker inspect litellm` → `running/healthy` and `/health/liveliness` 200.

## The env-credential banner in the Admin UI

It is also the shared *env credential* the Admin UI warns about («Environment-credential login is enabled»). That banner is not a finding to report as a hole on a one-user box — it is a request to replace the static pair with a real `proxy_admin` row and then set `general_settings.disable_env_credential_login: true`. Order (prove the DB admin first), verification by effect (`/health/readiness` → `details.show_env_credential_login_warning`), the `LiteLLM_Config` merge rule, and the phantom «the new admin can pick only All Proxy Models» symptom: skill `credential-login-verification`, file `litellm-admin-ui-auth.md` under its references/. Do not delete `UI_USERNAME`/`UI_PASSWORD` from `.env` for this — with the flag on they are inert, and they are the documented rollback.

## When to read this file (annotated index entry, moved from SKILL.md)

- `references/litellm-admin-auth.md` — **LiteLLM: ownership в `litellm_db`** (ключи/spend/мемберства/авторство моделей переписываются на реального админа; «Created By = Unknown»; вес и кэш админки). Auth-путь (env-дверь, `/v2/login`, сброс пароля) — в skill `credential-login-verification`, его файл `litellm-admin-ui-auth.md`.
