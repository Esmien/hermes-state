---
name: openai-siwc-gateway
description: "Use when ChatGPT plan feeds third-party tools."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [openai, oauth, litellm, gateway, siwc]
    related_skills: [ai-stack, llm-route-bench]
---

# Sign in with ChatGPT (OSS) gateway

## When to Use

Owner asks whether a ChatGPT plan can drive a third-party agent «officially», or the grey
`chatgpt/` LiteLLM provider (device flow + `chatgpt.com/backend-api/codex`) needs a lawful
replacement. The documented path is SIWC for open-source / locally hosted apps.

## Two routes, one plan

- **Grey**: LiteLLM `chatgpt/` provider — device-code login at
  `auth.openai.com/api/accounts/deviceauth/*`, presents itself as `codex_cli_rs`, calls
  `https://chatgpt.com/backend-api/codex/responses`. Works, but impersonates an official
  client; can be closed by upstream without notice.
- **White (SIWC)**: dynamic client registration → PKCE → `POST https://api.openai.com/v1/responses`
  with the OAuth access token. Docs explicitly forbid pointing this flow at `backend-api`.

## SIWC facts that matter (verified Oct 2026)

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
  отказ это или цикл ретраев. Если у группы живая только плановая нога (серая `chatgpt/` заблокирована),
  ошибка идёт прямо в чат — для таких групп держать отдельную fallback-группу на не-плановом провайдере.

## Building the bridge (stdlib only)

`/root/siwc/gateway.py` + systemd `siwc-gateway.service`, binds `172.17.0.1:4010` (docker
host-gateway) and `127.0.0.1:4010`. LiteLLM registers it as
`model: openai/<slug>`, `api_base: http://host.docker.internal:4010/v1`,
`api_key: <any>`; expose it as `siwc/<slug>` first so existing routes keep working.

## Migrating routes without changing client config

Goal: clients keep the same model names, only the upstream changes. LiteLLM has no
"switch deployment" button, and two deployments under one name = random load balancing,
so the order matters:

1. `POST /model/update {"model_name": "<public name>", "litellm_params": {full params},
   "model_info": {"id": "<new id>"}}` — rename the siwc deployment onto the public name.
   `litellm_params` must be complete; a partial body silently keeps the old model name.
2. `POST /model/block {"model_id": "<old id>"}` — disables the grey deployment without
   deleting it (`model_info.blocked: true`), so the name now resolves only to white.
3. Watch out for pre-existing multi-deployment pools: a name can already carry several
   deployments (e.g. free-proxy copies or an OpenCode route that demands
   `x-opencode-session`). Blocking only the grey one leaves the rest mixed in, and the
   broken members keep failing intermittently exactly as before.
4. Verify with a tool call plus the gateway log line — a `200` from LiteLLM alone does not
   prove which upstream served it. When the name still carries several deployments, one
   probe proves nothing: repeat the call until every deployment has served once, or
   shrink the pool first. A blocked deployment stays visible in `/model/info` with
   `blocked: true` — read its flag, never infer it from absence.
5. After any `/model/update`, GET the object back and assert the changed field. A `200`
   from the update endpoint does not confirm the mutation landed — a body with swapped
   keys returns success while keeping the old value.

Revert: `POST /model/unblock {"model_id": ...}`.

## Group placement, priority and fallbacks

- **Order, not fallbacks, expresses «subscription first».** Inside one group set the SIWC leg
  `litellm_params.order = 1` and the other provider `order = 2`: the router serves order 1 and
  only moves on when that deployment errors or 429s. A `fallbacks` entry is for crossing
  *groups*, not for ranking legs of the same group.
- **A group leg must be usable by the clients that will hit it.** An OpenCode-backed leg needs
  `x-opencode-session`; if it has to serve non-OpenCode clients, inject it in
  `litellm_params.extra_headers` when creating/updating that deployment — otherwise every call
  lands on `400 MissingSessionID`.
- **Timeout-driven fallback across providers** (e.g. free relay → paid/OpenCode leg): set
  `litellm_params.timeout` on the primary deployments, then add
  `router_settings.fallbacks: [{group: [target_group]}]` to
  `/home/ai_service/ai-stack/ai/litellm/config.yaml` and `docker restart litellm`. Verify with
  `GET /router/settings`; a normal call only proves the primary, so force a slow/failed primary
  if the fallback itself matters.

For model inventory and cleanup, see `ai-stack` → `references/model-provenance.md`; the block/unblock procedure is documented above.

## Fallback на другой провайдер (OpenRouter и пр.)

- **Цель fallback — отдельная группа, а не второй деплой в той же.** Клиенты ходят по
  `/v1/chat/completions`, провайдер сам выбирает путь (`openai/` → `/responses` через мост,
  `openrouter/` → `/chat/completions`); подменять путь внутри одного деплоя не нужно.
