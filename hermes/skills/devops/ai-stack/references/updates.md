# Updating stack containers

> Loaded from the `ai-stack` skill. Read this when upgrading one container, rolling tags, LiteLLM upgrade.

## Updating one container (e.g. Open WebUI)

Review the delta first (recipe in `references/upstream-release-review.md`), then backup and pull+recreate just that service — never a full `deploy.sh` (it restores DBs):

```bash
docker inspect open-webui --format '{{.Image}}'   # record the CURRENT image id for rollback
sudo -u ai_service /home/ai_service/ai-stack/ai/backup-databases.sh   # ABSOLUTE path; retention keeps newest 3 per DB
cd /home/ai_service/ai-stack/ai
docker compose pull open-webui                    # foreground is fine
docker compose up -d open-webui                   # run with background=true, then process_manage action=wait
```

- **Version bumps take throwaway backups, not permanent ones.** The owner's standing instruction: dump the affected DB plus copies of `.env`, `.env.example`, `docker-compose.yml`, the Dockerfile and `docker inspect` output into a timestamped temp dir (e.g. `/root/owui-update-<ts>/`), do the work, verify, then delete the whole dir and any `/tmp` scratch — «убери за собой мусор». Never leave `*.bak.<ts>` copies next to configs; git history is the record (see `references/repo-hygiene.md`). A `pg_dump` written as `postgres` into a root-only dir fails with permission denied — dump to `/tmp` first and `mv` with `chmod 600`.
- **`up -d` must be run with `background=true`.** It returns instantly in reality, but the terminal tool's foreground guard rejects it as an "apparent long-lived server/watch process" — run it backgrounded (add `notify`), then wait on the handle with `process_manage action=wait`. `pull` runs fine in the foreground.
- **`ENABLE_DIRECT_INTEGRATIONS` gates the terminal/tool servers since 0.12.4.** While off (the default) saved Integrations connections are silently dropped from chats; before 0.12.4 the flag only hid the settings tab, so an instance can look fine and lose its terminal. Verify via a token login → `curl -s /api/config` (`features.enable_direct_integrations`) and the boot log line `Initialized N terminal server(s)`. **The env var alone is not enough** — `Config.seed_defaults(DEFAULT_CONFIG)` only fills missing keys, so an existing `direct.integrations.enable=false` row in the `config` table wins over the env; flip it too: `sudo -u postgres psql -d webui_db -c "update config set value='true'::json where key='direct.integrations.enable'"`. Same precedence applies to every PersistentConfig key.
- **Verify** (with fresh output): `docker inspect open-webui --format '{{.State.Health.Status}}'` (expect `healthy`), `curl -s 127.0.0.1:8080/api/version` (returns the version actually running — JSON, not the image tag), `docker inspect open-webui --format '{{.RestartCount}}'` (expect `0`), and `curl -s -o /dev/null -w '%{http_code}' 127.0.0.1:8080/` (expect `200`). Then read the alembic lines: `docker logs open-webui --since 5m | grep -iE 'alembic|migrat|error|traceback'` — schema migrations run on start, so a failed migration shows up there.
  - A clean boot on a patch bump can log only `Context impl PostgresqlImpl` / `Will assume transactional DDL` with **no `Running upgrade` line** — that means no pending migrations, not a broken run.
  - Grepping the logs for `error` also matches unrelated benign noise. In particular `open_webui.routers.audio:get_available_voices ... http://litellm:4000/v1/audio/voices → 404` is structural — LiteLLM does not implement that path (`curl 127.0.0.1:4000/v1/audio/voices` returns 404) and it appears on every Open WebUI version. Confirm with that curl before reporting it as a regression.
- **Open WebUI is not a plain pull here** — `esmien/webui:local` is rebuilt from `webui-branding/`, and the base is pinned by digest in `webui-branding/Dockerfile` (`ARG OPENWEBUI_BASE`). Bump by *release tag*, not `:main`: `docker pull ghcr.io/open-webui/open-webui:vX.Y.Z`, take `docker inspect --format '{{index .RepoDigests 0}}'`, put the `@sha256:…` into `ARG`, then `docker compose build --pull open-webui` and `docker compose up -d --force-recreate open-webui` (`background=true`).
  - The `sed`+`grep -q` guard failing the build is **the intended behaviour**, not a broken Dockerfile: upstream moved the `WEBUI_NAME += ' (Open WebUI)'` line, so the rebrand needs re-checking before anything ships.
  - The previous `esmien/webui:local` image does **not** survive as a rollback target (the rebuild replaces the tag and the old image can already be gone). Rollback = put the previous base digest back into `ARG` and rebuild; keep that old digest in `RESTORE_WEBUI.md`.
  - After the update, confirm branding survived inside the container, not just in the UI: `docker exec open-webui grep -n 'rebranded: Esmien AI' /app/backend/open_webui/env.py`, `docker exec open-webui printenv WEBUI_NAME`, and `curl -s 127.0.0.1:8080/static/splash-dark.png | sha256sum` vs `sha256sum webui-branding/out/splash-dark.png`. The UI caches favicons aggressively — hard refresh before declaring the rebrand broken.

