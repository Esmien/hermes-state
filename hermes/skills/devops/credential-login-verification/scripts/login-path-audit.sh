#!/bin/bash
# Read-only credential / login-path inventory. Prints NO secret values.
# Verifies: which auth paths exist, whether the running process holds the
# credential from .env, and whether the live endpoint accepts it.
#
# Usage: login-path-audit.sh [container] [env-file] [public-url]
# Auto-detects the host-root prefix (/mnt/host) when running inside a container
# that sees the host filesystem.
set -u

CONT="${1:-litellm}"
URL="${3:-https://llm.esmien.qd.je}"
UKEY="UI_USERNAME"
PKEY="UI_PASSWORD"

# --- host-root prefix auto-detect -------------------------------------------
if [ -f "/mnt/host/etc/hostname" ] && [ -d "/mnt/host/home" ]; then
  ROOT="/mnt/host"
else
  ROOT=""
fi
ENVF="${2:-$ROOT/home/ai_service/ai-stack/ai/.env}"

say() { printf '\n===== %s =====\n' "$1"; }
die() { printf 'ERROR: %s\n' "$1"; }

[ -r "$ENVF" ] || { die "cannot read env file: $ENVF"; exit 1; }

read_val() {  # KEY -> value from $ENVF, stripped of quotes; empty if absent
  local v
  v="$(grep -m1 "^$1=" "$ENVF" 2>/dev/null | cut -d= -f2-)"
  v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
  printf '%s' "$v"
}
sha8() { printf '%s' "$1" | sha256sum | cut -c1-8; }

say "env file"
printf 'path: %s\n' "$ENVF"
printf 'mtime: %s\n' "$(stat -c %y "$ENVF" 2>/dev/null)"
printf 'container start: %s\n' "$(docker inspect "$CONT" --format '{{.State.StartedAt}}' 2>/dev/null)"

say "auth paths in the running container"
docker exec -i "$CONT" python - <<'PY' 2>&1 | grep -v '^$'
import os
try:
    from litellm.proxy.auth.login_utils import get_ui_credentials
    u, p = get_ui_credentials(os.getenv("LITELLM_MASTER_KEY"))
    print(f"env path (UI_USERNAME/UI_PASSWORD): ACTIVE   user_len={len(u)} pass_len={len(p)}")
except Exception as e:
    print(f"env path: INACTIVE ({type(e).__name__}: {e})")
print(f"UI_PASSWORD set in env: {bool(os.getenv('UI_PASSWORD'))}"
      f"  -> master-key fallback {'ACTIVE' if not os.getenv('UI_PASSWORD') else 'unused'}")
PY

say "credential in .env vs in the running process (hash only)"
UV="$(read_val "$UKEY")"; PV="$(read_val "$PKEY")"
CENV="$(docker inspect "$CONT" --format '{{json .Config.Env}}' 2>/dev/null)"
get_cenv() {
  printf '%s' "$CENV" | python3 -c \
    "import sys,json;d=dict(x.split('=',1) for x in json.load(sys.stdin) if '=' in x);print(d.get('$1',''),end='')" 2>/dev/null
}
CUV="$(get_cenv "$UKEY")"; CPV="$(get_cenv "$PKEY")"
report_pair() {
  local name="$1" fv="$2" cv="$3" verdict
  if [ -z "$fv" ]; then verdict="ABSENT in .env (container has $( [ -n "$cv" ] && echo 'a value' || echo 'none'))"
  elif [ "$fv" = "$cv" ]; then verdict="SAME"
  else verdict="DRIFT — container still holds the old value"
  fi
  printf '%-12s file(len=%s sha=%s) container(len=%s sha=%s) -> %s\n' \
    "$name" "${#fv}" "$(sha8 "$fv")" "${#cv}" "$(sha8 "$cv")" "$verdict"
}
report_pair "$UKEY" "$UV" "$CUV"
report_pair "$PKEY" "$PV" "$CPV"

if [ -n "$PV" ] && [ -n "$CPV" ] && [ "$PV" != "$CPV" ]; then
  printf 'ACTION: .env is newer than the running process -> recreate, not restart:\n'
  printf '        docker compose up -d --force-recreate %s\n' "$CONT"
fi

say "password strength (value never printed)"
# NB: pass through the environment, not stdin — a heredoc would shadow a pipe.
PV_FOR_PY="$PV" python3 - <<'PYEOF'
import os, collections, math
p = os.environ.get("PV_FOR_PY", "")
if not p:
    print("empty - nothing to grade (check the .env path above)")
    raise SystemExit
