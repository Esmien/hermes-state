# Bounded memory curation (MEMORY.md / USER.md)

Two curated stores are injected into the system prompt on **every** turn, so their size is a permanent tax:

| store | file | limit key in `config.yaml` |
|---|---|---|
| agent notes | `$HERMES_HOME/memories/MEMORY.md` | `memory.memory_char_limit` (default 2200) |
| user profile | `$HERMES_HOME/memories/USER.md` | `memory.user_char_limit` (default 1375) |

Entries are separated by a line containing only `§`.

## Measure in characters, not bytes

`ls -l` lies on Cyrillic text: each Cyrillic char is 2 bytes, so a 1041-char file shows 1511 bytes. Compare against the limit with `len(open(p, encoding='utf-8').read())`, never `wc -c`.

## Remedy order — cheapest first, budget increase last

1. **Dedupe and merge.** The same fact usually exists twice (subscriptions, bot tokens, backup paths). Merge into one entry keeping every detail, drop the repetition. Good for 150–400 chars, no information lost.
2. **Move detail into a skill, leave a pointer.** Memory keeps `what/where` in one line (`задачи → /root/.hermes/tasks/backlog.md, протокол в скилле owner-task-digest`); the skill keeps the procedure. Task-specific facts belong in the skill that governs that task — career facts in the career skill, stack paths in the stack skill, design concepts in the repo's `docs/`. This frees room *and* makes the knowledge load contextually instead of every turn.
3. **Raise the limit — only as a last resort.** A bigger store costs tokens on every turn and, worse, makes trivia read as a standing instruction. The owner's standing decision: budget increases degrade inference quality, so trade detail for pointers instead.

## What belongs in memory at all

- identities and access levels (`<id> = <person>, what they may do`), one line each
- invariants with no task home (host root = `/`, recovery repos must mirror the host)
- pointers: file paths, skill names, doc paths, route names
- **not**: procedures (→ skill), per-task progress (→ board file), secrets (→ `.env`; memory holds the path only), anything stale within a week (→ session history)

## Procedure when a write is rejected at the limit

1. `read_file` both stores.
2. Back up: `cp $HERMES_HOME/memories/MEMORY.md $HERMES_HOME/backups/memory/MEMORY.md.<ts>` (same for `USER.md`).
3. Rewrite the file with the merged/trimmed entries, keeping the `§` separators.
4. Verify: `len()` of each file is under its limit and `text.split('§')` gives the expected entry count.
5. Re-check that every fact you moved still exists at the destination — a pointer to nothing is worse than the full entry.
6. When several entries change at once, prefer one `memory` batch call: the char limit is checked only on the final result, so removals and additions can travel together.

Leave ≥20 % headroom after curation; a store sitting at 99 % makes the next add fail mid-task.
