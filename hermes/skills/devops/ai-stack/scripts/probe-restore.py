#!/usr/bin/env python3
"""Restore-пробник: восстанавливает свежие дампы в временные БД, ничего не отправляя в Telegram.

Зачем: `monitor.py verify` и бота `/backups` сами отправляют отчёт, поэтому отладка ими
= дубли сообщений владельцу. Этот скрипт импортирует monitor.py и вызывает
`_restore_into_temp_db` напрямую — тот же код, что в ночной проверке, но без send.

Запуск от root (нужен `sudo -u postgres` без пароля):
    python3 scripts/probe-restore.py                # обе БД
    python3 scripts/probe-restore.py litellm_db     # одна

Exit 0 — все восстановились, 1 — есть FAIL. Ничего не удаляет: временные БД
создаёт и дропает сам `_restore_into_temp_db` в finally.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

MONITOR = Path("/home/ai_service/notifications/monitor.py")


def load_monitor() -> ModuleType:
    spec = importlib.util.spec_from_file_location("monitor_probe", MONITOR)
    if spec is None or spec.loader is None:
        raise SystemExit(f"не удалось загрузить {MONITOR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # модуль сам подхватывает .env из своей директории
    return module


def main(argv: list[str]) -> int:
    monitor = load_monitor()
    groups, order, _files = monitor.collect_backup_groups()
    wanted = argv or order
    rc = 0
    for name in wanted:
        if name not in groups or not groups[name]:
            print(f"FAIL {name}: дампов не найдено")
            rc = 1
            continue
        ok, detail = monitor._restore_into_temp_db(name, groups[name][0])
        print(f"{'OK  ' if ok else 'FAIL'} {name}: {detail}")
        if not ok:
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
