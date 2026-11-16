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
