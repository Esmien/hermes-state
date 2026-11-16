# Purge LiteLLM logs (fails, model families) in `litellm_db`

Owner asks «вычисти из логов fail-записи / записи моделей X». Logs live in the host
PostgreSQL (`sudo -u postgres psql -d litellm_db`), not in the container.

## 1. Where the rows actually are

- `"LiteLLM_SpendLogs"` — per-request log page (~150 MB at 34k rows, 1 month). Columns
  `status` (`success`/`failure`), `model` (**upstream** name, e.g. `free-gemini-4-argon`),
  `model_group` (preset, e.g. `google/gemini-4-argon`).
- `"LiteLLM_ErrorLogs"` — separate error table, often 0 rows: empty means «no fails here»,
  it does NOT mean the fails are gone — they sit in SpendLogs with `status='failure'`.
- Aggregates, one row per (date, model, key/user/tag): `"LiteLLM_DailyModelUsage"`,
  `"LiteLLM_DailyUserSpend"`, `"LiteLLM_DailyTeamSpend"`, `"LiteLLM_DailyTagSpend"`,
  `"LiteLLM_DailyGlobalSpend"`, `"LiteLLM_DailyEndUserSpend"`, `"LiteLLM_DailyRequestErrors"`.
  They carry their own `spend`/`api_requests` and are NOT recomputed from SpendLogs, so a
  SpendLogs-only delete leaves the Usage page showing the old money. Ask whether to clean them
  too when the owner only said «логи» — the answer here was yes.

## 2. «Модель с префиксом free» = `model ILIKE 'free%'`

Free routes are deployments named `free-<model>` (`free-claude-opus-5.5`, `free-gpt-6-astra`, …);
their `model_group` is the normal preset. So match **both** columns, otherwise a name like
`free.openrouter/free` (group) is missed:

```sql
where model ilike 'free%' or model_group ilike 'free%'
```

**`free%` is not enough for the aggregates.** SpendLogs stores the upstream name as
`free-gpt-6-astra`, but the daily tables record it as **`openai/free-gpt-6-astra`** under a
bare group (`astra`, `gemini_free`, `minimax`) — the leading `openai/` prefix makes a `LIKE
'free%'` filter miss them, and «astra осталась в логах» is exactly this case. Use
`model ILIKE '%free%'` (contains) on `LiteLLM_Daily*` tables, then confirm the bare groups
are empty (`model_group='astra'` → 0).

Count before deleting — `count(*) filter (...)` per condition plus the overlap, and report
numbers. `status='failure'` overlapped 0 with the free set in practice.

## 3. Order of work

1. `pg_dump -Fc -d litellm_db` → `/tmp`, `install -m 600 -o root -g root` into
   `/home/ai_service/ai-stack/backups/litellm_db_pre-purge_<ts>.dump` (430 MB DB ⇒ ~40 MB dump).
2. One `psql -v ON_ERROR_STOP=1` heredoc: `BEGIN;` + one DELETE per table + `\echo` + `COMMIT;`.
   `\echo` markers make the per-table `DELETE n` lines readable in the transcript.
3. `vacuum analyze` one table per `psql -c` (VACUUM cannot run inside a transaction).
4. Verify: `count(*) filter (where status='failure')` and the free predicate return 0, and
   `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:4000/health/liveliness` = 200.

No container restart needed — the proxy reads the DB per request.

## 4. Say plainly what did not change

`pg_table_size` stays the same after plain `VACUUM` (space becomes reusable, file not
truncated) — do not promise freed disk. `VACUUM FULL` would shrink it but locks a table the
proxy writes to; offer it separately. `Last30d*` views and the dashboard counters derive from
the remaining rows, so they drop on the next page load.

Grep for errors in `docker logs litellm` is noisy: HTTP access lines containing
`/gateway/errors/activity` match `-i error`. Filter for `exception|Traceback|ERROR:` instead.

## 5. Tokenator: `api_base` is the only reliable filter

**Before deleting a «provider», enumerate its dependents and say which live groups they feed.**
A provider name reads like a dump target («Токенатор в утиль»), but the same credentials can be
the only legs of a route the owner actively uses — removing them silently trades «cleanliness»
for a dead preset. Print `model_name`, upstream, `order`, credential for every deployment behind
that provider, name the groups that would be left with zero legs, and let the owner carve out the
exception («argon оставь») **before** any DELETE. Cross-check afterwards with `/model/info` that
the count of surviving provider rows equals the number he wanted kept.
The provider's name appears **nowhere in plaintext** in `LiteLLM_ProxyModelTable`:
`api_base`, `model` and `litellm_credential_name` are encrypted at rest with `LITELLM_SALT_KEY`,
so `litellm_params::text ILIKE '%tokenator%'` returns zero rows even while the deployments exist.
Use `GET 127.0.0.1:4000/model/info` with the master key (it decrypts) to attribute rows to a
credential; in `"LiteLLM_SpendLogs"` the plaintext `api_base` (`https://api.tokenator.top/v1`)
and `metadata` are queryable directly.

