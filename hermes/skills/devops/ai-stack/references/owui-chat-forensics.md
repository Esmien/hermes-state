# Разбор чата Open WebUI в БД (жалобы на качество модели)

> Read when the owner relays «модель галлюцинирует / врёт / городит лишнее» from himself or another user, or when you need to know what a chat model could actually do in a given session.

## Why the DB, not the story

A user's complaint («он придумывает», «он ничего не проверил») is a hypothesis, not a fact. The chat row carries the evidence that decides it: which model ran, what was attached, and whether any tool call happened. Answer from that, then judge the model — verdict first, evidence second, no defending a model from memory.

## Access

`webui_db` lives on the **host PostgreSQL** (not in compose), next to `litellm_db`:

```bash
sudo -u postgres psql -d webui_db -Atc 'select id,name,email,role from "user" order by created_at;'
```

Match the person by name **and** email fragment — several users share a first name, and a wrong `user_id` zeroes the whole search.

## List a user's chats

Build one readable line per chat; never `select chat` in a listing:

```sql
select id||'|'||coalesce(title,'')||'|'||to_char(to_timestamp(updated_at),'YYYY-MM-DD HH24:MI')
from chat where user_id='<uuid>' order by updated_at desc limit 15;
```

## Traps

- The `chat` column is **`json`, not `jsonb`**: `jsonb_typeof(chat->'x')` fails with «function does not exist», and `chat::jsonb` in the same expression keeps failing. Do not fight it in SQL — dump `chat::text` for **one row** into a file and parse in Python.
- **Select one row per query.** `json_build_object(...)::text` over many rows comes back as a single unparseable mega-line (the nested JSON flattens), so keep the listing query separate from the content query.
- Timestamps are epoch seconds: `to_timestamp()`, and remember the host is UTC.

## Extract the messages in order

Messages are a **dict** keyed by id under `chat->'history'->'messages'`, so there is no array order — walk `parentId` backwards from `history.currentId` and reverse:

```python
import json
d = json.load(open('one_chat.json'))
msgs = d['history']['messages']; nid = d['history']['currentId']; order = []
while nid and nid in msgs:
    order.append(msgs[nid]); nid = msgs[nid].get('parentId')
order.reverse()
# narrative text only
for m in order:
    c = m.get('content') or ''
    print(m.get('role'), len(c), c[:300].replace('\n', ' '))
```

An assistant message also carries `model`, `output` (the reasoning blocks), `usage`, and `meta.task_id`/`response_started_at`/`response_ended_at`. There is no `files`/`content` pair to unpack: user attachments sit in the **user** message as `files: [{type: 'collection', id, name}]` — a knowledge-base collection, i.e. RAG, not a terminal.

## The decision: did the model have hands?

**`m.get('tool_calls')` is not where they live, and its absence proves nothing.** In chats stored by current Open WebUI the calls are items of `message.output[]` with `type: "function_call"`, each paired with a `function_call_output` that carries the real `command`, `exit_code` and `output` (plus `log_path` for background runs):

```python
for m in order:
    calls = [o['name'] for o in (m.get('output') or []) if o.get('type') == 'function_call']
    if calls:
        print(m.get('role'), calls)
```

Count them over the whole row before saying anything about hands:

```bash
grep -o '"type":"function_call"' one_chat.json | wc -l
grep -o '"name":"[a-z_]*"' one_chat.json | sort | uniq -c | sort -rn | head
```

Names that occur in practice: `run_command`, `get_process_status`, `write_file`, `read_file`, `execute_code`, `view_knowledge_file`, `grep_knowledge_files`, `list_knowledge`, `query_knowledge_files`, `ask_user`, `display_file`.

**Never print a message's `output` truncated** while deciding this: the reasoning block comes first and the calls sit after it, so `json.dumps(...)[:400]` looks exactly like «инструментов не было» and yields a confident wrong verdict. Same for a `.get('content')`-only pass — assistant content is just the narrative.

Only a **zero** count supports «рук не было». Then confirm what could have been bound at all:

```bash
sudo -u postgres psql -d webui_db -Atc "select name,type,is_active from function order by updated_at desc limit 15;"
sudo -u postgres psql -d webui_db -Atc "select id,name from tool order by updated_at desc limit 10;"
docker inspect open-webui --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -iE 'interpreter|code_exec|jupyter|mcp'
```

Last check, when the narrative claims files were written: look for them where they should be, rather than inferring from the text —

```bash
docker exec <sandbox-container> ls -la /home/user/workspace/<project>
```

A missing path means the session ran ephemeral and the work did not survive, which is a different finding from «модель соврала» and is worth telling the owner on its own.

## Interpreting the answer — three different defects

1. **Fabricated verification** — only when the row contains **no** `function_call` at all, while the narrative says «проверил», «прогнал 55 кейсов», «все файлы записаны», «поставил pydantic 2.13.5». It is not an error in the code, it is a report about actions that never ran; the tell-tale is a self-contradiction in the same chat («пакетов нет и ставить нельзя» → «установил»). Count first: one existing call for the same subject already destroys this diagnosis.
2. **Real logic error**: extra normalisation, duplicate validation, code that violates the ticket's own wording. The model often admits it when challenged — that is normal review work, not hallucination.
3. **Unverified assumption about the environment** — stated as fact («pydantic тут нет») and then disproved by the model's own next command, or never checked. Cheapest to fix with one probe, and the reason a terminal matters more than a better model.

Verdict shape depends on the count, and the two shapes are not interchangeable:

- zero calls → «модель не врёт про код — она врёт про проверку, потому что проверять ей нечем», и лечится это инструментом, а не моделью;
- calls present → жалоба не про галлюцинации, а про качество ревью: назвать конкретные ошибки, отметить, что обе исправлены после замечаний, и не защищать модель по памяти.

## Giving the model hands — what that costs

Binding `open-terminal` to a chat model makes «проверил» mean a command with output. Before doing it, know what that container is:

```bash
docker inspect open-terminal --format 'user={{.Config.User}} priv={{.HostConfig.Privileged}} net={{.HostConfig.NetworkMode}}'
docker inspect open-terminal --format '{{range .Mounts}}{{.Source}} -> {{.Destination}} rw={{.RW}}{{"\n"}}{{end}}'
docker port open-terminal
```

On this host it is **uid 0:0**, host `/` mounted read-write at `/mnt/host`, plus `/var/run/docker.sock` — full host control, not a sandbox (it only listens on `127.0.0.1`, so the boundary is the gateway and WebUI auth). Per-user sandboxes (`ot-u-<slug>`, non-root, one project folder) are the right target instead → `references/sandbox-terminal.md`.

So the answer to «сделай так, чтобы он реально проверял» is: отдельный контейнер под конкретный проект, без `docker.sock`, с non-root и лимитами — а не привязка глобального терминала к чужому пользователю.
