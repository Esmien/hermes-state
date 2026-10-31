# Subscription-backed routes: what is under the name, and what is official

Use when a route is supposed to spend a ChatGPT plan instead of API credit, or when the
owner asks «куда реально уходят запросы» / «это вообще легально». The name on the route
tells nothing: `openai/gpt-6.1-sol` can be the paid API or the subscription backend.

## 1. Resolve every route to its real upstream

```bash
K=$(grep -m1 '^LITELLM_MASTER_KEY=' /home/ai_service/ai-stack/ai/.env | cut -d= -f2-)
curl -s -H "Authorization: Bearer $K" http://127.0.0.1:4000/model/info | python3 -c "
import sys,json
for m in json.load(sys.stdin)['data']:
    lp=m.get('litellm_params',{}) or {}
    print(m['model_name'], '->', lp.get('model'))
" | sort -u
```

`model_name` is the public alias, `litellm_params.model` is the provider that actually
serves it. `openai/gpt-*` mapping to `chatgpt/*` means plan quota; mapping to
`openai/*` means metered API. Print the mapping before answering anything about billing.

## 2. The `chatgpt/` provider in LiteLLM is the Codex backend, not the API

Verified by reading the installed package, not the docs (paths are version-specific —
grep for them instead of trusting these line numbers):

```bash
docker exec litellm sh -c 'grep -rn "CHATGPT_API_BASE\|DEFAULT_ORIGINATOR\|deviceauth" \
  /app/.venv/lib/python3.13/site-packages/litellm/llms/chatgpt/common_utils.py'
```

- `CHATGPT_API_BASE = https://chatgpt.com/backend-api/codex` → inference goes to
  `/responses` there. `api.openai.com` is not involved at all.
- Auth is the **device-code** flow: `auth.openai.com/api/accounts/deviceauth/usercode` →
  `/deviceauth/token`, then a refresh token in `/tokens/auth.json`
  (`access_token`, `refresh_token`, `id_token`, `account_id`, `expires_at`).
- `DEFAULT_ORIGINATOR = codex_cli_rs` plus a Codex-shaped User-Agent: the proxy presents
  itself as the official Codex CLI. That is the part with the ToS exposure — the requests
  look like a first-party client on a private backend.
- `/v1/chat/completions` is bridged to Responses internally; there is no chat backend.
- Consequence to say out loud: no API key, no per-token billing, spend is plan quota. And
  the failure mode is a one-commit shutdown of every `chatgpt/*` route at once — Claude
  and Google already did exactly that to their OAuth clients.

## 3. The documented path exists: Sign in with ChatGPT (SIWC) for OSS

OpenAI publishes an OAuth flow for open-source / self-hosted apps that spends the user's
plan through the **public** API. It is a different animal from the device flow above, and
its docs say explicitly: use `https://api.openai.com/v1/responses`, do **not** point this
flow at ChatGPT's `backend-api`.

Authorization (`https://auth.openai.com/api/accounts/authorize`, URL-encoded):

- `client_id=dynamic_agent_client` for first registration; the callback returns the issued
  `client_id` (`oaiapp_...`) — store that one, never `dynamic_agent_client`.
- `agent_name_hint` (app name), `ext_agent_host_id` (stable per host, e.g. `urn:uuid:<machine-id>`).
- `response_type=code`, `state`, `nonce`, `code_challenge_method=S256`, `code_challenge`.
- `scope=openid profile email offline_access resource.invoke chatgpt.tokens.use.direct`.
- `resource=https://api.openai.com/v1`.
- `redirect_uri` — HTTP loopback on `127.0.0.1` only, e.g.
  `http://127.0.0.1:1455/auth/callback`; scheme/host/path fixed, port may vary, `localhost`
  is not accepted. On a headless VPS the browser cannot reach that callback: either
  `ssh -L 1455:127.0.0.1:1455` from the workstation, or have the owner paste the failed
  redirect URL back (code is single-use and short-lived).

Exchange: form-encoded `authorization_code` grant to
`https://auth.openai.com/api/accounts/oauth/token` with `client_id`, `code`,
`code_verifier`, the same `redirect_uri` and `resource`. No client secret.
Inference: `GET /v1/models` (keep `visibility == "list"`, use `slug` as `model`), then
`POST /v1/responses` with **`store: false` and `stream: true` mandatory**, token as bearer.

## 4. Before promising a bridge, test tool calling

A Responses-only upstream means LiteLLM has to bridge chat→responses, and that bridge is
where function calls die (the model sees namespaced tools and answers in prose). So the
cheap experiment is not «build the bridge», it is: one SIWC token, one `/v1/responses`
request with a single `strict` function tool, consumed as SSE, looking for an
`response.output_item.done` event whose item is `function_call` with the right name and
JSON arguments. `function_call` present → the bridge is worth building; prose only →
migrating is pointless regardless of how official the flow is, and the plan stays on the
current route with a known risk.

## 5. Do not accept a second-hand description of our own config

The owner may paste another model's audit (including a confident one with links) that
claims something about this stack. Verify by reading the installed package and
`/model/info` before agreeing or disagreeing; a correct general statement («there is an
official OAuth for OSS») does not decide the specific one («our provider uses it»). Report
file + constant names as evidence, and keep the verdict to what was actually observed.
