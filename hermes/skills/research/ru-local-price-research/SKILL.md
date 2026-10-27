---
name: ru-local-price-research
description: "Use when pricing or comparing city stats in RU."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Research, Russia, Pricing, LocalServices, YandexMaps]
    related_skills: [blocked-page-recovery]
---

# RU Local Price Research

Task shape: "изучи цены <чего-то> в <городе>, посоветуй где дороже берут / дешевле отдают".
The answer is a verdict with named places and a number, not a list of links.

## When to Use

- "где дороже берут / куда сдать / сколько стоит" anything in a named Russian city
  (ломбарды и скупка металла, ремонт, услуги, товары).
- Comparing local vendors before recommending one, especially when the user wants a
  single pick rather than a survey.
- Whenever a shop's own advertised price would otherwise be repeated as fact.
- **Comparing cities by a local metric** ("где пробки злее — Краснодар или Новосибирск?",
  "где дороже жизнь"). Same shape: verdict first line, one number per side, one reason.
  Congestion sources: `references/city-traffic-ru.md`. Cost of living, rent, real estate,
  climate, fares and intercity travel: `references/city-comparison-ru.md`.
- **Family relocation / long two-city comparison report** — different deliverable, not a
  verdict line. Load `city-relocation-report`; use this skill only for its numbers.

## Procedure

1. **Anchor first, shops second.** Get the official/reference price before reading any
   vendor site — vendor sites quote marketing numbers that are months stale
   ("цена от 2400 ₽/г" sitting next to a 10 000 ₽/г market).
   - Gold/silver/platinum: CBR metals XML (per gram of PURE metal, cp1251):
     ```bash
     curl -s "https://www.cbr.ru/scripts/xml_metall.asp?date_req1=DD/MM/YYYY&date_req2=DD/MM/YYYY" \
       | iconv -f cp1251 -t utf-8 | grep -oE 'Date="[0-9.]+" Code="1"><Buy>[0-9,]+' | tail -3
     ```
     `Code=1` gold, `2` silver, `3` platinum, `4` palladium. Convert to a fineness:
     585 → ×0.585. Cross-check USD/RUB from `https://www.cbr-xml-daily.ru/daily_json.js`.
   - For other domains use the exchange/regulator/tariff source of that market, never a
     seller's own "от".

   Then fix which question it is — **сдать** (scrap) or **купить** (retail). Scrap anchors on
   melt and shop buy rates; retail anchors on melt × retail multiple + stones + work and
   never on scrap rates. Retail procedure and source list:
   `references/jewelry-retail-ru.md`.

2. **Pull real local vendors from Yandex Maps.** Its search pages are server-rendered:
   plain curl + tag stripping returns shop names, ratings, addresses AND the promo price
   snippets (e.g. `Special offer: Увеличили оценку золота 585 до 6 200 ₽/г`).
   ```bash
   curl -sL -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36' \
     "https://yandex.ru/maps/35/krasnodar/search/<urlencoded-query>/?ll=38.975%2C45.035&z=12" -o /tmp/ym.html
   ```
   Then strip `<script|style>` → tags → collapse whitespace and read the text; also regex
   `/maps/org/[^"]+/\d+` for org ids. Per org, fetch `/prices/` (full tariff list, often
   sourced from the business itself and dated) and `/reviews/` (real deals, staff, whether
   they actually pay). Krasnodar city id is 35; swap slug and id for other cities.

3. **Verify the vendor really operates in the city.** Federal chains publish one rate
   site-wide but may have no branch nearby (check the site's city list — "52 филиала в 18
   городах" does not include every city). Cross-check the address on Maps.

4. **Separate three different numbers** before recommending:
   - list/promo ceiling ("до 6 200 ₽/г", "7 100 ₽ за первый грамм") — usually a loan
     valuation or a first-unit promo;
   - what an ordinary transaction actually pays;
   - what lands in the client's hand after spread, minimums and deductions.
   Never report a ceiling as the expected payout.

5. **Answer format** (Vladislav's preference): verdict in the first line naming the place;
   then anchor price + math; then 3-5 concrete places with address and the number each
   advertises, marked published vs expected; expected net range; one short script of what
   to ask on the phone. Plain Russian, no jargon, date every price.
   Follow-ups inside the same topic ("а крестик возьмут?", "а сколько это в розницу") get a
   short direct answer from data already gathered — do not restart the research pipeline.
   For city-vs-city comparisons: verdict in the FIRST line ("Краснодар злее"), then one
   annual/sustained metric per city with its source and year, then the structural reason,
   then one practical clause (where/when the pain actually hits). Two sources with
   different methodologies beat one ranking — say so if they agree.
   When the owner reacts to the retail-vs-scrap gap ("сдавать за 12 изделие за 50"), answer
   with the decomposition (metal / melee stones / work / brand) in one screen and move
   straight to the urgency question — no defending the shop, no sympathy paragraph. If the
   money is needed today, recommend залог over продажа: order of options in
   `references/gold-scrap-ru.md`.

## Pitfalls

- **Per-city subdomain lead-gen fleets masquerade as local shops.** Domains like
  `resurs-gold.ru`, `krd.region-zoloto.ru`, `krasnodar.centre-zoloto.ru`, `vip-faberge.ru`
  clone one page across dozens of cities, carry generic reviews, publish an absurdly low
  "от" price, and have no office. Tell: city switcher with 30+ cities, identical text,
  only a callback form. Never recommend them as a place to walk into.
- **Yandex Maps prices are frequently loan valuations** (залог), not purchase prices.
  Quote them as "оценка", and state that outright sale pays ~10-15% less unless confirmed.
- **Check the curl HTTP code before parsing.** A failed fetch leaves the previous
  `/tmp/x.html` in place, so a tag-stripper happily prints the last page and the numbers
  look plausible but belong to another vendor/city. Fetch with `-w '%{http_code}'`.
- **Prices move daily.** Recompute the anchor the day of the answer; call out moves
  ("за неделю −7%") instead of reusing week-old scraped figures.
- Small ticket sizes flip the ranking: first-unit promos and minimum weights beat the
  best per-gram rate. Always model the user's actual quantity.
- **A city summary card is not a data table.** Skokstoit-style blocks render blanks and
  placeholder arithmetic ("Аренда 1-к — ₽/мес", "индекс 7 294 ₽") that look like real
  numbers once the markup is stripped; take each metric from its own section page and
  sanity-check it against a second source.
- **Rosstat secondary and listing newbuild prices measure different things** (registered
  deals vs asking prices). Never average them; report both and say which one the swap
  arithmetic uses.

## Reference

- `references/gold-scrap-ru.md` — pawn-shop mechanics for gold/silver in Russia: melt
  math, залог vs скупка, white-gold deductions, hallmark/weight checks.
- `references/city-traffic-ru.md` — congestion/город metrics: which sources render
  server-side, what parses, and why TomTom's own site does not.
- `references/city-comparison-ru.md` — the rest of a city comparison: rent, real estate
  (Rosstat vs listings), climate normals, fares, rail/flight between cities, sources that
  block a datacenter IP.
- `references/jewelry-retail-ru.md` — what new jewelry costs to BUY: price model
  (melt × multiple + melee + work), segment ladder, producer sites whose prices parse.
