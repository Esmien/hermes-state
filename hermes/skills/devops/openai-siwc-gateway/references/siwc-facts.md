# SIWC facts that matter (verified Oct 2026)

- Authorize: `https://auth.openai.com/api/accounts/authorize` with
  `client_id=dynamic_agent_client`, `agent_name_hint`, `ext_agent_host_id`,
  `response_type=code`, `redirect_uri=http://127.0.0.1:PORT/auth/callback` (path fixed,
  port may vary, never `localhost`), `scope=openid profile email offline_access
  resource.invoke chatgpt.tokens.use.direct`, `resource=https://api.openai.com/v1`,
  `state`, `nonce`, `code_challenge_method=S256`, `code_challenge`.
- Callback returns `code,state,client_id` — the issued `client_id` is `oaiapp_…`; it must be
  saved and reused for later sign-ins. Token exchange: form POST to
  `https://auth.openai.com/api/accounts/oauth/token`, `grant_type=authorization_code`,
  no client secret. Refresh uses `grant_type=refresh_token` + `client_id` + `resource`.
- Inference: only `/v1/responses`, `store:false`, `stream:true`. Function calling works
  cleanly (verified: `function_call` with correct name and JSON arguments), so a chat→
  responses bridge does not break tools.
- Model catalog: `GET /v1/models` returns the account plan models (`visibility == list`).
- No rate-limit headers come back; quota is invisible, same subscription allowance.
- **`The ChatGPT user has reached their Subscription Sharing usage limit` — это квота аккаунта, не баг моста.**
  Текст приходит от OpenAI (в LiteLLM — `BadRequestError`/400 на `/v1/responses`) и означает, что общий
  allowance подписки выбран для всех клиентов сразу: Codex CLI, OpenCode и этот мост делят один пул.
  Остаток нигде не читается (ни заголовков, ни `/usage`: `hermes usage` отвечает «нет данных»), поэтому
  вариантов два — ждать сброса окна или увести клиента на маршрут без подписки. Диагностика по факту:
  `docker logs litellm | grep -i "Subscription Sharing"` даёт время и модель, `grep -c` — единичный
  отказ это или цикл ретраев. **400 от моста убивает всю цепочку: `order` не сработает, fallback-группа
  тоже.** `litellm.should_retry()` ретраит только 408/409/429/5xx, а `should_retry_this_error()` для
  прочих 4xx сразу делает `raise` — поэтому `order=2`/`fallbacks` молча не работают, и текст ошибки
  приходит в чат, хотя нога формально здорова и в cooldown не уходит. Сама ошибка при стриме приходит
  **не HTTP-кодом, а событием `response.failed` внутри 200-потока** — поэтому маппинг только на
  уровне статуса ничего не меняет (проверено: после него ровно тот же `BadRequestError` в чате).
  Лечение — в мосте, две точки: `relay_error()` для не-200 (400/403 с «usage limit» → `429`
  `rate_limit_error`) и **чтение стартового потока ДО отправки 200** (`handle_responses` и `handle_chat`): отказ идёт
 **не первым событием**, а в любой момент до первого вывода — реальные последовательности на этом
 хосте: `created → in_progress → output_item.added → failed`, `created → in_progress → metadata →
 failed` и `created → in_progress → metadata → error`. Список «тихих» типов бесполезен (состав
 меняется), поэтому правило простое: **копить всё, пока не встретится `*.delta` / `output_item.done` /
 `completed` / `incomplete`** (лимит ~200 событий), и только тогда отдавать 200; встретили
 `response.failed`/`error` — 429. Стриминг сохраняется, тормозятся только pre-text события.
 Проверка в реальном отказе: строка `responses failed before stream: <type> <msg>` в
 `/root/siwc/gateway.log` (юнит пишет stdout/stderr туда, а не в journald — `journalctl -u
 siwc-gateway` пуст и это норма). `aggregate()` тоже должен
  ставить `status='failed'` для `response.failed`, иначе sync-ветка отдаёт пустой 200. Тест логики —
  `assets/host/siwc/test_gateway_quota.py` (8 кейсов, monkeypatch `upstream`), сквозная проверка —
  стаб с 429 на `order=1` + OpenRouter на `order=2`: отвечает `order=2`, и в стриме, и без; Если у группы живая только плановая нога (серая `chatgpt/` заблокирована),
  ошибка идёт прямо в чат — для таких групп держать отдельную fallback-группу на не-плановом провайдере.
