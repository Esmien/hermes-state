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

A message arrives from an id other than the owner's, the ssh-only gate misbehaves (especially after a Hermes upgrade), a Telegram notification never arrived, or the owner asks who is allowed to do what.

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
- Health check: `scripts/check-notification-bots.py` in the `ai-stack` skill — `getMe` per token, usernames only, plus the `file_id` restore registry.
- After editing `notifications/.env`, restart **every** unit that reads it: the token is loaded into process memory at start, so a unit restarted before the edit keeps polling `getUpdates` 404 until the next restart.
