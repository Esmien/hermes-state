# Push-outage drill for the Hermes state backup

Goal: prove that a commit created while GitHub is unreachable ends up on the remote without human action. Three levels; run the cheapest that answers the question, and the live one when the owner asks for "valid 100%" — he does.

## Level 1 — stub (backoff only, ~40 s)

```bash
cat > /tmp/fake-backup.sh <<'EOF'
#!/bin/bash
n=$(cat /tmp/fake-count 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > /tmp/fake-count
[ "$n" -le 2 ] && exit 1; exit 0
EOF
chmod +x /tmp/fake-backup.sh; rm -f /tmp/fake-count /tmp/watch-drill.log
timeout 40 env BACKUP=/tmp/fake-backup.sh WATCH_LOG=/tmp/watch-drill.log \
    QUIET=5 MAXDELAY=20 RETRY_MIN=3 RETRY_MAX=6 bash /usr/local/bin/hermes-state-watch.sh
cat /tmp/watch-drill.log
```

Expected: `snapshot FAILED rc=1, повтор через 3s` → `retry after failure` → `FAILED … 6s` → `ok`. Proves the watcher retries; proves nothing about git.

## Level 2 — sandbox (catch-up branch, ~30 s, no network)

```bash
rm -rf /tmp/sbx && mkdir -p /tmp/sbx && git init -q --bare /tmp/sbx/remote.git
cp -a /var/lib/hermes-state/repo /tmp/sbx/repo
sed -e 's#^STATE_DIR=.*#STATE_DIR="/tmp/sbx"#' -e 's#^GIT_REMOTE=.*#GIT_REMOTE="/tmp/sbx/remote.git"#' \
    -e 's#^LOG_FILE=.*#LOG_FILE="/tmp/sbx/backup.log"#' \
    /usr/local/bin/hermes-state-backup.sh > /tmp/sbx/b.sh && chmod +x /tmp/sbx/b.sh
/tmp/sbx/b.sh                                   # baseline push to the bare remote
git -C /tmp/sbx/repo commit -q --allow-empty -m catchup-test
/tmp/sbx/b.sh                                   # expect: "local HEAD … missing on remote — catch-up push"
test "$(git -C /tmp/sbx/repo rev-parse main)" = "$(git -C /tmp/sbx/remote.git rev-parse main)" && echo match
```

`git init --bare` defaults to `master`, so compare `main` explicitly — `rev-parse HEAD` on the bare repo fails with `Needed a single revision` and looks like a broken test.

## Level 3 — live (the real remote, ~12 min)

1. Back up and block only the git host; `api.github.com` must stay reachable so the script's repo-existence check passes:

```bash
cp /etc/hosts /tmp/hosts.bak
printf '# TEMP drill: block git push\n127.0.0.1 github.com\n' >> /etc/hosts
getent ahostsv4 github.com | head -1          # 127.0.0.1 expected
```

2. Make a real, wanted change inside a watched path (documentation is ideal) — a no-op `touch` produces no commit and proves nothing.
3. Wait one debounce window (~90 s) and read the log: `✓ committed <sha>`, then `ERROR: git push … failed (commit <sha> stays local, watcher retries)`, then retry intervals 60 → 120 → 240 → 300 s, each ending in `FAILED`.
4. Restore and verify:

```bash
cp /tmp/hosts.bak /etc/hosts && grep -c drill /etc/hosts   # 0
getent ahostsv4 github.com                                  # real IP
```

5. Wait for the next scheduled retry (≤300 s + 15 s cycle). Expected: `retry after failure` → `local HEAD <sha> missing on remote — catch-up push` → `✓ pushed <sha>`. No manual snapshot.
6. Confirm the remote actually has it, using the API (not the git CLI, which has no credentials in an interactive shell):

```bash
K=$(grep -m1 '^GITHUB_KEY=' /home/ai_service/ai-stack/ai/.env | cut -d= -f2- | tr -d '"')
curl -s -H "Authorization: Bearer $K" https://api.github.com/repos/Esmien/hermes-state/commits/main \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["sha"])'
git -C /var/lib/hermes-state/repo rev-parse HEAD              # shas must match
```

## Rules and pitfalls

- The whole block/unblock is a **system-file edit**: keep it in its own command, never bundled with unrelated work — approval covers the entire command line, and a timeout discards all of it.
- Always restore from the `/tmp/hosts.bak` copy, not by editing the file by hand; then prove the block is gone (`grep -c`).
- Expect Telegram alerts during the drill (they are real, the failure is real). With alert throttling the owner sees one message per 30 min, not one per retry.
- `getent hosts github.com` can echo `127.0.0.1 localhost github.com` from a stale entry/search domain and look like the block is still active — use `getent ahostsv4` for the truth.
- Record the timeline from the two logs in the report (commit time, refusal time, retry times, delivery time); "works" without times is not evidence.
