#!/usr/bin/env bash
# Ставит юниты доски задач из харнесса в systemd. Идемпотентно.
# Источник правды: /root/.hermes/units/ (бэкапится в hermes-state), а не vps-infra.
set -euo pipefail

UNITS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../units" && pwd)"
UNITS=(
    hermes-task-digest.service
    hermes-task-digest.timer
    hermes-task-board-watch.service
    hermes-task-board-watch.path
)

for unit in "${UNITS[@]}"; do
    install -m 644 "$UNITS_DIR/$unit" "/etc/systemd/system/$unit"
done

systemctl daemon-reload
systemctl enable --now hermes-task-digest.timer hermes-task-board-watch.path
systemctl list-timers hermes-task-digest.timer --no-pager | sed -n 1,2p
systemctl list-paths hermes-task-board-watch.path --no-pager | sed -n 1,2p
