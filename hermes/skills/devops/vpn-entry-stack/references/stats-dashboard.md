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

The owner can have a profile in `users.json` that carries **the legacy UUID itself**. His subscription then silently redistributes the shared key, `users.py sync` answers «клиентов добавлено 0» (the client already exists by id, so nothing is added), and no `in-general:<имя>` client ever appears in `config.json` — his traffic always lands in the shared-key row, mixed with every other device on that key. The question that starts the hunt: «а почему я себя не вижу в таблице».

How to tell, before blaming the dashboard for a missing person:

1. `inbounds[in-general].settings.clients` — a name in `users.json` does not mean a name in the live config.
2. Compare ids: the bare-email clients (email == tag) all share one UUID, and `users.json[<name>]['uuid']` equal to it is the diagnosis.

Fix: put a fresh `uuid.uuid4()` into `users.json`, re-run `users.py sync` (it now adds one client per inbound), then `vpn-cfg apply`. The tokens and URLs stay the same — only the profile content changes — so his devices must refresh the subscription, and until each one does, its traffic keeps falling into the shared row. Back up `users.json` first; the old uuid is the shared key and must stay on the bare-email clients.

Row names are the owner's to dictate: he names the shared row after the guest holding it («Саша») and keeps his own («Владислав (главный)»). Use his strings verbatim — a descriptive invention like «Главный ключ (мой + Саша)» reads as noise and gets rejected. Labels carry no explanation inside them.

## Счётчики не зависят от адресов

«Трафик из нового входа/выхода в статистику попал?» решается механизмом, а не сверкой адресов:
счётчики живут на `user>>>` (кто, по инбаунду) и `outbound>>>` (куда, по тегу). Смена IP входа
или `sendThrough` у выхода не меняет ни одного ключа — цифры продолжают идти в те же строки.
Меняется только смысл подписи: строка «Эстония (основной)» — это тег `direct`, и после
`direct.sendThrough: <edge>` она означает «выход через edge», а не «выход с brand». Доказательство
— рост счётчика между двумя ручными запусками `stats_collect.py`, а не дата в `data.json`.

## Dashboard

- Collector: `/root/vpn-router/stats_collect.py`, run by `vpn-stats.timer` every 5 min (state `/var/lib/vpn-stats/state.json`, page data `/var/www/vpn-stats/data.json`).
- Page: `/var/www/vpn-stats/index.html` (self-contained, inline CSS/JS, numbers only — the owner rejects progress bars/charts noise).
- Панель живёт **только** на `stats.esmien.com` (DNS-only, `127.0.0.1:9443 proxy_protocol ssl http2`, basic auth по `/etc/nginx/vpn-stats.htpasswd`, отдельный сертификат `stats-esmien-com`). Старая `stats.esmien.ru` уничтожена вместе с vhost и A-записью — не восстанавливать. Коллектор считает по людям и выходам независимо от имени входа; проверить реальным трафиком через вход и ростом счётчиков. Панель — это статистика трафика, не деньги: не заявлять о переносе расходов, не найдя их источник.

### Доступ только через VPN (решение владельца)

Панель не должна открываться из интернета вообще: сервер для владельца не должен выглядеть
личным сервисом. Закрывается на уровне nginx, а не авторизацией:

```nginx
allow 85.92.158.238;   # edge = адрес, с которого выходят наши же клиенты
allow 127.0.0.1;
deny all;
error_page 403 = @drop;
location @drop { return 444; }
```

Блок `deny` и `@drop` ставятся в **оба** серверных блока каждого vhost-а (`:80` и TLS-блок `:9443`);
`444` вместо `403` — чтобы снаружи соединение просто рвалось, и сканер не видел даже факта
существования адреса. Правило живёт в живых файлах `/etc/nginx/conf.d/stats.*.conf`, их копии —
`vpn-service/nginx/stats.*.conf`; обновлять в одном заходе, `apply` их не перегенерирует.