### Proving the terminal tool still executes after an update

A healthy container plus `Initialized 1 terminal server(s)` proves loading, not usage — the flag gate fires per request. `scripts/probe-owui-terminal.py` runs the whole check (login → `/api/config` → real chat with a marker command → evidence lines) and cleans up its test chat.

- The request field is **`terminal_id`** (the connection UUID), not `tool_ids: ["terminal:<uuid>"]`. A `terminal:`-prefixed id is treated as a workspace tool, resolves to nothing, and the model answers «инструмент недоступен» while the API still returns 200.
- Non-stream requests return the model's `tool_calls` **without executing them**; execution happens in the streaming/background pipeline. Send `stream: true` with `chat_id` + `session_id` + `terminal_id`.
- With `chat_id` the completion runs as a background task that needs the UI websocket session, so the chat may stay empty (`Event caller: session … not owned by requesting user`). That is not a tool failure — **prove execution from the downstream side**: `docker logs open-terminal --since 3m | grep '/execute'` shows `POST /execute` + `GET /execute/<id>/status` coming from the Open WebUI container IP. Optionally read the result with the connection key from the DB (`select value->0->>'key' from config where key='terminal_server.connections'`) — never print that key.
- Pick a probe model that answers on plain chat-completions (`deepseek-v41-flash` works). Groups that need provider session headers (e.g. `opencode/*` demanding `x-opencode-session`) return 400 and are not evidence about the UI.
- Both the `terminal_servers` and the saved Integrations connections depend on `ENABLE_DIRECT_INTEGRATIONS` (bullet above) — fix the flag before blaming the terminal.

### Updating LiteLLM (its tag is rolling — find out what it ships first)

Same backup → pull → recreate → verify sequence, with three extra checks specific to LiteLLM:

- **Read the version inside the image before committing to a tag.** The container has **no `pip`, no `python` on `PATH` and no `curl`** — only the venv interpreter, so `import litellm; litellm.__version__` fails (the module has no `__version__`) and `pip show` returns `executable file not found`. Use `importlib.metadata` and the venv path:
  ```bash
  docker inspect ghcr.io/berriai/litellm:<tag> --format '{{.Created}}'   # build date, not the version
  docker exec litellm /app/.venv/bin/python -c "import importlib.metadata as m;print(m.version('litellm'))"
  docker run --rm --entrypoint /app/.venv/bin/python ghcr.io/berriai/litellm:<tag> \
    -c "import importlib.metadata as m;print(m.version('litellm'))"      # probe a tag WITHOUT touching the live container
  ```
- **`main-latest` is a rolling tag that serves pre-release builds — never upgrade to it blindly.** Compare what it resolves to against the newest *stable* release from `curl -s 'https://api.github.com/repos/BerriAI/litellm/releases?per_page=10' | grep -E '"(tag_name|published_at)"'` (ignore every `-rc.`/`-dev.` tag). If `main-latest` ships a dev version, **pin the compose image to the newest stable `ghcr.io/berriai/litellm:vX.Y.Z`** rather than rolling — a one-line compose edit, reversible the same way, and it stops silent dev upgrades on every future pull. Update the services table above when you change the pin.
- **Verify with a real completion through the gateway, not just health.** A bearer key can be read from the container's own env without ever printing it: `docker exec litellm /app/.venv/bin/python -c "import os,json,urllib.request; k=os.environ['LITELLM_MASTER_KEY']; ..."` against `http://127.0.0.1:4000/v1/chat/completions` (and `/v1/models` for a model count). Also confirm migrations: `docker logs litellm --since 5m | grep -iE 'prisma|migrat|error'` must show `No pending migrations to apply`.
- **A release review must answer "does this remove a workaround we maintain?" — and prove it from the source, not the changelog.** Traffic here is plain chat-completions (`hermes.opencode/*`, `hermes/*`, `chat.opencode/*`, `tokenator/*`, `other.openrouter/*`, `deepseek/*`), so chat↔Responses and `/v1/messages` bridge fixes are not a reason to upgrade; the three standing workarounds (`/v1/audio/voices` 404, `reasoning_effort` 400 on OpenRouter-backed groups, ghost models echoed from key allowlists) each need an explicit fixed/not-fixed verdict. Recipes — filter the 500+ PR bullets programmatically, check route existence in the tag's git tree, diff the provider transformation file between tags — are in `references/upstream-release-review.md`, section 3.

