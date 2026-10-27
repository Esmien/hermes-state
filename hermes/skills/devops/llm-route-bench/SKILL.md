---
name: llm-route-bench
description: "Use when a model seems worse: bench LiteLLM routes."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [ai-stack, litellm, benchmark, models, routes]
    related_skills: [ai-stack]
---

# LiteLLM route benchmark

## When to Use

Use when the owner says a model «тупит / хуже работает / отказывается», when comparing a
cheap model against an expensive one, or after any change of a route/credential in the
gateway. The point is to separate **model quality** from **route quality** with numbers.

## Rule zero

**Never call an expensive route without an explicit instruction from the owner.**
`scripts/ab_bench.py` refuses opus/gpt-6/sonnet unless `--allow-expensive` is passed —
keep that guard. Cheap defaults (deepseek-v4.1-flash, claude-haiku-5.5) are fine to run
for verification; everything else only on a direct request, and say the price up front.

## Procedure

1. **Probe for a hidden prompt first.** A proxy can prepend a foreign system prompt to
every call: the model then follows instructions the owner never gave, and the owner pays
for those tokens. Send `«Скажи одно слово: ок»` with `max_tokens=5` and read
`usage.prompt_tokens`; ~20-60 tokens is clean, **hundreds to thousands means injection**.
   ```bash
   python3 scripts/ab_bench.py --probe deepseek/deepseek-v4.1-flash
   ```
2. **Run the task set** (`--runs 2` for stability). Tasks are graded deterministically —
   exact JSON keys, exact arithmetic, exact word count, exact tool name/args, two tool
   calls inside one assistant message. No LLM judge, so the numbers are not opinions.
3. **Read the summary**: pass rate, median latency, `$/успех`. Compare cost per *successful*
   task, not per token.
4. **Test the same model on a second route** before blaming the model. If the model passes
   on a clean route and fails on the proxy, the route is the defect.

## What the numbers already showed (Oct 2026)

- Easy tasks (single tool call, arithmetic, needle) do **not** separate models — everything
  scored 100%. Only constraint/format/parallel-tool tasks discriminate.
- `anthropic/claude-opus-5.5` via the tokenator «free-claude» proxy injected **2.8k-11k
  tokens** of a foreign prompt into ordinary calls → failed word-limit and strict-JSON,
  and cost ~$0.05 per call instead of ~$0.002. The same model on `aider.*`, and sonnet on
  `openrouter.anthropic/claude-sonnet-5.5`, were clean and scored 8/8.
- deepseek-v4.1-flash: 8/8 at ~$0.0004 per task — 20-40x cheaper than the broken Claude
  route with no quality loss on these tasks.

## Pitfalls

- Tool tasks silently become text tasks if `tools=` is not passed to the agent loop — check
  `turns=[...]` in the output; `calls=0` on a tool task means the harness bug, not the model.
- `/model/info` may report cost 0 for a route (free credits). Cost columns then lie: use the
  provider's public price in the report and say it is estimated.
- A route that answers «ок» fine can still inject on the next call — injection is
  intermittent, so probe 3 times and trust the minimum, not the average.
- Keep the spend visible: print `$/success` per model, not total only.

## Files

- `scripts/ab_bench.py` — probe + 8 deterministic tasks + price lookup from `/model/info`.
  Reads `LITELLM_MASTER_KEY` from `/home/ai_service/ai-stack/ai/.env`, never prints it.
