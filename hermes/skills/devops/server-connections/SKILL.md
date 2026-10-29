---
name: server-connections
description: "Use when adding, listing or using saved server logins."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [ssh, credentials, address-book, restricted-user]
---

# Saved server connections (`conn`)

## When to Use

The user wants to add a server to the book («name / ip / user / pass»), list or delete saved servers, or act on one of them («подключись к box, посмотри диск»). Also load it when a restricted (ssh-only) account asks for anything that needs a remote host.

The host keeps a root-only address book so the SSH-restricted Telegram account can reach its own servers without an operator typing credentials each time.

- Store: `/var/lib/hermes-connections/connections.json` (dir `0700`, file `0600`, root).
- CLI: `/usr/local/bin/conn` — list, add, del, ssh, scp, ping.
- The store is **outside** `~/.hermes`, so it never lands in the state backup repo.

## Talking to the user

He phrases it as «добавь сервер: name / ip / user / pass». Map that onto:

```bash
conn add <name> <host> <user> '<password>' [--port N]
conn ping <name>                      # prove it works before reporting back
conn ssh <name> -- <remote command>   # the normal way to act
conn list                             # safe to show: passwords are masked
conn del <name>
```

Rules:

- **Never echo the password back**, not even masked beyond what `conn list` prints. Report `added: name -> user@host:port` and the `conn ping` result.
- **Always `conn ping` after `add`** — it is the only proof the credentials and port are right.
- **Always go through `conn`**, never paste credentials into a bare `ssh`/`sshpass` call: the store is the single place to rotate them.
- One remote command per call. A pipe inside the remote command is fine (`conn ssh box -- 'df -h | tail -1'`); a local `;`, `&&`, `$(...)` or backtick is not — the `ssh-only-gate.py` hook blocks those, by design.
- Names: letters, digits, `-`, `_`. Keep them short — the user says «подключись к <name>».
- Deleting a server is `conn del <name>`; ask once before doing it if the name was ambiguous.

## What the gate allows

The restricted account (Telegram ID 917728475) may run exactly `ssh` and `conn <list|ls|add|del|rm|ssh|ping|help>`. `scp`, `sftp`, ssh port forwarding (`-L/-R/-D/-W`), `-A`, `-i`, `-F`, `-o *Forward*`/`ProxyCommand`/`LocalCommand` are deliberately blocked: scp with a local source exfiltrates files off this box, and a tunnel bypasses the tool gate entirely. Every other tool call — `read_file`, `write_file`, `patch`, web, cron, `clarify`, `docker`, anything else — is blocked by `/root/.hermes/agent-hooks/ssh-only-gate.py`. That hook fails closed, so a broken gate denies rather than permits.

**The hook resolves the owner from the internal session id**, not from the payload's `session_id` shape: `hooks.pre_tool_call` payloads carry `20261029_143418_5743154a`-style ids, so the gate looks the id up in `~/.hermes/state.db` (`sessions.id` → `session_key`/`user_id`). Matching the platform key directly in the payload silently never fires — that mistake left the gate a no-op once.

## Pitfalls

- **`sshpass -p <pass>` puts the password in `ps`.** `conn` uses `SSHPASS` + `sshpass -e`; keep it that way if you ever touch the script.
- **Password in the chat transcript is unavoidable** at `conn add` time: the user types it, the model passes it as an argv element. Say so once if he asks about security, and offer SSH keys (`ssh-keygen` + `ssh-copy-id` over `conn ssh`) as the stronger option.
- **Entries are per-host, not per-purpose**: `conn ssh box -- 'sudo ...'` runs as the stored user. If a host needs two accounts, store two names (`box`, `box-root`).
- **A corrupt store** makes every `conn` call fail loudly with the JSON error; fix it with `python3 -m json.tool` rather than re-adding entries blindly — a bad write loses all saved servers.
- **The hook only fires once the gateway has been restarted** after the `hooks:` block was added to `config.yaml`; `hermes hooks list` must show `✓ allowed`.
