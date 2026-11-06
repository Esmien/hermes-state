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
подписку в OpenCode / другой сторонний клиент», «куда реально уходят запросы от chatgpt/».
Read `references/access-pricing.md`
before quoting any number — it carries the official price ladder, the discount levers,
the per-plan allowances, and the subscription-vs-API rule per vendor;
`references/subscription-routes.md` covers which upstream a plan-backed route really uses
and the official OAuth shape it should be compared against.

## Rule zero

**Never call an expensive route without an explicit instruction from the owner.**
`scripts/ab_bench.py` refuses opus/gpt-6/sonnet unless `--allow-expensive` is passed —
keep that guard. Cheap defaults (deepseek-v4.1-flash, claude-haiku-5.5) are fine to run
for verification; everything else only on a direct request, and say the price up front.

**A bench is only worth its price if the model is in the owner's working set.** Quote the
cost before building anything bigger than a probe, and drop the job when the answer is
«им не пользуюсь»: a perfect table for a model he will never call is vanity spend, and he
will say so.

## Procedure

1. **Probe for a hidden prompt first.** A proxy can prepend a foreign system prompt to
every call: the model then follows instructions the owner never gave, and the owner pays
for those tokens. Send `«Скажи одно слово: ок»` with `max_tokens=5` and read
`usage.prompt_tokens`; ~20-60 tokens is clean, **hundreds to thousands means injection**.
   ```bash
   python3 scripts/ab_bench.py --probe deepseek/deepseek-v4.1-flash
   ```
2. **Choose tasks that match the owner's actual work.** For an agent comparison, use multi-step
   incident investigations with isolated, read-only synthetic tools, misleading clues, partial
   evidence, safe remediation, verification and rollback. Identical model IDs, prompts, tool
   schemas and settings are mandatory; never substitute the current agent or another route.
   Keep short deterministic tasks as protocol smoke tests, not evidence of agent superiority.
   Run repeated trials where feasible; disclose when results are single-shot.
   Score factual diagnosis, evidence, uncertainty, safety, verification and rollback separately
   from JSON formatting. Validate graders with positive and negative examples: substring checks
   can misclassify negation and cannot assess semantic safety. Manually review relevant answers,
   label subjective judgments, and do not present an unchecked heuristic as an objective score.
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

## Проверка подлинности перепродаваемого маршрута

Вопрос «а не подсунули ли под именем X модель послабее» решается **парным сравнением**, а не
самоидентификацией: тот же промпт гоняется по подозрительному маршруту, по тому же
названию модели на доверенном маршруте и по 1–2 контролю (средний + слабый). Готовый
харнесс — `scripts/authenticity_probe.py`; сырые замеры складывай в JSON, таблицу строй из него.

1. **Сначала дешёвые пробы возможностей:** `GET /v1/models` (поле `owned_by`, `context_length`,
   флаги `reasoning`/`vision`), картинка 1×1 пиксель (заявленный vision), наличие
   `usage.completion_tokens_details.reasoning_tokens` у рассуждающей модели, иголка в 60k
   символов. Всё это одна-две копейки и сразу отсекает заглушки.
2. **Затем жёсткий набор с точными ответами**: математика, где ответ считается кодом
   (нули факториала, `pow(a,b,m)`, комбинаторика, число-теория), и задачи на код, которые
   гарнесс **исполняет** скрытыми тестами. Ответ «на глаз» не годятся: у модели может быть
   верный ход мысли и неверное арифметическое число.
3. **Сравнивай вердикты по задачам, а не только сумму.** Совпадение «подозрительный ≡
   доверенный» на всех задачах + провал контролей там, где оба прошли — это и есть ответ.
   Если подозрительный совпадает с *слабым* контролем, а не с доверенным — модель подменена.
4. **Говори границы методики.** Набор из 9–12 задач отличает класс модели, а не конкретную
   сборку: «не хуже настоящего» ≠ «доказано, что это он». Так и формулируй.
5. **Паритет качества не оправдывает маршрут.** Если обёртка при равном результате даёт 3×
   латентность, врёт в `usage` и держит мёртвый free-пул — вердикт «модель настоящая, но
   держать её в группе незачем»: цена и задержка решают, а не одна только схожесть ответов.

**`usage` перепродавца — не измерение, а его собственный счётчик.** У прокси-обёрток
`prompt_tokens` может быть искажён (в замерах — почти ровно в 2× на латинице и на кириллице),
и по нему нельзя ни считать цену, ни судить о лимитах. Для фингерпринта токенизатора — только
разница с доверенным маршрутом на ОДНОМ И ТОМ ЖЕ тексте (`references/route-fingerprinting.md`),
цена — по сигнатуре провайдера, а не по `usage` обёртки.

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
- **Hard tier saturates too.** `scripts/code_bench_hard.py` (4 tasks / 51 hidden tests:
  binary frame decoder with resync, thread-safe token bucket on an injected clock,
  quirk-preserving refactor with decoy "improvements", expression parser with unary-minus
  vs `^` traps) was passed 51/51 first-shot by both Sol 6.1 and Terra. Conclusion: at
  frontier level, *single-shot* code generation no longer separates models — only agent
  loops, UX/design taste and multi-file work do. Stop building harder puzzles; build a
  multi-turn harness instead. Validate the harness with `--selftest` (reference must be
  100%, each broken variant must fail its declared tests) before spending a single call.

## Pitfalls

- **Правильные ответы считай в коде харнесса, не в голове.** Ручной ключ к задачам дважды
  оказывался неверным (остаток степени, время встречи поездов) и вся команда моделей
  выглядела как четыре провала — это ошибка ключа, а не моделей. Если контроль, который
  обязан пройти, сыпится на задаче — подозревай грейдер, а не маршрут.
