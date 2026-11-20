---
name: openai-siwc-gateway
description: "Use when a subscription plan feeds third-party tools."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [openai, google, oauth, litellm, gateway, siwc]
    related_skills: [ai-stack, llm-route-bench]
---

# Sign in with ChatGPT (OSS) gateway

## When to Use

Owner asks whether a ChatGPT plan can drive a third-party agent «officially», or the grey
`chatgpt/` LiteLLM provider (device flow + `chatgpt.com/backend-api/codex`) needs a lawful
replacement. The documented path is SIWC for open-source / locally hosted apps.

Первое, что решается в любом таком вопросе, — **есть ли у вендора белый OAuth для сторонних
приложений**. У OpenAI есть (SIWC), поэтому серый провайдер меняется на белый. У Google нет —
там вопрос закрывается, см. раздел ниже.

## Two routes, one plan

- **Grey**: LiteLLM `chatgpt/` provider — device-code login at
  `auth.openai.com/api/accounts/deviceauth/*`, presents itself as `codex_cli_rs`, calls
  `https://chatgpt.com/backend-api/codex/responses`. Works, but impersonates an official
  client; can be closed by upstream without notice.
- **White (SIWC)**: dynamic client registration → PKCE → `POST https://api.openai.com/v1/responses`
  with the OAuth access token. Docs explicitly forbid pointing this flow at `backend-api`.

## SIWC facts that matter (verified Oct 2026)

Endpoint URLs, client id and model ids read from the live auth flow — the bridge must match them exactly.

Full text → [references/siwc-facts.md](references/siwc-facts.md)

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
  *groups*, not for ranking legs of the same group. **Every leg of a mixed group needs an explicit
  `order`**: a leg left at `None` is dropped from selection the moment any sibling declares one
  (see the `order` pitfall below), so «grey `order: 1` / bridge without order» silently means
  «grey only» — and `/model/info` still shows the bridge unblocked and healthy.
- **A group leg must be usable by the clients that will hit it.** An OpenCode-backed leg needs
  `x-opencode-session`; if it has to serve non-OpenCode clients, inject it in
  `litellm_params.extra_headers` when creating/updating that deployment — otherwise every call
  lands on `400 MissingSessionID`.
- **Prove which leg served from `LiteLLM_SpendLogs`, not from the log body.**
  `docker logs litellm | grep provider=` names the provider, never the deployment, and a group can
  hold two legs of the same provider. One query per group settles it:
  `sudo -u postgres psql -d litellm_db -Atc "select coalesce(\"api_base\",'-'), model, count(*),
  round(sum(spend)::numeric,4) from \"LiteLLM_SpendLogs\" where \"startTime\" > now() - interval
  '24 hours' and model like '%<slug>%' group by 1,2 order by 3 desc"` — one row per leg, with the
  upstream URL and the money. A leg missing from that result served nothing, whatever
  `/model/info` claims about it.
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

## Учебный прогон квоты (сквозной, без ожидания реального отказа)

Quota cannot be summoned on demand, so the fallback chain is debugged by injecting the same event: a second bridge instance with `SIWC_FAKE_QUOTA=1` on its own port.

Full text → [references/quota-drill.md](references/quota-drill.md)

## Media on the bridge

- **The bridge carries images now, and that matters for route order.** `convert_messages` builds
  `input_text` + `input_image` parts for user messages (`image_url` may be a dict or a string, data
  URL or `/api/v1/files/...`). Before this patch it joined `p.get('text')` and silently dropped every
  image, so the white route was blind while the grey one was not — and a blind primary looks like
  "the model forgot how to see pictures".
- **White primary, grey fallback**: per group set the bridge deployment `order=1` and the `chatgpt/`
  one `order=2`. Every leg needs an explicit order — a leg left at `None` disappears the moment a
  sibling declares one.
- **`/model/update` bookkeeping does not always reach the router.** The DB and `/model/info` show the
  new order, yet calls die with `429 No deployments available ... cooldown_list=[]` (a blocked grey
  sibling + an in-memory leg still at `order=None`). Reliable fix: `/model/delete` the leg and
  `/model/new` it again; a bridge leg needs `api_key` (any string) or the upstream client complains
  `AuthenticationError: The api_key client option must be set`.
- **Restarting the unit is enough for code changes** — but check both binds afterwards
  (`172.17.0.1:4010` and `127.0.0.1:4010`), and probe with a real PNG: `prompt_tokens` ~670 means the
  image arrived, 13–19 means it was dropped again.

## Google (Gemini / Antigravity): подписка в API не проносится

Белого OAuth-пути нет: официального способа кормить стороннее приложение квотой AI Pro/Ultra не
существует. Поэтому «вытащим JWT и refresh, напишем скрипт» здесь не серяя зона, а прямо названное
в ToS нарушение: Antigravity OAuth в чужом софте и harvest Gemini CLI OAuth караются до постоянного
бана, а баны идут по общему бэкенду и задевают CLI и Code Assist заодно. Отвечать на такой запрос
надо вердиктом «нет» с механизмом, а не планом реверса.

Легальный маршрут зеркальный: не «подписка в наш шлюз», а **наш хост в их клиенте** — официальный
CLI крутится на сервере с зарубежным адресом, владелец ходит в него по SSH. Механика входа, keyring,
гео-гейт по IP, уровни квот и граница «свой клиент да / чужой прокси нет» →
[references/google-plans.md](references/google-plans.md); привязка egress отдельного юзера к нужному
адресу — `scripts/pin-egress-uid.sh` (см. тот же файл).

## Pitfalls

First one after any host reboot: check **both** binds, not `systemctl is-active`.

Full text → [references/pitfalls.md](references/pitfalls.md)
