#!/usr/bin/env bash
# vpn-cfg - edit and apply the VPN router config (container vpn-router)
#   vpn-cfg status            inbound/outbound summary + container state
#   vpn-cfg show [filter]     print config.json
#   vpn-cfg edit              back up, then open in $EDITOR
#   vpn-cfg apply             validate JSON, restart, health-check routes (auto-rollback)
#   vpn-cfg rollback          restore the newest backup and restart
#   vpn-cfg backups           list backups
set -euo pipefail

CFG=/root/vpn-router/config.json
BRAND=/root/vpn-router/brand.json
BAK=/root/vpn-router/backups
CONTAINER=vpn-router
HOST=vpn.esmien.qd.je

mkdir -p "$BAK"

status() {
  python3 - "$CFG" "$BRAND" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1]))
brand = json.load(open(sys.argv[2]))
print(f"host:      {brand['host']}:{brand['port']} (backup {brand['alt_port']})")
print(f"inbounds:  {len(cfg['inbounds'])}")
for i in cfg["inbounds"]:
    path = i.get("streamSettings", {}).get("wsSettings", {}).get("path", "-")
    print(f"  {i['tag']:<10} 127.0.0.1:{i['port']:<6} {path}")
print(f"outbounds: {', '.join(o['tag'] for o in cfg['outbounds'])}")
print(f"rules:     {len(cfg['routing']['rules'])}")
print(f"default:   {cfg['routing']['rules'][-1].get('outboundTag')}")
PY
  echo "container: $(docker inspect -f '{{.State.Status}} restarts={{.RestartCount}}' "$CONTAINER")"
}

apply() {
  python3 -m json.tool "$CFG" >/dev/null || { echo "config.json: invalid JSON - not applying"; exit 1; }
  cp -a "$CFG" "$BAK/config-$(date +%Y%m%d-%H%M%S).json"
  docker restart "$CONTAINER" >/dev/null
  sleep 6
  local ok=1
  for p in /general /france /fi; do
    code=$(curl -sS -m 10 --resolve "$HOST:8443:127.0.0.1" -o /dev/null -w '%{http_code}' "https://$HOST:8443$p" || true)
    printf '  %-9s %s\n' "$p" "$code"
    [ "$code" = "400" ] || ok=0
  done
  if [ "$ok" = "1" ]; then
    echo "applied, routes answer (400 = waiting for WebSocket upgrade, expected)"
  else
    echo "health check failed - rolling back"; rollback
  fi
}

rollback() {
  local last
  last=$(ls -1t "$BAK"/config-*.json 2>/dev/null | head -1 || true)
  [ -n "$last" ] || { echo "no backups"; exit 1; }
  echo "rollback to $last"
  cp -a "$last" "$CFG"
  docker restart "$CONTAINER" >/dev/null
  sleep 5
  echo done
}

case "${1:-status}" in
  status) status ;;
  show) shift; python3 -m json.tool "$CFG" | { [ $# -gt 0 ] && jq "$@" || cat; } ;;
  edit)
    cp -a "$CFG" "$BAK/config-$(date +%Y%m%d-%H%M%S).json"
    "${EDITOR:-nano}" "$CFG"
    python3 -m json.tool "$CFG" >/dev/null && echo "JSON valid - apply with: vpn-cfg apply"
    ;;
  apply) apply ;;
  rollback) rollback ;;
  backups) ls -1t "$BAK"/config-*.json 2>/dev/null | head -10 ;;
  *) sed -n '2,9p' "$0"; exit 1 ;;
esac
