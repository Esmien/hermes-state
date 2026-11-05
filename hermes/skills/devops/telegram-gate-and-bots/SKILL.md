---
name: telegram-gate-and-bots
description: "Use when a non-owner writes or the ssh gate is checked."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [devops, telegram, access-control, bots, gateway, identity]
---

# Telegram identity, the ssh-only gate, the notification bots

## When to use

When a message arrives from an id other than the owner's, the ssh-only gate misbehaves (especially after a Hermes upgrade), a Telegram notification never arrived, the owner wants notifier bots landing in specific forum topics, or the owner asks who is allowed to do what. Also load it whenever a notification bot has to reach a supergroup topic or the task board changes chat.

## Who writes

- **214062001 — Владислав**, owner and only operator. Full access, all tools.
- **917728475 — Игорь**. **ssh/scp/sftp only**, enforced fail-closed by the `pre_tool_call` hook `~/.hermes/agent-hooks/ssh-only-gate.py`. He must never learn infrastructure, paths, services, tools, or the owner's identity. A non-ssh request is refused with no explanation of why — not even a hint about what is blocked.

## Hard rules

- **Never assert who is talking from config or memory.** Read `inbound message: platform=… user=… chat=<id>` in `/root/.hermes/logs/gateway.log` before describing an id or an access level; when asked «уверен?», re-read the log instead of repeating the earlier claim.
- **A registered hook is not a working gate.** Hook payloads carry Hermes' internal task id, never the platform session key, so an id-matching hook can silently allow everyone. Prove any restriction against a payload captured from the live gateway and re-verify after Hermes upgrades (the `hermes-agent` skill has the per-user access control reference).
- The gate is **fail-closed**: if it errors, everything including ssh/scp/sftp is refused. Fix the hook, never the policy.

## Notification bots (none implies the others)

- `@esmien_vps_notificator_bot` — alerts (`BOT_TOKEN`), `@esmien_ai_backups_bot` — files/backups (`FILE_BOT_TOKEN`). Both live in `/home/ai_service/notifications/.env` (mode 640 root:ai_service); values never printed, `BOT_OWNER=214062001`.
- Hermes' own messages go through a **third** bot: `TELEGRAM_BOT_TOKEN` in `/root/.hermes/.env` (`@esmien_vps_admin_bot`). «Уведомления приходят» proves only that one.
- One script sends most of it: `/home/ai_service/notifications/monitor.py` (`monitor` / `backup` subcommands, run by `postgres-backup-notify.service`, timer units). It picks `BOT_TOKEN` for monitoring and `FILE_BOT_TOKEN` for file/backup reports, and addresses `BOT_OWNER`. Disk/inode thresholds and backup dir live in the same `.env` — key names only when inspecting.
- **Routing a notifier into a forum topic is a payload field, not a membership.** The bot joins the supergroup once; every send then carries `chat_id=<group id>` + `message_thread_id=<thread_id>`. Never tell the owner a bot can be "added to a topic" — that operation does not exist in Telegram, and he will ask again.
- **Implementation on this host:** `/home/ai_service/notifications/.env` carries `BOT_TARGET_CHAT`/`BOT_TARGET_THREAD` (for `BOT_TOKEN` senders) and `FILE_TARGET_CHAT`/`FILE_TARGET_THREAD` (for `FILE_BOT_TOKEN` senders); `BOT_OWNER` stays as the DM fallback. Empty vars = old behaviour, so the same code serves both layouts.
- **`monitor.py` is one sender of nine.** Patching it alone leaves silent DM senders behind: monitoring also comes from `docker-incident-detector.py`, `litellm-watchdog.py`, `searxng-quality-check.py`, `docker-detector-liveness.sh`, `docker-incident-agent.sh`, `litellm-incident-agent.sh`; backups also from `hermes-history-backup.py`, `secrets-offsite-backup.py`, `webui-data-backup.py`; the task board from `task-board-digest.py` (`OWNER_CHAT_ID` + `TASK_THREAD_ID` in `/etc/vps-infra/task-board.env`). Grep `BOT_OWNER`/`FILE_BOT_TOKEN` across `/usr/local/bin` before declaring the move done.
- **Per-sender scope matters:** alerts in a backup script must pass `token=`/`chat_id=` explicitly, otherwise the call falls through to `BOT_TOKEN` and a backup failure lands in the monitoring topic.
- **A moved task board needs its pointer re-anchored.** `task-board-digest.py` edits a stored `chat_id`+`message_id`; after the chat changes, compare the pointer's chat with the configured one and send a fresh message instead of editing the old DM one.
- **Bot API has no topic-list call** (`getForumTopics`/`getChatTopics` → 404). Take `thread_id` from a `t.me/c/<group>/<n>` link, from `gateway.log` `response ready: … session=…:<chat>:<thread>`, or by having the owner post in the topic and reading `reply_to_id` (= thread id) from `inbound message`.
- **Never block a bot to silence it.** Telegram answers a blocked bot's `sendMessage` with 403 (`bot was blocked by the user`); the alert then disappears with no error anyone reads. Archive + mute only. Before endorsing «отправляю всех ботов в архив и забываю», enumerate what still posts to the DM: every `hermes send -t telegram` caller (boot notify, push-script failures, state-backup, postcheck) addresses the home channel, and `owui-signup-approver.py` has its own token and chat.
- **An interactive command bot breaks in a group for two independent reasons — fix both.** A long-polling bot (`server-monitor-bot.service` → `monitor.py run_bot`) that authorises `chat_id == BOT_OWNER` rejects every group command, because a supergroup id is negative: `bot: команда от -100… отклонена (не владелец)`. Authorise by the sender (`from.id`), never by the chat. A reply sent without `message_thread_id` then lands in General instead of the topic the command came from: carry the incoming `message_thread_id` into the reply — a module-level reply-target set for the duration of one update does it without threading a parameter through every helper. Diagnose «бот молчит в теме» with `journalctl -u <bot>.service | grep -E 'отклонена|409'` before reading the code.
- **One `getUpdates` consumer per token, ever.** A second poller on the same token receives `HTTP 409 Conflict: terminated by other getUpdates request` and updates split or vanish unpredictably; nothing reaches Telegram as an error, the bot simply looks dead. Check for a live unit on that token before starting a drill, a test copy, or a second instance.
- **Not everything should move:** `hermes send`-based notices (boot notify, push-script errors) address the home channel; retarget them only with `--to telegram:<chat>:<thread>` and only when the owner asks.
- Prove membership and forum mode per token with `getMe` + `getChat?chat_id=<group>` (print username / `is_forum` only, never the token). "Bot is in the group" is a fact to verify, not to assume from the owner's UI.
- **Prove routing by sending, not by restart.** These senders read `.env` on every run (oneshot timers, and `task-board-watch` re-reads per call), so no restart is needed; run the script's own send path (`/usr/bin/python3 monitor.py send '…'`) and check the `sent … chat=… thread=…` line. Use the **system** `/usr/bin/python3` — the Hermes tool interpreter lacks these scripts' dependencies.
- **Report layout he expects:** verdict first, then a labelled list of what now goes where, then what changed technically. When the owner must act in the Telegram UI, end with a numbered «что делать тебе» list of 1–3 steps and nothing else — mechanism first produced «Не понял ничего. Мне что делать?».
- If backup dumps and the offsite secrets key now land in a group topic, say so plainly: everyone added to that group sees them.