**Обязательное дополнение — правило маршрутизации.** Клиентский запрос к панели уходит с того
выхода, куда его направил сервер; через NL/Gemini он придёт с чужого IP и получит `444`. Поэтому
в `config.json` перед доменными правилами:
`{"type":"field","domain":["domain:stats.esmien.com","domain:stats.esmien.ru"],"outboundTag":"direct"}`
— тогда панель открывается с любого устройства внутри туннеля.

Симптом «через VPN тоже не пускает» и его причина: TLS-рукопожатие проходит, а `curl` падает
`HTTP/2 stream 1 was not closed cleanly: PROTOCOL_ERROR`, и в `stream-443.log` по этому соединению
нет ни строки — значит запрос вышел не через edge. Проверять обе стороны одним замером:
`curl --interface 85.92.158.238 https://stats.esmien.com/` (эмулирует источник-клиент) → `401`,
снаружи → обрыв (`000`), и только потом браузером через туннель. Цена решения, которую надо озвучить:
без живого VPN панель недоступна совсем, включая владельца.
- Credentials are his to pick: write `user:$(openssl passwd -apr1 '<pw>')` into the htpasswd file, `chgrp www-data` it, then prove both sides — new login `200`, old login `401`.

### Subscription generator

A block on the same page creates profiles: input name → POST `api/new` → three links back.

- API: `/root/vpn-router/subgen_api.py`, stdlib `ThreadingHTTPServer` on `127.0.0.1:9198`, unit `vpn-subgen.service` (`Restart=always`). nginx proxies `location /api/` to it on the stats vhost; auth is the vhost's basic auth, so the API is never reachable directly.
- It shells out to `python3 users.py add <name>` with `timeout=600` — that command already does uuid + both tokens + pages + `xray -test` + blue/green apply + nginx reload, so the API must not repeat any of it. Measured 10–40 s per profile.
- Return the links from `users.json` after the call, not by parsing stdout.
- Validate the name (`^[A-Za-zА-Яа-яЁё0-9 _-]{2,24}$`) — it becomes a directory name under `/var/www/esmien-sub/`.
- Accept JSON `POST` only: a cross-site form cannot set `Content-Type: application/json` without a preflight the backend never answers.
- Deletion is a second endpoint on the same API: `POST api/del {"name": ...}` shells out to `python3 users.py rm <name>` (same 600 s timeout, whole config re-applied). In the table the button lives in a trailing action cell, and the payload must be the **raw key** the collector emits (`u.key`), not the display label — «Владислав (главный)» is not a profile name and `users.py rm` would fail on it. Emit `key` plus `deletable` from the collector and render the button only when `deletable` is true.
- The bare-tag row (a shared main key) gets **no** delete button — there is no profile behind it. The owner's own personal row gets no delete either: it is `PROTECTED` (403 from `api/del`) and carries «перевыпустить» instead, which returns fresh links. Everyone else keeps «удалить».
- Every row also carries a «ссылка» copy button: the collector emits a `https://share.esmien.com/u/<token>` page per person from `users.json` (`""` for the bare-tag row). The API `subgen_api.links()` and CLI `users.py` also return `.com` page and subscription links on 443; `brand.json` remains on `.ru` to keep old subscriber rendering alive. Test the create branch in isolation if no temporary user can safely be deleted, and say explicitly when a real create was not tested.
- Render **every** user from `users.json`, not only those xray has counters for: merge `page_links()` keys into `state["users"]` at render time (`setdefault` with zeroes). Otherwise people who never connected are invisible and he cannot tell whose links never got used.
- Confirm destructive UI by typing the name into an inline field (`placeholder` = the exact string to type), not with a bare second click: the row then ends up in a state where a stray tap on a phone cannot destroy someone's connection. Wrong input clears the field and re-prompts. **He asks for a capability, he decides its risk** — build the button, do not argue that deletion is too dangerous; the guard is the typed name, not a missing feature. Refusing or quietly omitting it reads as dumbing the panel down and gets pushed back on immediately.
- Say plainly what deletion costs: `users.py rm` moves the token directories to `/var/www/esmien-sub/.disabled/`, revokes them, drops the uuid from the config and applies it — the person's tunnel drops mid-apply and their old links die. Recovery means re-adding with the archived uuid and tokens, so it is not a one-click undo.
- Verify the generator through the real URL (create a throwaway profile, then `users.py rm` it: tokens move to `/var/www/esmien-sub/.disabled/` and the config is re-applied). Do the same for delete: create, delete via `api/del`, and confirm the person is gone from `users.json`, from `config.json` and from `api/users`; deleting a name that does not exist must answer 404, not silently succeed.

