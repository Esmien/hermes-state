# ChatGPT/Codex subscription as a stack route

Deep dive for: «отдать подписку ChatGPT как OpenAI-совместимый API» / «добавить
Sol 6.1 в Open WebUI». LiteLLM ships a native provider for this — no third-party
shims. Everything below is LiteLLM's documented behaviour; re-check the provider
docs before quoting numbers.

## Shape

`chatgpt/` provider → `https://chatgpt.com/backend-api/codex` (the Codex backend,
not api.openai.com), device-code OAuth. The proxy exposes `/v1/responses` and
`/v1/chat/completions` (chat is bridged to Responses). Open WebUI then sees these
models through the normal LiteLLM connection — no OWUI-side hack.

## Procedure

1. **Version gate first.** `chatgpt/` ships in LiteLLM >= 1.106 (needs the `mcp`
   package, already inside the image). This stack runs v1.106.6; there is no
   `python` on the container PATH, so probe with its venv interpreter:
   `docker exec litellm /app/.venv/bin/python -c "import litellm.llms.chatgpt; print('ok')"`.
   Missing → bump deliberately per `references/updates.md`, never with a rolling tag.
2. **Log in OUTSIDE the proxy, from a throwaway container.** Workers have no
   terminal for the device code. The image ENTRYPOINT is the litellm CLI, so
   `docker run <img> /app/.venv/bin/python …` fails with `Unknown command:
   /app/.venv/bin/python` — always pass **`--entrypoint`**:
   ```bash
   mkdir -p /root/litellm-chatgpt
   docker run --rm --entrypoint /app/.venv/bin/python \
     -e CHATGPT_TOKEN_DIR=/tokens -v /root/litellm-chatgpt:/tokens \
     ghcr.io/berriai/litellm:v1.106.6 -c \
     "from litellm.llms.chatgpt.authenticator import Authenticator; Authenticator().get_access_token(); print('LOGIN_DONE')"
   ```
   The flow is non-interactive: it prints a URL + a code the owner enters in the
   browser (code TTL ~15 min), so run it backgrounded, relay the code, wait for
   `LOGIN_DONE`. Result: `/root/litellm-chatgpt/auth.json` with `access_token`,
   `account_id`, `refresh_token`, `expires_at`. The owner cannot do this from the
   admin UI — say so plainly instead of hunting for a button.
3. **Mount that dir writable** into the litellm service: compose volume
   `/root/litellm-chatgpt:/tokens` + env `CHATGPT_TOKEN_DIR: /tokens` (the root
   image needs no `chown 65534`; the `-non_root` image does). Access token ~10
   days, refresh token single-use and written back into the same file, so a
   read-only mount dies at the first refresh.
4. **Discover the account's model list from the backend, do not guess ids** —
   section below — then add the routes.
5. **Prove BOTH doors** with a real request before reporting success:
   `/v1/responses` (native) and `/v1/chat/completions` (bridged). Use
   `max_tokens` >= 100: a reasoning model given a tiny budget returns
   `content: null` with the text in `reasoning`, which is not a failure.

## Model catalog — ask the backend, never guess

The Codex backend lists what the signed-in plan actually serves. Run it through
the container interpreter, with `Authorization: Bearer <access_token>` plus
`ChatGPT-Account-Id` from `auth.json`:

```python
# docker cp a script in, or -c one-liner with the image's venv python
d=json.load(open('/tokens/auth.json'))
h={'Authorization':'Bearer '+d['access_token']}
if d.get('account_id'): h['ChatGPT-Account-Id']=d['account_id']
urllib.request.urlopen(urllib.request.Request(
  'https://chatgpt.com/backend-api/codex/models?client_version=1.0.0', headers=h))
```

- **`client_version` is mandatory** — without it the call 400s with
  `missing … ('query', 'client_version')`.
- Each entry carries `slug`, `display_name`, `context_window`,
  `supported_reasoning_levels` — use those instead of hardcoding model ids or
  context sizes in docs.
- The list is a superset of what is sensible in a chat UI: besides the current
  GPT-6.x family it returns reserve and internal entries (e.g. `gpt-reserve`,
  `codex-auto-review`). Add the chat models; leave the internal reviewer out and
  say why.
- A model's *availability tier* differs from its id: `-pro`, `-fast`, Ultrafast
  are plan/price variants, not separate deployments. Do not add them as routes.

## Adding / removing routes in the DB

`STORE_MODEL_IN_DB=True`, so routes are DB rows, not `config.yaml` — add and
remove them through the proxy API with the master key (`/model/info` lists rows
with their ids):

- add: `POST /model/new` with `{"model_name": "gpt-6.1-sol", "litellm_params":
  {"model": "chatgpt/gpt-6.1-sol"}, "model_info": {"mode": "responses"}}`. Do not
  hand-set `api_base` — the provider already knows the Codex endpoint, and an
  explicit one only creates a second, subtly different deployment.
