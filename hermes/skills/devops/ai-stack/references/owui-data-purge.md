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

## 2. Map what a chat actually owns

A chat row is NOT the whole chat:

| table | what |
|---|---|
| `chat` | title, owner, timestamps, whole `chat` JSON |
| `chat_message` | per-message rows (newer OWUI) — orphans if you delete only `chat` |
| `chat_file` | chat → `file.id` links |
| `chatidtag`, `feedback`, `shared_chat` | possible extras; check before deleting |

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
DELETE FROM chat_message WHERE chat_id IN (SELECT id FROM doomed);
DELETE FROM chat_file    WHERE chat_id IN (SELECT id FROM doomed);
DELETE FROM chat         WHERE id IN (SELECT id FROM doomed);
COMMIT;
SQL
```

No restart needed — OWUI reads chats from the DB per request.

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
- Family members' chats sit in the same `chat` table — a date-only request is ambiguous about
  them, so make the owner pick the scope in the confirmation.
