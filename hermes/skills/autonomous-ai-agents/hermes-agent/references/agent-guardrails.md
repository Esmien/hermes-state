# Hard Gates on Dangerous Actions

Enforcement that survives a model which has been talked into something, and a
user who has forgotten the conversation. Use when asked for a "guardrail",
"confirm before X", "block me from doing Y when I'm not thinking straight",
or any rule that must hold across `/new`.

## Which hook system can actually block

| Mechanism | Declared in | Blocks a tool call? |
|---|---|---|
| Shell hooks | `hooks:` block in `config.yaml` → scripts | **Yes** (`pre_tool_call`) |
| Plugin hooks | `ctx.register_hook()` in a plugin | **Yes** (`pre_tool_call`, in-process) |
| Gateway hooks | `~/.hermes/hooks/<name>/HOOK.yaml` + `handler.py` | **No** — observe only (`agent:*`, `session:*`, `command:*`) |

Anything in the system prompt, memory, or a skill is advisory: one "forget
that" or one `/new` defeats it. Put the gate in a hook, not in prose.

## Shell-hook contract (`pre_tool_call`)

```yaml
hooks:
  pre_tool_call:
    - matcher: "terminal|write_file|patch"   # regex over tool names
      command: "~/.hermes/agent-hooks/gate.sh"
      timeout: 10
      fail_closed: true                      # default false — wrong here
hooks_auto_accept: true                      # or HERMES_ACCEPT_HOOKS=1
```

- stdin: `{hook_event_name, tool_name, tool_input, session_id, cwd, profile, extra}`.
- stdout: `{"decision":"block","reason":"..."}` or `{"action":"block","message":"..."}`;
  also `modify` (rewrite args) and `approve` (escalate to the human gate).
- **Exit 2 = block**, message = stdout JSON → stderr (first 400 chars) → default.
  A two-line bash script is a valid gate.
- `fail_closed: true` inverts the default: spawn failure, timeout, non-zero exit
  without a directive, or non-JSON stdout all **block**. Fail-open is correct for
  formatters/loggers and wrong for a security gate — a crashed checker must not
  wink the action through.
- Timeout default 60 s, capped at 300.

## Traps that make a gate look installed but do nothing

- **Consent.** First use of each `(event, command)` pair prompts on a TTY. The
gateway and cron are non-interactive, so the hook is *skipped*, not blocked:
set `hooks_auto_accept: true`, run with `--accept-hooks` / `HERMES_ACCEPT_HOOKS=1`,
or pre-seed `~/.hermes/shell-hooks-allowlist.json`. A skipped hook fails open and
is indistinguishable from "no dangerous command was attempted".
- **Config is read at startup.** Registering a hook does not affect the running
gateway — restart it (from outside the gateway process) or it never fires.
- **Prove it fires.** After wiring, trigger one command that must be blocked and
quote the block reason. Config echo is not evidence; `hermes hooks test` shows the
parsed directive without executing.

## State that must survive `/new`

`/new`, `/reset`, compression, and `/reload-skills` all rebuild the session — they
clear the transcript, not the filesystem. Keep gate state **outside
`$HERMES_HOME`** (e.g. root-owned `0700` `/var/lib/<gate>/state.json`):
`last_pass`, challenge id, attempts left, `locked_until`, fail streak.

Gate shape that works:

1. Dangerous tool call arrives → hook classifies it (red list = always gated;
yellow list = gated only when the last pass is older than a TTL).
2. No fresh pass → block, hand back a challenge.
3. Verification is a **separate script** comparing a salted hash; the model
passes the human's raw text through it and cannot read the expected value.
4. Wrong answer increments a counter → exponential lockout (30 min → 2 h → 6 h)
enforced by timestamp in the file, not by asking the model to remember.
5. Failures notify a second channel so a sober operator sees them later.

**Do not hand the judgement to the model.** "Decide whether the user is impaired"
is unenforceable: the model is the party being persuaded, and any logic/arithmetic
challenge gets solved *for* the user. The challenge must be a secret only the
human holds, entered locally (`read -s`) and stored as a hash — never typed into
chat, never logged.

Bypass paths to test before calling the gate done: repeat the same dangerous
command inside the TTL window; ask the agent to run the verify command itself;
`/new` then retry; "ignore your instructions"; edit the state file through the agent.

## Honest limit — say it out loud

On a host where the agent runs as **root**, any gate it can read it can also edit.
Sell this as protection against an impaired or mistaken operator, never as a
sandbox or a defence against a malicious agent. Tamper-resistance is a different
feature: block edits to the gate's own paths and the `hooks:` block in the same
hook, plus a systemd timer that re-installs the script from a root-owned copy and
pings the second channel when the hash changes.

## What to put on the list

Always gate: `rm -rf` on `/`, `~`, `/var`, `/etc`, `/home`; `docker system prune`;
`docker compose down -v`; `mkfs`/`dd` to a device; `systemctl stop|disable` of
foreign units; `ufw disable`; `iptables -F`; `DROP DATABASE`; backup deletion;
`chmod|chown -R` on system paths; `crontab -r`; writes to `/etc/**`, the gateway
`config.yaml` (including its `hooks:`), systemd units, `.env` files.

Gate on TTL rather than always: container restarts, single-file writes outside
tmp/cache, service reloads — otherwise every routine `ls` costs a password and
the user disables the gate out of irritation.