- remove: `POST /model/delete` with `{"id": "<uuid>"}`.
- **Two rows with the same `model_name` are not an error** — LiteLLM treats them
  as two deployments of one group and load-balances/fails over. It still looks
  like a bug in the admin UI, so after any batch add, count rows per
  `model_name` via `/model/info` and delete the duplicate.
- Adding routes needs no restart; Open WebUI picks the new names up on refresh.
- Verified on 1.106.6: every `chatgpt/` model answers on both `/v1/responses` and
  `/v1/chat/completions`, and `temperature` / `max_output_tokens` ride through
  because `drop_params: true` strips them before the backend sees them.

## Hard limits of the bridge

- **One ChatGPT login per proxy process.** Every virtual key, user and team then
  spends that one account; a second person's subscription needs a second
  deployment.
- **The provider reports zero cost; the value has to be injected.** Cost map prices for these slugs exist (per 1M: 6.1 Sol $2/$10, 6.1 Terra $1/$5, Astra $10/$50, Luna $0.10/$0.50, 5.6 Sol $4/$20, 5.6 Terra $2/$12, 5.6 Luna $0.20/$1.20 — read them from `litellm.model_cost` inside the image rather than trusting this list), but the `chatgpt/` provider is subscription-mode and reports zero, so nothing is priced unless each deployment carries explicit `input_cost_per_token` / `output_cost_per_token` / `cache_read_input_token_cost`. Those numbers are a **shadow value** — the plan is flat-rate and the quota is per message — so rpm/tpm stays the real guard; the dollar figure is for «кто сколько сожрал» and for comparing subscription vs API cost.
- **Setting the rates is not the same as getting them applied — always verify in SpendLogs.** On v1.106.6 a deployment can show non-zero rates in `/model/info` and still log every request at `$0` with `Billable request priced at $0 … pricing entry '<uuid>' declares non-zero rates … reason="pricing_not_applied"`. The same warning appears on unrelated `hermes.deepseek/*` rows, so it is a cost-calculator path problem, not a per-model mistake. After any pricing change send one request and read `LiteLLM_SpendLogs.spend` directly — a green `/model/info` proves nothing, and a UI showing `$0.00000000` may be the truth.

  Do not conclude from a single zero row that the calculator is broken. Recompute the
  expected figure by hand — `prompt_tokens × in_rate + output_tokens × out_rate`, with the
  per-token rates from the deployment — and issue one fresh request. A new row that matches
  your arithmetic to the cent proves the path works; only a fresh row that still logs `0`
  while the arithmetic says otherwise is a real defect. **Output drives the bill**, at 5×
  the input rate on Sol: an «объясни подробно» answer that ran to ~12.5 K output tokens
  billed ~$0.16, while a compact code answer on the same model billed ~$0.02. Explanation
  and overview questions belong on the cheaper tier (Terra/Luna) or behind an explicit
  length cap, not on the strongest coding route.
- **Reasoning text never streams, and that is upstream, not a config bug.** The Codex
  backend emits `response.reasoning_summary_text.delta` for nothing, even when the request
  asks for `reasoning: {effort, summary: "auto"}` — call it directly (bypassing the proxy)
  and the event stream contains only `output_item.added/done` with an encrypted reasoning
  item. The chat bridge then forwards that item whole as one `delta.reasoning_items` chunk.
  Practical consequence: no slider or client setting can make «думает» appear progressively;
  offer a elapsed-time indicator instead, and read `reasoning_tokens` from usage when you
  need to know how much thinking was bought.
- **Backend rejects** `max_tokens`, `max_output_tokens`, `max_completion_tokens`
  and `metadata`; LiteLLM strips them. It also rejects `temperature` for these
  models — the stack's `drop_params: true` is what keeps Open WebUI from 400ing.
- **The allowance is the Codex/Work quota** — the same pool Codex CLI, OpenCode
  and Hermes spend, so a chat UI on this route eats coding quota. Plus-era
  estimates per 5 h (local messages): Astra 5–45, Sol 6.1 15–160, Sol 6.0 15–150,
  Terra 35–285, Luna 350–3000; a weekly cap applies on top without a published
  number. Order answers by cost: Luna/Terra first, Astra last.
- **GPT-6.1 Sol is not a Chat model.** OpenAI exposes 6.1 Sol and 6.1 Terra only in
  ChatGPT Work and Codex; Chat serves GPT-6 (6.0 Sol) and the 5.6 family. When the
  owner says «я купил Plus, а где актуальная модель» — the answer is «переключись
  на Work или в Codex», not «обнови приложение».
- **Failure modes**: `ChatGPT device-code login needs a human` or `There are no
  healthy deployments` = no/expired auth.json (re-login outside, replace the
  file, restart). There is no logout/revoke call — delete the file and sign the
  session out on OpenAI's side.

## Operating the route once it exists

- **Enumerate models from the backend, never from guesses.**
  `GET https://chatgpt.com/backend-api/codex/models?client_version=1.0.0` with the
  OAuth bearer + `ChatGPT-Account-Id` returns the real catalogue for THIS account
  (`slug`, `context_window`, `supported_reasoning_levels`). Plain `/models`
  without `client_version` is a 400.
