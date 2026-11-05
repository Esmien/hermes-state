#!/usr/bin/env python3
"""What does a given LiteLLM user actually see? Probe as that user without their password.

Run INSIDE the litellm container (reads LITELLM_MASTER_KEY from its own env):
    docker cp scripts/probe-litellm-admin-view.py litellm:/tmp/probe.py
    docker exec litellm python /tmp/probe.py <user_id>
docker exec litellm rm -f /tmp/probe.py

Mints a short-lived key bound to <user_id>, asks the same endpoints the Admin UI asks, deletes the
key again on the way out. Prints counts and model names only — never a key value.

Exit 0 = probe ran (read the numbers); 1 = could not mint a probe key (see printed status).
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:4000"
MK = os.environ.get("LITELLM_MASTER_KEY")


def call(path, body=None, key=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method="POST" if data else "GET")
    req.add_header("Authorization", "Bearer " + (key or MK or ""))
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:  # noqa: BLE001 - probe: report, do not crash
        return -1, repr(e)


def model_names(resp, field="model_name"):
    if isinstance(resp, dict):
        resp = resp.get("data") or []
    if not isinstance(resp, list):
        return []
    return sorted({m.get(field) for m in resp if isinstance(m, dict) and m.get(field)})


def main() -> int:
    if not MK:
        print("LITELLM_MASTER_KEY is not in this environment — run inside the litellm container")
        return 1
    user_id = sys.argv[1] if len(sys.argv) > 1 else ""
    if not user_id:
        st, users = call("/user/list")
        rows = (users.get("data") or []) if isinstance(users, dict) else []
        print(f"/user/list -> {st}")
        for u in rows:
            print(f"  {u.get('user_id')}  {u.get('user_email')}  {u.get('user_role')}  {u.get('models')}")
        print("pass a user_id to probe model visibility")
        return 0

    st, resp = call("/key/generate", {"user_id": user_id, "duration": "30m", "key_alias": "agent-view-probe"})
    key = resp.get("key") if isinstance(resp, dict) else None
    print(f"probe key for {user_id} -> {st}")
    if not key:
        print("  body:", str(resp)[:200])
        return 1
    try:
        st, resp = call("/user/info", None, key)
        role = (resp.get("user_info") or {}).get("user_role") if isinstance(resp, dict) else None
        print(f"role={role}  /user/info -> {st}")

        for label, path, field in (
            ("/model/info", "/model/info", "model_name"),
            ("/v1/models", "/v1/models", "id"),
            ("/model_group/info", "/model_group/info", "model_group"),
        ):
            st, resp = call(path, None, key)
            names = model_names(resp, field)
            print(f"{label:18} -> {st}  unique={len(names)}  sample={names[:3]}")

        st, resp = call("/key/generate", {"models": ["all-proxy-models"], "duration": "15m"}, key)
        print(f"key/generate as this user (models=[all-proxy-models]) -> {st}")
        child = resp.get("key") if isinstance(resp, dict) else None
    finally:
        keys = [k for k in (key, locals().get("child")) if k]
        st, _ = call("/key/delete", {"keys": keys})
        print(f"cleanup /key/delete -> {st} ({len(keys)} keys)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
