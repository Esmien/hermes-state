#!/usr/bin/env python3
"""pre_tool_call gate: a specific Telegram user may use ONLY ssh/scp/sftp.

Restricted identities are resolved from the internal session id via
~/.hermes/state.db (sessions.session_key / user_id), e.g.
    agent:main:telegram:dm:<user_id>          (DM, chat_id == user id)
    agent:main:telegram:group:<chat>:<user_id> (per-user group session)

Everything else (any other sender, CLI, cron) is untouched.

Contract: always print a single JSON object and exit 0.
Failure mode is fail-CLOSED for restricted sessions and no-op for everyone
else, so a crash can never silently widen the restricted user's access.
"""
import json
import shlex
import sqlite3
import sys

RESTRICTED_USERS = {"917728475"}

# Commands the restricted user is allowed to run, by first token.
ALLOWED = {"ssh", "conn"}

# Subcommands of `conn` (the address book) the restricted account may use.
CONN_SUBCOMMANDS = {"list", "ls", "add", "del", "rm", "ssh", "ping", "help", "--help"}

# Substrings that turn an ssh client into a local command runner.
FORBIDDEN_SUBSTRINGS = (
    "proxycommand",
    "localcommand",
    "permitlocalcommand",
    "proxyjump",  # allowed in principle, but only in the plain -J form
)

# Options that pull in a local program, config, key, agent or a tunnel.
#   -L/-R/-D/-W: port and SOCKS forwarding = a way around the tool gate entirely
#   -A: forward the host's ssh-agent;  -i: use a local key file
#   -F: alternate ssh_config (can define ProxyCommand)
FORBIDDEN_EXACT = {"-s", "-f", "-e", "-F", "-A", "-a", "-i", "-L", "-R", "-D", "-W", "-w", "-N", "-S"}
FORBIDDEN_PREFIXES = ("-L", "-R", "-D", "-W")  # -L8080:host:80 form
# `-o KEY=VALUE` is an allowlist, not a blacklist: OpenSSH keeps growing options
# that run a LOCAL program (ProxyCommand, LocalCommand, KnownHostsCommand, …) and a
# blacklist is always one release behind.
ALLOWED_O_KEYS = (
    "stricthostkeychecking", "user", "port", "connecttimeout", "serveraliveinterval",
    "serveralivecountmax", "compression", "loglevel", "batchmode", "identitiesonly",
    "preferredauthentications", "numberofpasswordprompts", "requesttty",
    "tcpkeepalive", "setenv", "ciphers", "macs", "kexalgorithms", "hostkeyalgorithms",
    "pubkeyacceptedalgorithms", "updatehostkeys", "hashknownhosts",
)

OPERATOR_CHARS = ";&|<>()`$\n\r"
# Tokens that mean the local shell would chain/redirect something.
SHELL_OPERATORS = {";", ";;", "&", "&&", "|", "||", ">", ">>", "<", "<<",
                   "(", ")", "|&", ">&", "<&"}



STATE_DB = "/root/.hermes/state.db"
ROUTING_JSON = "/root/.hermes/sessions/sessions.json"


def _key_is_restricted(key: str, uid: str = "") -> bool:
    if uid and uid in RESTRICTED_USERS:
        return True
    return any(part in RESTRICTED_USERS for part in (key or "").split(":"))


def restricted(session_id: str) -> bool:
    """Resolve the gateway session key for an internal session id.

    The hook payload carries the INTERNAL id (e.g. 20261029_143418_5743154a),
    not the platform key, so the owner must be looked up in state.db.
    """
    if not session_id:
        return False
    resolved = False
    try:
        con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=3)
        try:
            row = con.execute(
                "select session_key, user_id from sessions where id = ?",
                (session_id,)).fetchone()
        finally:
            con.close()
        resolved = True
        if row:
            return _key_is_restricted(row[0] or "", row[1] or "")
    except Exception:
        resolved = False
    try:
        data = json.load(open(ROUTING_JSON, encoding="utf-8"))
        for key, val in data.items():
            if isinstance(val, dict) and val.get("session_id") == session_id:
                return _key_is_restricted(str(key))
        resolved = True
    except Exception:
        pass
    if not resolved:
        raise RuntimeError("cannot resolve session owner; refusing to guess")
    return False


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
    if head == "conn":
        sub = tokens[1].strip("'\"") if len(tokens) > 1 else "help"
        if sub not in CONN_SUBCOMMANDS:
            return f"conn subcommand '{sub}' is not permitted"
        return None
    if head not in ALLOWED:
        if not (head == "sshpass" and "ssh" in tokens):
            return (f"only ssh (and the conn address book) is permitted for "
                    f"this account; '{head}' is not")

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        low_tok = tok.lower()
        if tok in FORBIDDEN_EXACT:
            return f"forbidden option: {tok}"
        if tok.startswith(FORBIDDEN_PREFIXES) and len(tok) > 2:
            return f"forbidden option: {tok} (port/SOCKS forwarding)"
        if low_tok == "-o" and i + 1 < len(tokens):
            nxt = tokens[i + 1]
            key = nxt.split("=", 1)[0].strip().lower()
            if key not in ALLOWED_O_KEYS:
                return f"ssh option -o {nxt.split('=', 1)[0]} is not permitted"
            i += 1
        elif low_tok.startswith("-o") and len(tok) > 2:
            key = tok[2:].split("=", 1)[0].lower()
            if key not in ALLOWED_O_KEYS:
                return f"ssh option -o {tok[2:].split('=', 1)[0]} is not permitted"
        i += 1

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
            print(json.dumps({
                "action": "block",
                "message": ("This account has ssh-only access: only the "
                            f"terminal tool running ssh/scp/sftp, not '{tool}'."),
            }))
            return

        command = (payload.get("tool_input") or {}).get("command", "")
        reason = gate(command)
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