- **OpenRouter-деплой берёт ключ из `litellm_credential_name: "Openrouter LiteLLM"`.**
  `OPENROUTER_API_KEY` в контейнере может быть мёртвым (`401 User not found`) — рабочие
  OR-модели всё равно ходят через credential. Создавая группу, копировать именно
  `custom_llm_provider: openrouter` + `litellm_credential_name`, иначе получаешь 401.
- **`/model/block` не действует мгновенно:** роутер продолжает отдавать запросы
  заблокированному деплою (кэш списка моделей), поэтому «заблокировал → упало → сработал
  fallback» **не** проверяется. Надёжный тест: временная группа с мёртвым `api_base`
  (`127.0.0.1:9`) + per-request `fallbacks: [{tmp: [target]}]`; ответ с id `gen-…` означает,
  что отдал OpenRouter. После теста — `/model/delete` и проверить `count(*)` в
  `LiteLLM_ProxyModelTable`.
- Проверка, что YAML реально применился: `/router/settings` отдаёт `fields[]`, и в нём
  `fallbacks` — а не значение верхнего уровня (верхний уровень `null` ничего не значит).

## Pitfalls

- **После перезагрузки хоста проверять оба bind, а не `systemctl is-active`.** Юнит стартует
  раньше, чем docker поднимает `docker0`, `bind(172.17.0.1:4010)` падает с `EADDRNOTAVAIL`,
  поток умирает молча — юнит остаётся `active`, `127.0.0.1:4010` отвечает, а LiteLLM получает
  `Cannot connect to host host.docker.internal:4010` / `Connect call failed ('172.17.0.1', 4010)`.
  Симптом со стороны клиента: модель группы падает с `InternalServerError`, а у групп без
  `router_settings.fallbacks` — сразу ошибка в чат. Лечение: `After=/Wants=docker.service`
  в юните **и** повтор bind в `serve()` (сеть может отстать и от этого). Проверка после
  любого reboot: `ss -ltnp | grep 4010` должен показать **две** строки (`172.17.0.1` и `127.0.0.1`).
  Копии юнита и `gateway.py` лежат в `vps-infra/assets/host/{systemd,siwc}/` (`auth.json` — нет).

- **`stream` must be read before you force it.** Setting `body['stream'] = True` and then
  deciding "client wanted a stream?" always answers False, so the gateway returns an
  aggregated JSON to a caller that expects SSE. LiteLLM reports it as
  `APIConnectionError: openai closed the responses stream before any terminal event` — 100%
  reproducible on `/v1/responses`, invisible on `/v1/chat/completions`.
- **Always synthesise a terminal event.** If the upstream stream ends without
  `response.completed|incomplete|failed`, emit a synthetic `response.completed` yourself;
  otherwise the proxy turns a merely truncated answer into a hard error.
- **Upstream rejects `max_output_tokens < 16`**; clamp every `max_tokens`/
  `max_completion_tokens` to `max(16, int(value))`.
- **`/model/update` bookkeeping is treacherous.** Pass `model_info.id` and the full
  `litellm_params`; then re-read `/model/info` and assert `blocked` **per deployment id**.
  After a rename the flag can end up on the wrong row, which silently leaves the grey
  route live and looks like a gateway bug.
- `order` in `litellm_params` does not give strict priority under `simple-shuffle` — for a
  real "primary → fallback" chain put the secondary in its own model group and declare it
  in `router_settings.fallbacks`.
- `ext_agent_host_id` must be a hyphenated **UUIDv4** with `urn:uuid:` prefix; a hex
  machine-id gives `invalid_authorize_request` / `param: ext_agent_host_id`.
- Host-ID and client-id must persist; restarting or re-signing-in must not mint a new host.
- Aggregate streamed responses from `response.output_item.done`; `response.completed.output`
  is **empty** even when the model answered — relying on it yields blank messages.
- `urllib.request` is easy to forget when only `urllib.parse` is imported; refresh then
  fails with a bare `AttributeError`.
- Restarting by `pkill -f <path>` misses a process started as `python3 gateway.py` from its
  own cwd — check `ss -lntp` before assuming the new build is live; an old instance keeps
  the port and the new one dies with `Address already in use`.
- Headless VPS: the loopback callback cannot be reached from the owner's browser. Either
  `ssh -L PORT:127.0.0.1:PORT` or have them paste the failing redirect URL; the code is
  single-use and short-lived.
- Authorize URLs and auth.json carry tokens — never echo them; scratch copies must be wiped.
- **The upstream stream can close early**: `openai closed the responses stream before any
  terminal event (response.completed...)`. It surfaces in LiteLLM as
  `MidStreamFallbackError` and looks like a route failure. Treat it as intermittent upstream
  behaviour: retry once inside the sidecar before reporting a defect.
