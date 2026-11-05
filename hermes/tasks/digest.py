#!/usr/bin/env python3
"""Дайджест задач владельца: понедельничная сводка и точечные события в Telegram.

Файл задач: /root/.hermes/tasks/backlog.md (формат — скилл owner-task-digest).
Бот: TASK_BOT_TOKEN из /root/.hermes/tasks/.env (не печатать).

Использование:
  digest.py digest            отправить дайджест (так его зовёт таймер)
  digest.py preview           напечатать дайджест, ничего не отправлять
  digest.py event "текст"     отправить точечное обновление
  digest.py event --task 1 "текст"   обновление с указанием задачи
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent
BACKLOG = BASE / "backlog.md"
ENV = BASE / ".env"
MSK = dt.timezone(dt.timedelta(hours=3))

STATUS_ORDER = ["in_progress", "blocked", "pending", "done"]
STATUS_TITLE = {
    "in_progress": "🔴 В работе",
    "blocked": "🧱 Заблокировано",
    "pending": "⏳ В очереди",
    "done": "✅ Закрыто",
}
STATUS_SHORT = {
    "in_progress": "в работе",
    "blocked": "заблокирована",
    "pending": "в очереди",
    "done": "закрыта",
}
PRIORITY_MARK = {"high": "🔥", "normal": "", "low": "·"}


def load_env() -> tuple[str, str]:
    values: dict[str, str] = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values["TASK_BOT_TOKEN"], values.get("OWNER_CHAT_ID", "")


def parse_backlog() -> list[dict]:
    tasks: list[dict] = []
    current: dict | None = None
    for raw in BACKLOG.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        m = re.match(r"^##\s+#(\d+)\s+(.*)$", line)
        if m:
            current = {"id": m.group(1), "title": m.group(2).strip(), "note": "", "progress": 0,
                       "status": "pending", "priority": "normal", "updated": ""}
            tasks.append(current)
            continue
        if current is None or not line or line.startswith("#") or line.startswith("<!--"):
            continue
        key, sep, val = line.partition(":")
        if not sep:
            continue
        key, val = key.strip().lower(), val.strip()
        if key == "progress":
            digits = re.sub(r"[^0-9]", "", val)
            current["progress"] = int(digits) if digits else 0
        elif key in ("status", "priority", "updated", "note"):
            current[key] = val
    return tasks


def fmt_task(task: dict, show_note: bool = True) -> str:
    title = f"<b>#{html.escape(task['id'])}</b> {html.escape(task['title'])}"
    marks = []
    if task["status"] == "in_progress" and task["progress"]:
        marks.append(f"{task['progress']}%")
    if task["priority"] == "high":
        marks.append(PRIORITY_MARK["high"])
    elif task["priority"] == "low":
        marks.append("низкий")
    tail = f" · {' · '.join(m for m in marks if m)}" if marks else ""
    out = title + tail
    if show_note and task["note"]:
        out += f"\n   <i>{html.escape(task['note'])}</i>"
    return out


def build_digest(tasks: list[dict]) -> str:
    now = dt.datetime.now(MSK)
    active = [t for t in tasks if t["status"] != "done"]
    done = [t for t in tasks if t["status"] == "done"]
    weekday = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"][now.weekday()]
    months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря"]

    lines = [
        "🧭 <b>Задачи на неделю</b>",
        f"<i>{weekday}, {now.day} {months[now.month - 1]} · "
        f"{len(active)} активных, {len(done)} закрыто</i>",
        "━━━━━━━━━━━━━━",
    ]
    for status in STATUS_ORDER:
        group = [t for t in tasks if t["status"] == status]
        if not group:
            continue
        lines.append(f"<b>{STATUS_TITLE[status]}</b> ({len(group)})")
        for task in group:
            lines.append(fmt_task(task, show_note=(status != "done")))
        lines.append("")

    if not tasks:
        lines += ["<i>Список пуст.</i>", ""]

    total = len(tasks)
    done_pct = round(len(done) / total * 100) if total else 0
    lines.append("━━━━━━━━━━━━━━")
    lines.append(f"Прогресс: <b>{done_pct}%</b> ({len(done)}/{total})")
    lines.append(f"<i>Сводка задач · {now:%H:%M} МСК</i>")
    return "\n".join(lines).strip()


def send(text: str) -> dict:
    token, chat_id = load_env()
    if not chat_id:
        raise SystemExit("OWNER_CHAT_ID не задан в .env")
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.load(resp)
    return {"ok": payload.get("ok"), "message_id": payload.get("result", {}).get("message_id")}


def build_event(text: str, task_id: str | None) -> str:
    now = dt.datetime.now(MSK)
    tasks = parse_backlog()
    header = "🔄 <b>Обновление задач</b>"
    if task_id:
        task = next((t for t in tasks if t["id"] == task_id), None)
        if task:
            header = (f"🔄 <b>Задача #{html.escape(task_id)}</b> · "
                      f"{STATUS_SHORT.get(task['status'], task['status'])}"
                      + (f" ({task['progress']}%)" if task["status"] == "in_progress" and task["progress"] else ""))
    body = html.escape(text).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>").replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
    return f"{header}\n{body}\n<i>{now:%d.%m %H:%M} МСК</i>"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Дайджест задач владельца")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("digest", help="отправить дайджест в Telegram")
    sub.add_parser("preview", help="напечатать дайджест")
    ev = sub.add_parser("event", help="отправить точечное обновление")
    ev.add_argument("text")
    ev.add_argument("--task", default=None)
    args = parser.parse_args(argv)

    if args.cmd == "preview":
        print(build_digest(parse_backlog()))
        return 0
    if args.cmd == "digest":
        print(json.dumps(send(build_digest(parse_backlog())), ensure_ascii=False))
        return 0
    print(json.dumps(send(build_event(args.text, args.task)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
