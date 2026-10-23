#!/usr/bin/env python3
"""Audit every webui_db.model row and find the ghosts Open WebUI cannot route.

Liveness = a real POST to Open WebUI /api/chat/completions (max_tokens=1) with the admin
session — the same path the UI takes. Do NOT probe LiteLLM directly with the master key:
Open WebUI strips connection tags from alias rows and resolves presets via base_model_id,
so a direct probe reports working models as dead.

Verdicts:
  200                                   -> alive
  MissingSessionID / missing x-...      -> alive (opencode-backed group needs a session header)
  {"detail":"Model not found"}          -> ghost: no connection advertises it (nor its base)
  anything else                         -> dead

Usage:
  python3 audit-dead-models.py            # report only
  python3 audit-dead-models.py --delete   # snapshot dead rows, then delete them

Secrets are read from ai/.env and `docker exec litellm printenv`; they are never printed.
Rows the API refuses to delete are reported with their md5(id) for a manual SQL pass.
"""
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ENV = "/home/ai_service/ai-stack/ai/.env"
BACKUP_DIR = "/home/ai_service/ai-stack/backups"
OWUI = "http://127.0.0.1:8080"
WORKERS = 6


def env_value(key):
    with open(ENV) as fh:
        for line in fh:
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip("\"'")
    raise SystemExit(f"{key} not found in {ENV}")


def psql(sql):
    return subprocess.run(
        ["sudo", "-u", "postgres", "psql", "-d", "webui_db", "-tAc", sql],
        capture_output=True, text=True, check=True,
    ).stdout


def post_json(url, payload, token=None, timeout=90):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    return urllib.request.urlopen(req, timeout=timeout)


def admin_token():
    email = psql("select email from \"user\" where role='admin' limit 1").strip()
    return json.load(post_json(OWUI + "/api/v1/auths/signin",
                               {"email": email, "password": env_value("UI_PASSWORD")}))["token"]


def probe(token, model):
    try:
        post_json(OWUI + "/api/chat/completions",
                  {"model": model, "messages": [{"role": "user", "content": "hi"}],
                   "max_tokens": 1, "stream": False}, token, timeout=60).read()
        return 200, ""
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:300].decode("utf-8", "replace")
    except Exception as exc:  # timeout / connection reset
        return -1, str(exc)[:200]


def alive(code, err):
    return code == 200 or "MissingSessionID" in err or "missing x-" in err


def main():
    delete = "--delete" in sys.argv
    token = admin_token()

    # Enumerate the TABLE, not the API listings: /api/models and /api/v1/models/base
    # both return fewer rows than the DB and hide exactly the stale aliases we are after.
    rows = json.loads(psql(
        "select coalesce(json_agg(json_build_object('id',id,'base',base_model_id,"
        "'active',is_active)),'[]') from model;"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(lambda r: (r, probe(token, r["id"])), rows))

    dead, kept = [], []
    for row, (code, err) in results:
        (kept if alive(code, err) else dead).append((row, code, err))

    print(f"rows={len(rows)} alive={len(kept)} dead={len(dead)}")
    for row, code, err in sorted(dead, key=lambda x: x[0]["id"]):
        print(f"  DEAD  {row['id']!r} base={row['base']!r} :: {err[:90]}")

    if not delete:
        print("\nreport only — pass --delete to snapshot and remove the dead rows")
        return

    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(BACKUP_DIR, f"webui_dead_models_{ts}.jsonl")
    ids = json.dumps([row["id"] for row, _, _ in dead])
    snapshot = json.loads(psql(
        "select coalesce(json_agg(row_to_json(m)),'[]') from model m "
        f"where id in (select jsonb_array_elements_text('{ids}'::jsonb));"))
    with open(path, "w") as fh:
        for item in snapshot:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    subprocess.run(["chown", "ai_service:ai_service", path], check=False)
    print(f"snapshot: {path} ({len(snapshot)} rows)")

    refused = []
    for row, _, _ in dead:
        try:
            post_json(OWUI + "/api/v1/models/model/delete", {"id": row["id"]}, token).read()
        except urllib.error.HTTPError as exc:
            refused.append(row["id"])
            print(f"  refused ({exc.code}) {row['id']}")
    print(f"\ndeleted via API: {len(dead) - len(refused)}")
    if refused:
        print("delete these in SQL (history first, same transaction), targeting md5(id):")
        for mid in refused:
            print(f"  '{mid}' -> md5 {hashlib.md5(mid.encode()).hexdigest()}")
        print("  begin; delete from model_history h using model m where h.model_id=m.id and md5(m.id) in (...);")
        print("         delete from model m where md5(m.id) in (...); commit;")


if __name__ == "__main__":
    main()
