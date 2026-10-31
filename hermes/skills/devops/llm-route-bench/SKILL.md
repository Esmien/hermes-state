---
name: llm-route-bench
description: "Use when a model seems worse or LLM cost/limits matter."
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

Also use when the question is money rather than quality: «где взять модель дешевле»,
«стоит ли подписка», «какие там лимиты», «я не зря заплатил», «можно ли затащить
подписку в OpenCode / другой сторонний клиент». Read `references/access-pricing.md`
before quoting any number — it carries the official price ladder, the discount levers,
the per-plan allowances, and the subscription-vs-API rule per vendor.

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

## Code-generation bench (hidden tests)

Use when the question is «какая модель лучше пишет код», not «какой маршрут чище». Full
recipe, task ladder and the observed baseline: `references/code-gen-bench.md`; runnable
harness: `scripts/code_bench.py`.

- One request per (model, task), no retry, **no system prompt**, `reasoning_effort=high`.
  A second attempt measures cooperation, not first-shot quality.
- Grade by executing hidden tests against the extracted last ```python block in a subprocess
  with a timeout. Never read the code yourself and never ask the model to grade itself.
- Rank by pass count, then latency, then tokens. On algorithm tasks every model in this
  stack scores 100%, so burn and speed are the only signal left — report `$/успех`, and for
  subscription routes report quota share instead of dollars.
- Every code bench must contain at least one **behavioural-preservation** task (rewrite a
  module without changing its API) and one **bug-hunt** in a multi-hundred-line file. Those
  two separate models; algorithm puzzles do not.

## Pitfalls

- `opencode/*` groups need the `x-opencode-session` header on **every** endpoint — without it
  the deployment answers 400 in a way that reads like a bad model name (seen on
  `/v1/chat/completions`). They also want the Responses API: the
  channel rejects `/chat/completions` (`Model does not support this protocol`) while
  `/v1/responses` answers fine. Fix in the deployment: `litellm_params.model =
  "responses/<model>"` — LiteLLM then bridges chat→responses itself and text tasks start
  passing. Tools survive only on raw `/v1/responses`: through the bridge the model sees them
  namespaced (`default.get_pawn_rate`) and answers in prose without ever emitting a
  `function_call`, so every tool task fails. Agentic work stays on the OpenRouter route.
- Meta's `muse-spark-1.3-contributor` via OpenRouter rejects `max_tokens < 16`
  (`max_output_tokens must be >= 16`), so a 5-token probe returns a false 400. The probe uses
  16 and labels unanswered probes `route error`, not `clean`.
- Tool tasks silently become text tasks if `tools=` is not passed to the agent loop — check
  `turns=[...]` in the output; `calls=0` on a tool task means the harness bug, not the model.
- `/model/info` may report cost 0 for a route (free credits). Cost columns then lie: use the
  provider's public price in the report and say it is estimated.
- A route that answers «ок» fine can still inject on the next call — injection is
  intermittent, so probe 3 times and trust the minimum, not the average.
- Keep the spend visible: print `$/success` per model, not total only.
- A prompt like «перепиши чисто, поведение сохранить» gets public functions renamed (`total`
  → `to`) unless the tests call the API by name. Always assert the exact public names, not
  just the behaviour — the rename is the most common real regression.
- Numeric unit mismatches (docstring says milliseconds, code sleeps seconds) are invisible to
  every model acting as reviewer, including the strongest ones. To measure review ability,
  ask explicitly to compute the value for a few inputs and compare it with the docstring;
  «найди баг» alone returns stylistic findings and misses the arithmetic.
- A route can answer with a **different model** than its name promises, and can strip
  reasoning while still doing the work. Neither is visible in the name or in self-description;
  decide with the tokenizer fingerprint in `references/route-fingerprinting.md` (constant delta
  vs proportional delta), never with «кто ты» or the UI label.

## Files

- `references/access-pricing.md` — official per-token ladder, discount levers (cache,
  batch/flex, long-context cliff, reasoning effort), subscription allowances per plan,
  reseller markup math, the subscription-vs-API rule and the per-vendor matrix for
  plugging a plan into a third-party client, and how to answer «стоит ли оно того».
- `scripts/ab_bench.py` — probe + 8 deterministic tasks + price lookup from `/model/info`.
  Reads `LITELLM_MASTER_KEY` from `/home/ai_service/ai-stack/ai/.env`, never prints it.
- `references/code-gen-bench.md` — model-name resolution in the gateway, harness design,
  the six-task ladder, grading gotchas, cross-review protocol, baseline results.
- `references/route-fingerprinting.md` — как отличить подмену модели и вырезанные
  рассуждения по `usage.prompt_tokens` и полям ответа, с порядками величин по семействам.
- `scripts/code_bench.py` — hidden-test generator bench: four tasks (truncate, CSV, legacy
  refactor, 250-line bug hunt), runs inside the sandbox, writes JSONL.
