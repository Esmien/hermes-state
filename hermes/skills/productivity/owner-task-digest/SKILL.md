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
- **Safety net:** `/root/.hermes/tasks/watchdog.py` + `hermes-task-board-watch.{path,service}` — watches `backlog.md` and sends the transition event itself (`✏️ в работе → ✅ закрыта`, «новая задача на доске»), so a forgotten manual notification still reaches the owner. State: `/var/lib/hermes-task-board/state.json`; the first run only writes the baseline.
- Bot: `@esmien_agent_todo_bot`, token in `/root/.hermes/tasks/.env` (mode 600, backed up offsite). **Never print it.**
- Schedule: systemd `hermes-task-digest.timer` — Monday 05:30 UTC = **08:30 MSK**, `Persistent=true`.
- Both are in the recovery chain: `tasks/` (minus `.env`) → `hermes-state` repo; units → `vps-infra/assets/host/systemd/`.

## Board format (parse contract — digest.py depends on it)

```
## #1 Краткая суть задачи
status: todo | in_progress | done | declined
file: vps-infra/docs/modules-plan.md
```

Статусов ровно четыре: `◻️` todo, `✏️` in_progress, `✅` done, `❌` declined (broken/rejected/deleted — тот же `declined`; legacy `pending`/`blocked` парсер понимает, но писать их не надо). **Ни приоритетов, ни прогресс-процентов, ни дат на доске** — владелец потребовал их убрать; не возвращать ни в файл, ни в сообщение.

`file:` — это и есть та самая ссылка внизу сообщения: путь к документу или исходнику, который держит детали и который владелец назовёт, когда захочет контекст. Никогда не указывать туда сообщение чата.

Правка блока → сразу событие. Не перенумеровывать существующие задачи: id живут в чате.

## Protocol — every state change notifies

1. Edit `backlog.md` (status, title, file).
2. Immediately: `python3 /root/.hermes/tasks/digest.py event --task N "что изменилось и почему"`.
3. New task: append a block, then `event --task N "новая задача: ..."`.
4. Closing: `status: done` + `event --task N "закрыта: что сделано"`.

Silent board edits are the failure mode: the owner asked for **every** change in Telegram, not only the Monday brief. One digest a week plus silence in between reads as a dead project. Manual `event` is the primary path (it carries the *why*); the path-unit watcher only guarantees that a forgotten one still arrives, and its message is the bare transition — never rely on it instead of a real update.

After any status change check the effect: `journalctl -u hermes-task-board-watch.service -o cat -n 3` → `events sent: N`.

## Checks

- Format/dry: `python3 /root/.hermes/tasks/digest.py preview`
- Send now: `python3 /root/.hermes/tasks/digest.py digest`
- Timer: `systemctl list-timers hermes-task-digest.timer --no-pager`
- Last run: `systemctl show hermes-task-digest.service -p Result -p ExecMainStatus`

## Формат сообщений — лаконично, без наворотов

Владелец забраковал богатое оформление: прогресс-бары, приоритеты, группы с шапками и счётчики — *«всё шумное, лаконично и понятно, без наворотов»*. Остаётся только это:

- шапка: `🗂 <b>Задачи</b> · 5 ноября` — и всё;
- один блок на задачу: эмодзи статуса + `#id` + одна строка сути, следующей строкой путь из `file:` в `<code>`;
- больше ничего: ни секций, ни итогов, ни процентов, ни «фокуса», ни разделителей.

Событие такое же короткое: эмодзи статуса + `#id` + заголовок, одна строка «что изменилось», время. Плейн-текст лучше структуры, когда сообщение в две строки.

`parse_mode=HTML` + `disable_web_page_preview=true`; экранировать текст через `html.escape` и возвращать только `b`/`i`/`code` — Telegram молча отклоняет сообщение с сырыми `<`/`&`, и тишина выглядит как «таймер не сработал».

После правки формата отправлять живое сообщение: владелец обсуждает дизайн по артефакту. Доставку подтверждать по журналу (`journalctl -u hermes-task-digest.service -o cat | tail -3` → `{"ok": true, "message_id": N}`), а не по `Result=success`.

## Стиль

Доска, не проза: эмодзи статуса, одна строка сути, путь к файлу. Без советов, без подгоняния, без стриков — владелец хочет спокойный темп и прозрачность состояний, поэтому сообщение сообщает состояние и останавливается.

**Доска живёт только в `backlog.md`.** Список todo-инструмента привязан к сессии и в новой сессии пуст — искать там задачи бессмысленно. Если владелец говорит «вот первая таска» и её нет на доске, смотреть описания в `/root/vps-infra/docs/*.md` (там живут планы и концепты) и спрашивать одной строкой, а не засевать доску догадками.
