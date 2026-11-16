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
