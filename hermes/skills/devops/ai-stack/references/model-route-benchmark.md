# Model / route benchmarking through LiteLLM

Use when the owner says "model X is worse than model Y", asks whether a complaint is about
the model or the harness, or before switching a LiteLLM group/route. The deliverable is a
verdict (`маршрут` / `модель` / `разницы нет`) plus numbers, not an opinion.

## Procedure

1. **Enumerate and price.** Key never leaves the shell — one compound command:
   ```bash
   set -a; . /home/ai_service/ai-stack/ai/.env; set +a
   curl -s -H "Authorization: Bearer $LITELLM_MASTER_KEY" http://127.0.0.1:4000/v1/models
   curl -s -H "Authorization: Bearer $LITELLM_MASTER_KEY" http://127.0.0.1:4000/model/info
   ```
   `model_info`/`litellm_params` carry `input_cost_per_token` / `output_cost_per_token`
   (dollars per token). Several entries for one model name = several credentials/fallbacks,
   so the *route*, not the model name, is the thing being compared.

2. **Hidden-prompt probe first, before any quality test.** Send a ~19-token request
   (`"Скажи одно слово: ок"`, `max_tokens: 5`) 3-5 times and record `usage.prompt_tokens`.
   Normal routes answer 19-62. Thousands mean the provider injects its own system prompt:
   the model follows instructions nobody gave and the owner pays input price for them.
   The injection is intermittent — a single clean call proves nothing.

3. **Same harness, same task set, deterministic grading.** One script, tools passed
   explicitly, temperature 0, each task run at least twice (see `scripts/model-route-bench.py`).

4. **Report** pass rate, median latency, $ per task and **$ per successful task**. The last
   one is the number to quote: a cheap model needing two attempts still wins by 20-40x.

## Task set that discriminates

Easy tasks (one tool call, plain arithmetic, needle in text) are passed by every modern
model — they are sanity checks only, never evidence of quality. Separators:

- exact word count ("ровно 40 слов, без markdown") — kills models that explain nicely;
- negative constraint (forbidden word + max words per line);
- strict JSON with a nested array and a computed total;
- two tool calls in one assistant message, then a derived percentage;
- tool args buried in dirty prose ("проба 585-я", address with junk) — must arrive as int 585;
- a broken function, graded by executing the fixed code on test input;
- long document with distractor numbers.

Contradictory-instruction prompts ("округли и не округляй") are bad graders: picking one
branch is a defensible answer, so a fail there says nothing about the model.

## Pitfalls

- **Pass `tools=` explicitly.** A harness default of `tools=None` produces zero tool calls,
  every model fails the tool tests, and the "finding" is a bug in the benchmark.
- **Distance the route, not the model name.** The same opus-class model on one credential
  can report 2 800-14 900 prompt tokens for a 19-token request while another credential
  reports 62; the poisoned route looks dumber *and* costs 4-10x more per call.
- Reasoning/thinking tokens legitimately inflate `completion_tokens`, not `prompt_tokens`.
  A constant floor that shows up even on `max_tokens=5` requests is injection, not thinking.
- Do not grade with an LLM judge when an exact check exists (word count, JSON schema,
  executed code) — the judge adds its own bias and its own bill.
- Route/group changes in `litellm_db` need explicit owner confirmation; the benchmark only
  produces the recommendation.

## Reading the result out loud

One line first: "дело не в модели, у маршрута подмешан чужой промпт" (or "модель"), then the
small table, then the fix — switch the group to the clean credential, or pin the cheap model
for agentic work. Vladislav accepts a cheap model winning: quote the 20-40x cost gap and the
equal pass rate plainly, no hedging.
