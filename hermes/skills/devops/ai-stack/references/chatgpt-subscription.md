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

1. **Version gate first.** The provider is documented against LiteLLM >= 1.106 and
   needs the `mcp` package (`pip install 'litellm[proxy]'` pulls it). This stack is
   pinned to an older tag — check inside the container before promising anything:
   `docker exec litellm python -c "import litellm.llms.chatgpt; print('ok')"`.
   Missing → bump deliberately per `references/updates.md`, never with a rolling tag.
2. **Log in OUTSIDE the proxy.** Workers have no terminal for the device code; the
   login must already exist on disk when the proxy starts.
   `python -c "from litellm.llms.chatgpt.authenticator import Authenticator; Authenticator().get_access_token()"`
   → prints URL + code → tokens land in `~/.config/litellm/chatgpt/auth.json`
   (override with `CHATGPT_TOKEN_DIR` / `CHATGPT_AUTH_FILE`).
3. **Mount that file writable** into the litellm container (`chown 65534` for the
   non-root image). Access token ~10 days; the refresh token is single-use, so a
   read-only copy dies at the first refresh. One file shared by every worker —
   separate copies diverge and only one survives.
4. **Add the route** to the model list used by the gateway:
   `model_name: gpt-6.1-sol` / `model_info: {mode: responses}` /
   `litellm_params: {model: chatgpt/gpt-6.1-sol}` (same for `gpt-6.1-terra`,
   `gpt-6-luna`, `gpt-6-astra` — only ids the account's plan actually serves).
5. **Restart, then prove it** with a real request (`/v1/responses`, one short
   prompt) before telling the owner it works.

## Hard limits of the bridge

- **One ChatGPT login per proxy process.** Every virtual key, user and team then
  spends that one account; a second person's subscription needs a second
  deployment.
- **No price in the cost map** → recorded spend is $0 and `max_budget` never
  fires. Cap with `rpm_limit` / `tpm_limit` per key, or one consumer drains it.
- **Backend rejects** `max_tokens`, `max_output_tokens`, `max_completion_tokens`
  and `metadata`; LiteLLM strips them. It also rejects `temperature` for these
  models — the stack's `drop_params: true` is what keeps Open WebUI from 400ing.
- **The allowance is the Codex/Work quota** (≈15–160 Sol messages per 5 h, shared
  weekly pool). It is the same pool Codex CLI, OpenCode and Hermes spend — a chat
  UI on this route is eating coding quota.
- **Failure modes**: `ChatGPT device-code login needs a human` or `There are no
  healthy deployments` = no/expired auth.json (re-login outside, replace the
  file, restart). There is no logout/revoke call — delete the file and sign the
  session out on OpenAI's side.

## Exposure policy

Personal subscription, personal risk: sharing it with other people is a terms
breach whose cost lands on the owner's account, not on the users. Allowed shape —
VPN/LAN only, per-consumer virtual keys with rpm/tpm caps, no `0.0.0.0` binding, no
scripted loops (steady identical traffic is what automation looks like; a couple
of humans typing is not). Do not build features that assume this route survives a
vendor auth change.
