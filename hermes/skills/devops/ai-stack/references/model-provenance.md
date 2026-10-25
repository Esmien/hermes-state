# Model provenance and cleanup in Open WebUI

> Loaded from the `ai-stack` skill. Read this when ghost models, dead/disabled presets, model ids that 400 or vanish.

## Model provenance in Open WebUI (ghost models)

Admin → Settings → Models is a **merged** list, so an entry can be visible with **no row in `webui_db.model`**. `Models.svelte` renders `getModels` (DB rows **+ everything the connections advertise**) then appends `getAllModels` (DB only). Three provenance classes:

1. **Connection model** — comes from a connection's `/v1/models`. In `GET /api/models` it carries `"connection_type": "external"` and a `urlIdx`; its tag names the group. The UI offers **Reset** (`canResetModel` = not a preset + present in the merged list), никогда Delete.
2. **DB model** — a row in `webui_db.model` (workspace preset or plain custom model); the UI offers **Delete**. `webui_db.model` has **no `access_control` column** in 0.12 — the «Частное»/Private badge means "no public read grant" (`access_grants`); views filter on `private`/`public`, `enabled`/`disabled`.
3. **Ghost** — a name a connection advertises that has no backend at all.

Diagnose (admin token = `POST /api/v1/auths/signin` with the **email** from `select email from "user" where role='admin'` — `UI_USERNAME` is NOT an email — plus `OWUI_ADMIN_PASSWORD` from the approver env):

```bash
curl -s 127.0.0.1:8080/api/models -H "Authorization: Bearer $TOKEN"      # merged: shows connection_type / urlIdx / tags
curl -s 127.0.0.1:8080/api/v1/models/base -H "Authorization: Bearer $TOKEN"  # DB rows only
```

Connections all point at `litellm:4000/v1`; the **index into `openai.api_base_urls` is the `urlIdx`**, and `openai.api_keys` at the same index is the LiteLLM virtual key that selects the model group:

```bash
sudo -u postgres psql -d webui_db -Atc "select value::text from config where key='openai.api_base_urls';"
```

Delete a DB model with the API (it cascades `model_history`; a hand-written `DELETE` must remove `model_history` rows in the same transaction — see the cleanup subsection below):

```bash
curl -s -X POST 127.0.0.1:8080/api/v1/models/model/delete -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"id":"<model-id>"}'
```

**A ghost cannot be deleted from Open WebUI — fix it at the source.** Worked example: `hermes/thinkingmachines/inkling:free` showed in the admin list as `external`/`urlIdx 5`/tag `hermes` while having no `webui_db.model` row, no `litellm_db."LiteLLM_ProxyModelTable"` row and no `/v1/model/info` (master-key) entry. Cause: **LiteLLM echoes a virtual key's `models` allowlist verbatim in `/v1/models`, even for names that do not exist**. The key `OpenRouter Hermes` still carried the dead name:

```bash
curl -s "127.0.0.1:4000/key/info?key=$KEY" -H "Authorization: Bearer $LITELLM_MASTER_KEY"
curl -s -X POST 127.0.0.1:4000/key/update -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' -d '{"key":"<KEY>","models":["hermes/deepseek-v4.1-flash"]}'
```

`$KEY` = plaintext value from `webui_db.config` key `openai.api_keys` at that `urlIdx`. Open WebUI re-reads connection models on its own (its cache expires) — **no container restart needed**, verify with the two `curl` calls above. Always snapshot the row (`select row_to_json(m) from model m where id=...`) and the key's old `models` list before changing anything.

### Dead / disabled model cleanup (DB presets)

**Never retype a model id from tool output into an API call.** Model names that contain `claude-…` are redacted in tool output (printed as `anthropic/` + nothing), so a copy-pasted `key/update` payload silently writes a truncated, non-existent name and can drop the real entries. Build every payload programmatically from `webui_db` / `/v1/models` in one Python process and print only counts and `md5()` prefixes for verification.

**The definitive liveness probe is Open WebUI's own endpoint, not LiteLLM.** `POST 127.0.0.1:8080/api/chat/completions` with `max_tokens=1` tests exactly the path a user takes: OWUI resolves a DB preset to its `base_model_id`, and refuses ids no connection advertises with `{"detail":"Model not found"}`. A direct LiteLLM probe gives false answers in both directions — it 400s on the `<connection_tag>.<model>` alias rows that OWUI serves fine, and it 400s on `opencode/*` groups that are alive but demand an `x-opencode-session` header (treat `MissingSessionID` as alive). Run the sweep concurrently (6 workers) — serial takes ~10 min for 100 rows.