### Pitfalls hit while building it

- **StartedAt alone is not a reliable baseline.** It catches a restarted container, but the counter set also changes when the collector follows a colour flip or reads another inbound, and those switches produced repeated full-counter additions. Key counters per container and per inbound and treat any decrease without a container change as a reset (baseline, add nothing).
- **State keys must be the raw identity, never the display label.** With `state["users"]`/`counters` keyed by the label, every rename (and the owner renames labels) missed the old counter key, took `prev = 0` and added the whole counter again — the row doubled. Keep state keyed by `email.split(":")[-1]` with a `@legacy` sentinel for the bare-tag key and map to the display name (`LABELS`) only at render time; renames then cost nothing.
- Route totals must be **aggregated by human label**, not by tag: tags `p1…p23` all map to one "Подписка (узлы провайдера)" row, otherwise the page shows a dozen identical rows with "—".
- `/etc/nginx/vpn-stats.htpasswd` must be `root:www-data 0640`; plain `0640 root:root` gives **500** (nginx workers are www-data), not 401.
- **Иконки рисует страница, данные остаются текстом.** Флаги — инлайновые SVG (три `<rect>`),
  лого Gemini — инлайновый SVG с их градиентом; в `data.json` подпись простая
  («Нидерланды (Gemini)»). Эмодзи в данных — источник рассинхрона: часть устройств отдаёт tofu,
  у эмодзи-флагов на разных ОС разная ширина, а клиенты VPN вообще превращают в аватарку только
  флаг, остальные эмодзи рисуют в строке рядом с серой заглушкой.
- **Скриншот — не измерительный прибор.** Headless Chromium держит минимальную ширину окна
  (~500 px): `--window-size=390,1100` рендерит на 500, поэтому «мобильный» скриншот показывает
  не тот экран, что у владельца, а `vision_analyze` по такому PNG уверенно «не находит» числа,
  которые в DOM есть (и наоборот — видит флаг Эстонии там, где нарисован нидерландский).
  Разметку проверять измерением: временная копия `_debug.html` со скриптом, который через
  ~2.5 с пишет в `document.title` JSON `{clientWidth, scrollWidth, rects .rows .v}`, и
  `chrome --headless=new --dump-dom … | grep -o '<title>.*</title>'`. `clientWidth == scrollWidth`
  = горизонтального переполнения нет; наличие и текст значений — тем же `--dump-dom` с разбором
  HTML в Python. Глазами по картинке проверять только косметику.
- **Маршруты — грид-строки, не таблица.** Таблица с `white-space: nowrap` в двух колонках на
  телефонной ширине выезжает за экран, и число оказывается ровно за краем кадра — выглядит как
  «строки без значений». Список `.rows .row { display:grid; grid-template-columns: 1.5em minmax(0,1fr) auto }`
  даёт фиксированный слот под иконку, эллипсис на названии и число, прижатое вправо; в таблице
  людей на узкой ширине лишняя колонка скрывается через `nth-child`, а не через прокрутку.
