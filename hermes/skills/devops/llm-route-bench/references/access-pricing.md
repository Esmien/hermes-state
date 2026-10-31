# Access & pricing of frontier models

Use when the owner asks where to get a model cheaper, whether a subscription is worth
it, or what a plan actually includes. Re-verify numbers at the vendor's own docs before
quoting — the ladder changes, the *structure* below does not.

## Always cost per successful task, never per token

Sticker price says nothing about the bill: cache hits, reasoning tokens and context
length move it 5-10x. Compare $/success like `ab_bench.py` does.

## OpenAI ladder (GPT-6.1 Sol, Standard, per 1M tokens)

- input $2, **cached input $0.10** (5% of input), cache write $2.50, output $10
- above 272K input tokens the **whole request** moves to $4 / $15 — trim context
  instead of paying the cliff
- Batch and Flex are **50% off**; Fast is 2x; Ultrafast 6x
- reasoning tokens bill as output, so `reasoning_effort` is the biggest single lever

Siblings: GPT-6 Astra $10/$50 (flagship), GPT-6.1 Terra and GPT-6 Luna far cheaper.

## Saving levers, in order

1. **Stable prefix / prompt cache.** In an agent loop this is the whole game: effective
   input can fall to a few percent of sticker.
2. **Stay under the long-context threshold.**
3. **Batch/Flex for anything non-interactive** — test sweeps, bulk generation.
4. **Subscription instead of API** for interactive agent work (flat, no long-context
   surcharge). Sign the CLI in with the plan account, not an API key, or you pay twice.
5. **Cheaper sibling for easy tasks**; reserve the frontier model for hard ones.

## Subscriptions: what a plan really gives

ChatGPT (verify at `learn.chatgpt.com/docs/pricing` and the help-center article
"GPT-6 and other models in ChatGPT"):

- Work and Codex **share one allowance**; Chat is pooled separately.
- Plus, local messages per 5-hour window: Sol 15-160, Astra 5-45, Terra 35-285,
  Luna 350-3000. Weekly cap on top. Fast mode consumes 2.5x. Ultrafast is Pro $500+.
- Plus is positioned as «a few focused coding sessions each week» — not a daily driver.
- **Model by surface matters:** plain Chat runs GPT-6 (= 6 Sol at Medium/High on Plus);
  6.1 Sol, 6.1 Terra and Astra exist only in Work and Codex. «Купил Plus, а 6.1 Sol нет
  в меню» is product design; switch to Work or use the Codex client, and update the
  client — stale desktop builds hide new models.

Google: AI Pro ~$19.99 includes Gemini 4 Argon in the Antigravity app and CLI; limits
are published as «more rate limits» plus a credit pool, not as numbers — say so rather
than inventing a count.

Claude:

- **Free** is a real $0 plan, no fixed published count: a rolling 5-hour allowance,
  ~15-40 messages, ~30-100/day, and it scales down with long chats, attachments and
  extended thinking. Sonnet + Haiku, 1M context; Opus/Fable are paid. No Claude Code,
  no API credits, no Console access — so there is nothing to plug into a coding client.
- **Pro $20** = claude.ai plus the official Claude Code, under session and weekly caps.
  It explicitly does **not** include Console API usage (Anthropic's own help centre says
  so) — API is a separate wallet billed per token, with a small minimum top-up.
- **Max** buys more quota on the same products, still not API.
- Quote the planes the owner actually needs: «подписка даёт X» and «API даёт Y» are two
  separate purchases, and paying for one never satisfies the other.

## Subscription → third-party client: the vendor matrix

The recurring question is «вот у меня подписка, подключу её в OpenCode / Cline / агент».
Answer from this rule, not from the client's feature list:

- **Subscription ≠ API key.** No consumer plan of any vendor converts into an API
  credential; API is metered billing in the vendor console. Anything claiming otherwise
  is a proxy, a resale, or a ToS violation.
- **Subscription OAuth in third-party clients is a per-vendor permission, and most
  vendors revoked it.** Anthropic blocked subscription OAuth for third-party tools — only
  the official Claude Code works on a Pro/Max account; proxy plugins that re-add it are a
  ban risk. Google shut the consumer-tier path down (AI Pro / Ultra / Code Assist for
  individuals), breaking the OpenCode Gemini-OAuth plugins, and its CLI FAQ calls
  piggybacking on that OAuth a terms violation. OpenAI still lets Codex OAuth serve
  OpenCode through the plan allowance — that is the exception, not the pattern.
- **OpenAI's exception has two shapes, and they are not equivalent.** The documented one is
  Sign in with ChatGPT for open-source/self-hosted apps: dynamic client registration, PKCE,
  `resource=https://api.openai.com/v1`, inference on `POST /v1/responses` with `store:false`
  and `stream:true`. The other is the device-code flow behind the `chatgpt/` provider, which
  masquerades as `codex_cli_rs` against `chatgpt.com/backend-api/codex` — the docs for the
  first shape explicitly forbid pointing at `backend-api`. When answering «мы же легально?»,
  say which shape the stack actually uses before giving any verdict; details and the check
  recipe are in `references/subscription-routes.md`.
- **Order of checks before saying yes:** does the plan include an API/Console account
  (no → stop), does the vendor allow plan OAuth outside its own client (no → stop), is
  there an official first-party CLI that the client merely wraps (that is the only
  supported shape).
- **Never present a proxy/plugin workaround as the answer.** Name it once as a ToS/ban
  risk with no support, then give the supported route: vendor API key, or the vendor's
  own CLI on the plan.
- Subscription caps are anti-arbitrage, not stinginess: agentic runs are tens of
  thousands of tokens per task, so a flat $20 on agent traffic is instantly unprofitable
  and gets closed the moment it is used. Say this plainly when the owner reads the
  restriction as «душат обычных юзеров» — the $20 tier is a funnel into Max and API, and
  enterprise seats plus API volume are where the vendor's revenue actually is.

## RU resellers

- Markup math: their ₽/1M ÷ (official $/1M × FX). ~2x is typical (ProxyAPI);
  `api-rank.com` publishes multipliers per model to cross-check.
- «от N ₽/1M» is the teaser component (cached input), not the rate you will pay.
- You are buying the payment channel and no-VPN access, not the model. For an owner who
  already has cards/routes abroad, the reseller is strictly worse.
- Shared/second-hand accounts are a ToS violation with a stranger holding the key —
  mention once as a non-option, do not price it.

## Answering «я не зря заплатил?»

Verdict first, then one number that decides it, then the concrete move. If the purchase
was already made: say what it is worth as flat-rate capacity, and how to squeeze it
(right client, right surface, cheap settings). Sunk cost gets a straight answer, not
comfort.