State the owner settled on 2026-11-16: **Tokenator stays** — 4 credentials (`Tokenator 0626 /
24d3 / 3b89 / 6cb8`) and 4 deployments, all four legs of `google/gemini-4-argon` (`order=1`,
bare upstream `gemini-4-argon`), plus the OpenCode leg (`order=5`). Other Tokenator legs
(`deepseek-v4.1-flash`, `claude-haiku-5.5`, `gpt-6-sol`, `gemini-3.1-pro`) were removed on
2026-11-06 and exist only as historic log rows. «Снести Tokenator» therefore means: purge those
log rows, **not** the credentials and **not** the argon legs — the owner keeps argon alive
because it works. When purging, exclude `model_group IN ('google/gemini-4-argon','gemini-4-argon')`
or the live route loses its history (25 rows kept vs 513 deleted in that pass).

Snapshot before deleting: `psql -tA -c "select json_agg(t) from (select * from \"LiteLLM_SpendLogs\"
where …) t"` → `backups/litellm_tokenator_spendlog_rows_<ts>.json`, `600 root` (5 MB for 513 rows).
Daily aggregates carry **no** provider/`api_base` column, so Tokenator spend cannot be separated
there — leave them alone and say so instead of guessing.

## 6. «В выгрузке остался мусор» = `user_id=''` + `model=''`

The owner's usage export (`user_usage_daily_with_models_*.json`) reads `LiteLLM_DailyUserSpend`,
not SpendLogs. Cleaning SpendLogs does **nothing** to it. The visible junk is rows with
`user_id=''`, `model=''`, `api_key=<random 64-hex>`, zero tokens, `spend=0`,
`failed_requests=1`, `total_response_time_ms=0` — requests that failed before user/model
resolution. In one case 188 750 such rows existed (95 024 of them in a single burst on 2026-11-03)
while nginx logged only 222 requests that day: it is the proxy's internal aggregation writing
them, **not** internet noise — their `api_key` values match none of `"LiteLLM_VerificationToken"`.
They surface in the export as rows with `entity_id:""` and `model:null`.

Fix: back up, then `DELETE … WHERE coalesce(user_id,'')='' AND coalesce(model,'')=''` in both
`"LiteLLM_DailyUserSpend"` and `"LiteLLM_DailyTeamSpend"` (team table carries the same 188 751
rows under `team_id=''`). Keep rows that have a real model and only a missing user — those are
the owner's own curl/probe traffic (~122 rows, ~$0.5) and are real usage. Snapshot via
`CREATE TABLE _bak AS SELECT …` → `\copy … to program 'gzip -c > …'` → `install -m 600` →
`DROP TABLE _bak` (55 MB table, 12 MB gz). `VACUUM ANALYZE` leaves both tables at their old
120 MB size — the space is reusable, not returned; say so.

After the purge the trickle is 1–4 rows/day; if it returns as a burst, look at the proxy's daily
aggregation instead of deleting again.

## 6. «Мусор в выгрузке» = unattributed rows, not leftover logs

The UI export («user usage daily with models», `[{date, entity_id, entity_alias, model, spend,
api_requests, …}]`) is built from `"LiteLLM_DailyUserSpend"`, so purging SpendLogs never cleans it.
Rows the owner reads as garbage are `user_id=''` **AND** `model=''`: `prompt/completion_tokens=0`,
`spend=0`, `failed_requests=1`, `total_response_time_ms=0`, and a per-row `api_key` hash that
matches **no** row in `"LiteLLM_VerificationToken"`. They are requests that failed before user or
model resolution — the proxy's aggregator writes one row each, and they surface in the export as
`model: null` with an empty `entity_id`.

Diagnose in this order, it saves a wrong verdict:

1. `select count(*) filter (where coalesce(user_id,'')='') empty_user, count(*) filter (where
   coalesce(user_id,'')='' and coalesce(model,'')='') empty_both from "LiteLLM_DailyUserSpend";`
2. Date histogram of `empty_both` — garbage arrives in bursts (one day held 95 k of 188 k rows),
   so report the spike day instead of implying steady leakage.
3. Prove it is not external traffic before blaming scanners: count the vhost's requests and `401`s
   for that day (`zgrep '<dd/Mon/yyyy>' /var/log/nginx/llm.access.log.*.gz | awk '{print $9}'`).
   If nginx shows a couple of hundred hits, the rows were generated internally.
4. `2026-11-06`-style attribution traps: `user_id` can be the empty string, not `NULL` — always
   compare with `coalesce(...)` or `=''`. 

Cleanup: delete `user_id='' AND model=''` from **both** `"LiteLLM_DailyUserSpend"` and
`"LiteLLM_DailyTeamSpend"` (they mirror each other, ~same row count) and keep the handful of
user-less rows that carry a real `model` — those are legitimate direct API/probe calls with real
spend. Offer «and the user-less ones too» as a separate choice; the owner's export is
user-oriented, but the money is his.

State of the data after such a pass: 189 456 → ~706 rows in DailyUserSpend, export drops from
555 to ~516 rows, 39 `model: null` entries disappear. Trickle of 1–4 new rows a day continues and
is harmless; a new burst means something upstream is hammering with unknown keys — investigate
`LiteLLM_VerificationToken` lookups rather than deleting again.

## 7. Two habits that keep the transcript readable

- Never run a 4-table `UNION ALL … GROUP BY` overview without `LIMIT`: it printed 264 rows and
  buried the finding. Ask for `count(*) filter (...)` first, then a capped sample.
- `psql -c` with two statements returns two result sets — fine; but `-tA` + `json_agg` is the only
  shape that both snapshots rows for rollback and stays small enough to read.
