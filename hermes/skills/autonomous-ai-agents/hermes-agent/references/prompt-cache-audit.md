# Prompt / KV cache health audit

Use when asked "do my settings break the prefix/KV cache?", "timestamps in requests?",
"does dynamic tool loading break the prefix?", or any investigation of cache hit rate.

## Rule 0 — measure before you theorize

Hermes logs the real hit rate per API call. Answer from these numbers, never from config
reading alone:

```bash
grep -h 'cache=' ~/.hermes/logs/agent.log | tail -400
# API call #49: model=... in=33621 out=165 total=33786 latency=2.1s cache=33408/33621 (99%)
```

Parse `cache=(\d+)/(\d+)` and report the **median** over the last few hundred calls. A
healthy busy session sits at 96-100% (median ~99%). Then explain any outliers you find.

Expected, non-actionable outliers:

- **Session start** — the first 1-3 calls of a session are cold (11-53%).
- **Compaction** — one call near 0% right after a summary, recovering by the next call.
- **Upstream one-offs** — a single call at 17-66% that returns to ~99% on the very next
  call is provider-side eviction/backend rotation, not a Hermes prefix breaker. Same
  `api_base` for the surrounding calls confirms it.
- The **base prefix (~11.5k tokens of system prompt + tools) is reused even immediately
after compaction** — reuse never drops to zero on a warm route.

## 1. Inspect the actual request bytes

On a failed/policy-gated call Hermes dumps the literal body to
`~/.hermes/sessions/request_dump_*.json`. Read it: top-level `request.body` should contain
exactly `model`, `messages`, `tools`, `reasoning_effort` — no `metadata`, no `user`, no
nonce/uuid/timestamp. That absence is the proof that the prefix is request-stable.

## 2. Config keys that decide prefix stability

Check each explicitly; report the value, don't assume the default:

| Key | Cache-safe value | Why |
|---|---|---|
| `gateway.message_timestamps.enabled` | `false` | When true, each inbound message is rendered with a timestamp prefix — new bytes in the history. |
| `compression.proactive_prune_tokens` | `0` (off) | Any nonzero value rewrites stale tool results mid-session = new prefix. |
| `compression.idle_compact_after_seconds` | `0` (off) | Idle compaction rewrites history without the user doing anything. |
| `compression.threshold_tokens` | as high as the route tolerates | Effective trigger = `min(threshold_tokens, threshold × context_length)`. This is the ONE planned cache break — every compaction costs a full re-prefill. |
| `prompt_caching.cache_ttl` | inert here | Anthropic-only (`cache_control` breakpoints). On a custom/OpenAI-compatible route no markers are sent and the upstream does automatic prefix caching. |
| `display.runtime_footer.enabled` | either | Display-only: the transcript persists raw `agent_messages`, so the `model · 12%` footer never enters the prompt. |

## 3. Where variability lives inside the system prompt

The prompt is assembled in tiers (stable / context / volatile) and built **once per
session** (`agent._cached_system_prompt`). It is invalidated in exactly two places: context
compression, and `switch_model` (which sets `_cached_system_prompt = None` deliberately).
The date line and the `MEMORY [n% — x/y chars]` header sit in the **last, volatile block**,
so a rebuild only disturbs the tail, not the ~11.5k prefix.

Pitfall: don't report the date/percentage header as a per-turn cache breaker. It changes
only when the prompt is rebuilt, and it is positioned last on purpose.

## 4. Dynamic tool loading is cache-safe by design — verify, don't "fix"

The deferred-tool mechanism keeps the prefix byte-stable:

- `tools.tool_search` replaces deferred schemas with fixed **bridge** schemas
  (`tool_search`, `tool_describe`) that are always present; the count in the array does
  not change as tools are discovered.
- The `Deferred tool catalog` block is rendered with `sorted()` groups and names
  ("byte-stable — the request prefix stays cacheable") and its token budget is derived from
  `context_length`.
- Loaded parameter schemas come back **inside the `tool_describe` tool result** — i.e. the
  tail — never injected into the `tools` array.
- Schema key order is frozen and the array order is deterministic, so a restart reproduces
  the same bytes.

## 5. Never mutate a live conversation to "optimize" the cache

See the Hard Invariants in SKILL.md: don't rewrite earlier messages, swap the toolset, or
inject fresh context into the middle of a session. The only sanctioned break is compaction —
and the way to have fewer breaks is a **higher `compression.threshold_tokens`**, not editing
history.

## 6. Upstream side

On a LiteLLM / Open WebUI route the real prefix cache belongs to the upstream provider. Read
the per-request `cached_tokens` from LiteLLM's spend logs — query and the model-group
mapping are in the `ai-stack` skill. Note that another client (a different Open WebUI model
sharing the same LiteLLM group) can contend for the same prefix cache and produce hit-rate
blips that are not Hermes' fault.
