# Restricting ONE gateway user's tools or commands

Use when the owner says «добавь этого человека в аллоулист, но пусть у него будет доступ только к X» — a guest/colleague who may talk to the bot but must not get the owner's full tool access.

## What Hermes does and does not enforce

- `allow_from` / `TELEGRAM_ALLOWED_USERS` — **who may talk to the bot at all**. Nothing else.
- `allow_admin_from` + `user_allowed_commands` (under `platforms.<p>.extra`) — gates **slash commands** only. The docs say it plainly: plain chat is unaffected, a non-admin keeps full tool access. Do not sell this as a tool restriction.
- The only enforceable per-user layer is a **`pre_tool_call` shell hook** that reads the session key and returns a block directive. Gateway hooks (`~/.hermes/hooks/`) cannot block — observe only.
- A second profile + second bot token gives real isolation (own skills, memory, toolsets) but needs a token from BotFather; offer it, don't assume it's available.

## Session keys — how to tell who is asking

| Scope | Key |
|---|---|
| DM | `agent:main:<platform>:dm:<chat_id>` — for a private chat `chat_id` **is** the user id |
| Group, per-user (default) | `agent:main:<platform>:group:<chat_id>:<user_id>` |
| Group, shared | `agent:main:<platform>:group:<chat_id>` |
| Channel | `agent:main:<platform>:channel:<chat_id>:<user_id>` |
| Topic in DM | `agent:main:<platform>:dm:<chat_id>:<thread_id>` |

Profiles replace `main` with the profile name. Match on the last two segments after splitting on `:`, never on a substring — a substring match also fires for an unrelated chat id that merely contains the digits.

## Wire-up

1. **Allowlist** the id in `.env` (`TELEGRAM_ALLOWED_USERS`, comma-separated). Append with a regex edit of that one line, back up first, and verify by **count + masked ids** — never `cat` the file.
2. **Script** under `~/.hermes/agent-hooks/` (start from `templates/ssh-only-gate.py`), `chmod +x`. Contract: always print exactly one JSON object, always exit 0; on any exception emit `block` for restricted sessions and `{}` for everyone else.
3. **Register** in `config.yaml`. `hermes config set` cannot express a list of dicts, so append the block at **EOF** (top-level keys are order-independent) rather than restructuring a multi-thousand-line file, then `yaml.safe_load` it to prove validity:

```yaml
hooks_auto_accept: true
hooks:
  pre_tool_call:
    - matcher: ".*"
      command: "/root/.hermes/agent-hooks/ssh-only-gate.py"
      timeout: 10
      fail_closed: true
```

4. **Consent.** An unapproved `(event, command)` pair is *skipped*, not blocked — fail-open and silent. `hooks_auto_accept: true` is honoured at runtime (`_prompt_and_record(accept_hooks=...)`), but `hermes hooks doctor` keeps reporting «not allowlisted» until the pair exists in `~/.hermes/shell-hooks-allowlist.json`. Seed that file directly instead of waiting for a TTY prompt:

```json
{"approvals": [{"event": "pre_tool_call", "command": "/root/.hermes/agent-hooks/gate.py",
  "approved_at": "<ISO-Z>", "script_mtime_at_approval": "<mtime of the script, ISO-Z>"}]}
```

`hermes hooks doctor` must then print all four ticks (executable, allowlisted, unchanged since approval, valid JSON).

5. **Restart is mandatory** — config and hooks are read at startup and SIGHUP does not reload config. The agent **cannot** restart the gateway from inside a session (the tool layer refuses: SIGTERM would kill the restarting command mid-flight). Finish every change, then hand the owner the one-liner:

```
hermes gateway restart
```

with a ready rollback: `cp config.yaml.bak-<date> config.yaml && cp .env.bak-<date> .env && hermes gateway restart`. Say what to check if the bot goes silent.

6. **Verify before the restart, prove after.** `hermes hooks doctor` / `hermes hooks list` before; `journalctl --user -u hermes-gateway | grep "shell hook registered"` after the owner restarts. `hermes hooks test pre_tool_call` substitutes its own `echo` command into the synthetic payload — it proves registration and wire-shape parsing, **not** your policy logic, so test the policy by piping JSON payloads straight into the script.

## Designing an ssh-only policy (the common ask)

Allow the `terminal` tool only, first token in `{ssh, scp, sftp}`, and block:

- `ProxyCommand`, `LocalCommand`, `PermitLocalCommand`, and `-F` — each lets an ssh client run a **local** program from a config/option;
- `-S` — scp/sftp `-S` names the program to run locally;
- `$(...)` and backticks **anywhere in the string** — command substitution executes locally even inside double quotes, so a remote-looking `ssh h "$(id)"` is local code execution;
- standalone shell-operator tokens (`;`, `&&`, `|`, `>`, `(`, …) via `shlex.shlex(punctuation_chars=True)`.

Do **not** substring-scan for `|` or `>`: `ssh h "df -h | tail -1"` is a legitimate remote pipeline. Tokenise, then compare whole tokens. Same reason to block by token rather than regex for flags.

## Rules that keep it honest

- `fail_closed: true` makes every tool call for **all** sessions depend on the script — keep its first action «not a restricted session → print `{}` and return», and wrap the whole body in `try/except` that can still emit JSON.
- Cost is one subprocess per tool call (~80 ms). Fine, but say it out loud if the owner is tuning latency.
- The gate is keyed on the session-key format. An upgrade that reshapes keys silently widens access — put «re-verify the gate after upgrades» in the handover.
- A restricted user still owns whatever the destination gives him: ssh into his own box as root and everything there is his. State that boundary instead of implying the agent sandboxed him.
- On a root host the agent can read and edit the hook itself. Call it protection against a guest's mistakes, never a sandbox.
