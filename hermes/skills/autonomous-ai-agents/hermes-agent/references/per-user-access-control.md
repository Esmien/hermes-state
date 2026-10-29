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

**The `pre_tool_call` payload does not contain that key.** Its fields are exactly `hook_event_name, tool_name, tool_input, session_id, cwd, profile, extra` — no `chat_id`, no `user_id`, no `session_key`, and `extra` carries only task/turn/api ids. `session_id` is Hermes' **internal task id** (`20261029_143418_5743154a`), and it can arrive **empty** on nested calls (`execute_code` invoking `terminal`). So a gate that splits `session_id` and compares the segments with a restricted user id never matches: it prints `{}` for everyone, the restricted account gets full root, and every health check still looks green (`shell hook registered`, `hooks doctor` all ticks). If you inherit such a gate, treat the restriction as absent until proven otherwise.

## Resolve identity through the state store instead

`~/.hermes/state.db` → table `sessions` maps the internal id to the platform identity:

```
sessions(id, source, created_source, user_id, session_key, chat_id, chat_type, thread_id, display_name, ...)
```

```python
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
row = con.execute("select user_id, chat_id from sessions where id=?", (session_id,)).fetchone()
# row is (user_id, chat_id); for a DM both equal the sender's id; NULL for cron/CLI sessions
```

Keep the session-key branch as a fast path for payloads that do carry a key, and fall back to this lookup — the shipped template does both. Access notes:

- No `sqlite3` CLI on this host: query from `python3 -c` or `execute_code`, never a shell heredoc (the command guards intercept script bodies) and never the live `state.db` through a guard-scanned heredoc.
- Copy `state.db` to a scratch path (`~/.hermes/cache/scratch/`) before ad-hoc inspection; the live file is open in the gateway process.
- The hook must open it read-only (`mode=ro`) and must not crash when the file or the profile path is missing — resolve the profile home from `$HERMES_HOME`, not a hardcoded `~/.hermes`.
- Accept that an unreadable DB degrades the gate to a no-op; the honest mitigation is verifying from the restricted account after every change, not pretending the hook fails closed on identity.

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

7. **Capture the payload the gateway actually sends, then test against it.** Registration + a hand-written payload with a correct `session_id` prove nothing about identity. Instrument, fire one tool call, read back, revert:

```python
# op #1 in main(), before any policy logic; remove it in the same session
with open("/tmp/gate-payload.jsonl", "a") as f:
    f.write(json.dumps(payload, default=str)[:4000] + "\n")
```

   Then call one `terminal` tool and read the tail. Confirm three things: which field carries identity (here: none), whether `session_id` is populated, and that the resolved id is the *sender's*, not the owner's. Final proof is a **real message from the restricted account** being refused — a test you cannot run from the owner's session, so hand it to the owner as the last check.

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
- The gate is keyed on `session_id → sessions.user_id` resolution. Any change to the payload shape, the `sessions` schema, or the profile path silently widens access — put «re-verify the gate from the restricted account after upgrades» in the handover.
- Never describe a user's access level from `home_channel`, memory, or an earlier answer. The chat in play may be the restricted account while `home_channel` names the owner; read the `inbound message: … chat=<id>` line in `~/.hermes/logs/gateway.log` first.
- A restricted user still owns whatever the destination gives him: ssh into his own box as root and everything there is his. State that boundary instead of implying the agent sandboxed him.
- On a root host the agent can read and edit the hook itself. Call it protection against a guest's mistakes, never a sandbox.
