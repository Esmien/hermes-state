# Gold / silver scrap in Russia: how the numbers work

## Melt value (the only honest anchor)

```
melt_per_gram = CBR_gold_per_gram × (fineness / 1000)
```

585 → ×0.585; 750 → ×0.750; 925 silver → ×0.925. CBR quotes per gram of pure metal,
the same unit retail sites misuse. For a 2 g 585 chain: `CBR × 0.585 × 2`.

## Three price levels a pawn shop uses

| Level | Typical vs melt | What it means |
|---|---|---|
| Залоговая оценка (loan) | 90-115% | what they lend per gram; often the "оценка X ₽/г" on the site and in Yandex Maps |
| Скупка / продажа без выкупа | 65-90% | outright purchase, what the client actually receives |
| Promo ("первый грамм", "тариф Индивидуальный") | up to ~115% on gram 1 only | marketing ceiling; later grams fall back to base rate |

A shop advertising 6 200 ₽/г for 585 on a ~6 100 ₽ melt may still hand over ~5 200-5 600
per gram on an outright sale. Ask for "продажа без выкупа" and "сколько итого на руки".

## White gold

Same 585 fineness, same melt value. Most chains accept it at the same rate; a minority
deduct 5-10% citing rhodium plating or a silver/palladium-rich alloy. The deduction is not
justified by the metal — do not accept it without a stated per-gram price. Some shops list
"белое золото" as a separate service line, which is a good sign they price it normally.

## On-site checks that change the offer

- **Hallmark (клеймо)** missing or unreadable → assay or refusal, price drops sharply.
- **Weight** is measured on their scale: ask to weigh in front of you.
- **Minimum weight** (1-3 g) and per-item limits: a 2 g chain can fall under a lower rate
  or be refused by small buyers.
- **Tariff conditions** may exclude religious items, wedding bands, single earrings — a
  plain chain usually qualifies for the top bracket, a cross does not.

## Source hygiene

- CBR XML is the anchor; chain rates (585 Золотой, Ломбард-Л1, Пионер and similar) are the
  market quotes; Yandex Maps org `/prices/` pages carry the business-supplied tariff list.
- Sites with a `город` switcher and 30+ city subdomains selling "скупка золота" are lead
  generators with no local office.
- Verify a federal chain has a branch in the target city before naming it.
