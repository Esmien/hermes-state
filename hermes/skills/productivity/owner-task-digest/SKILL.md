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

## Граница харнесс / инфра (правило владельца)

**Харнесс — описания и инструкции. Инфра — всё, что работает на сервере.**

- харнесс: доска-документ `/root/.hermes/tasks/backlog.md`, этот скилл
- инфра: скрипты `/usr/local/bin/task-board-{digest,watch}.py` (источник `vps-infra/assets/host/bin/`), юниты `hermes-task-{digest.*,board-watch.*}` (источник `vps-infra/assets/host/systemd/`), токен `/etc/vps-infra/task-board.env` (600, в офсайт-архиве секретов), рантайм-состояние `/var/lib/hermes-task-board/`

Скрипты и юниты зарегистрированы в `install.py` (`CORE_TIMERS`, `HERMES_UNITS`, `HOST_BIN_SCRIPTS`). Не класть работающее в `/root/.hermes` и не держать описания задач в `vps-infra`.

## Where things live

- Board (harness document): **`/root/.hermes/tasks/backlog.md`** — the single source of truth.
- Sender (infra): `/usr/local/bin/task-board-digest.py` — `digest` (send a NEW message; the Monday timer), `refresh` (edit the live board in place), `preview`.
- **One live message, edited in place.** Task work never sends new messages: status change → `refresh` → `editMessageText` on the stored message id (`/var/lib/hermes-task-board/message.json`). A new message appears only on the Monday digest, and that message becomes the live board. If the owner deleted the message (`message to edit not found` / `message can't be edited`) the sender falls back to a new message and re-points the pointer; `message is not modified` counts as success.
- **Safety net (infra):** `/usr/local/bin/task-board-watch.py` + `hermes-task-board-watch.{path,service}` — watches `backlog.md`, compares with `/var/lib/hermes-task-board/state.json` and calls the same `refresh`, so a forgotten manual refresh still lands. The first run only writes the baseline.
- Bot: `@esmien_agent_todo_bot`, token in `/etc/vps-infra/task-board.env` (600, offsite-archived). **Never print it.**
- Schedule: systemd `hermes-task-digest.timer` — Monday 05:30 UTC = **08:30 MSK**, `Persistent=true`.
- **Ownership:** the board document and this skill are harness; the sender, the watcher, their units and the token are infra. Do not duplicate them across the boundary, and do not park working daemons in `/root/.hermes`.

## Board format (parse contract — digest.py depends on it)

```
## #1 Краткая суть задачи
status: todo | in_progress | done | declined
file: tasks/docs/modules-plan.md
```

Статусов ровно четыре: `◻️` todo, `✏️` in_progress, `✅` done, `❌` declined (broken/rejected/deleted — тот же `declined`; legacy `pending`/`blocked` парсер понимает, но писать их не надо). **Ни приоритетов, ни прогресс-процентов, ни дат на доске** — владелец потребовал их убрать; не возвращать ни в файл, ни в сообщение.

`file:` — это и есть та самая ссылка внизу сообщения: путь к документу или исходнику, который держит детали и который владелец назовёт, когда захочет контекст. Путь указывается от `~/.hermes/` (`tasks/docs/...`), потому что подробные описания задач живут в харнессе. Никогда не указывать туда сообщение чата и никогда не путь внутри `vps-infra` — там остаются только доки про саму инфраструктуру.

Правка блока → сразу событие. Не перенумеровывать существующие задачи: id живут в чате.

## Protocol — every state change notifies

1. Edit `backlog.md` (status, title, file).
2. Immediately: `python3 /usr/local/bin/task-board-digest.py refresh` — edits the live board message. Never `sendMessage` for a task change and never write a separate per-task message.
3. New task: append a block, then `refresh`.
4. Closing: `status: done` + `refresh`.

