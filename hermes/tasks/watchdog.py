#!/usr/bin/env python3
"""Страховка доски задач: ловит изменения backlog.md и ПРАВИТ живое сообщение в Telegram.

Зачем: правило «молчаливых правок нет» не должно зависеть от того, вспомнил агент или нет.
Path-юнит `hermes-task-board-watch` дёргает этот скрипт на каждое изменение файла; скрипт
сравнивает доску с прошлым снимком и, если что-то поменялось, вызывает `digest.update_board`
— то есть редактирует живое сообщение, а не отправляет новое. Новое сообщение появляется
только понедельничной сводкой (или если живое сообщение удалили).

Первый запуск (нет снимка) только пишет baseline — без правок и сообщений.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

TASKS = pathlib.Path("/root/.hermes/tasks")
STATE = pathlib.Path("/var/lib/hermes-task-board/state.json")

spec = importlib.util.spec_from_file_location("digest", TASKS / "digest.py")
digest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(digest)  # type: ignore[union-attr]


def snapshot() -> dict[str, dict]:
    return {t["id"]: {"status": t["status"], "title": t["title"], "file": t["file"]}
            for t in digest.parse_backlog()}


def load_previous() -> dict[str, dict] | None:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save(current: dict[str, dict]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    current = snapshot()
    previous = load_previous()
    if previous is None:
        save(current)
        print("baseline written:", len(current))
        return 0
    if previous == current:
        print("no changes")
        return 0

    result = digest.update_board()
    save(current)
    print("board updated:", json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
