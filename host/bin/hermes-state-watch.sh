#!/bin/bash
# Коммит состояния Hermes в GitHub по факту изменений (а не по таймеру).
#
# Слушает inotify на всё, что попадает в снапшот (config, memories, skills,
# cron, plugins, hooks, scripts + хостовые скрипты/юниты/runbook), ждёт
# «тишины» QUIET секунд и запускает hermes-state-backup.sh. Тот сам решает,
# есть ли реальные изменения (git diff --cached --quiet) и пушит только их.
#
# Почему не systemd .path: PathModified= смотрит каталог нерекурсивно, а
# изменения приходят из подпапок skills/*/ и memories/.
set -uo pipefail

BACKUP=/usr/local/bin/hermes-state-backup.sh
LOG=/var/log/hermes-state-watch.log
QUIET=${QUIET:-90}        # тишина после последнего события, сек
MAXDELAY=${MAXDELAY:-900} # максимум от первого события до коммита, сек
CYCLE=15                  # окно ожидания событий в inotifywait, сек

HERMES=${HERMES_HOME:-/root/.hermes}
WATCH=(
    "$HERMES/skills"
    "$HERMES/memories"
    "$HERMES/plugins"
    "$HERMES/hooks"
    "$HERMES/scripts"
    "$HERMES/cron"
    "$HERMES/config.yaml"
    "$HERMES/SOUL.md"
    /usr/local/bin
    /etc/systemd/system
    /etc/docker-autorecover.conf
    /etc/hermes-boot-expected-containers.txt
    /etc/logrotate.d/hermes-state-backup
    /home/ai_service/ai-stack/runbook-containers.md
    /home/ai_service/ai-stack/ai/backup-databases.sh
)
# .hub — 51 МБ клон хаба, в снапшот не идёт; .git/__pycache__/локи — шум
EXCLUDE='(\.hub/|\.git/|__pycache__/|\.locks/|\.lock$|\.tmp$|hermes-state/repo|\.curator_backups/)'

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" >>"$LOG"; }

run_backup() {
    log "changes detected → snapshot"
    if "$BACKUP" >>"$LOG" 2>&1; then
        log "snapshot ok"
    else
        log "snapshot FAILED rc=$?"
    fi
}

[[ -x "$BACKUP" ]] || { log "FATAL: $BACKUP not executable"; exit 1; }
: >"$LOG" 2>/dev/null || true
log "watcher start (quiet=${QUIET}s maxdelay=${MAXDELAY}s paths=${#WATCH[@]})"

# старт сервиса = догоняем изменения, сделанные пока watcher лежал
run_backup

pending=0
first=0
last=0

while true; do
    if inotifywait -r -q -t "$CYCLE" \
            -e modify,create,delete,move,moved_to,moved_from,attrib,close_write \
            --exclude "$EXCLUDE" "${WATCH[@]}" >/dev/null 2>&1; then
        now=$(date +%s)
        [[ "$pending" -eq 0 ]] && first=$now
        pending=1
        last=$now
    else
        rc=$?
        if [[ "$pending" -eq 1 && "$rc" -eq 2 ]]; then
            now=$(date +%s)
            if (( now - last >= QUIET )) || (( now - first >= MAXDELAY )); then
                run_backup
                pending=0
                first=0
            fi
        elif [[ "$rc" -ne 2 ]]; then
            # каталог исчез/права/иное — не умираем молча
            log "inotifywait rc=$rc, retry in 10s"
            sleep 10
        fi
    fi
done
