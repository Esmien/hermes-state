#!/usr/bin/env python3
"""Audit whether a secret value has reached any recovery repo, in the worktree or in history.

Prints repo names, hit counts and redacted context lines only — never the secret itself,
and never takes the value from argv (argv is visible in `ps`).

Usage:
    secret-leak-scan.py --source /root/.secrets/cf.ini                 # value = part after the first '='
    secret-leak-scan.py --source /etc/hysteria/config.yaml --key cloudflare_api_token
    secret-leak-scan.py --value-file /tmp/secret.txt                   # bare value on one line
    secret-leak-scan.py --source X --extra-repo /path/to/repo --commits 40

Exit status: 1 = at least one hit in a repo (leak or risk), 0 = clean.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_REPOS = (
    "/root/vps-infra",
    "/root/vpn-service",
    "/root/esmien-vpn-cli",
    "/payment-service",
    "/root/deploy/music_bot",
    "/var/lib/hermes-state/repo",  # live clone of hermes-state, NOT /root/.hermes (not a git repo)
)

TOKENISH = re.compile(r"(?<![A-Za-z0-9_\-])[A-Za-z0-9_\-]{32,}(?![A-Za-z0-9_\-])")
KEYWORDS = ("token", "secret", "api_key", "apikey", "password", "passwd")
PLACEHOLDER = re.compile(r"^(__[A-Z_]+__|xxx+|\.\.\.|YOUR_.*|REDACTED|<.*>)\s*$", re.I)


def resolve_value(args: argparse.Namespace) -> str:
    if args.value_file:
        return Path(args.value_file).read_text().strip()
    text = Path(args.source).read_text(errors="ignore")
    if args.key:
        m = re.search(rf'{re.escape(args.key)}\s*[:=]\s*["\']?([A-Za-z0-9_\-]{{16,}})', text)
        if not m:
            sys.exit(f"key {args.key!r} not found in {args.source}")
        return m.group(1)
    if "=" in text:
        return text.split("=", 1)[1].strip().strip('"\'')
    return text.strip()


def git(repo: str, *argv: str) -> str:
    r = subprocess.run(["git", "-C", repo, *argv], capture_output=True, text=True)
    return r.stdout.strip()


def audit_value(value: str, repos: list[str], path_globs: list[str]) -> int:
    hits = 0
    for repo in repos:
        worktree = [l for l in git(repo, "grep", "-l", "-F", value).splitlines() if l.strip()]
        history = [l for l in git(repo, "log", "--all", "--oneline", "-S", value).splitlines() if l.strip()]
        names = []
        for g in path_globs:
            names += [l for l in git(repo, "log", "--all", "--oneline", "--", g).splitlines() if l.strip()]
        if worktree or history:
            hits += 1
        print(f"== {repo}")
        print(f"   worktree: {len(worktree)} {worktree[:3]}")
        print(f"   history : {len(history)} {[c[:60] for c in history[:3]]}")
        if names:
            print(f"   path-history ({','.join(path_globs)}): {len(names)} {[c[:60] for c in names[:2]]}")
    return hits


def context_scan(repos: list[str], commits: int, values: list[str]) -> int:
    """Look for secret-shaped literals on added lines of recent commits (no values printed)."""
    found = 0
    for repo in repos:
        log = git(repo, "log", "--all", f"-{commits}", "--format=%h %ad %s", "--date=short")
        for line in log.splitlines():
            sha = line.split()[0]
            diff = git(repo, "show", "--format=", "--unified=0", sha)
            for l in diff.splitlines():
                if not l.startswith("+") or l.startswith("+++"):
                    continue
                low = l.lower()
                if not any(k in low for k in KEYWORDS):
                    continue
                cand = [v for v in TOKENISH.findall(l) if not PLACEHOLDER.match(v) and v not in values]
                if cand:
                    found += 1
                    redacted = TOKENISH.sub("<R>", l.strip())[:140]
                    print(f"   ! {repo} {line[:70]} | {redacted}")
    return found


def main() -> int:
    p = argparse.ArgumentParser()
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--source", help="file holding the secret (ini/env/yaml)")
    src.add_argument("--value-file", help="file whose whole content is the secret")
    p.add_argument("--key", help="field name to extract from --source, e.g. cloudflare_api_token")
    p.add_argument("--extra-repo", action="append", default=[], help="additional git repo to audit")
    p.add_argument("--path-glob", action="append", default=["*cf.ini", "*secret*", "*.env"],
                   help="also list any history that touched such paths (repeatable)")
    p.add_argument("--commits", type=int, default=30, help="how many recent commits to scan for literals")
    p.add_argument("--no-context-scan", action="store_true")
    args = p.parse_args()

    value = resolve_value(args)
    repos = [r for r in [*DEFAULT_REPOS, *args.extra_repo] if (Path(r) / ".git").exists()]
    print(f"value length: {len(value)}; repos: {len(repos)}")

    hits = audit_value(value, repos, args.path_glob)
    if hits:
        print("RESULT: value found in repo content/history — treat as a leak, rotate and clean")
    else:
        print("RESULT: no repo contains the value (worktree or history)")

    if not args.no_context_scan:
        print("\n-- secret-shaped literals on recently added lines (redacted) --")
        pending = context_scan(repos, args.commits, [value])
        print(f"candidates: {pending}")

    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
