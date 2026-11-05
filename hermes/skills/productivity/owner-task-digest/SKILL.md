---
name: owner-task-digest
description: "Use when updating the owner's task board or its digest."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [productivity, tasks, telegram, digest, reporting]
---

# Owner task board and weekly digest

## When to use

A task is added, started, blocked, progressed or closed for the owner — or the weekly digest must be checked, resent or rescheduled.

## Where things live

- Board: **`/root/.hermes/tasks/backlog.md`** — the single source of truth.
- Sender: `/root/.hermes/tasks/digest.py` (`digest` | `preview` | `event "text" [--task N]`).
- Bot: `@esmien_agent_todo_bot`, token in `/root/.hermes/tasks/.env` (mode 600, backed up offsite). **Never print it.**
- Schedule: systemd `hermes-task-digest.timer` — Monday 05:30 UTC = **08:30 MSK**, `Persistent=true`.
- Both are in the recovery chain: `tasks/` (minus `.env`) → `hermes-state` repo; units → `vps-infra/assets/host/systemd/`.

## Board format (parse contract — digest.py depends on it)

```
## #1 Short title
status: pending | in_progress | blocked | done
priority: high | normal | low
progress: 0..100
updated: YYYY-MM-DD
note: one line, no line breaks
```

Edit the block, `updated:` to today, then send the event. Never renumber existing tasks — ids are referenced in chat.

## Protocol — every state change notifies

1. Edit `backlog.md` (status/priority/progress/note/updated).
2. Immediately: `python3 /root/.hermes/tasks/digest.py event --task N "что изменилось и почему"`.
3. New task: append a block, then `event --task N "новая задача: ..."`.
4. Closing: `status: done` + `progress: 100` + `event --task N "закрыта: что сделано"`.

Silent board edits are the failure mode: the owner asked for **every** change in Telegram, not only the Monday brief. One digest a week plus silence in between reads as a dead project.

## Checks

- Format/dry: `python3 /root/.hermes/tasks/digest.py preview`
- Send now: `python3 /root/.hermes/tasks/digest.py digest`
- Timer: `systemctl list-timers hermes-task-digest.timer --no-pager`
- Last run: `systemctl show hermes-task-digest.service -p Result -p ExecMainStatus`

## Формат сообщений — визуальный артефакт, а не список строк

Владелец оценивает дайджест глазами в Telegram; вариант «аккуратный текст строками» он забраковал. Обязательный минимум:

- `parse_mode=HTML`, `disable_web_page_preview=true` — Markdown не использовать;
- шапка `🗂 ПЛАН НЕДЕЛИ` + дата и счётчики, разделитель `──────────────`;
- группы по статусам с эмодзи: 🔥 в работе, 🧱 заблокировано, 🟡 в очереди, ✅ закрыто;
- у каждой задачи прогресс-бар `▰▰▰▰▱▱▱▱▱▱ 35%` и приоритет (🔥 высокий / ⚪ обычный / 🧊 низкий);
- пояснение задачи — в `<blockquote>`, отдельной строкой, а не курсивом в хвосте заголовка;
- подвал: `🎯 Фокус` (главная задача), `📊 Итог` с общим баром, время МСК;
- событие по одной задаче — карточка: статус-чип, бар, текст в цитате, время.

Экранировать пользовательский текст через `html.escape`, затем возвращать только разрешённые теги (`b`, `i`, `code`): Telegram отклоняет сообщение с «сырыми» `<`/`&`, и не приходит вовсе — молчание выглядит как «таймер не сработал».

После правки формата отправлять живое сообщение и показывать его: дизайн владелец обсуждает по артефакту, а не по описанию. Доставку подтверждать по журналу юнита (`journalctl -u hermes-task-digest.service -o cat | tail -3` → `{"ok": true, "message_id": N}`), а не по `Result=success`.

## Стиль

Board, not prose: groups by status, progress, the note as the one-line «why». No advice, no nagging, no streaks — the owner wants steady progress in a calm tempo and transparency of states, so the digest reports state and stops there.

**Доска живёт только в `backlog.md`.** Список todo-инструмента привязан к сессии и в новой сессии пуст — искать там задачи бессмысленно. Если владелец говорит «вот первая таска» и её нет на доске, смотреть описания в `/root/vps-infra/docs/*.md` (там живут планы и концепты) и спрашивать одной строкой, а не засевать доску догадками.