- Routes with zero traffic are filtered out of the page; an empty `routes` list is legitimate right after a state reset.
- **Never trust the panel's totals without ground truth.** Before explaining a traffic jump, run `vnstat -d` / `-h`: if one person's 24h figure exceeds what the whole `ens3` moved that day, the collector is broken, not the traffic real. Two counter sets alternating in `samples` (e.g. repeating 1815.0/172.6 MB values) are the signature of a cumulative counter being added whole instead of a delta.
- **Counters must be keyed per container and per inbound** — `u:<container>:<name>:<inbound>:<dir>`. Keying by user name only means a value from another inbound or the other blue/green container gets compared with this one and, when it is smaller, the whole value is charged as traffic. Avoid processing a decrease as growth: a decrease without a container change is a reset, i.e. a new baseline.
- **`vpn-cfg apply` never restarts the traffic-carrying container**, so after a flip the old container keeps serving long-lived websockets while the collector reads only the new one — that direction loses traffic; do not compensate by scaling.
- **Repairing inflated history**: samples ≥1 GiB per 5-minute interval are artifacts on this host (NIC peak is ~6 GiB/hour) — drop them, recompute `total` from the remainder, reset route totals (no per-day breakdown exists), and say plainly that route history was wiped.
- **A bare-tag client row (`@legacy`, «общий ключ (без имени)») is a leftover shared UUID.** It is safe to delete when `grep -rl <uuid> /var/www/esmien-pages /var/www/esmien-sub` finds nothing and no generator writes it; drop the client from every inbound, `vpn-cfg apply`, re-run a tunnel test, and remove the `@legacy` row from `state.json` too.
- **Don't call `systemctl start vpn-stats.service` in a tight test loop.** Systemd start-rate limiting can put the oneshot into `start-limit-hit` and block future timer runs; use `python3 /root/vpn-router/stats_collect.py` with its existing lock, or wait. If hit, `systemctl reset-failed vpn-stats.service`, run one start and verify success.
- **A 5-minute timer is too slow for an admin page.** Every load must refresh on demand: the page `POST`s `api/refresh` (which runs `stats_collect.py` synchronously, 90 s timeout) and only then reads `data.json`, and create/reissue call the same `load()` instead of leaving a stale table until the next tick. Wrap the collector body in `fcntl.flock(..., LOCK_EX | LOCK_NB)` on `/var/lib/vpn-stats/lock` and exit 0 when the lock is taken — otherwise the timer and a manual refresh can compute the same delta twice.
- Retired `/u/` pages must be pruned by the page generator, not just left on disk: after a delete or a reissue the old token's file keeps answering 200 with dead links. Check both ways after the operation — retired → 404, live → 200 — and keep the page count equal to tokens × kinds (two per person).
- To show the owner the page, screenshot it without touching basic auth: `python3 -m http.server 9199 --bind 127.0.0.1 --directory /var/www/vpn-stats` in the background, then `/root/.hermes/tools/chromium-1208/chrome-linux64/chrome --headless=new --no-sandbox --disable-gpu --hide-scrollbars --window-size=880,620 --virtual-time-budget=5000 --screenshot=<png> http://127.0.0.1:9199/`, kill the server, and read the PNG back with `vision_analyze` before sending — it catches tofu glyphs, duplicated rows and empty columns that `curl` cannot.

## Proving attribution, not assuming it

`scripts/probe_user_key.py` builds a throwaway xray client from one subscription (`--token`), or from the bare main key (`--legacy`), runs it as a local socks, downloads N bytes and prints the byte count plus the egress IP. Run it with the person's token, wait one collector tick, and their row must move by ~N bytes — the only proof that per-user counters are wired to the right key. (Don't confuse it with `scripts/probe_sub.py`, which probes the provider's nodes for exit geo and Google's country verdict.)

Watch the returned `size_download`: the free speed endpoints cap the request and answer `1` byte for too big a `bytes=` value, which reads like a dead key. A few MB (2–8 MB) works; treat `1` byte as "ask smaller", not as a failure.

**Свой тестовый клиент собирается из `users.json` + `brand.json`, а не из одного `users.json`.**
В записи профиля только `uuid`, `token`, `token_lte`, `title`, `created` — ключа `path` там нет
(`KeyError: 'path'`), путь берётся из `brand.json["paths"]["public_general"]`, а адрес/SNI — из
`share.esmien.com` (тот же вход, что у людей на 443). Проверка такого клиента годится для «вход
отвечает» и для source-IP-ограничений (см. доступ к панели), но не заменяет тест с устройства
владельца.

## Reachable data, cheap

`outbound>>>` counters give "how much went through FR / RU / direct" for free — no Prometheus, no exporters, one loopback port and one timer.

Before turning any of this into a separate service, read `references/control-plane.md`: the users/keys/traffic layer is solved software (Marzban, 3x-ui), the one-node product layer is not, and the honest options come with different price tags.
