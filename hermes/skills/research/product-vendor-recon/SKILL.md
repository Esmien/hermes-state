---
name: product-vendor-recon
description: "Use when assessing an AI product or SaaS vendor."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Research, DueDiligence, SAAS, AI, Russia]
    related_skills: [blocked-page-recovery, ru-local-price-research]
---

# Product / Vendor Recon

One-shot answer to "what is <product>, how does it work, why would I need it,
what's under the hood". Answer in Russian. Verdict in the FIRST sentence — the
user wants a call, not a table of contents.

## When to Use

- The user names a product, service or AI tool and asks what it is / whether to
  use it / "что по мозгам".
- You are about to recommend, install or pay for a third-party AI or SaaS tool
  and need to know whose model it runs and who operates it.
- A vendor's claims (made in Russia, own model, unlimited) need checking before
  they go into a report.

## Procedure

1. **Disambiguate the name before researching.** Search the bare token alone and
   with "AI". Acronyms routinely collide (a company, a university lab, a person's
   surname). If several real entities match, cover the one the context implies,
   name the other in one closing line, and never merge their facts.
2. **Map the site in one curl pass**, then convert: `/`, `/help/` or docs index,
   the pricing/limits page, `/docs/api/`, `/privacy/`, `/offer/`. Use the
   `blocked-page-recovery` skill's `scripts/html_to_text.py`
   (`python3 html_to_text.py page.html`) — no renderer needed for server-rendered
   pages. Follow the help-index links by grepping `href=` out of the saved HTML.
3. **Find the real brains, not the marketing name.** The landing page names the
   flagship model; the tier table says which plans get a different, slower one.
   The public API doc usually exposes a neutral id (`default`, `smart`) plus a
   `/models` limits block — read it to see context window, output cap and whether
   the id hides a swappable backend. Search the model name itself to place it
   (vendor, release date, price per 1M tokens, benchmark tier) before judging
   quality claims.
4. **Identify who is behind it** from the footer, not the about page: ИНН /
   ОГРН(ИП) → `https://www.rusprofile.ru/id/<ОГРН>` gives registration date,
   founders, co-owner companies, whether the entity is still active. Check the
   director's ИНН to find related entities. A brand-new shell with 10k ₽ capital
   and an established company holding a minority stake are very different risks;
   say which one it is.
5. **Trace the data path.** In the privacy policy read the cross-border section
   ("трансграничная передача"): which provider receives the content, whether the
   operator disclaims responsibility for it, whether content is stored at all.
6. **Sanity-check the ratings.** Review/rating sites are sometimes owned by the
   product's owner — they usually disclose it in small print. Treat scored
   reviews as marketing until independent ones exist; quote user reviews only as
   anecdotes, never as benchmarks.
7. **Close with fit, not features.** One paragraph: what it replaces, who it is
   wrong for, and the concrete safe setting for this user (never give a
   code agent full write access to a prod tree; keep `.env` and keys out of the
   opened folder).

## Pitfalls

- A Russian-facing wrapper is almost never a Russian model: it is a resold
  foreign API behind a local proxy and local billing. Say it plainly — it is the
  single most important fact for price, latency and blocking risk.
- "Main model is X" on the landing page does NOT mean every plan runs X. Only the
  tier table is authoritative; the cheapest tier is usually a weaker text-only
  model with a smaller context.
- Convert ₽/month to $ before comparing with foreign subscriptions; at typical
  rates a mid tier lands near a flagship chat subscription, and the limits
  (5-hour + weekly windows, like Claude Code) decide real cost, not the sticker.
- If a product asks for a review score from a site it owns, that is a disclosure,
  not a rating. Do not present it as independent validation.
- Do not infer the app stack from the file extension or install instructions —
  state only what the docs say (OS support, CLI name, API base URL).
