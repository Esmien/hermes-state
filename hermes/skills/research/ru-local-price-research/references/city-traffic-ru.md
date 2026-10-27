# City metrics for RU comparisons (traffic first)

Task shape: "где пробки злее — A или B?", "где воздух грязнее", "где дороже жизнь".
Answer = verdict + one sustained metric per side + structural reason + practical clause.
A single-day snapshot ("сейчас 7 баллов") never answers a "где злее" question.

## Source map

| Source | Renders for curl? | What you get | Trust |
|---|---|---|---|
| `numbeo.com/traffic/in/<City>` | yes, plain HTML tables | Traffic Index, Time Index (min), Inefficiency Index | crowd-sourced, thin samples in RU — direction only |
| `tomtom.com/traffic-index/...` | **no** — Astro SPA, data fetched client-side | annual hours lost / congestion % | primary, sensor-based |
| Yandex Maps `/<city>/probki/` | JS score widget | current score only | not an annual metric |
| SEO aggregators (`zaimi.ru` and clones) | yes | rewritten TomTom hours-lost tables | pointer only — find the primary |

## Parsing Numbeo

Server-rendered table rows; no renderer needed:

```bash
curl -s -m 25 -A 'Mozilla/5.0 (X11; Linux x86_64) Chrome/124' \
  "https://www.numbeo.com/traffic/in/Krasnodar" -o /tmp/nb.html
```

Then in Python: strip `<script|style>`, pull `<tr>` blocks, keep rows whose cells match
`Traffic Index|Time Index|Inefficiency|CO2`. Cite Time Index as "minutes one-way in rush
hour" — it is the most intuitive of the three. Works for any city slug Numbeo knows;
if a slug 404s, the city is not covered, don't guess a variant.

## TomTom pitfalls

- City URLs moved: `/traffic-index/<slug>-traffic/` 301s to `/traffic-index/city/<slug>`,
  which 404s for most non-megacities. Do not chase the slug.
- `/traffic-index/ranking/` returns HTTP 200 with ~850 KB of HTML and **zero city data** —
  it is an Astro shell; the numbers arrive via a client-side call. Grepping the page or
  the `_astro/*.js` bundles for city names yields nothing. Stop after one probe.
- If a city page does load, look for `application/ld+json` / `__NEXT_DATA__` before
  assuming a renderer is required.

## What the numbers mean

- Compare **hours lost per year** or **average rush-hour travel time**, not peak score.
  Краснодар vs Новосибирск: ~132 vs ~117 h/yr (TomTom 2024/25, 3rd vs 5th in RF); Numbeo
  Traffic Index 224 vs 166. Different methodologies agreeing is what makes the verdict safe.
- Annual averages hide the shape of the pain: a city can rank lower on average and still
  be brutal at 08:00–09:00 (bridge chokepoints). State the day-shape clause in one sentence.
- Structural reasons worth one line, because they explain persistence: growth vs road
  supply, number of river crossings, share of car commuters.

## Answer template

```
**<Город> злее** — и стабильно, не в отдельный день.
- <Source 1, year>: <number> vs <number> (место в РФ)
- <Source 2>: <number> vs <number>
Причина: <one structural sentence>.
Практически: <where/when it actually bites>.
```

No links dump, no methodology essay.
