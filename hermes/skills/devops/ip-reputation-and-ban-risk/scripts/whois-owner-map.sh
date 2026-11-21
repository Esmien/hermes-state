#!/usr/bin/env bash
# whois-owner-map.sh — кто на самом деле держит адреса, без HTTP-API.
#
# Зачем: ip-api на части блоков отдаёт пустое поле `as`, а ip.guide/bgpview могут не
# резолвиться. whois по порту 43 отвечает почти всегда, и именно в нём лежит то, что решает
# судьбу адреса: владелец (org-name), netname и maintainer (mnt-by). Один и тот же mnt-by у
# «нашего» и «чужого» адреса = общий пул перепродавца и общая судьба при блоке по ASN.
#
# Использование:
#   scripts/whois-owner-map.sh 1.1.1.1 2.2.2.2 vetka.txt
#   scripts/whois-owner-map.sh < ips.txt
set -u

ips=("$@")
if [ ${#ips[@]} -eq 0 ]; then
  mapfile -t ips
elif [ -f "${ips[0]}" ]; then
  mapfile -t ips < "${ips[0]}"
fi

declare -A tally=()
printf '%-16s %-8s %-22s %-34s %s\n' IP ASN NETNAME OWNER MNT
for ip in "${ips[@]}"; do
  ip="${ip%%[[:space:]]*}"; ip="${ip%%,}"
  [ -z "$ip" ] && continue
  w="$(timeout 25 whois "$ip" 2>/dev/null || true)"
  asn="$(printf '%s\n' "$w" | grep -im1 -E '^(origin|aut-num):'  | awk '{print $2}')"
  netname="$(printf '%s\n' "$w" | grep -im1 '^netname:'  | awk '{print $2}')"
  owner="$(printf '%s\n' "$w" | grep -im1 -E '^(org-name|descr):' | cut -d: -f2- | sed 's/^ *//')"
  mnt="$(printf '%s\n' "$w" | grep -im1 '^mnt-by:' | awk '{print $2}')"
  printf '%-16s %-8s %-22.22s %-34.34s %s\n' \
    "$ip" "${asn:-?}" "${netname:-?}" "${owner:-?}" "${mnt:-?}"
  tally["${owner:-?}|${mnt:-?}"]=$(( ${tally["${owner:-?}|${mnt:-?}"]:-0} + 1 ))
done

echo '---'
echo "уникальных владельцев: ${#tally[@]}"
for k in "${!tally[@]}"; do
  printf '  %-2s x %-34.34s %s\n' "${tally[$k]}" "${k%%|*}" "${k##*|}"
done
