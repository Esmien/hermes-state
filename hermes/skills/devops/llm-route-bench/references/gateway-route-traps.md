# Gateway route traps — OpenCode deployments and `hermes.*` usage stripping

Two failure modes of *this* gateway that look like model defects. Read before diagnosing a
route as broken, and before editing a deployment.

## `opencode/*` — header, protocol, and where deployments actually live

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

## `hermes.*` routes via Open WebUI strip `usage`

- **`hermes.*` routes via Open WebUI strip `usage` (`in=0/out=0` on every call).** Token
  and cost columns are then unusable — rank by pass rate, then latency, and say the spend
  is unmeasurable on that route instead of printing `$0.00` as if it were free. Same logic
  in reverse: a probe that errors while the task set passes means the *probe shape* is
  wrong (a reasoning route enforcing a minimum `max_tokens`), not a broken route — raise
  `max_tokens` and re-probe instead of flagging the route. На малом бюджете рассуждающий маршрут
  отвечает `200` с пустым `content` и всеми токенами в `reasoning_tokens` — это тоже артефакт
  бюджета: смотри `finish_reason` и `usage.completion_tokens_details`, прежде чем называть ответ пустым.
