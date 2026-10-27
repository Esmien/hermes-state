# City-vs-city data in RU: what parses and what it gives

Companion to `city-traffic-ru.md` (congestion). This file covers the rest of the
quantitative side of a city comparison: cost of living, rent, real estate, climate,
fares, and door-to-door travel between the two cities.

## Fetch recipe (extract backend may be search-only)

When the environment's `web_extract` cannot fetch pages, plain curl + a tag stripper is
the workhorse. Yandex/CIAN/MirKvartir block bots, but the sources listed below do not.

```bash
curl -sL -m 40 --compressed \
  -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36' \
  -o /tmp/res_<name>.html -w '%{http_code} %{size_download}' "$URL"
```

Then strip in Python (not sed/awk): drop `<script|style|noscript>`, turn
`</p|div|tr|li|h\d|td|th>` into newlines, remove remaining tags, `html.unescape`,
collapse spaces. Check the HTTP code first — a failed fetch leaves the previous file in
`/tmp` and the stripper prints a plausible page for the wrong city.

The general web search is noisy for Russian price queries (foreign news portals, gambling
mirrors). Treat snippets as leads only; open the known server-rendered source instead.

## Source map

| Source | URL shape | Yields | Notes |
|---|---|---|---|
| Skokstoit | `skokstoit.ru/<slug>` plus `/arenda`, `/transport`, `/klimat`, `/nedvizhimost` | Rosstat-anchored: rent median by room count, fares, fuel, internet/mobile, median salary, Open-Meteo climate normals | Country-wide, so one methodology across cities. Take numbers from the SECTION pages; the city summary card has blank/broken fields (missing 1-room rent, a nonsense "index 7 294 ₽"). Heavy use → 403, pace requests |
| RealtyMag | `realtymag.ru/<region>/<city>/novostroyka/prodazha/prices` | Newbuild ₽/m² average and by room count, by metro station AND by district, 12-month dynamics | Asking prices, not registered deals |
| Ассоциация застройщиков Краснодара | `ap-r.ru/novosti/ceny-na-novostroyki-krasnodara/` | Median newbuild price for a typical comfort-class flat + per-district extremes | Krasnodar only; monthly article, dated |
| MirKvartir rent | `arenda.mirkvartir.ru/...` | Average rent by room count, also a "с животными" cut | Direct curl → 403; the search snippet carries the average — quote it as MirKvartir with the date |
| Tutu | `tutu.ru/poezda/<From>/<To>/` | Rail: "от N ₽", "от N суток" | Server-rendered; use instead of rasp.yandex.ru, which serves SmartCaptcha |
| S7 / FlightConnections | `s7.ru/ru/flight/from/<A>/to/<B>/` | Direct-flight existence, price floor, carriers | Distance and block time from FlightConnections |

Blocked for a datacenter IP: `gogov.ru` (429), `hh.ru` API
(`{"errors":[{"type":"forbidden"}]}`), `rasp.yandex.ru` (captcha), CIAN and
MirKvartir direct. Do not fight them — substitute a server-rendered source or state the
fact qualitatively instead of inventing a vacancy count.

## Two price numbers that must not be averaged

- **Rosstat secondary market** = registered-deal averages.
- **Listing newbuild averages** = asking prices across all classes.

They diverge by design, and in a heated market the inversion is real and useful to
report: Krasnodar secondary well above its newbuilds (overheated resale), Novosibirsk
newbuilds well above its secondary. Quote both, name the methodology, and never blend
them into one "average city price" — the swap arithmetic (sell here, buy there) depends
on which of the two you compare.

## Ratio checks before publishing

- Rent ratio and ЖКХ ratio should point the same way as the climate/season length; if not,
suspect the season or the area of the flat in the source.
- A per-m² figure times a plausible area must land inside the reported price band for
that room count — if the article's median flat and its median metre disagree, one of them
is a promo or a different class.
- Cross-check every headline money number against a second source; two sources with
different methodology that agree are what justifies putting a number in the verdict.
