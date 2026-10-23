#!/bin/bash
# Ночная проверка бэкапа PostgreSQL для cron-задачи Hermes.
# Задача: гарантировать РОВНО ОДИН отчёт в бот уведомлений за прогон —
# отчёт отправляет сам monitor.py verify. Если запустить verify дважды
# (в том числе из LLM-агента), владелец получит дубль сообщения.
set -uo pipefail

LOG=/var/log/hermes-backup-verify.log
LOCK=/run/hermes-backup-verify.lock
MONITOR=/home/ai_service/notifications/monitor.py

# Одновременные (параллельные) запуски отсекаем: второй сразу выходит.
exec 9>"$LOCK"
if ! flock -n 9; then
    echo "verify: предыдущая проверка ещё выполняется, повтор пропущен"
    exit 0
fi

stamp=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
out=$(/usr/bin/python3 "$MONITOR" verify 2>&1)
rc=$?

{
    echo "[$stamp] verify exit=$rc"
    [ -n "$out" ] && printf '[%s] %s\n' "$stamp" "$out"
} >> "$LOG" 2>/dev/null

if [ "$rc" -ne 0 ]; then
    /usr/bin/python3 "$MONITOR" send \
        "⚠️ Проверка ночного бэкапа завершилась ошибкой (exit $rc). Смотри: journalctl -u postgres-backup.service -n 50 --no-pager и $LOG" \
        >/dev/null 2>&1
fi

echo "verify выполнен (exit=$rc); отчёт отправлен в бот уведомлений"