f = collections.Counter(p)
h = -sum((c / len(p)) * math.log2(c / len(p)) for c in f.values())
bits = h * len(p)
has = lambda pred: any(pred(c) for c in p)
print("len=%d unique=%d" % (len(p), len(f)))
print("classes: lower=%s upper=%s digit=%s special=%s" % (
    has(str.islower), has(str.isupper), has(str.isdigit),
    has(lambda c: not c.isalnum())))
print("entropy=%.1f bits" % bits)
print("verdict:", "strong (treat as a key)" if bits >= 128 else ("adequate" if bits >= 80 else "WEAK"))
PYEOF

say "live endpoint check (POST) — 200 + token means the credential works"
TMP="$(mktemp)"
for ep in /v2/login /login; do
  BODY="$(python3 -c "import json,sys;print(json.dumps({'username':sys.argv[1],'password':sys.argv[2]}))" "$UV" "$PV")"
  code="$(curl -sk -m 12 -o "$TMP" -w '%{http_code}' -X POST "$URL$ep" \
    -H 'Content-Type: application/json' --data "$BODY" 2>/dev/null)"
  tok="$(python3 -c "
import json
try:
    d = json.load(open('$TMP'))
    print('token-present' if d.get('token') else 'no-token')
except Exception:
    print('unparsed')
" 2>/dev/null)"
  case "$code" in
    200) mark="OK" ;;
    401) mark="rejected" ;;
    429) mark="throttled (wait before retrying)" ;;
    *)   mark="code $code" ;;
  esac
  printf '  %-10s -> %s  %s  [%s]\n' "$ep" "$code" "$tok" "$mark"
done
rm -f "$TMP"

say "db-side admin rows (each one is a full door)"
# LiteLLM's DB lives on the HOST Postgres (systemd), not in lyria-postgres.
# Compose builds DATABASE_URL from ${LITELLM_DB_PASSWORD}; it is usually NOT a
# literal DATABASE_URL line in .env, so resolve the password both ways.
DB_URL="$(grep -m1 '^DATABASE_URL=' "$ENVF" 2>/dev/null | cut -d= -f2-)"
if [ -n "$DB_URL" ]; then
  DBPASS="$(printf '%s' "$DB_URL" | sed -n 's|.*://[^:]*:\([^@]*\)@.*|\1|p')"
  DBUSER="$(printf '%s' "$DB_URL" | sed -n 's|.*://\([^:]*\):.*|\1|p')"
  DBNAME="$(printf '%s' "$DB_URL" | sed -n 's|.*/\([A-Za-z0-9_]*\)$|\1|p')"
else
  DBPASS="$(read_val LITELLM_DB_PASSWORD)"
  DBUSER="litellm"; DBNAME="litellm_db"
fi
DBUSR="${DBUSER:-litellm}"; DBNAME="${DBNAME:-litellm_db}"
Q="select coalesce(user_email,'(no email / env-admin)'), user_role, length(password) from \"LiteLLM_UserTable\" where password is not null order by created_at;"
if [ -z "$DBPASS" ]; then
  printf 'skipped: no DATABASE_URL and no LITELLM_DB_PASSWORD in %s\n' "$ENVF"
else
  DB_OUT="$(docker run --rm --net=host -e PGPASSWORD="$DBPASS" postgres:17-alpine \
    psql -h 127.0.0.1 -U "$DBUSR" -d "$DBNAME" -At -F' | ' -c "$Q" 2>&1)"
  if printf '%s' "$DB_OUT" | grep -qiE 'error|fatal'; then
    printf 'DB check failed: %s\n' "$(printf '%s' "$DB_OUT" | head -2)"
  elif [ -z "$DB_OUT" ]; then
    printf '  no password-bearing users\n'
  else
    printf '  %s\n' "$DB_OUT"
  fi
  printf '  (each row above is an independent login path)\n'
fi

say "throttle / trusted_proxy_ranges"
if docker logs "$CONT" --since 60m 2>&1 | grep -q 'trusted_proxy_ranges is not set'; then
  printf 'WARNING present in logs -> limits apply per proxy address, not per real client.\n'
  printf 'ACTION: set trusted_proxy_ranges to the nginx ranges in general_settings.\n'
else
  printf 'no warning in the last 60m\n'
fi

say "done — nothing was changed"
