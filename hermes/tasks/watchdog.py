#!/usr/bin/env python3
"""Страховка доски задач: ловит изменения backlog.md и сама шлёт событие в Telegram.

Зачем: правило «молчаливых правок нет» не должно зависеть от того, вспомнил агент или нет.
Path-юнит `hermes-task-board-watch` дёргает этот скрипт на каждое изменение файла; скрипт
сравнивает статусы с прошлым снимком и отправляет по одному короткому сообщению на переход.

Первый запуск (нет снимка) только пишет baseline — без сообщений.
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

LABEL = {"todo": "◻️ в очереди", "in_progress": "✏️ в работе", "done": "✅ закрыта", "declined": "❌ отклонена"}


def snapshot() -> dict[str, dict]:
    return {t["id"]: {"status": t["status"], "title": t["title"]} for t in digest.parse_backlog()}


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

    sent = 0
    for task_id, task in current.items():
        old = previous.get(task_id)
        if old is None:
            digest.send(digest.build_event("новая задача на доске", task_id))
            sent += 1
        elif old["status"] != task["status"]:
            text = f"{LABEL.get(old['status'], old['status'])} → <b>{LABEL.get(task['status'], task['status'])}</b>"
            digest.send(digest.build_event(text, task_id))
            sent += 1
        elif old["title"] != task["title"]:
            digest.send(digest.build_event("уточнена формулировка", task_id))
            sent += 1

    for task_id, old in previous.items():
        if task_id not in current:
            digest.send(digest.build_event("задача снята с доски", None).replace("Обновление задач", "Задача убрана") +
                        f"\n<i>#{task_id} {old['title']}</i>")
            sent += 1

    save(current)
    print("events sent:", sent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