`GET /api/v1/models/base` can return more rows than `/api/models` shows in the chat selector: stale alias rows left by older LiteLLM configs (`chat.opencode/*`, `aider.*`, `*.tokenator/*`, `other.*`, `img.openrouter/*`) linger in the DB, appear in Admin → Settings → Models, and answer `Model not found`. They are safe to delete; presets that carry a `system` prompt (`image-generator`, `video-generator`) are custom models — never sweep those, the user's rule is «кастомные не трогать».

`webui_db.model` marks a hidden model with **`is_active=false`** — there is no `enabled` column (that word only appears in the UI/badge text). `GET /api/v1/models/base` returns DB rows as a plain list, while `GET /api/models` returns a **dict** `{"data": [...]}`.

**Disabled ≠ dead: prove liveness with a real completion — but probe through Open WebUI, not LiteLLM.** POST `127.0.0.1:8080/api/chat/completions` with `{"model": <id>, "messages":[{"role":"user","content":"hi"}], "max_tokens":1, "stream": false}` and the admin token. That is the exact path the UI takes, so it is the only probe whose verdict matches what the user sees:
- `200` → alive; if the row is `is_active=false` it is merely switched off — **keep it and say so** instead of deleting.
- `{"detail":"Model not found"}` → no connection advertises the id (nor its `base_model_id`) → ghost, dead.
- a LiteLLM error body passed through verbatim → dead, **except** `MissingSessionID` / `Request is missing x-opencode-session`: those groups are **alive** (opencode-backed and needing a session header the plain probe cannot send). Never delete on that error.
- **A direct master-key POST to `127.0.0.1:4000/v1/chat/completions` is NOT a valid liveness test for an Open WebUI id.** It gives false verdicts in both directions: Open WebUI strips the connection tag from alias rows (`aider.anthropic/` answers because LiteLLM has `anthropic/`), resolves presets through `base_model_id`, and its registry can hold ids LiteLLM rejects. Judge only by the Open WebUI answer. `/v1/models` stays unusable as a liveness source either way — LiteLLM echoes dead names from virtual-key allowlists and can serve groups it does not list.

**Audit the `model` table, not the API listings.** In one pass `GET /api/models` returned 59 ids, `/api/v1/models/base` 100, while `webui_db.model` held 123 — DB-only rows are invisible in the chat selector yet still listed in Admin → Settings → Models, and they are exactly the stale aliases left behind by previous LiteLLM configs (`chat.opencode/*`, `aider.*`, `*.tokenator/*`, `other.*`, `hermes.opencode/*`). Enumerate with `select coalesce(json_agg(json_build_object('id',id,'base',base_model_id,'active',is_active)),'[]') from model;` and probe every row. **Parallelise (≈6 workers, 60 s timeout)** — 123 sequential probes with long upstream timeouts take over 10 minutes.

**A ghost that lives only in a key allowlist has no DB row at all.** It surfaces as `<connection_tag>.<model>` (e.g. `chat.chat/qwen3-coder-…`) because LiteLLM echoes the key's `models` list into `/v1/models`. Compare every key's list against `/v1/models` and repair with `key/update` — see the provenance section above.

Ready-made probe (report-only by default; `--delete` snapshots the rows and removes the dead ones): `scripts/audit-dead-models.py`.

Order of operations:
1. Snapshot every row you are about to delete — the whole dead set, not only the disabled ones: `select coalesce(json_agg(row_to_json(m)),'[]') from model m where id in (...);` → `/home/ai_service/ai-stack/backups/webui_dead_models_<ts>.jsonl` (chown `ai_service`). A curated preset can carry a long system prompt in `params`, so the backup is the only way back.
2. Check the merged list (`/api/models`) for the same id with `connection_type=external` — a DB-only id can be deleted safely; an id a connection also advertises would reappear as a live connection model after deletion.
3. Delete through `POST /api/v1/models/model/delete` (cascades `model_history`).
4. **Some ids the API refuses with `401 "We could not find what you're looking for"`** — typically junk rows whose id ends in a provider tail like `tokenator/` or `paid/anthropic/…`, and rows absent from `/api/v1/models/base`. Finish those in SQL, deleting history first in one transaction:
   ```sql
   begin;
   delete from model_history h using model m where h.model_id=m.id and md5(m.id) in ('<md5>',...);
   delete from model m where md5(m.id) in ('<md5>',...);
   commit;
   ```
   Target by **`md5(id)`, not by literal id**: long ids get visually truncated in tool output, so a pasted id silently deletes nothing (`DELETE 0`). Collect `md5(id)` from psql and pass those.
5. Verify: dead count in DB and via `/api/models`, `select count(*) from model_history h where not exists (select 1 from model m where m.id=h.model_id)` = 0, and re-probe a sample of the kept models through `/api/chat/completions` to confirm they still answer 200.

When the user says «удали мёртвые», delete only the ones that fail the probe — a disabled-but-working model is a config choice, not garbage. Report counts (dead removed / alive kept), the backup path, and the surviving disabled entries.

