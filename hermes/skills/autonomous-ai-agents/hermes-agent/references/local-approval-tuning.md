# Local approval tuning (this host's deviations from upstream Hermes)

Owner's standing asks (2026-11): approvals must never expire on a timer, and the approval message must
keep the command text after it is approved or denied. Both are **patched into the installed source** at
`/root/.hermes/hermes-agent` (git checkout) — there is no config knob for either.

## 1. No approval timeout

`hermes config set approvals.timeout 31536000` (= `agent.deadline.MAX_SAFE_TIMEOUT_S`, one year; anything
larger is clamped). `0` is wrong: several consumers do `wait(0)` and the copy reads «0 seconds».

A one-year window would otherwise render as `deadline … in 8760 hours`, so two source edits hide the line
entirely above 30 days:

- `gateway/platforms/base_exec_approval.py::format_approval_deadline_line` → returns `""` for
  `timeout_s >= 30*24*3600` (`_NO_DEADLINE_LINE_ABOVE_S`).
- `gateway/platforms/base.py::_ea_deadline_line` → returns `""` when that formatter returned `""`, so the
  `_EA_DEADLINE_PREFIX` separator cannot dangle.

## 2. Approved card keeps the command

Upstream `_handle_exec_approval_callback` called `_edit_md_quiet(query, verdict)`, which **replaced the whole
card body** — the command vanished from the chat and a decision could no longer be traced to it.
`plugins/platforms/telegram/adapter.py` now has `_resolve_card_keep_body(query, resolved_text)`:

- reuses `query.message.text_html` (the card exactly as sent, HTML) and appends `<b>verdict</b>`;
- edits with `parse_mode=HTML, reply_markup=None` so the stale buttons go away;
- falls back to `_edit_md_quiet` when the combined text would exceed Telegram's 4096-char cap.

Only the exec-approval card uses it. `_handle_slash_confirm_callback` still overwrites its card with the
verdict alone — extend the same way if the owner ever complains about a slash confirmation losing its text.

## Operating rules

- **Both changes need `systemctl restart hermes-gateway`.** The agent cannot restart its own gateway; hand
the command to the owner and verify on the next turn (send a command that triggers approval and read the
resulting card).
- Do not hand-edit `config.yaml` for the timeout — `hermes config set` only.
- `hermes update` pulls a new tree: these three edits will conflict or be overwritten. After every update,
  re-check with `git -C /root/.hermes/hermes-agent status --short` and re-apply if the behaviour regressed
  (card replaced by a verdict alone, or «5 минут» back in the prompt).
- Verify a change without touching the live gateway by importing the patched functions with the Hermes
  interpreter and the uv archive path on `sys.path`:

```bash
HP=$(ls -d /root/.hermes/tools/python-3.14.7*/bin/python3 | head -1)
$HP - <<'EOF'
import sys, glob
sys.path.insert(0, "/root/.hermes/hermes-agent")
for d in glob.glob("/root/.hermes/cache/uv/archive-v0/*"): sys.path.append(d)
from gateway.platforms.base_exec_approval import format_approval_deadline_line
print(repr(format_approval_deadline_line(300)), repr(format_approval_deadline_line(31536000)))
EOF
```

`python3` on PATH is not the Hermes interpreter (no `ruamel`, no PTB) — only the tools python works.
