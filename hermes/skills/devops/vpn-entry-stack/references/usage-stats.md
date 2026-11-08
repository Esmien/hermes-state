# Usage stats: who actually uses the subscriptions, and how much

Two questions land here: «моими подписками хоть кто-то пользуется?» (cheap: nginx logs) and «сколько
каждый прокачал / давай дашборд» (needs xray `StatsService`).

## Answer shape

Verdict first as a count — «реально ходят трое из семи» — then one bullet per person with last-seen in
МСК and what proves it (client UA + fetch cadence, or `stats` bytes), then a plain sentence about what
*cannot* be measured yet. The owner reads it as a status report: no tables, no charts, no methodology
essay. People who were handed a link and never connected are a separate list, not a footnote.

## 1. Cheap pass — nginx logs, no config change

`/var/log/nginx/vpn-8443.log*` (`.gz` included) carries `$remote_addr [$time_local] "$method $path"
$status bytes rt="…" ua="$http_user_agent"`.

- `/sub/<token>` — the app refreshing its profile. `profile-update-interval: 12` means ~2 fetches/day from
  one installed device, so a steady daily cadence **is** proof of a live install.
- `/u/<token>` — a human opened the landing page (button/link tap, not an install).
- Map token → person from `users.json` (`token`, `token_lte`) and print names only, never tokens.
- Group by app UA (`Happ/…`, `ClashMeta/…`, `INCY/…`, `FlClash/…`): the app tells you the platform and
  proves the profile was imported. A person with page views and zero client-UA `/sub/` fetches has not
  installed anything yet — say that, not «пользуется».

**Filter your own verification traffic before drawing any conclusion.** Every probe during a key rollout
fetches the subscription with `curl/8.x` from `127.0.0.1` or the host's own address, and it lands on
exactly the person you were testing. Exclude `127.0.0.1`, the host IP and the `curl` UA; a «user» with 34
fetches inside one 10-minute window is your rollout, not a human. This is the single easiest way to hand
the owner a wrong answer.

Tunnel traffic cannot be attributed from these logs: `/general` lines carry no identity, exit addresses,
shared home NATs and the legacy key all collide on the same IP. Per-IP `general` counts answer «somebody
tunnels», never «who».

## 2. Exact pass — xray `StatsService`

Four pieces; missing any one gives an empty answer instead of an error:

```json
"stats": {},
"policy": {"levels": {"0": {"statsUserUplink": true, "statsUserDownlink": true}},
           "system": {"statsInboundUplink": true, "statsInboundDownlink": true,
                      "statsOutboundUplink": true, "statsOutboundDownlink": true}},
"api": {"tag": "api", "services": ["StatsService", "HandlerService"]}
```

plus an inbound `{"tag":"api-in","listen":"127.0.0.1","port":10185,"protocol":"dokodemo-door",
"settings":{"address":"127.0.0.1"}}` and a routing rule `{"type":"field","inboundTag":["api-in"],
"outboundTag":"api"}` **at index 0** — ahead of the `geoip:private → blocked` rule, or the api's own
loopback traffic gets blocked and the query hangs. Loopback only, never published.

**Any builder that rewrites `routing.rules` must keep that rule first.** `scenario_routes.py install`
collected every `inboundTag` rule into the tail, so the api rule slid down to index 4 — behind
`geoip:private → blocked` — and the symptom looked nothing like routing: the dashboard banner read
`последний опрос не удался: failed to dial 127.0.0.1:11185`, `ss` showed that port listening, and the
*idle* colour still answered on 10185 because it had started on the previous config. Match `api-in`
before any ip/domain block, and after a flip check the **active** colour's port, not the other one.

`vpn-bluegreen.py` must learn three things in the same pass, or `apply` refuses the flip (correctly, but
it looks like a broken config):

- `lint()` rejects an inbound with no clients → skip `protocol == "dokodemo-door"`.
- `lint()`/`xray -test` treat `outboundTag: "api"` as dangling — the api module registers that outbound
  implicitly. Allow `cfg["api"]["tag"]` as a known tag; do **not** add a real `blackhole` outbound with
  that tag, it breaks the service.
- `probe_direct()` requests every inbound over HTTP expecting `400` and a dokodemo-door inbound cannot
  answer, so the fresh colour reports `24/25` and the flip is refused. Skip dokodemo-door in the probe too.

Query with the host binary (no container shell needed) on the **active** colour's port — `10185` for `a`,
`11185` for `b`, because the B config is derived with `+1000`:

```bash
COLOR=$(cat /root/vpn-router/vpn-color); PORT=$([ "$COLOR" = a ] && echo 10185 || echo 11185)
/usr/local/bin/xray api statsquery --server=127.0.0.1:$PORT -pattern "user>>>"
```

Reading the answer:

- Names are `user>>><email>>>traffic>>>uplink|downlink`. Email is `<inbound-tag>:<имя>` for a per-user key
  and a **bare tag** (`in-general`) for the legacy global key — sum across inbounds, strip the tag prefix,
  and label bare-tag entries as the legacy key instead of inventing a person.
- **Counters live in memory and reset on every `apply`/restart**, blue/green flips included. History is a
  collector that stores deltas, never a reader of the raw values.
- Verify attribution by pushing a known volume through one person's key and reading the number back
  (8 MB through her link showed up as ~7.65 MB down). «The query returned something» is not a test.

## 4. Пул или персональный кред — инжект известного объёма

«Сидит ли кто-то ещё на моих кредах» решается одним замером, а не рассуждением про
архитектуру реселлера. Наблюдение без нагрузки бесполезно: на объёмах < 1 МБ шум панели
того же порядка, и отношение 2× ничего не значит.

1. `scripts/pool_probe.py sample` — снимок `subscription-userinfo` по каждой подписке + xray-счётчики
   (UA тот же, что у `sub_expiry.py`, — панель не считает это новым устройством).
2. `scripts/inject.py p1 200` — качает ровно 200 МБ через релейный выход; outbound копируется из
   `config.json` verbatim, UUID не печатается.
3. Пауза 2–3 мин (нода отдаёт статистику в панель с задержкой), снова `sample`, затем `report`.

Чтение: дельта плана ≈ инжект (±1 %) → кред персональный. Кратно больше или рвано → на нём кто-то ещё.

- Панель отдаёт `upload=0` по обоим планам — считается только **download**, сравнивать надо с ним.
- Инжект идёт мимо `vpn-router`, поэтому в его outbound-счётчиках не виден; «фон» в отчёте —
  только обычный трафик стека.
- Замер по «мобильному» плану ничего не докажет, если им пользуется семья: там дельта чужая по определению.
- Замерено здесь: 200.0 МБ инжекта → +200.9 МБ в счётчике серверного плана (0.45 % — заголовок
  VLESS и округление), т.е. серверный кред персональный.

## 3. Dashboard — agreed shape

- Collector on a `systemd` timer (5 min): query the active colour, diff against
  `/var/lib/vpn-stats/state.json`, accumulate per-person up/down and last-seen plus per-outbound totals,
  write `data.json` beside a static page.
- Page: one self-contained HTML (inline CSS/JS, no CDN): per person 24 h / 7 d / all-time and last
  connect, per route (FR / RU / Estonia), and an explicit list «дали ссылку, ни одного подключения».
  No charts, no progress bars, no sparkline spam — the owner rejects visual noise in reports.
- Access: its own grey hostname with basic auth. Do **not** hang it off a path under `vpn-*.conf`: those
  files are generated by `apply_brand.py`, so a new path means editing the template, and `/u/<token>`-style
  token URLs already exist for the per-person pages.
