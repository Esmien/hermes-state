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

When a message arrives from an id other than the owner's, the ssh-only gate misbehaves (especially after a Hermes upgrade), a Telegram notification never arrived, the owner wants notifier bots landing in specific forum topics, or the owner asks who is allowed to do what.

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
- **Routing a notifier into a forum topic** is a payload field, not a membership: the bot is added to the supergroup once, then every send uses `chat_id=<group id>` + `message_thread_id=<thread_id>`, with `BOT_OWNER` kept as fallback for `sendMessage` when the topic vars are absent. Bot API has no topic-list call — take the `thread_id` from the `t.me/c/...` link or from the agent's `gateway.log` after the owner posts in that topic.
- Prove membership and forum mode per token with `getMe` + `getChat?chat_id=<group>` (print username / `is_forum` only, never the token). "Bot is in the group" is a fact to verify, not to assume from the owner's UI.
- After editing `notifications/.env`, restart **every** unit that reads it: the token is loaded into process memory at start, so a unit restarted before the edit keeps polling `getUpdates` 404 until the next restart.
