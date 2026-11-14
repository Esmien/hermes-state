# Purge Open WebUI chats / uploaded files by date or user

Owner asks «снеси диалоги старше N» / «почисти файлы». Work happens in `webui_db`
(host PostgreSQL) plus `/home/ai_service/webui_data/uploads`. Always confirm scope and
take a dump first — chat deletion is cheap to describe and impossible to undo without one.

## 1. Scope and cutoff — one confirmation, both questions

Count per user first, then put the scope choice into the SAME destructive-action
confirmation (choices: «только мои N», «все в вебуи M») instead of a separate clarify call.

```bash
# cutoff: owner speaks MSK — convert his local midnight to epoch
CUT=$(TZ=Europe/Moscow date -d '2026-10-22 00:00' +%s)
sudo -u postgres psql -d webui_db -c "
select u.name, count(*) filter (where c.updated_at < $CUT) older, count(*) total
from chat c join \"user\" u on u.id=c.user_id group by 1 order by 2 desc;"
```

`chat.created_at` / `updated_at` are **epoch seconds (bigint)**, not timestamps. Resolve the
owner's `user.id` by email — never hardcode the UUID.

Display them in MSK by converting the bigint first and applying the zone to the timestamp:
`to_char(to_timestamp(c.updated_at) at time zone 'Europe/Moscow','MM-DD HH24:MI')`. The
reverse form `to_timestamp(c.updated_at at time zone 'UTC')` fails with
`function pg_catalog.timezone(unknown, bigint) does not exist`.

## 2. Map what a chat actually owns

A chat row is NOT the whole chat:

| table | what |
|---|---|
| `chat` | title, owner, timestamps, whole `chat` JSON |
| `chat_message` | per-message rows (newer OWUI) — orphans if you delete only `chat` |
| `chat_file` | chat → `file.id` links |
| `chat_view_state` | per-user view state (exists on 0.13.x, gets rows for every chat opened) |
| `chatidtag`, `shared_chat`, `automation_run` | tags / public links / scheduled runs — usually 0 rows, still delete |
| `feedback` | no `chat_id` column here; check before assuming it |

Do not trust an old list — enumerate instead:
`select table_name, column_name from information_schema.columns where table_schema='public' and column_name in ('chat_id','chatid');`

`file` is referenced with **`ON DELETE CASCADE`** from `chat_file`, `knowledge_file` and
`channel_file`: deleting a `file` row silently removes the knowledge-base link too. So
before touching files, verify the id is not referenced anywhere else.

## 3. Dump first (the encrypted-backup dir is not a fresh dump)

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
F=/home/ai_service/ai-stack/backups/webui_db_pre-purge_$TS.dump
sudo -u postgres pg_dump -Fc -d webui_db -f /tmp/wb.dump \
  && install -m 600 -o root -g root /tmp/wb.dump "$F" && rm -f /tmp/wb.dump
```

Keep it `600 root`. It restores DB rows only — **disk files are gone for good**; say that
plainly in the report.

## 4. Delete chats in one transaction

```bash
sudo -u postgres psql -d webui_db -v ON_ERROR_STOP=1 <<SQL
BEGIN;
CREATE TEMP TABLE doomed AS SELECT id FROM chat
 WHERE user_id='<uuid>' AND updated_at < $CUT;
SELECT count(*) FROM doomed;
DELETE FROM chat_message    WHERE chat_id IN (SELECT id FROM doomed);
DELETE FROM chat_file       WHERE chat_id IN (SELECT id FROM doomed);
DELETE FROM chatidtag       WHERE chat_id IN (SELECT id FROM doomed);
DELETE FROM chat_view_state WHERE chat_id IN (SELECT id FROM doomed);
DELETE FROM shared_chat     WHERE chat_id IN (SELECT id FROM doomed);
DELETE FROM automation_run  WHERE chat_id IN (SELECT id FROM doomed);
DELETE FROM chat            WHERE id IN (SELECT id FROM doomed);
COMMIT;
SQL
```

No restart needed — OWUI reads chats from the DB per request. After the transaction, prove
zero orphans before reporting: `select count(*) from chat_message m left join chat c on
c.id=m.chat_id where c.id is null;` (same for `chat_file`).

## 4b. Purge by title («убери тестовые чаты / пинги»)

When the ask is not a date cutoff but «все тестовые», classify first and delete by title
family in the SAME transaction shape:

```sql
select c.title, count(*),
       min(to_char(to_timestamp(c.updated_at) at time zone 'Europe/Moscow','MM-DD HH24:MI')) first,
       max(to_char(to_timestamp(c.updated_at) at time zone 'Europe/Moscow','MM-DD HH24:MI')) last
