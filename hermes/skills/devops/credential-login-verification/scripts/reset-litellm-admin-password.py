#!/usr/bin/env python3
"""Reset a LiteLLM DB admin's password and prove the account is a full admin.

Run on the host (it talks to the gateway over 127.0.0.1:4000). Secrets come from the
environment, never argv, and are never printed.

    MK=<master key> NEWPASS='<owner-supplied>' python3 reset-litellm-admin-password.py <user_id> [--keep-reset-flag]

What it does:
  1. POST /user/update {user_id, password}          (fails loudly if the password policy rejects it)
  2. POST /v2/login with the email from the row     (JSON; /login is form-encoded and always 401s here)
  3. decodes the session JWT claims, prints role / user_id / password_reset_required
  4. probes with claims["key"] (the JWT itself is NOT a bearer): /v1/models, /model/info,
     /key/list, /user/list, then /key/generate with an explicit 2-model list, deleted afterwards

Exit code 0 only when login and every probe succeeded.

Notes: an admin-set password makes LiteLLM stamp password_reset_required=true. Pass
--keep-reset-flag to leave it (owner picks his own password next login); otherwise the
script clears it in LiteLLM_UserTable so the login lands on the dashboard.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("LITELLM_URL", "http://127.0.0.1:4000")
MASTER = os.environ.get("MK") or os.environ.get("LITELLM_MASTER_KEY")
NEWPASS = os.environ.get("NEWPASS")


def call(path: str, body=None, key: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:  # noqa: BLE001
        return -1, repr(e)


def sql(query: str) -> str:
    """Read/write the host Postgres as the postgres superuser (ai-stack host layout)."""
    return subprocess.run(
        ["sudo", "-u", "postgres", "psql", "-d", "litellm_db", "-tAc", query],
        capture_output=True, text=True, check=False,
    ).stdout.strip()


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    keep_flag = "--keep-reset-flag" in sys.argv
    if not args or not MASTER or not NEWPASS:
        print(__doc__)
        return 2
    uid = args[0]

    st, resp = call(f'/user/info?user_id={uid}', key=MASTER)
    email = (resp or {}).get("user_info", {}).get("user_email") if isinstance(resp, dict) else None
    if not email:
        print("user/info ->", st, "no user_email on that row; cannot drive /v2/login", (resp or "")[:200])
        return 1

    st, resp = call("/user/update", {"user_id": uid, "password": NEWPASS}, MASTER)
    print("user/update ->", st)
    if st != 200:
        print("  policy/API said:", resp)
        print("  hint: uppercase + special character are required; append a suffix and retry")
        return 1

    if not keep_flag:
        sql(f"update \"LiteLLM_UserTable\" set password_reset_required=false where user_id='{uid}'")

    st, resp = call("/v2/login", {"username": email, "password": NEWPASS})
    print("v2/login ->", st)
    if st != 200 or not isinstance(resp, dict) or not resp.get("token"):
        print("  body:", str(resp)[:200])
        return 1

    jwt = resp["token"]
    payload = jwt.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload))
    print(
        "  claims: user_id=%s role=%s email=%s pw_reset=%s"
        % (str(claims.get("user_id"))[:8], claims.get("user_role"), claims.get("user_email"),
           claims.get("password_reset_required"))
    )
    skey = claims.get("key")
    if not skey:
        print("  no claims['key'] — cannot probe the session")
        return 1

    ok = claims.get("user_role") == "proxy_admin"
    st, resp = call("/v1/models", key=skey)
    ids = [i.get("id") for i in (resp or {}).get("data", [])] if isinstance(resp, dict) else []
    print("  /v1/models ->", st, "models:", len(ids))
    ok = ok and st == 200 and bool(ids)

    st, resp = call("/model/info", key=skey)
    n = len((resp or {}).get("data", [])) if isinstance(resp, dict) else 0
    print("  /model/info ->", st, "entries:", n)
    ok = ok and st == 200 and n > 0

    for path, field in (("/key/list", "keys"), ("/user/list", "users")):
        st, resp = call(path, key=skey)
        cnt = len((resp or {}).get(field, [])) if isinstance(resp, dict) else 0
        print(f"  {path} ->", st, f"{field}:", cnt)
        ok = ok and st == 200

    if len(ids) >= 2:
        st, resp = call("/key/generate", {"models": ids[:2], "duration": "10m", "key_alias": "probe-handover"}, skey)
        made = isinstance(resp, dict) and bool(resp.get("key"))
        print("  /key/generate(models=[2]) ->", st, "created:", made,
              "models:", (resp or {}).get("models") if isinstance(resp, dict) else resp)
        ok = ok and st == 200 and made
        if made:
            call("/key/delete", {"keys": [resp["key"]]}, skey)
            print("  probe key deleted")

    print("VERDICT:", "full proxy_admin session verified" if ok else "account is NOT a working full admin")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
