#!/usr/bin/env bash
# Карта сетей по одному адресу или по списку (аргументы — IP или путь к файлу с IP).
# Одна строка на адрес: IP  AS<asn>  <организация>  <страна ASN>  |  <город>, <страна по гео>
# Зачем: пачка адресов в разных странах часто оказывается одной ASN — тогда
# независимых выходов нет, и вердикт ставится по сети, а не по per-IP листам.
set -uo pipefail

if [ $# -eq 0 ]; then
    echo "usage: $0 <ip|file>..." >&2
    exit 2
fi

ips=()
for arg in "$@"; do
    if [ -f "$arg" ]; then
        while read -r line; do
            [ -n "$line" ] && ips+=("$line")
        done < "$arg"
    else
        ips+=("$arg")
    fi
done

asns=()
for ip in "${ips[@]}"; do
    out=$(curl -s --max-time 12 "https://ip.guide/$ip" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print("lookup-failed"); raise SystemExit
a = d.get("network", {}).get("autonomous_system", {}) or {}
l = d.get("location", {}) or {}
print(f"AS{a.get(\"asn\")} {str(a.get(\"organization\"))[:32]} {a.get(\"country\")} | {l.get(\"city\")}, {l.get(\"country\")}")
' 2>/dev/null)
    [ -z "$out" ] && out="lookup-failed"
    printf '%-16s %s\n' "$ip" "$out"
    case "$out" in AS*) asns+=("${out%% *}");; esac
done

uniq_asns=$(printf '%s\n' "${asns[@]:-}" | sed '/^$/d' | sort -u)
count=$(printf '%s\n' "$uniq_asns" | sed '/^$/d' | wc -l)
echo "---"
echo "уникальных сетей: $count из ${#ips[@]} адресов"
if [ "$count" = "1" ] && [ "${#ips[@]}" -gt 1 ]; then
    echo "ВСЕ В ОДНОЙ ASN — независимых выходов нет, бан/абуз выносит их разом"
fi
