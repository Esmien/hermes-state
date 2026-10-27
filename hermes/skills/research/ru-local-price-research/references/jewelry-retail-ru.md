# Retail price of NEW jewelry in Russia (what it costs to buy)

Use when the question is "сколько стоит в рознице", not "сколько дадут". Scrap math does
not answer it: the same 2 g 585 cross worth ~12 000 ₽ in metal retails for 30 000–50 000 ₽.

## Model the price, do not average listings

```
retail = metal_at_retail_rate + stones_retail + work/rhodium/brand
```

- **Metal:** melt × 1.5–2.0, or the chain's own ₽/г rate for the fineness. Melt is per gram
  of pure metal × fineness (see `gold-scrap-ru.md`); re-anchor it the day you answer.
- **Melee diamonds (рассевка, <1.5 mm):** wholesale 2 000–4 000 ₽/ct, so 18 stones of 1 mm
  are ~0.09–0.1 ct ≈ 300–500 ₽ of stone. Retail adds ~300–1 500 ₽ per stone. Many small
  stones are a look, not value — say so instead of repeating the brand's story.
- **Work, rhodium plating, hallmark, brand:** 5 000–20 000 ₽; a brand can double the total.

## Segment ladder (report all four when the user has no brand in mind)

| Segment | Typical | Notes |
|---|---|---|
| Marketplaces (Ozon, 585GOLD) | cheapest, often 2× under chains | check the real weight — 0.7–1.2 g is common where a 2 g piece is assumed |
| Chains (585 Золотой, SOKOLOV, SUNLIGHT) | 1.5–2× marketplace list | real price is the promo price (‑50…‑70%), list is decoration |
| Producer-direct (KOUZ/Костромской юв. завод, Покровский юв. завод, Бронницкий) | similar list, honest specs | product cards carry «Средний вес» + «Описание вставок» (e.g. «кр-57 90-120 (10 шт)») + мм per stone |
| Brands / на заказ (DAF, ателье) | 2–3× producer | crosses with diamonds median around 100 000 ₽ |

Always close with the resale number for the same piece — the retail-to-скупка ratio (3–4×)
is the part of the answer the user actually needs.

## Where parseable prices live

- `kouz.ru` — server-rendered cards: name, «Средний вес», stone description, list price and
  discount. Best source for weight+stone+price in one page.
- `pokrovgold.ru`, `bronnitsy.com` — category pages embed schema.org `ItemList` JSON-LD;
  grep `"price":` and `"name":` out of `<script type="application/ld+json">`.
- Big chains (SOKOLOV, 585 Золотой, SUNLIGHT, Ozon) build price grids client-side or answer
  curl with 401/403/307 — read their numbers from search-result snippets and per-org Yandex
  Maps `/prices/` pages instead of retrying the catalogue, and don't spend more than one
  attempt on them.

## Pitfalls

- A given price belongs to a given weight: never quote a catalogue price without the gram
  figure printed on the same card. "Крест с бриллиантами от 24 290 ₽" is a 0.8 g item.
- Producer list price with `‑25%` is still the producer's own "от"; state it as list, then the
  realistic promo range.
- Diamond count says nothing about value: 10 stones of 90–120 (≈0.06 ct) is the same order of
  money as 18 stones of 1 mm. Ask for mm or carat before comparing two items.
