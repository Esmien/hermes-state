# Compact base64 images out of Open WebUI chats into file storage.
#
# Why: a chat tool that emits `data:image/...;base64` in its `files` event makes Open WebUI
# persist the same base64 twice - chat_message.files AND the whole-history JSON chat.chat.
# At ~5 MB per generated image that is ~10 MB per image in the DB. This rewrites each data
# URI into a real upload (file + chat_file rows) and leaves only /api/v1/files/<id>/content.
#
# Run INSIDE the open-webui container so it uses the app's own DATABASE_URL and storage:
#   docker cp scripts/compact-webui-images.py open-webui:/tmp/
#   docker exec -i open-webui python -c "import os; os.environ['UPLOAD_DIR']='/tmp/test-uploads'; exec(open('/tmp/compact-webui-images.py').read())"
#
# Always do the first pass against a restored COPY of webui_db (createdb + pg_restore
# --no-owner --no-privileges, then GRANT ALL to the app role) and check the resulting
# chat/chat_message sizes before running it on the live DB. After the live run:
#   vacuum (full, analyze) chat;  vacuum (full, analyze) chat_message;   # one statement per -c
#
# Env: DSN (default: $DATABASE_URL), UPLOAD_DIR (default /app/backend/data/uploads), DRY_RUN=1
# Idempotent: only entries whose url starts with data:image/ are touched.

import base64
import hashlib
import json
import os
import re
import time
import uuid

import psycopg2

DSN = os.environ.get("DSN") or os.environ["DATABASE_URL"]
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/app/backend/data/uploads")
DRY = os.environ.get("DRY_RUN") == "1"
URL_TMPL = "/api/v1/files/{}/content"
DATA_RE = re.compile(r"^data:(image/[A-Za-z0-9.+-]+);base64,(.+)$", re.S)
EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
       "image/gif": ".gif", "image/bmp": ".bmp", "image/avif": ".avif"}

os.makedirs(UPLOAD_DIR, exist_ok=True)

conn = psycopg2.connect(DSN)
conn.autocommit = False
cur = conn.cursor()

cur.execute("select id, user_id, chat_id, files::text from chat_message "
            "where files::text like '%%data:image%%' order by chat_id")
rows = cur.fetchall()
print(f"messages with base64 files: {len(rows)}")

total_bytes = 0
migrated = 0
chats = {}


def sniff(raw: bytes, declared: str) -> str:
    """LiteLLM mislabels JPEG payloads as image/png - believe the magic bytes."""
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    for sig, mime in ((b"\x89PNG\r\n\x1a\n", "image/png"),
                      (b"\xff\xd8\xff", "image/jpeg"),
                      (b"GIF8", "image/gif")):
        if raw.startswith(sig):
            return mime
    return declared


def store_image(raw: bytes, mime: str, user_id: str):
    fid = str(uuid.uuid4())
    ext = EXT.get(mime.lower(), ".png")
    name = f"generated-image{ext}"
    path = f"{UPLOAD_DIR}/{fid}_{name}"
    if not DRY:
        with open(path, "wb") as fh:
            fh.write(raw)
        os.chmod(path, 0o644)
    meta = {"name": name, "content_type": mime, "size": len(raw),
            "file_hash": hashlib.sha256(raw).hexdigest(), "data": {}}
    ts = int(time.time())
    if not DRY:
        cur.execute(
            "insert into file (id,user_id,filename,meta,created_at,hash,data,updated_at,path) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (fid, user_id, name, json.dumps(meta), ts, None, "{}", ts, path),
        )
    return fid, name


for msg_id, user_id, chat_id, files_json in rows:
    try:
        files = json.loads(files_json) if files_json else []
    except Exception:
        print(f"SKIP {msg_id}: bad json")
        continue
    if not isinstance(files, list):
        continue

    new_files = []
    mapping = {}
    changed = False
    for f in files:
        url = f.get("url") if isinstance(f, dict) else None
        m = DATA_RE.match(url or "") if isinstance(url, str) else None
        if not m:
            new_files.append(f)
            continue
        mime, b64 = m.group(1), m.group(2)
        try:
            raw = base64.b64decode(b64, validate=False)
        except Exception as exc:
            print(f"SKIP {msg_id}: decode {exc}")
            new_files.append(f)
            continue
        mime = sniff(raw, mime)
        fid, name = store_image(raw, mime, user_id)
        newurl = URL_TMPL.format(fid)
        mapping[url] = newurl
        total_bytes += len(raw)
        migrated += 1
        changed = True
        new_files.append({**{k: v for k, v in f.items() if k != "url"},
                          "id": fid, "url": newurl, "name": name,
                          "content_type": mime})
        if not DRY:
            ts = int(time.time())
            cur.execute(
                "insert into chat_file (id,user_id,chat_id,file_id,message_id,created_at,updated_at) "
                "values (%s,%s,%s,%s,%s,%s,%s) on conflict do nothing",
                (str(uuid.uuid4()), user_id, chat_id, fid, msg_id, ts, ts),
            )
    if changed:
        chats.setdefault(chat_id, {}).update(mapping)
        if not DRY:
            cur.execute("update chat_message set files=%s where id=%s",
                        (json.dumps(new_files), msg_id))

print(f"images: {migrated}, decoded bytes: {total_bytes / 1048576:.1f} MiB, chats: {len(chats)}")

# chat.chat holds the same data URIs verbatim (base64 is JSON-safe), so a per-chat
# string replace keeps the history JSON consistent with chat_message.files.
for chat_id, mapping in chats.items():
    cur.execute("select chat::text from chat where id=%s", (chat_id,))
    row = cur.fetchone()
    if not row:
        continue
    text = row[0]
    before = len(text)
    for old, new in mapping.items():
        text = text.replace(old, new)
    if len(text) != before:
        if not DRY:
            cur.execute("update chat set chat=%s where id=%s", (text, chat_id))
        print(f"chat {chat_id}: {before / 1048576:.1f} -> {len(text) / 1048576:.1f} MiB")

if DRY:
    conn.rollback()
    print("DRY RUN: rolled back")
else:
    conn.commit()
    print("committed - now VACUUM (FULL, ANALYZE) chat and chat_message")
