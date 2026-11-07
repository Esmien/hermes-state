# Per-user traffic stats and the dashboard

## Xray side

`/root/vpn-router/config.json` carries three blocks beyond the defaults:

- top level `"stats": {}`
- `"policy": {"levels": {"0": {"statsUserUplink": true, "statsUserDownlink": true}}, "system": {statsInbound*/statsOutbound* true}}`
- `"api": {"tag": "api", "services": ["StatsService", "HandlerService"]}`
- inbound `{"tag": "api-in", "listen": "127.0.0.1", "port": 10185, "protocol": "dokodemo-door", "settings": {"address": "127.0.0.1"}}`
- routing rule `{inboundTag: ["api-in"], outboundTag: "api"}` placed **first**, before the `geoip:private → blocked` rule (127.0.0.1 is private and would otherwise be blocked).

Blue/green: `vpn-cfg build` bumps every inbound port by 1000 for the B variant, so the api port is **10185 on colour a, 11185 on colour b**. Always derive it from `/root/vpn-router/vpn-color`.

Two things in `vpn-bluegreen.py` need to tolerate the api inbound, otherwise `apply` refuses (it reports `24/25` and does not flip):

1. `lint()` — skip the "нет ни одного клиента" check for `protocol == "dokodemo-door"`, and accept `cfg["api"]["tag"]` as a valid `outboundTag` (the api module registers that outbound implicitly; declaring a real outbound with the same tag breaks xray).
2. `probe_direct()` — skip `dokodemo-door` inbounds; they never answer an HTTP probe with 400.

Query from the host (the container uses host networking):

```
/usr/local/bin/xray api statsquery --server=127.0.0.1:<10185|11185> -pattern "user>>>"
```

Names are `user>>><email>>>traffic>>>uplink|downlink`, plus `inbound>>>tag>>>...` and `outbound>>>tag>>>...`.

## Attribution

Client emails are `<inboundTag>:<имя>` for per-user keys, but the **legacy/global key has email == its own tag** (`in-general`, `ws-in`). So `email.split(":")[-1]` is the person, and a bare tag means the shared legacy key — label it, never attribute it to one person.

The owner can have a profile in `users.json` that carries **the legacy UUID itself**. His subscription then silently redistributes the shared key, `users.py sync` answers «клиентов добавлено 0» (the client already exists by id, so nothing is added), and no `in-general:<имя>` client ever appears in `config.json` — his traffic always lands in the shared-key row, mixed with every other device on that key.

How to tell, before blaming the dashboard for a missing person:

1. `inbounds[in-general].settings.clients` — a name in `users.json` does not mean a name in the live config.
2. Compare ids: the bare-email clients (email == tag) all share one UUID, and `users.json[<name>]['uuid']` equal to it is the diagnosis.

Fix: put a fresh `uuid.uuid4()` into `users.json`, re-run `users.py sync` (it now adds one client per inbound), then `vpn-cfg apply`. The tokens and URLs stay the same — only the profile content changes — so his devices must refresh the subscription, and until each one does, its traffic keeps falling into the shared row. Back up `users.json` first; the old uuid is the shared key and must stay on the bare-email clients.

When a key is shared, never name its row after the guest who happens to hold it. The main key belongs to the owner even after he hands it out, so label it neutrally («Главный ключ (мой + …)») and let him choose the names — a row labelled with someone else's name reads to him as a claim that the guest is the principal.

## Dashboard

- Collector: `/root/vpn-router/stats_collect.py`, run by `vpn-stats.timer` every 5 min (state `/var/lib/vpn-stats/state.json`, page data `/var/www/vpn-stats/data.json`).
- Page: `/var/www/vpn-stats/index.html` (self-contained, inline CSS/JS, numbers only — the owner rejects progress bars/charts noise).
- Vhost `stats.esmien.ru`: A record grey (direct, no Cloudflare), `listen 127.0.0.1:9443 proxy_protocol ssl http2`, wildcard cert, basic auth against `/etc/nginx/vpn-stats.htpasswd`.

### Pitfalls hit while building it

- **Counters reset on every restart**, and `vpn-cfg apply` restarts a container each time. The collector therefore stores the container's `.State.StartedAt`; if it changed, this sample is a baseline (delta 0), not a delta — otherwise a flip counts the whole accumulated counter again as new traffic.
- Route totals must be **aggregated by human label**, not by tag: tags `p1…p23` all map to one "Подписка (узлы провайдера)" row, otherwise the page shows a dozen identical rows with "—".
- `/etc/nginx/vpn-stats.htpasswd` must be `root:www-data 0640`; plain `0640 root:root` gives **500** (nginx workers are www-data), not 401.
- No emoji flags in generated HTML: they render as tofu in headless Chromium and show up in screenshots.
- Routes with zero traffic are filtered out of the page; an empty `routes` list is legitimate right after a state reset.
- To show the owner the page, screenshot it without touching basic auth: `python3 -m http.server 9199 --bind 127.0.0.1 --directory /var/www/vpn-stats` in the background, then `/root/.hermes/tools/chromium-1208/chrome-linux64/chrome --headless=new --no-sandbox --disable-gpu --hide-scrollbars --window-size=880,620 --virtual-time-budget=5000 --screenshot=<png> http://127.0.0.1:9199/`, kill the server, and read the PNG back with `vision_analyze` before sending — it catches tofu glyphs, duplicated rows and empty columns that `curl` cannot.

## Reachable data, cheap

`outbound>>>` counters give "how much went through FR / RU / direct" for free — no Prometheus, no exporters, one loopback port and one timer.
