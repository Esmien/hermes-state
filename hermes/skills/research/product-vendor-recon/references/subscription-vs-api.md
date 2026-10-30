# Subscription vs API: платить или считать, и как подключить

Depth for SKILL.md step 8. Numbers below are a snapshot of the OpenAI price
list at the time of writing — always re-check the vendor's model page before
quoting them, but the STRUCTURE (tiers, surcharges, shared allowances) is what
you actually reason with.

## Rate structure worth memorising

- Standard: input $2 / cached input $0.10 (5%) / cache write $2.50 / output $10
  per 1M. Reasoning tokens bill as OUTPUT — `reasoning_effort` is a bigger cost
  lever than prompt length.
- Above ~272K input tokens the WHOLE request re-prices (2x input, 1.5x output).
  Staying under the threshold beats trimming cleverly.
- Batch and Flex = −50%; Fast = 2x; Ultrafast = 6x. Subscription allowance burns
  at 2.5x in Fast.
- Subscription (Plus-tier) coding allowance, per 5 hours, shared by every
  surface of that vendor (its chat Work mode, its CLI, and any third-party
  agent signed in with the same account): flagship 5–45 messages, main coding
  model 15–160, cheap tier 35–285, cheapest 350–3000. Weekly cap on top.
- Included allowance carries no long-context surcharge; credits and API usage
  do.

## Break-even, in one line

One real agent task ≈ 8–15 requests × 30–50K context. Uncached that is
$0.5–1.5 per task; with a stable cached prefix, 2–3x less. So a $20–27/month
subscription pays off at roughly 20–40 tasks per month — below that the API is
cheaper, above it the subscription is the bulk discount. Say the threshold, not
«дешевле/дороже».

Cheap levers, best first: cached prefix (never edit the head of the prompt),
stay under the long-context threshold, Batch for everything non-interactive,
low reasoning effort for routine work, and route routine tasks to the cheap
sibling model instead of the flagship.

## Wiring a coding subscription into an agent stack (verified)

Hermes → the vendor's own OAuth provider, no API key:

```bash
hermes auth add openai-codex --type oauth --no-browser   # prints link + code
hermes config set model.aliases.sol openai-codex/gpt-6.1-sol
hermes chat -q "Reply with exactly: OK" -m sol
sqlite3 $HERMES_HOME/state.db \
  "select session_id, model, billing_provider from session_model_usage order by rowid desc limit 3"
```

The alias switches per session; the default route stays as configured. Always
verify in `state.db` — a silent fallback otherwise looks like success.

OpenCode → first-class, no plugin:

```
opencode → /connect → OpenAI → "ChatGPT Plus/Pro" → browser login → /models
```

A generic OpenAI-compatible client with no OAuth support can still be pointed
at `hermes proxy`, which exposes the OAuth-backed provider as a local OpenAI
endpoint.

Warn in the same breath: all these surfaces share ONE allowance. Three tools
signed into one account are one quota split three ways, not three quotas.

## «Модели нет в списке» — сначала каталог, потом план

Agent CLIs (OpenCode and friends) do not hardcode model ids: they snapshot the
models.dev registry into a local cache on start. A model released after that
snapshot is simply absent from `/models` — the account may well have access.

Order of checks, cheapest first:

1. Confirm the id exists in the live registry:
   `curl -s https://models.dev/api.json` → `openai.models["gpt-6.1-terra"]`.
   If it is there, the plan/account is not the problem — the client cache is.
2. Delete the cache and restart the TUI so it re-fetches:
   Linux `rm ~/.cache/opencode/models.json`, macOS
   `rm ~/Library/Caches/opencode/models.json`.
3. Only if the client is genuinely older, upgrade it — check against the
   registry first (`opencode --version` vs the npm `opencode-ai` latest), because
   «upgrade» on an already-latest build changes nothing and wastes the owner's
   patience.
4. Declaring the model under `provider.<name>.models` in `~/.config/opencode/opencode.json`
   is a fallback for ids the registry lacks, not a fix for a stale cache — and
   it must land in the GLOBAL config, not a project-level `opencode.jsonc`.

## Rate structure worth memorising

## Pitfalls

- Never promise an API from a chat subscription. OAuth-in-third-party-tool is
  tolerance, not a contract; it breaks silently when the vendor changes auth.
- A subscription's newest model may live on only one surface (Work/CLI) and be
  absent from plain chat — that is product design, not a bug; check the
  availability table before debugging the user's client.
- Within chat, a single menu entry can BE the coding model: a generically named
  entry (`GPT-6`) maps to the coding model at several thinking levels, while the
  top level (`Pro`/Extra High) silently switches to the flagship. Read the
  vendor's model page before telling the owner which weights answer them.
- The sticker price is not the real one: cache hits, reasoning effort and the
  long-context threshold move the bill several-fold in either direction.
- Refunds: a RU reseller usually keeps the money; the vendor's own billing may
  refund within its window. Do not promise a refund — tell the owner to stop
  auto-renew and measure the paid month.
