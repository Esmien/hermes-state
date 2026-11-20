#!/usr/bin/env bash
# pin-egress-uid.sh — привязать исходящий трафик одного пользователя к конкретному
# адресу этого хоста (policy routing по uid), не трогая VPN-стек.
#
# usage: pin-egress-uid.sh [--apply] <user> <src-ip> [gw] [iface] [table]
#
# Без --apply только показывает текущий egress пользователя. С --apply добавляет
# маршрут в отдельную таблицу и правило по uid, затем проверяет egress из-под
# пользователя И из-под root (root должен остаться на прежнем адресе).
#
# ВНИМАНИЕ: ip rule / ip route живут до перезагрузки. Для постоянства переносить
# те же две команды в unit с After=network-online.target.
set -euo pipefail

APPLY=0
if [ "${1:-}" = "--apply" ]; then APPLY=1; shift; fi

USER_NAME=${1:?usage: pin-egress-uid.sh [--apply] <user> <src-ip> [gw] [iface] [table]}
SRC_IP=${2:?нужен адрес-источник}
IFACE=${4:-$(ip route show default | awk '/^default/{print $5; exit}')}
GW=${3:-$(ip route show default | awk '/^default/{print $3; exit}')}
TABLE=${5:-200}
UID_N=$(id -u "$USER_NAME")

egress() { runuser -u "$USER_NAME" -- curl -s --max-time 10 https://ipinfo.io/ip || echo FAIL; }

printf 'user=%s uid=%s src=%s gw=%s iface=%s table=%s\n' "$USER_NAME" "$UID_N" "$SRC_IP" "$GW" "$IFACE" "$TABLE"
printf 'egress before: %s\n' "$(egress)"

if [ "$APPLY" = 1 ]; then
    ip route replace default via "$GW" dev "$IFACE" src "$SRC_IP" table "$TABLE"
    ip rule add uidrange "$UID_N-$UID_N" lookup "$TABLE" priority 1000 2>/dev/null || true
    printf 'egress after:  %s\n' "$(egress)"
    printf 'root egress:   %s  (не должен измениться)\n' "$(curl -s --max-time 10 https://ipinfo.io/ip || echo FAIL)"
    ip rule show | grep "uidrange $UID_N-$UID_N" || echo 'WARN: правило не найдено'
    echo 'note: правила не переживут перезагрузку — перенести в unit после network-online.target'
fi