from chat c where c.user_id='<uuid>' group by 1 order by 2 desc;
```

- Test runs leave families, not singletons: one repeated title (`Synthetic overflow test` ×17),
  ping-looking titles (`Проверка связи`, `запрос связи`, `Ping-сообщение`), and memory-check
  titles (`Назови маркер памяти`, `Запрос о памяти`, `Запрос знаний обо мне`).
- Leftover test ACCOUNTS (pilot users, `test@…`) hold the bulk of the junk; offer them as a
  scope choice in the same confirmation. Their chats are invisible in the owner's sidebar,
  which is why he does not mention them.
- Short real-looking Q&A sitting inside the test window (`три отличия TCP UDP`, 2 messages) is
  genuinely ambiguous: list those as a second question in the same confirm call instead of
  guessing. The owner's answer has been «тоже удалить» — he does not want half a run left.
- Cross-check by `(chat::jsonb)->'models'` and message counts before deciding: 2-message chats
  on a test-only model id are tests, 20–30-message chats on a normal preset are real.

## 5. Files: recover the mapping from the dump, then delete

Once `chat_file` rows are deleted the file ids are gone from the live DB, so recover them
from the dump:

```bash
cp "$F" /tmp/pr.dump && chmod 644 /tmp/pr.dump   # 600 root → postgres cannot read it
sudo -u postgres createdb purge_ref
sudo -u postgres pg_restore -d purge_ref --no-owner --no-privileges /tmp/pr.dump
sudo -u postgres psql -d purge_ref -c "create table doomed_files as
  select distinct cf.file_id from chat_file cf join chat c on c.id=cf.chat_id
  where c.user_id='<uuid>' and c.updated_at < $CUT;"
```

`pg_restore ... warning: errors ignored on restore: 1` is normal here.

`file.path` holds **container** paths (`/app/backend/data/uploads/<uuid>_name`, legacy
`/home/webui/open-webui-env/lib/.../data/uploads/...`) — the host file is
`/home/ai_service/webui_data/uploads/$(basename path)`. Sizes live in `file.meta->>'size'`.

Dry-run before deleting: join the id list to `chat_file` / `knowledge_file` /
`channel_file` in `webui_db`, count exist / missing on disk, sum size. Expect a chunk of
`missing` rows (metadata whose file was pruned earlier) — those are fine, skip them.

Then remove the existing paths and delete only unreferenced `file` rows in the same
statement (`delete from file where id in (...) and not exists (...)`). Never `rm -rf` the
uploads dir and never touch `webui_data/cache` — `whisper` (~464 MB), `tiktoken` and `audio`
there are models/TTS cache, unrelated to chats; `generated_images` is separate too.

Cleanup: `dropdb purge_ref`, remove `/tmp/pr.dump` and the intermediate id lists.

Attachments that belonged only to the purged chats stay behind as unreferenced `file` rows
plus their bytes in `uploads`. Recovering their ids needs the dump (step 5) — so either do
step 5 in the same pass or report them by name and size and ask. Never delete them silently:
file deletion is the irreversible half of the job.

## 6. Report

Numbers, not narration: deleted chats / message rows / file links / files + MB, uploads dir
before→after, disk free, `/health` = 200, dump path as the rollback, and the one-line caveat
that restored rows will point at files that no longer exist.

## Pitfalls

- **psql temp tables live only inside one session.** `create temp table` in one `psql -c`
  and `\copy`/`select` in the next fails with `relation does not exist`. Put create + `\copy`
  + queries in ONE heredoc, or write the id list to a file first.
- `\copy` is a psql meta-command: it cannot be mixed into a `-c "sql; \copy …; sql"` string.
- A 600-root dump cannot be read by the `postgres` user — copy to `/tmp` with `644` before
  `pg_restore` into a scratch DB; delete the copy afterwards.
- Deleting only `chat` leaves `chat_message` orphans that still bloat `webui_db`; always
  clear the child tables.
- **`VACUUM` cannot run inside a transaction block**, and `psql -c "vacuum a; vacuum b;"`
  wraps the statements in one — run one `psql -c "vacuum analyze <table>;"` per table. Plain
  `vacuum analyze` after a purge only refreshes stats and drops dead tuples for reuse: the
  reported `pg_database_size` does NOT shrink, so do not promise freed disk. `VACUUM FULL`
  would shrink it but locks the tables — the owner's live chats are in them.
- Family members' chats sit in the same `chat` table — a date-only request is ambiguous about
  them, so make the owner pick the scope in the confirmation.

## When to read this file (annotated index entry, moved from SKILL.md)

- `references/owui-data-purge.md` — **Удаление чатов/файлов Open WebUI по дате или юзеру** (`webui_db`: `chat` + `chat_message` + `chat_file`, восстановление маппинга файлов из дампа, пути `file.path` → `webui_data/uploads`, что нельзя трогать). Read before any «снеси диалоги» / «почисти файлы» request.