- **Лёгкий набор насыщается**: факториалы, иголка в стоге, простая арифметика — 9/9 у всех,
  включая слабый контроль, и различий нет. Задачи должны быть тяжелее среднего контроля,
  иначе бенч измеряет вежливость, а не модель.
- **Free-пул перепродавца — отдельное состояние, а не свойство модели.** Протухший (или
  недавно не пополненный) ключ отдаёт `429` вида «free models are for active keys» на всех
  `free-*` именах, при этом платное имя того же вендора работает. Перед выводом «модель
  сломалась» проверь и платное, и `free-` имя поодиночке.
- `opencode/*` groups need the `x-opencode-session` header on **every** endpoint — without it
  the deployment answers 400 in a way that reads like a bad model name (seen on
  `/v1/chat/completions`). They also want the Responses API: the
  channel rejects `/chat/completions` (`Model does not support this protocol`) while
  `/v1/responses` answers fine. Fix in the deployment: `litellm_params.model =
  "responses/<model>"` — LiteLLM then bridges chat→responses itself and text tasks start
  passing. Tools survive only on raw `/v1/responses`: through the bridge the model sees them
  namespaced (`default.get_pawn_rate`) and answers in prose without ever emitting a
  `function_call`, so every tool task fails. Agentic work stays on the OpenRouter route.
  **Деплойменты живут в БД, а не в `config.yaml`** (`LiteLLM_ProxyModelTable`), и в них
  `litellm_params->>'model'` и `litellm_credential_name` хранятся **зашифрованными** — по
  строке модели не определить, какой из двух деплойментов группы сидит на OpenCode. Диагноз
  ставят сравнением с соседними группами: где `x-opencode-session` в `extra_headers` есть, а
  где нет. Лечение — дописать заголовок **всем** деплойментам группы (OpenRouter лишний
  игнорирует) и перезапустить контейнер:
  `UPDATE "LiteLLM_ProxyModelTable" SET litellm_params = jsonb_set(litellm_params,
  '{extra_headers}', coalesce(litellm_params->'extra_headers','{}'::jsonb) ||
  '{"x-opencode-session":"litellm-service-session"}'::jsonb), updated_at = now()
  WHERE model_name='<group>'`.
  Симптом «флапает через раз» = в группе два деплоймента, один без заголовка: проверять
  четырьмя подряд вызовами (`200 200 200 200`), а не одним.
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
- **Test the protocol and mode actually used by the agent.** A non-streaming pass does not
  certify streaming. Inspect SSE event types, content/tool deltas and `finish_reason`: Responses
  events on a chat endpoint can be misread as empty chat chunks. Do not infer which component
  dropped data or blame hidden reasoning without tracing the wire. If streaming is disabled,
  verify non-streaming tool calls end-to-end and don't require a streaming pass for that setup.
- **Count logical calls in the spend log, not rows.** Retries can multiply rows, but identical
  token counts and timing do not prove retries: correlate request IDs, attempt metadata and
  client logs before attributing rows or billing. State the rule explicitly
  («Terra — дефолт, Sol — эскалация») and keep the baseline table in the reference. When the
  owner says «ты же хуесосил Terra», search the sessions for what was actually said and
  answer from that quote: a false admission rewrites the stack's routing on a misremembered
  fact, and a bare denial without the quote reads as defensiveness.
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
- **The alias does not say who bills you.** Resolve `model_name → litellm_params.model`
  from `/model/info` before answering «это по подписке или по API?»: `openai/gpt-*` on top
  of `chatgpt/*` is plan quota against the Codex backend, `openai/*` is metered API. Recipe
  and the official alternative: `references/subscription-routes.md`.
- **Open WebUI display names are not API ids.** The UI shows «(Hermes) DeepSeek v4.1 Flash»
  while the API serves `hermes.deepseek/deepseek-v4.1-flash` — resolve every name through
  `GET /api/v1/models` before benching; a guessed id either 404s or silently benchmarks
  a different route.
- **`hermes.*` routes via Open WebUI strip `usage` (`in=0/out=0` on every call).** Token
  and cost columns are then unusable — rank by pass rate, then latency, and say the spend
  is unmeasurable on that route instead of printing `$0.00` as if it were free. Same logic
  in reverse: a probe that errors while the task set passes means the *probe shape* is
  wrong (a reasoning route enforcing a minimum `max_tokens`), not a broken route — raise
  `max_tokens` and re-probe instead of flagging the route. На малом бюджете рассуждающий маршрут
  отвечает `200` с пустым `content` и всеми токенами в `reasoning_tokens` — это тоже артефакт
  бюджета: смотри `finish_reason` и `usage.completion_tokens_details`, прежде чем называть ответ пустым.

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
- `references/subscription-routes.md` — как узнать, какой upstream и чей биллинг стоит за
  маршрутом, устройство `chatgpt/` (Codex backend + device flow под видом `codex_cli_rs`)
  и официальный OAuth-флоу OpenAI для OSS-клиентов с его обязательными параметрами.
- `scripts/code_bench.py` — hidden-test generator bench: four tasks (truncate, CSV, legacy
  refactor, 250-line bug hunt), runs inside the sandbox, writes JSONL.
- `scripts/code_bench_hard.py` — hard tier (frames, token bucket, quirk-preserving refactor,
  expression parser). Has `--selftest`: reference must score 100% and every broken variant
  must fail its declared tests, so the harness is proven before any model call is spent.
- `scripts/authenticity_probe.py` — парный тест «настоящая ли модель у перепродавца»: 6 задач
  с посчитанными в коде ответами, 3 задачи на код с исполнением, контроли, пробы vision и
  reasoning-токенов, сводка «совпадение с доверенным маршрутом» и JSON-выгрузка.
