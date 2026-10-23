#!/bin/bash
# Проверка env-гигиены ai-stack. Печатает только ИМЕНА ключей, значения не читает.
#   bash check-env-parity.sh [stack_dir]
# Коды: 0 — всё сходится, 1 — есть расхождения/подозрения.
set -uo pipefail
STACK=${1:-/home/ai_service/ai-stack}
ENVF="$STACK/ai/.env"
EXF="$STACK/ai/.env.example"
rc=0

keys() { grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "$1" | tr -d '='; }

[ -f "$ENVF" ] || { echo "FAIL: нет $ENVF"; exit 2; }
[ -f "$EXF" ]  || { echo "FAIL: нет $EXF"; exit 2; }

echo "== набор и порядок ключей =="
if diff <(keys "$ENVF") <(keys "$EXF") >/dev/null; then
    echo "OK: .env и .env.example совпадают ($(keys "$ENVF" | wc -l) ключей)"
else
    echo "FAIL: расхождение (.env < > .env.example):"
    diff <(keys "$ENVF") <(keys "$EXF") | sed 's/^/  /'
    rc=1
fi

echo "== обязательные ключи (preflight deploy.sh) =="
required=$(awk '
  /for key in/ { buf=""; f=1 }
  f { buf = buf "\n" $0 }
  f && /; do/ { f=0; if (buf ~ /LITELLM_MASTER_KEY/) { print buf; exit } }
' "$STACK/deploy.sh" 2>/dev/null | tr ' \\\t\n' '\n' | grep -E '^[A-Z][A-Z0-9_]+$' | sort -u)
if [ -z "$required" ]; then
    echo "WARN: не разобрал список из deploy.sh — проверь вручную"
else
    for k in $required; do
        if grep -qE "^${k}=.+" "$ENVF"; then :; else echo "  ПУСТО/НЕТ: $k"; rc=1; fi
    done
    [ "$rc" -eq 0 ] && echo "OK: все на месте"
fi

echo "== ключи без потребителей (кандидаты в мёртвые) =="
deepseek_dummy=0
for k in $(keys "$ENVF"); do
    hits=$(grep -rl --exclude='.env' --exclude='.env.example' \
             --exclude-dir=backups --exclude-dir=backup-deploy --exclude-dir=_state_snapshot \
             -- "$k" "$STACK" 2>/dev/null | head -2 | sed "s|$STACK/||" | tr '\n' ' ')
    out=$(grep -rl -- "$k" /usr/local/bin /etc/systemd/system 2>/dev/null | head -2 | tr '\n' ' ')
    if [ -z "$hits$out" ]; then
        echo "  DEAD? $k — ни одного потребителя в репо и в /usr/local/bin, /etc/systemd/system"
        rc=1
    fi
done
echo "(бэкапы, backup-deploy и _state_snapshot не считаются потребителями)"

exit $rc
