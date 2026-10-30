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