- **Custom prices go in `litellm_params`, not `model_info`.** Passing
  `input_cost_per_token` / `output_cost_per_token` inside `model_info` on
  `/model/new` is accepted with 200 and then silently dropped — spend stays $0.
  In `litellm_params` the same keys persist and SpendLogs start pricing the
  route (verified: spend went from 0 to $0.0006 for a 2-turn test).
- **`order` in `litellm_params` = priority inside a group.** Lower runs first,
  the next order takes over on failure or 429. Since LiteLLM cannot see the
  subscription quota, the fallback only fires after the backend rejects.
- **No rename API.** Changing a deployment's `model_name` (or merging it into an
  existing group) is delete + re-add with the same `litellm_params`.
- **A group's `mode` is per-deployment.** Mixing `chat` and `responses` inside
  one group makes behaviour depend on the endpoint, so keep a group homogeneous:
  subscribe deployments join an existing chat group as `mode: chat` (the provider
  bridges to Responses internally), while a Responses-only group stays
  `mode: responses`.
- **Group naming: `<provider>/<slug>`, one `model_name` per group.** Standard
  models live as `openai/gpt-6.1-sol`, `openai/gpt-6-luna`, … so they merge into
  a group with any other deployment of the same model. Client-specific duplicates
  get their own prefix (`aider.openai/gpt-6.1-sol`) because that client picks
  models by literal name and must not fall into the chat-facing group.
  OpenRouter-backed deployments keep `openrouter/` for a different reason: that
  relay breaks native routes, so they stay on chat-completions and should not be
  mixed with subscription deployments.
- **A fallback leg can be the thing that fails.** `opencode/*` deployments demand
  `x-opencode-session` and answer `400 MissingSessionID` without it, so a group
  whose second leg is opencode works for tools that send the header and fails for
  Open WebUI. Worse, that 400 masks the primary's real error (an invalid
  parameter or an exhausted quota comes back as `MissingSessionID`). When a group
  is meant to serve the chat UI, the fallback leg must not require client
  headers — check by issuing one deliberately invalid request and reading whose
  error comes back.

## Reasoning effort on these routes

Per-model levels, read from the account's own catalogue (`supported_reasoning_levels`):
Sol 6.1 / Terra 6.1 / Astra — `low medium high xhigh max ultra`, default `low`;
Luna — `low medium high xhigh max` (no `ultra`), default `medium`. **`ultra` is not
another effort rung**: it switches to subagents, so a UI should offer
`low…max` as a slider and a separate toggle for it.

Verify that the value actually reaches OpenAI instead of dying in the proxy: send
the same small task at every level with `reasoning: {"effort": …}` on
`/v1/responses` and compare `usage.output_tokens_details.reasoning_tokens`. A
value that is dropped by LiteLLM produces identical numbers at every level; a
value that propagates gives a rising sequence, and budget models give a hard
`0` at `low`. Add a negative control (`effort: "bogus"` must 400) — that proves
validation happens upstream rather than inside the gateway.

Use a task that actually needs thinking, not `2+2`: on a trivial prompt every
level saturates in tens of tokens and the sequence proves nothing. Measured on
Sol 6.1 with a ring-buffer/ISR task (~8.8 K prompt): `medium` 516 reasoning /
26 s, `high` 907 / 32 s, `xhigh` 3915 / 114 s, `max` 4142 / 117 s. Two
conclusions that hold up in practice — **`xhigh` is the only step that changes
what the model does** (4.3× over `high`), and **`max` is decorative** (+6 %
tokens, +3 s). Offer `medium → high → xhigh` as the real ladder and treat `max`
as a comfort option, not an engineering one. **The level is a ceiling, not a quota**: the
model stops when it judges the task done, so on an easy question `high` and `xhigh` land
close together (measured: 96 vs 349 reasoning tokens on one short answer, +$0.003) while
the same pair diverges 4× on a hard one. This makes escalation cheap in the upward
direction — recommend a low default plus a manual step up instead of paying for `max` on
every request. A UI control (OWUI `model_controls`)
should map its labels onto exactly those `reasoning_effort` values, and long
labels read better in a menu than on a slider.

## Owner's model role split

Standing assignment as of Oct 2026: **Sol 6.1 = architect + reviewer** (its quota is what
the subscription is bought for), **DeepSeek-flash = bulk coding**, **Luna = fast/cheap
answers**. Consequences for advice: do not propose Sol for overviews or «объясни
подробно» (output drives the bill), and when a reviewer is involved hand it the artifact
(diff/file), never a chat summary — a reviewer without the code invents findings.

## Exposure policy

Personal subscription, personal risk: sharing it with other people is a terms
breach whose cost lands on the owner's account, not on the users. Allowed shape —
VPN/LAN only, per-consumer virtual keys with rpm/tpm caps, no `0.0.0.0` binding, no
scripted loops (steady identical traffic is what automation looks like; a couple
of humans typing is not). Do not build features that assume this route survives a
vendor auth change.