Silent board edits are the failure mode: the owner asked for **every** change to show up on the board, not only the Monday brief. Manual `refresh` and the path-unit watcher are the same call, so there is no way to "forget": the watcher fires on any `backlog.md` write. Old and irrelevant messages are the owner's to delete — never try to clean the chat yourself.

Ответ `{"action": "unchanged"}` у `refresh` — не сбой: watcher успел обновить карточку первым и сравнил с уже сохранённым состоянием. Проверять надо содержимое `/var/lib/hermes-task-board/state.json` (есть ли новый `#id`/путь), а не код возврата.

**Сетевой сбой — повторить, а не объявлять поломку.** `refresh` может упасть с `urllib.error.URLError: Connection reset by peer`, пока api.telegram.org жив: один повтор проходит, и второй ответ часто сразу `unchanged`. Владельцу докладывать по состоянию в `state.json` (статус конкретной задачи), а не по коду возврата скрипта.

Правка доски в `~/.hermes/tasks` требует снапшота в тот же ход (см. ниже): без него репо расходится с хостом.

**Правка доски и новые планы не попадают в снапшот сами.** `hermes-state-watch` следит за `skills/`, `memories/`, `plugins/`, `hooks/`, `scripts/`, `config.yaml`, `SOUL.md` — каталога `$HERMES_HOME/tasks` в списке нет, в репо он приезжает только прогоном `/usr/local/bin/hermes-state-backup.sh` (или ночным `hermes-state-backup.timer`). Правило владельца «репо = живой хост» значит: после нового дока в `tasks/docs/` и записи в доску сразу прогнать бэкап (он же коммит + push) и подтвердить доставку строкой `✓ pushed <sha>`.

## Checks

- Format/dry: `python3 /usr/local/bin/task-board-digest.py preview`
- Send now (new message): `python3 /usr/local/bin/task-board-digest.py digest`
- Edit in place: `python3 /usr/local/bin/task-board-digest.py refresh`
- Timer: `systemctl list-timers hermes-task-digest.timer --no-pager`
- Last run: `systemctl show hermes-task-digest.service -p Result -p ExecMainStatus`

## Формат сообщений — лаконично, без наворотов

Владелец забраковал богатое оформление: прогресс-бары, приоритеты, группы с шапками и счётчики — *«всё шумное, лаконично и понятно, без наворотов»*. Остаётся только это:

- шапка: `🗂 <b>Задачи</b> · 5 ноября` — и всё;
- один блок на задачу: эмодзи статуса + `#id` + одна строка сути, следующей строкой путь из `file:` в `<code>`;
- больше ничего: ни секций, ни итогов, ни процентов, ни «фокуса», ни разделителей.

Событий-сообщений больше нет: любое изменение — это `refresh`, то есть правка той же карточки на месте. Не пытаться «дописать пояснение» отдельным сообщением — пояснение живёт в подробном доке по ссылке `file:`.

`parse_mode=HTML` + `disable_web_page_preview=true`; экранировать текст через `html.escape` и возвращать только `b`/`i`/`code` — Telegram молча отклоняет сообщение с сырыми `<`/`&`, и тишина выглядит как «таймер не сработал».

После правки формата отправлять живое сообщение: владелец обсуждает дизайн по артефакту. Доставку подтверждать по журналу (`journalctl -u hermes-task-digest.service -o cat | tail -3` → `{"ok": true, "message_id": N}`), а не по `Result=success`.

## Стиль

Доска, не проза: эмодзи статуса, одна строка сути, путь к файлу. Без советов, без подгоняния, без стриков — владелец хочет спокойный темп и прозрачность состояний, поэтому сообщение сообщает состояние и останавливается.

**Доска живёт только в `backlog.md`.** Список todo-инструмента привязан к сессии и в новой сессии пуст — искать там задачи бессмысленно. Если владелец говорит «вот первая таска» и её нет на доске, смотреть `~/.hermes/tasks/docs/*.md` (планы и концепты переехали в харнесс) и спрашивать одной строкой, а не засевать доску догадками.
