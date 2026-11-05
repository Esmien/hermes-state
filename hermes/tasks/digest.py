#!/usr/bin/env python3
"""Доска задач владельца: понедельничная сводка и точечные события в Telegram.

Файл задач: /root/.hermes/tasks/backlog.md (формат — скилл owner-task-digest).
Бот: TASK_BOT_TOKEN из /root/.hermes/tasks/.env (не печатать).

Использование:
  digest.py digest            отправить сводку (так его зовёт таймер)
  digest.py preview           напечатать сводку, ничего не отправлять
  digest.py event "текст"     точечное обновление
  digest.py event --task 1 "текст"
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

# ◻️ todo · ✏️ in progress · ✅ done · ❌ declined/broken/rejected/deleted
STATUS_ORDER = ["in_progress", "todo", "done", "declined"]
STATUS_EMOJI = {"todo": "◻️", "in_progress": "✏️", "done": "✅", "declined": "❌"}
ALIASES = {"pending": "todo", "blocked": "declined", "broken": "declined", "rejected": "declined",
           "deleted": "declined", "cancelled": "declined", "canceled": "declined"}
TAGS = (("&lt;b&gt;", "<b>"), ("&lt;/b&gt;", "</b>"), ("&lt;i&gt;", "<i>"),
        ("&lt;/i&gt;", "</i>"), ("&lt;code&gt;", "<code>"), ("&lt;/code&gt;", "</code>"))


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
            current = {"id": m.group(1), "title": m.group(2).strip(), "status": "todo", "file": ""}
            tasks.append(current)
            continue
        if current is None or not line or line.startswith("#") or line.startswith("<!--"):
            continue
        key, sep, val = line.partition(":")
        if not sep:
            continue
        key, val = key.strip().lower(), val.strip()
        if key == "status":
            val = ALIASES.get(val.lower(), val.lower())
            current["status"] = val if val in STATUS_EMOJI else "todo"
        elif key == "file":
            current["file"] = val
    return tasks


def fmt_task(task: dict) -> str:
    out = f"{STATUS_EMOJI.get(task['status'], '◻️')} <b>#{html.escape(task['id'])}</b> {html.escape(task['title'])}"
    if task["file"]:
        out += f"\n<code>{html.escape(task['file'])}</code>"
    return out


def build_digest(tasks: list[dict]) -> str:
    now = dt.datetime.now(MSK)
    months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря"]
    lines = [f"🗂 <b>Задачи</b> · {now.day} {months[now.month - 1]}", ""]
    for status in STATUS_ORDER:
        for task in (t for t in tasks if t["status"] == status):
            lines += [fmt_task(task), ""]
    if not tasks:
        lines.append("Пусто.")
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
    task = next((t for t in parse_backlog() if t["id"] == task_id), None) if task_id else None
    if task:
        head = f"{STATUS_EMOJI.get(task['status'], '◻️')} <b>#{html.escape(task['id'])}</b> {html.escape(task['title'])}"
    else:
        head = "🗂 <b>Обновление задач</b>"
    body = html.escape(text)
    for escaped, tag in TAGS:
        body = body.replace(escaped, tag)
    return f"{head}\n{body}\n<i>{now:%d.%m %H:%M}</i>"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Доска задач владельца")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("digest", help="отправить сводку в Telegram")
    sub.add_parser("preview", help="напечатать сводку")
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
