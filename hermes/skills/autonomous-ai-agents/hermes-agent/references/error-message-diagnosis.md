# Diagnosing a user-visible Hermes error message

Use when the user pastes a Hermes error string (CLI, TUI, desktop, gateway) and asks how to fix it.
The message is a symptom; the deliverable is cause + live-state evidence + workaround + minimal patch.

## Procedure

1. **Map the string to its i18n key, not to English wording.** Every user-visible CLI/TUI string lives in
   `locales/<lang>.yaml` (e.g. `locales/ru.yaml`). Grep a distinctive fragment of the *user's* text to get the
   key path, then grep the key name in the source to find the emitter.
   - `search_files(pattern="<fragment of the user's text>", path="<hermes tree>/locales")` → e.g. `handoff.already_in_flight`
   - `search_files(pattern="already_in_flight", path="<hermes tree>")` → the call site
   A translated message will not match the English source text, so searching the English wording finds nothing.
   **Scope every grep of the Hermes tree** (`--include=*.py`, or exclude `web_dist/`, `apps/desktop/`, `node_modules/`):
   the dashboard bundles under `hermes_cli/web_dist/assets/` are minified single-line files, so an unscoped grep
   returns one multi-megabyte "line" and floods the context with the whole i18n catalog. The same string usually
   exists in both `locales/<lang>.yaml` (CLI/TUI) and the web bundle (dashboard) — the YAML is the one to read.
2. **Read the emitter and the state it depends on.** RPC handlers return numeric codes (`_err(rid, 4027, ...)`) —
   grep the code number too; it is stable across locales.
3. **Inspect live state in `~/.hermes/state.db`** (SQLite). The `sqlite3` CLI is not installed on this host —
   use python3's sqlite3 with a read-only URI:
   ```
   python3 - <<'EOF'
   import sqlite3
   c = sqlite3.connect("file:/root/.hermes/state.db?mode=ro", uri=True); c.row_factory = sqlite3.Row
   for r in c.execute("SELECT id, handoff_state FROM sessions WHERE handoff_state IS NOT NULL"): print(dict(r))
   EOF
   ```
   Check the column exists first (`PRAGMA table_info(sessions)`) — the schema drifts (e.g. there is no `updated_at`).
4. **Check the config the code path reads** (e.g. `platforms.<name>.enabled`, `home_channel`). Grep `config.yaml`
   for the key and mask long digit runs before printing — chat/user IDs are not secrets but should not be dumped.
5. **Check whether it is a known upstream bug**: `web_search` for the message, then
   `curl -s https://api.github.com/repos/NousResearch/hermes-agent/issues/<n>` (and `/comments`).
   `web_extract` cannot fetch pages on this host — the configured extract backend is search-only; use `curl`.
6. **Check whether the local checkout already has the fix**: `git -C <hermes tree> log -1`, `git fetch origin`,
   `git rev-list --count HEAD..origin/main`, and grep the incoming log for the topic before proposing a patch.

## Rules

- **A message that names a cause is not evidence of that cause.** Verify the state the code actually reads before
  repeating the message back. A bare `UPDATE ... WHERE id = ?` that matches zero rows returns the same failure as a
  real conflict, so "already in flight" can mean "no such row" — check the row exists, not just the flag.
- **Report in this order**: cause with `file:line`, live-state evidence, immediate workaround, minimal patch. Then
  ask before patching Hermes source, and state that `hermes update` overwrites a local patch.
- **Do not import Hermes modules with the system `python3`** — it lacks the runtime deps (e.g. `ruamel`). Use the
  runtime interpreter under `~/.hermes/tools/python-*/bin/python3`, or read config/DB directly without importing.
- **A "not set" / "missing" display is not evidence the value is missing.** Trace the resolution path before
  reporting a config problem: the banner may read a field that is only populated later. Verify the real state
  independently (key present in `.env` by name + length, endpoint reachable, one live model call) and say plainly
  whether the message is cosmetic.
- **Never print `.env` values**; grep keys only. To prove a key exists without revealing it, print its length and
  prefix only: `python3 -c "...len(v), v.startswith('sk-')"`.

## Known instance: `/config` banner shows the API key as not set (custom provider)

The CLI `/config` banner prints "API-ключ: Не задан!" / "API key: not set" for a working custom provider.

- Cause: `show_config()` (`cli.py`) reads `self.api_key`, which `_init_model_and_provider()`
  (`hermes_cli/cli_init_mixin.py`) seeds **only** from `OPENROUTER_API_KEY` / `OPENAI_API_KEY`. A custom provider
  keeps its credential under its own `key_env` (e.g. `HERMES_CUSTOM_127_0_0_1_8080_API_KEY`), so the seed is empty.
  The real key is resolved lazily at first use via `_ensure_runtime_credentials()` — the code comment says so.
- Symptom shape: the banner is wrong only **before the first turn**; after one message `self.agent.api_key` is set
  and `/config` shows the masked key. The model itself works the whole time.
- Verify before answering: `hermes config get model` (shows the resolved masked key), key present in `.env` under the
  provider's `key_env` name, and one live call (`hermes chat -q "Reply with exactly: PONG"`).
- Fix if the user wants it: have `show_config()` resolve credentials (or read the provider's `key_env`) when
  `self.api_key` is empty. It is a Hermes source patch — ask first and note `hermes update` overwrites it.

## Known instance: `/handoff <platform>` reports "already in flight"

`/handoff` from a CLI session that has not yet persisted a row in `state.db` prints the "already in flight" message
while nothing is in flight: the CLI's row-creation step calls `set_session_title`, which returns 0 without inserting
when the row is missing, so the subsequent `request_handoff` UPDATE matches zero rows.

- Workaround: send any message in that session first (the first submit persists the row), then run `/handoff`.
- Fix: make the handoff path call `ensure_session(session_id, source="cli")` (a real upsert) instead of relying on
  `set_session_title` to create the row. The gateway-side `handoff.request` path is unaffected — it calls
  `_ensure_session_db_row`, which does insert.
