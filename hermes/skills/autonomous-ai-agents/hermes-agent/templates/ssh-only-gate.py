#!/usr/bin/env python3
"""pre_tool_call gate: listed gateway users may use ONLY ssh/scp/sftp.

Template — copy to ~/.hermes/agent-hooks/<name>.py, set RESTRICTED_USERS,
chmod +x, then register in config.yaml (see references/per-user-access-control.md).

Restricted identities are matched on the Hermes session key's last two segments:
    agent:main:telegram:dm:<user_id>
    agent:main:telegram:group:<chat_id>:<user_id>

Contract: always print a single JSON object and exit 0. Failure mode is
fail-CLOSED for restricted sessions and a no-op for everyone else, so a crash
can never silently widen the restricted user's access.
"""
import json
import shlex
import sys

RESTRICTED_USERS = {"000000000"}  # <- telegram/discord/... user ids

ALLOWED = {"ssh", "scp", "sftp"}

# Turn an ssh client into a local command runner.
FORBIDDEN_SUBSTRINGS = ("proxycommand", "localcommand", "permitlocalcommand")

# -F: alternate ssh_config (can define ProxyCommand); -S: program for scp/sftp;
# -f/-e/-s: background/escaping/subsystem; lowercased comparison.
FORBIDDEN_EXACT = {"-s", "-f", "-e", "-F"}

SHELL_OPERATORS = {";", ";;", "&", "&&", "|", "||", ">", ">>", "<", "<<",
                   "(", ")", "|&", ">&", "<&"}


def restricted(session_id: str) -> bool:
    if not session_id:
        return False
    return any(p in RESTRICTED_USERS for p in session_id.split(":")[-2:])


def gate(command: str) -> str | None:
    """Return a block reason, or None when the command is acceptable."""
    if not isinstance(command, str) or not command.strip():
        return "empty command"

    low = command.lower()
    for bad in FORBIDDEN_SUBSTRINGS:
        if bad in low:
            return f"forbidden option in ssh command: {bad}"
    # Command substitution runs a LOCAL program even inside double quotes.
    if "$(" in command or "`" in command:
        return "command substitution is not allowed"

    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError as exc:
        return f"unparsable command: {exc}"
    if not tokens:
        return "empty command"

    if any(tok in SHELL_OPERATORS for tok in tokens):
        return "shell operators are not allowed; run one ssh command per call"

    head = tokens[0].strip("'\"")
    if head not in ALLOWED and not (head == "sshpass" and "ssh" in tokens):
        return f"only ssh/scp/sftp are permitted for this account; '{head}' is not"

    for tok in tokens:
        if tok.lower() in FORBIDDEN_EXACT:
            return f"forbidden option: {tok}"
        if tok.startswith("-o") and "proxycommand" in tok.lower():
            return "forbidden option: ProxyCommand"
    return None


def main() -> None:
    restricted_session = False
    try:
        payload = json.load(sys.stdin)
        restricted_session = restricted(payload.get("session_id") or "")
        if not restricted_session:
            print("{}")
            return

        tool = payload.get("tool_name") or ""
        if tool != "terminal":
            print(json.dumps({"action": "block", "message": (
                "This account has ssh-only access: only the terminal tool "
                f"running ssh/scp/sftp, not '{tool}'.")}))
            return

        reason = gate((payload.get("tool_input") or {}).get("command", ""))
        if reason:
            print(json.dumps({"action": "block", "message": "ssh-only access: " + reason}))
        else:
            print("{}")
    except Exception as exc:  # never let a crash widen access
        if restricted_session:
            print(json.dumps({"action": "block",
                              "message": f"ssh-only gate failed closed: {exc}"}))
        else:
            print("{}")


if __name__ == "__main__":
    main()
