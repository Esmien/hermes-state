# Delegating to an External Coding Agent (opencode, Codex CLI, Claude Code)

Load this when asked whether to wire an external coding agent to Hermes, or
tasked to actually run one headlessly as a delegated worker.

## Is the integration worth building at all

- These tools are **same-category agents** as Hermes, not services. A bridge buys
  no capability — only (a) a long coding session isolated from the parent's
  context, (b) a fix run inside a git worktree, (c) a second opinion. Say that
  plainly instead of designing an integration.
- **Nothing is shared**: the external agent cannot see Hermes memory, skills,
  sessions, bots, or crons. Expecting that is the most common wrong assumption.
- `opencode mcp` configures opencode as an MCP **client** (it consumes MCP
  servers); opencode does not act as an MCP server, so "expose opencode to
  Hermes as an MCP tool" is not a thing. `opencode serve` / `opencode acp` are
  headless servers, but there is no documented Hermes↔opencode bridge — budget
  custom code if that is really wanted.
- The one cheap, genuinely useful integration: point the external agent at
  `hermes proxy` (OpenAI-compatible, no API key) so it uses a Hermes-side OAuth
  subscription. Precondition: the upstream is actually signed in — check
  `hermes proxy status` first, and never promise it before that shows logged in.

## Invoking opencode headlessly

```bash
opencode run '<prompt>'      # one-shot: prints the answer, exits — preferred
opencode serve [--port N]    # resident HTTP server; only if driven repeatedly
opencode models [provider]   # what is really available right now
opencode auth login          # provider credentials (subscription / API key)
opencode acp                 # ACP server, for ACP-capable editors
```

- `opencode models` FIRST. With no provider auth only the built-in free
  `opencode/*` models are listed and calls still succeed — a free model on a
  real traceback yields plausible-but-unverified patches, so never promise a
  fix before checking what model will run it.

## Measured footprint (Linux x86_64, snap build)

- `opencode run`, trivial prompt: peak RSS **~600 MB**, ~4 s wall.
- `opencode run`, read a log file and answer: peak RSS **~600 MB**, ~7 s.
- `opencode serve` resident: **~250 MB** RSS steady (Pss_Anon ~190 MB,
  Pss_File ~57 MB) — keeping it up buys startup latency only, not a RAM saving.
- **VSZ reports multi-GB** (these builds reserve huge virtual address space) —
  that is not RAM; never quote it as usage.
- Budget **1–1.5 GB** per real session, not 600 MB: a worktree session spawns
  per-language LSP child processes on top of the base.
- Measure, never estimate: `/usr/bin/time -v <cmd>` for a one-shot (read
  *Maximum resident set size*), and for a live process
  `grep -E '^(Rss|Pss|Pss_Anon|Pss_File)' /proc/<pid>/smaps_rollup`.

## Hard rules for unattended runs

- **Cap it**: `systemd-run --scope -p MemoryMax=1536M -p MemorySwapMax=0 -- <cmd>`.
  An uncapped agent on a swap-pressured host turns one stuck session into a
  global OOM that takes down innocent services; a capped one gets OOM-killed
  alone.
- **Serialize** — one session at a time, and not during another heavy memory
  spike (e.g. a vector-ingest / model-load burst in a neighbouring service).
- **Sandbox the fixer**: git worktree on its own branch, no docker socket, no
  write access to the production tree, a timeout. It emits a diff; it never
  deploys. Validate with `git apply --check` before presenting the patch.
- Never let it run a deploy script that restores databases by default.

## Process hygiene for probes

- Start a long-lived probe with `terminal(background=true, ...)`. **Hermes
  rejects shell-level background wrappers** (`setsid`, `nohup`, `&` + `disown`)
  and the command never runs — the call comes back as a refusal, not a probe.
- To stop a probe, never `pkill -f '<pattern>'` from inside the same command:
  the pattern matches the shell executing it, so the shell dies first — the call
  returns empty output with exit 0 and **everything after the `pkill` silently
  never runs**. Kill by PID, or use `pkill -x <exact-process-name>`, then verify
  the process is gone in a separate call.
