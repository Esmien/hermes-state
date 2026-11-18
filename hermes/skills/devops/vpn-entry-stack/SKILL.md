---
name: vpn-entry-stack
description: Use when editing or deploying the VPN entry stack.
version: 1.0.0
author: VPS Admin
license: MIT
---

# VPN entry stack (VLESS: Vision+TLS / WS / hysteria2)

## When to Use

Load this before touching anything that serves VPN clients: adding or removing a route, moving the public host or certificate, regenerating subscriptions, or answering a "VPN keeps dropping / no internet" report. Also load it for «нас РКН забанят?» / «что делать, если заблокируют» — `references/blocking-risk.md`. Not for the AI services on the same host — that is `ai-stack`.

The owner's home ISP (MTS, Krasnodar) drops **port 443** and kills **fake-TLS/MTProto** to this server's IP. What works is a *real* TLS handshake on a non-standard port. That single fact drives the whole design — verify it before debugging anything else.

## Reporting to the owner

**Инструкции, ранбуки и планы — лесенкой, без жаргона.** Он прямо просил: «пиши такие вещи как дебилу, всегда». Значит: нумерованные шаги, в каждом — одно действие, затем что ты увидишь после него. Никаких «поднять nginx stream на прослойке» — «взять дешёвый сервер в другой стране, поставить туда nginx, который переливает пакеты на наш». Термин можно, но сразу с переводом в скобках. Аналогии допустимы и приветствуются («съёмная входная дверь», «киоск с бумажками»). Скомканный текст с пятью терминами в строке он считает бесполезным, даже если всё в нём верно.

He runs this stack himself and treats reports as noise unless they answer the question he asked:

- Answer in one line, then at most three or four bullets of substance. The payload — a new subscription URL, a login, a number — goes at the top, bare, without a lead-in.
- Do not replay the checks you ran, list the files you touched, or volunteer «две оговорки» nobody asked for. A long report earns «да как же ты достал», an invented label earns «не приши лишнее» — the fix is fewer words, not more explanation of the words.
- When he corrects a name or a label, use his string verbatim and change nothing else in that pass: «просто — Саша. И всё» means exactly that, not «Главный ключ (мой + Саша)».
- A destructive request stated plainly («снеси нахуй X») is a work order: do it, then say in one line what died with it and how it would come back. Do not re-ask and do not lecture about the risk first.
- He asks «почему» to get a cause, not a plan: explain the mechanism in two or three lines and stop. Make the obvious fix instead of offering it. **No closing tail** — a volunteered «делать?» / «скинуть?» in every message is what he calls «хвост рассуждений»; ask only when a real branch needs his decision, then exactly one question (style rules live in `telegram-gate-and-bots`).
- Short is the default, but an explicit «подробно, по-человечески, для дебилов» is a different order and wins: then give the long version — analogy first (electronics/repair lands well), then the chain of steps, then what we gain, what we do not, and what it costs. Do not answer a request for depth with a summary; equally, do not turn a one-line question into that essay.
- When he argues with a model of his own («это целый сервис, его не положат»), first name the half he is right about, then dismantle the wrong half with the mechanism and a number. If the number contradicts something you said earlier, correct yourself in one line and replace it with the measured fact — he checks arguments against data, and a retracted figure costs less than a defended one.

## Layout

```
client -> nginx TLS (8443 primary, 2087 backup) -> xray container `vpn-router` (host network)
        -> outbound "fr" (external exit) | "direct" (this server)
```

Paths (same nginx server blocks). **Only `/ws` and `/general` exist today** — the owner had every other entry
pruned («нам от подписки нужны только маршруты до Gemini и до ру-сервисов»):

- `/ws` — owner's profile, everything goes through the external FR exit.
- `/general` — Estonia (direct exit), normal traffic; every published subscription points here.
- `/france`, `/test`, `/fi` — **removed** (were unused; Gemini is reached by the `bal-google` rule from
  `/general`, not by a separate entry). Re-adding one means inbound + nginx location + rule, in that order.

There is deliberately **no** RU-entry inbound: an earlier `/lte` route (`1.fan-video.study` → Selectel SPb → Helsinki, Google saw it as `ru`) was removed once it was clear the whitelist first hop has to be dialled by the client itself, never by this server. Whitelist entries ship as direct client links only — see `references/whitelist-mode.md`.

3x-ui is **not** part of the stack: container, volume, `/panel/` route, credentials file, panel vhost, its rate-limit zone and fail2ban jail were all removed. It managed two idle inbounds and could not express "this entry -> that exit", which is the whole point of the routing, so it was one public admin surface for nothing. `references/xui-panel.md` keeps only the CSRF/login knowledge in case a UI is ever reintroduced — do not bring a panel back off your own initiative.

Upstreams: 10081 `/ws`, 10082 `/general`; 10185 is the stats API. The 22 relayed `/p<i>` inbounds and the
`in-france`/`in-test`/`in-fi` entries were **deleted** along with their passthrough outbounds — the
subscription now serves only as exits (`fr`, `fi` for Gemini; `p15`, `p17` for `.ru`). Check the real ports
with `vpn-cfg status` instead of trusting a number from a report.

Adding a route means four coordinated edits, in this order: append an inbound (`tag`, 127.0.0.1, next free port, same client id, `wsSettings.path`) to `config.json`, add the outbound and a routing rule keyed on `inboundTag` **before** the catch-all `tcp,udp → direct` rule, add `paths` + `upstreams` entries to `brand.json`, then `apply_brand.py && nginx -t && systemctl reload nginx && vpn-cfg apply` (not a bare `docker restart` — `apply` proves the routes answer and reverts a broken config). Verify by dialling the new path through the tunnel and checking the egress with ipinfo — not by reading the config back.

Files: `/root/vpn-router/{config.json,brand.json,apply_brand.py,make_sub.py,make_template.py,import_sub.py,users.py,probe_sub.py,test_whitelist.py,gemini_geo_check.py,sub_expiry.py,route_ru.py,subs.json,users.json,failover.py,certbot_retry.py,provision_vpn_host.py}`, subscriptions in `/var/www/esmien-sub/<token>/`. Editing, applying and rolling back: `vpn-cfg` (`references/router-ops.md`). Per-user/route traffic counters and «кто пользуется подписками»: `references/usage-stats.md`. When a client reports that the VPN "keeps dropping": `references/client-drop-triage.md` — probe the server end to end before touching anything, and start with DNS: an entry whose name no longer resolves looks exactly like a dead VPN (app can't ping any node, browser still works from cache).

## Deploy / rebuild

The entry is deliberately one container plus flat files, so a fresh server is a script run, not a rebuild from memory:

```bash
bash assets/vpn/scripts/deploy.sh <domain> [email]     # nginx+stream, cert, container, vhosts, subs
python3 /root/vpn-router/import_sub.py <sub-file> [dead indices]
```

The VPN is its **own project**, not part of the AI-stack installer: the canonical repo is the private `Esmien/vpn-service` (`router/`, `nginx/`, `scripts/`, `systemd/`). A full server rebuild is therefore two steps — `install.py` for the AI stack, then `deploy.sh` from this repo for the entry; the bootstrap one-liner does not bring the tunnel back. After any structural change, regenerate the secret-free template with `router/make_template.py`, copy the live files into the repo, and commit — it must match the live host exactly. Runtime secrets stay out of git via `.gitignore`: `config.json` (client UUID), `users.json` (per-user UUIDs), `subs.json`, `whitelist_links.json`, `*.key`, `*.pem`, `*.enc`. Full procedure and pitfalls: `references/router-ops.md`.

The owner-facing counterpart is `/root/.hermes/docs/vpn-runbook.md`: scheme with real ports and paths, every design decision with its price, a nine-step rebuild with a check after each step, six diagnostic commands with a symptom table, and the pitfalls in `references/pitfalls.md`. It lives in the `hermes-state` snapshot, **not** in `vpn-service` (that repo takes only what actually runs on the host). After any structural change — a new port, path, scenario, timer or exit — update the runbook in the same pass; he asked for it so he can rebuild the stack by hand, and a stale runbook is worse than none.

## Changing the public host

Move host, port, cert and subscriptions in one pass: nginx server blocks, `brand.json` paths, regenerated subs, `vpn-cfg`'s own `HOST=` copy, then `apply_brand.py && nginx -t && reload && vpn-cfg apply` — a stale copy in `vpn-cfg` makes `apply` probe the old name and revert a good config.

Full text → [references/changing-public-host.md](references/changing-public-host.md)

## Scenario routing / one-node subscription

Server-side scenarios (Google→FR/FI, RU→Moscow or an owned RU box; YouTube deliberately rides the
Estonian exit) plus a subscription that exposes **one** node, and the jittered watchdog that falls
a dead scenario group back to Estonia: `references/scenario-routes.md`. Do not offer a user a
second node to tap **from a provider subscription** — that is provider traffic and ban risk, not a
feature. A second node that is our own transport (the UDP/hysteria2 fallback) or the legacy WS entry
is **not** shipped by default either: it appears only for token dirs carrying a `compat` marker, and
the default bundle carries exactly one node. Reason: a client that selects a throttled UDP node
concludes the whole VPN is dead and reports «не работает», while the server is fine — one node removes
that class of report entirely.

Two rules apply to every scenario edit: a balancer tag must also be listed in
`observatory.subjectSelector` (otherwise `leastPing` has no data for it and the matching requests
hang while every config check passes), and health checks must accept `2xx`/`3xx` through a URL
that answers *from that node's country* — a RU exit probed with `gstatic` reads permanently dead.
Full symptom list and fixes: `references/scenario-routes.md`.

When the RU scenario must stop depending on reseller relays, a small owned Russian VPS with a
VLESS+Reality inbound wired in as outbound `ru1` is the shape: provisioning, firewall allowlist,
IP-reputation acceptance test and rollback in `references/owned-ru-exit.md`; what to check on the
box before wiring it, and the exit-node pitfalls — `references/ru-exit-node.md`.

## Subscription

`make_sub.py` renders three formats and nginx picks one by User-Agent (`00-esmien-sub-map.conf`): Clash/Mihomo → `clash.yaml`, sing-box → `singbox.json`, everything else → base64 `list.txt`. URL shape: `https://<host>:8443/sub/<token>` — the port must be in the URL, plain 443 is blocked for the owner's ISP. The layout comes from the `kind` file in the token dir (`meta` = one node, `whitelist` = provider list, `full` = legacy 25-node list). **Только TLS:** подписка по `http://<IP>/sub/<token>` на :80 снята и заводить её заново нельзя — открытый текст отдаёт токен и весь список узлов любому на пути, а точечный блок 80-го убивает этот путь вслепую. Любой новый эндпоинт подписки/лендинга — только https на 8443.

Full text → [references/subscription-shapes.md](references/subscription-shapes.md)

## Вход на 443/4443 — nginx stream + Vision

**Фронт остался у nginx.** Xray не забирает 443: `stream`+`ssl_preread` просто маршрутизирует
по SNI, поэтому живой `stream-443.log` (реальный IP + SNI) сохраняется, а откат — это правка
двух файлов. Карта вынесена в `/etc/nginx/stream.d/443-map.conf`, `nginx.conf` подключает её
`include` внутри `stream {}`:

```
www.cloudflare.com -> 127.0.0.1:10445   # mtg, proxy_protocol
edge.esmien.ru     -> 127.0.0.1:10055   # VLESS+Vision+TLS (свой домен), +1000 для b
default            -> 127.0.0.1:9443    # все vhost'ы, proxy_protocol
```

Одна карта обслуживает **два** stream-сервера — `listen 443` и `listen 4443`: TCP/443 у части
операторов режется молча, и такому клиенту выдаётся вход на 4443.

- **Один вход на IP, и он не врёт про домен.** Два входа на одном адресе, из которых один
  заявляет чужой SNI, хуже одного честного: несовпадение SNI↔IP — готовая подпись подмены, она
  маркирует адрес, а блок по IP:порт убивает заодно чистый вход. Поэтому камо-REALITY с этого IP
  снят: `reality-in` удалён из `config.json`, камo-SNI из карты, узел из подписки. Маскарад под
  чужой домен возвращать **только на отдельном IP**; свой домен + свой серт + фолбэк-страница
  дают тот же эффект без подписи.
- **У Vision своё имя, а не то, на котором висят vhost'ы.** `vpn.esmien.ru` на 443 обязан уходить
  в `default` — иначе отваливается legacy WS `/general`, которым ходят консольные клиенты.
  Поэтому SNI для Vision — отдельный поддомен (`edge.esmien.ru`, A-запись на наш IP через CF API).
  После любой правки карты проверять оба: `curl -o /dev/null -w '%{http_code}' --resolve
  vpn.esmien.ru:8443:<ip> https://vpn.esmien.ru:8443/ws` (и `/general`) → `400`, плюс Vision
  сквозным клиентом через `edge.esmien.ru:4443`.
- **TLS внутри Xray требует серта в контейнере.** Серты копируются в data-volume каждого цвета
  (`/usr/local/etc/xray/vision.crt|key`) хуком `certbot renew`; `validate()` в `vpn-bluegreen.py`
  обязан монтировать этот volume, иначе `xray -test` падает `no such file` и apply не переключает
  трафик. Проба здоровья: `security=tls` без `wsSettings` = TCP-connect, иначе HTTP-код 400.
- **На одном IP — один вход, и SNI должен совпадать с ним.** Чужой SNI (камо REALITY, mtg-подмена
  `www.cloudflare.com`) маркирует *адрес*, а не отдельный поток: заморозка бьёт по IP:порту и
  убивает заодно чистый вход. Итог на этой VPS: единственный маршрут в карте —
  `edge.esmien.ru → vision-in` (443 и 4443), всё остальное — vhost'ы или reject. mtg
  (MTProto-прокси) удалён: контейнеры `mtproto-faketls*` остановлены с `restart=no`, мост
  `127.0.0.1:10445 → 10443` убран из nginx stream. Его UUID переехал в
  `/root/.secrets/ws-client-uuid` (его читают `mkcli.py` и `make_sub.py`).
- **`:443` — не святое.** У части операторов TCP/443 к конкретному IP режется молча: клиент
  показывает `timeout`, а в `stream-443.log` трафик падает с 157 к 11 коннектов за 10 мин. Диагноз
  ставится сравнением: тот же хост на 8443 отвечает (303 ms) → это не сервер. Проверять
  доступность снаружи — `check-host.net/check-tcp?host=<ip>:<port>` (JSON: `request_id`, потом
  `/check-result/<id>`, есть узлы `ru1`/`ru3`); если из РФ открыто, а у клиента нет — виноват его
  оператор, но вход надо перевозить туда, где клиенты. nginx stream держит одну и ту же SNI-карту
  на **443 и 4443**; REALITY-узел в подписке смотрит на 4443, hysteria слушает UDP/8443.
  `v2rayNG` показывает `timeout` у hysteria-узла всегда — он не умеет пинговать QUIC, это не
  диагностика.
- **Как это выглядело с камо (если его когда-нибудь вернут — только на отдельном IP).** Симптом
  заморозки: узел один раз поднимается (`access.log`: одна строка `reality-in -> fr`), через минуту
  все новые коннекты приходят с `bytes_in=0` и висят 30 с. REALITY платит RTT до `dest` на каждом
  рукопожатии, за `mts.ru` сидит WAF и рвёт relayed-хендшейк (`REALITY: processed invalid
  connection … handshake did not complete successfully`; в `stream-443.log` при этом `sni=` и
  `in≈4KB out≈9.5KB`, в `access.log` ноль строк `reality-in`), `www.microsoft.com` даёт 0.7 s на
  рукопожатие, а клиентский `fp=ios` не проходит аутентификацию (0/3 против 3/3 у `chrome` и
  `safari`). Отбирать только харнессом `scripts/reality-camo-probe.py <кандидаты> --fp
  chrome,safari,ios` (временный сервер на каждого кандидата, живой вход не трогает); годится 5/5,
  4/5 — брак.
- **«Я обновил подписку» ≠ профиль обновился.** iOS-клиенты мержат узлы, а не перезаписывают их:
  после смены камо клиент продолжал стучаться со старым `sni=`, а в его списке новый узел висел с
  `latency n/a`. Проверять надо не дату в приложении и не слова, а `stream-443.log` его IP: с каким
  SNI стучится и сколько байт приходит; совпадение с камо - единственное доказательство, что клиент
  доехал до нового узла.
- **Vision-фолбэк обязателен.** TLS-сервер, который завершает рукопожатие и молчит, — сам по себе
  отпечаток. `vision-in` отдаёт всё, что не VLESS, в локальный nginx-стаб:
  `"fallbacks": [{"dest": "127.0.0.1:8091"}]` + `root /var/www/vpn-stub`, и браузер на
  `vpn.esmien.ru:443` получает валидный серт и обычную 200-страницу.
- **Порт для фолбэка выбирать по `ss -tlnp`, а не по памяти.** `127.0.0.1:8081` был занят SearXNG:
  фолбэк отдавал `200`, но это была чужая страница, и проверка «код 200» ничего не заметила.
  Сверять тело/размер ответа (`size=181` у заглушки), а не только статус.

- **Карту перегенерирует `apply_brand.py` (`write_stream_map`) при каждом flip.** Если этого не
  делать, после blue/green-переключения карта указывает на мёртвый цвет: WS работает, Vision висит —
  самый коварный симптом.
- **Инбаунд `vision-in`**: `127.0.0.1:10055` (+1000 для цвета b), `security=tls`, серт из
  `/usr/local/etc/xray/vision.{crt,key}`, клиенты клонированы из `ws-in` с `flow=xtls-rprx-vision`,
  `sockopt.acceptProxyProtocol: true` (nginx отдаёт PROXY-префикс), `fallbacks` → локальный стаб.
  `xray x25519`-ключи REALITY остались в `/root/.secrets/reality.key`, но входом не используются.
- **Удалённый узел обязан исчезнуть из всех генераторов.** `build_meta` собирал список
  `[r_link, v_link, ws_link]` и падал `TypeError: expected str instance, NoneType found` на первом же
  `None`: собирать пары `(link, name)` и фильтровать пустые, а не полагаться на порядок `if`-веток;
  то же для clash `proxies` и sing-box `outbounds`. `make_sub.py` запускать без `>/dev/null` и смотреть
  exit-код — при падении он оставляет старые файлы, и подписка выглядит «нетронутой».
- **`probe_direct` в `vpn-bluegreen.py` должен пропускать reality-инбаунды**: HTTP-GET там получает
  закрытие соединения, и apply навсегда остаётся с «N-1 из N отвечают». Для reality health = TCP connect.
- **`xray -test` на хосте падает на `geoip:private` (`geoip.dat` лежит внутри контейнера)** — это не
  ошибка конфига; валидацию делает `vpn-cfg apply` внутри контейнера.
- **Логи:** пути в `config.json` ведут внутрь контейнера, `/var/log/xray` — docker-volume. Симлинк
  `/var/log/xray -> /var/lib/docker/volumes/<id>/_data` даёт хвост и logrotate на хосте (14 дней,
  `copytruncate`). В access-логе видно `[reality-in -> direct] email: …` — этого хватает для разбора.
  **Симлинк смотрит в volume цвета `a`, а трафик часто несёт `b`:** тогда `access.log` молчит сколько
  угодно долго, и вывод «клиент ничего не присылал» оказывается ложью — у него в это время 700 живых
  запросов. Перед любым разбором брать путь по активному цвету: `docker inspect vpn-router$([ $(cat
  /root/vpn-router/vpn-color) = b ] && echo -b) --format '{{range .Mounts}}{{if eq .Destination
  "/var/log/xray"}}{{.Source}}{{end}}{{end}}'` и читать уже оттуда (или перевесить симлинк).
- **Один мёртвый вход ≠ блок адреса.** Прежде чем объявить «режут IP целиком», сверить с входами из
  того же окна времени: если WS на 8443 и hysteria несут трафик — адрес жив, душат конкретный класс
  транспорта (голый TLS с Vision), и лечится это выбором другого входа, а не переездом. Обобщение
  «раз три входа подряд умерли, значит адрес» уже стоило неверного вывода при живых WS и UDP.
- **Релей, живой по пингу, может рвать поток.** `fr` отвечал 53 ms и одновременно сыпал
  `grpc/encoding: failed to fetch hunk … RST_STREAM PROTOCOL_ERROR`; всё, что на него маршрутизировано,
  умирало пачками. Судить выход только пачкой реальных HTTPS через него (6–10 запросов, нужно 6/6), а
  не пробой `generate_204` и не ICMP.
- **Подписка несёт три узла, и все — всем токенам** (решение владельца: это разные эшелоны,
  каждый страхует остальные). Порядок: `Vision` (VLESS+TLS на своём домене, адрес — **IP, а не
  домен**: DNS не нужен и не светится), `совместимость` (WS 8443), `UDP резерв` (hysteria2 8443/udp).
  Гейтинг маркерами `compat`/`udp` снят — не возвращать без просьбы; REALITY-узла в списке нет.
  «Клиент говорит, что VPN мёртв, а сервер жив» — читать `stream-443.log` по его IP: нет ни одного
  входа с нужным SNI ⇒ клиент к этому узлу не ходил вообще (устаревший профиль), а пустой `sni=` с
  `bytes_in=0` и `time=30.000` — это открытый сокет без ClientHello, тоже клиент.
  Порядок разбора — `references/client-drop-triage.md` → 4g.
- **Консольные конфиги под рукой:** `/root/vpn-router/cli/vision-10860.json` (SOCKS 10860, Vision) и
  `ws-10861.json` (SOCKS 10861, WS `/general`) — заново не генерировать, клиент забирает `scp`-ом.
  UUID в них — `ws-client-uuid`, и он обязан совпадать с инбаундом, к которому ведёт путь:
  `/ws` → `ws-in`, `/general` → `in-general`; чужой UUID даёт `000` на живом входе и выглядит как
  «WS сломался».
- **Откат:** `scripts/rollback-443-reality.sh` (снимок `pre-reality-*`: config, apply_brand,
  vpn-bluegreen, nginx.conf; отдельный снимок подписок; затем `apply` + `reload` + проверка).
  Проверка входов после любой правки фронта — `scripts/verify-443.sh`.
- **Голый IP не должен отвечать нами (18.11.2026).** Без явного `default_server` nginx отдавал
  любой неизвестный SNI первому vhost'у: снаружи это был серт `*.esmien.ru` и логин Open WebUI.
  Лечится `99-default-ssl-reject.conf`: `listen 127.0.0.1:9443 proxy_protocol ssl http2
  default_server; ssl_reject_handshake on;`. **Ловушка:** если в `listen` не повторить
  `proxy_protocol ssl http2` в точности как у остальных vhost'ов, nginx открывает второй,
  недостижимый сокет — конфиг валиден, а default не срабатывает и unknown SNI снова отдаёт 200.
  Симптом — `verify-443.sh` кажет `unknown SNI -> 200`. Плюс `server_tokens off` (в `http {}`).
- **Лишний узел в списке — это класс жалоб «ничего не работает».** Клиент выбирает нерабочий узел
  (замороженный UDP, устаревший WS, старый SNI) и делает вывод про весь VPN, хотя сервер жив.
  Поэтому у каждого узла в названии видно, что это запасной вход, а жалобу проверяют по
  `stream-443.log`/`access.log` его IP, а не по словам «обновил подписку».
- **Клиенты:** REALITY умеют v2rayNG, Hiddify, Streisand, Shadowrocket, NekoBox, mihomo/sing-box;
  старые Clash — нет. Подписка не переезжает: тот же `https://<host>:8443/sub/<token>`, тот же токен,
  те же UUID — клиент подтягивает сам (`profile-update-interval 12`).

Как это мерить снаружи и что реально скрытнее (Vision против WS+TLS, маска Apple, DDNS, панель) —
`ip-reputation-and-ban-risk` → `references/vpn-entry-stealth.md`.

## Deep dives (references)

- **Change the public host** — nginx, cert, `brand.json`, subscriptions and `vpn-cfg` host copy in one pass → `references/changing-public-host.md`
- **Per-user keys** — every person gets their own UUID and sub URL, so revocation touches nobody else → `references/per-user-keys.md`
- **Landing page per user (`/u/`)** — the page each user opens for their links → `references/landing-pages.md`
- **Usage stats** — per-user counters from the xray `StatsService`, «кто реально пользуется» → `references/usage-stats.md`
- **Blue/green** — applying a config change with no downtime → `references/blue-green.md`
- **Subscription expiry** — read it from the provider's `subscription-userinfo` header, not the panel; daily 07:00 UTC timer warns at 3/2/1 days → `references/subscription-expiry.md`
- **Upstream subscriptions** — relaying third-party nodes as exits → `references/upstream-subscriptions.md`
- **RU split** — banks / gosuslugi / VK / OZON / WB direct or via the RU exit → `references/ru-split.md`
- **Gemini / geo** — the country is Google's own lookup of the connection IP; measure with `scripts/gemini_geo_check.py` → `references/gemini-geo.md`
- **Whitelist mode** — the LTE whitelist list goes to the client as links, never through this server → `references/whitelist-mode.md`
- **Borrowed exit** — a third-party subscription used as an exit → `references/borrowed-exit.md`
- **Routing watchdog** — a timer rewrites routing every minute; edits must survive it → `references/routing-watchdog.md`
- **«Нас не съели ли VPN-клиенты?»** — three measurements instead of guesses → `references/client-share-measurements.md`
- **Блокировка РКН** — пять ручек (IP/SNI/диапазон/whitelist/**заморозка по пакетам**), замеры по 435 точкам и какие сети заморожены, триаж, переезд на новый IP, цена домена и общий IP с AI-стеком, проверка ASN/префиксов и спам-листов, почему CF перед VPN не защита, что даёт REALITY и почему сейчас не Hetzner/OVH → `references/blocking-risk.md`
- **Домен и доставка** — почему подписки надо вынести на отдельный регистрируемый домен, выбор зоны и регистратора, канал восстановления (бот + CF Pages + deep links), Cloudflare Tunnel для WebUI → `references/delivery-channel.md`
- **Pitfalls** — the full list of expensive mistakes → `references/pitfalls.md`

## Certificates

Full text → [references/certificates.md](references/certificates.md)

## Client devices — always-on Linux desktop

The GNOME «Добавить VPN» dialog offers only OpenVPN / PPTP / WireGuard; our entry is VLESS over WS+TLS, so none of them apply and there is nothing to tick there. Do not answer that by adding a WireGuard/OpenVPN inbound to the server either — a new public surface with its own auth and none of the routing rules.

When the owner says he does not want to keep a client window open, the shape is a **daemon in TUN mode**, not a GUI app (Hiddify/v2rayA need the window; a local proxy on `127.0.0.1` only reaches apps that honour a system proxy). mihomo over the `clash.yaml` subscription is the cheapest base: that profile is already a complete config, so only a `tun:` block plus `dns.listen` get injected and can be re-injected on every refresh. Full recipe, systemd units, verification and pitfalls: `references/linux-always-on-client.md`; the GUI-free desktop variant (merge script, unit files, FlClash/`add route 0: file exists` trap) — `references/desktop-mihomo-tun.md`.

## UDP backup entry — Hysteria2 (UDP/8443)

TSPU freeze counts **packets in one TCP connection** (~25 packets / ~16 KB, ~8 on mobile) and hangs it in both directions; the connection does not reset, the app just waits. UDP is untouched by that rule, so a UDP transport is the only thing that survives once a network is frozen. Measured 10.11.2026 over 435 endpoints / 154 hosters: 87% pass from RU, the rest freeze — and the freeze is per **network/AS**, whole companies at once (OVH, Hetzner incl. US/SG, DigitalOcean, Vultr, BuyVM, Scaleway, Gcore-type nets frozen; HostHatch, FlokiNET, Psychz, Time4VPS, Serverius pass). Check the ASN before recommending any hoster, and never promise UDP as immunity: blocking all UDP is a one-line rule, they just have not paid the collateral cost yet.

Live shape: `hysteria-server.service` → `/usr/local/bin/hysteria server -c /etc/hysteria/config.yaml`, listen `:8443` **UDP** (было `:443` — у части операторов этот порт к нашему IP режется так же, как TCP), wildcard cert, `obfs: salamander`, masquerade proxied to `http://127.0.0.1` (a probe without the obfs password lands on nginx and sees a normal page). Secrets in `/root/.secrets/hysteria-owner.txt` (0600); repo carries `hysteria/config.example.yaml`, both units and `scripts/install-hysteria.sh` — a rebuild is `bash scripts/install-hysteria.sh` and it keeps existing secrets.

**Hysteria must not dial the internet itself.** A bare UDP entry puts every user in Estonia: Gemini refuses and Gosuslugi 403s, which reads as «UDP не работает». The fix is one hop: Xray gets a loopback SOCKS inbound (`tag: udp-in`, port 10089, `udp: true`) and hysteria's only outbound is `type: socks5 → 127.0.0.1:10809`. That 10809 is `vpn-socks-relay.py`, which re-reads `/root/vpn-router/vpn-color` on every connection and dials 10089/11089 — because `derive_b` shifts *every* inbound port by +1000, so a static socks port breaks silently on the next blue/green flip. With the relay, server-side routing is shared: Google → FR, `.ru` → Moscow, rest → EE. Verify by resetting xray outbound counters, pulling Gosuslugi and `generate_204` through the hysteria client, and reading `p15`/`fr` deltas — not by trusting the config.

Pitfalls that cost a restart loop each: v2.14 replaced ACL with expressions (`acl.rules: [{outbound: name, match: expr}]`) — `proxy(name)` legacy syntax dies with «outbound proxy not found»; and with no ACL at all the **first outbound in the list** takes everything, so a single `xray` outbound needs no rule. `vpn-bluegreen.py`'s linter demands `settings.clients` on every non-dokodemo inbound, so a noauth loopback socks inbound is rejected until `socks` joins that exemption.

Per-token roll-out, never global: `python3 /root/vpn-router/hy2_users.py --apply` does the whole thing — `/root/.secrets/hysteria-users.json` is the source of truth (one password per person, `auth.type: userpass`, usernames transliterated), it rewrites every `meta` token's `extra_nodes.json`, rebuilds subs and restarts hysteria.

**Never print the auth block when checking it.** `grep -A12 ^auth:` dumps every password into the transcript — read the state file in Python and print usernames only. **Маскировать по имени ключа, а не по слову `password`:** блок устроен как `auth: → userpass: → <имя>: "<пароль>"`, поэтому регулярка вида `password\s*:` его не ловит и «структура без секретов» печатает пароли всех пользователей. Печатать только имена ключей, длины значений или `True`/`False`. If one leaks, delete the state file and re-run: rotation costs one restart and one subscription refresh.

**After any auth change, the symptom is a dead node, not a broken server.** Single password → per-user `userpass`, or a rotation, leaves every already-imported node holding a stale credential; the app reports timeout, the server is fine. Say «обнови подписку» before touching anything, and prove it with `journalctl -u hysteria-server` (`client connected {id: ...}`) plus xray's `inbound>>>udp-in>>>traffic` counters — a growing counter means the tunnel carries traffic. Triage order for this entry, including the tcpdump recipe and what a local loopback test does *not* prove: `references/client-drop-triage.md` §4e.

`build_meta` appends the extra to `list.txt` and to clash `proxies`, so every file outside `extra_nodes.json`/`list.txt`/`clash.yaml` stays byte-identical — verify with a `diff -rq` against a backup before claiming nothing broke. Link shape: `hysteria2://<user>:<pw>@<host>:8443/?sni=<host>&obfs=salamander&obfs-password=<obfs>#name`. v2rayNG cannot read hy2 and just will not import that node; Hiddify, NekoBox, sing-box and Clash Meta can. `singbox.json` is not extended by extras — a sing-box user gets the TCP node only. The clash group is `type: select` on purpose: do not turn it into url-test without saying so, a silent path change is what makes «connected, but Gemini says no» invisible.

## Домен как точка отказа — доставку отделить от туннеля

Владелец считает так: адрес — расходник (DNS TTL 300, пять минут), а имя хуже, потому что вшито в профили; SNI-блок `esmien.ru` убьёт и вход, и `/sub/`, и потребует ручной раздачи. Сейчас оба висят на `vpn.esmien.ru` — одна точка отказа. Что из этого следует: подписки живут на **отдельном регистрируемом домене** (не поддомене — правила матчатся по корню), туннельное имя становится расходником, а клиенты сами подтягивают новый узел за `profile-update-interval 12`. Reality тут — бонус (убирает имя из SNI), не основа: от TCP-заморозки и блока ASN он не спасает. Выбор зоны: `.com`/`.org` (Cloudflare Registrar — продление = регистрация, ~$10–11); `.us` отпадает (nexus: нужно присутствие в США), `.рф`/`.su` — та же юрисдикция, от которой страхуемся, промо-зоны (`.online`, `.shop`, `.tech`) дают вилку «−98% на год → втрое на продлении». **Юрисдикция регистратора важнее цены:** российский регистратор (nic.ru, Beget, Рег.ру) работает по требованиям РКН напрямую — страховка, выданная той же стороной, от которой страхуемся; Cloudflare и Porkbun клиентов из РФ принимают, оплата иностранной картой проходит, а часть западных (Namecheap, GoDaddy) после 2022 РФ не обслуживает — проверять у конкретного до оплаты. Брать сразу на 2–3 года: скачок продления в неудачный момент — более вероятная авария, чем бан. Reality тут — бонус (убирает имя из SNI), не основа: от TCP-заморозки и блока подсети не спасает.

**Согласованная схема (пока не построена):** подписки раздаёт Cloudflare — R2 с теми же файлами + Worker, повторяющий логику nginx `/sub/` и его заголовки; узлы переезжают на `.com`; `.ru` остаётся авангардом-редиректором. Честные границы: **узлы переезжают бесшумно**, а **URL подписки без действия человека не переносится** (301 живёт только пока старое имя резолвится; сохранит ли клиент адрес после редиректа — зависит от реализации, для Happ не проверено). CF-канал туннель не прикрывает: он по-прежнему коннектится на наш IP напрямую, так что шанс бана по адресу не падает — падает время восстановления. Жёсткий дедлайн не про РКН: продление `esmien.ru`.

**Вход-прослойка вместо переезда.** Согласовано с владельцем: дешёвый зарубежный VPS (Литва/Эстония, Time4VPS/FlokiNET/HostHatch — только незамороженный ASN и не 41745) с голым nginx stream: TCP 8443 + UDP 443 → наш адрес. Клиент видит вход, эстонский IP из РФ больше не виден (плечо Литва→Эстония границу не пересекает), а сгоревший вход меняется за ~300 ₽ и десять минут вместо двухчасового переезда стека. TLS остаётся сквозным, сертификат и SNI не меняются. Транспортный лимит важнее RAM: 1 ГБ хватает, 1–2 ТБ трафика на восемь человек — нет. Такой же сервер **внутри РФ** входом ставить нельзя: он станет видимым адресом, РКН увидит плечо к зарубежу, а хостер убьёт аккаунт по abuse; в роли выхода для `.ru` он и так уже есть (`p15`/`p17`).

**Канал восстановления — отдельно от доставки.** Telegram-бот переживает бан нашего адреса (ходит в `api.telegram.org` исходящим — люди получают сообщение от Telegram), страница-инструкция на нашем домене — нет: она нужна именно в момент аварии. Отсюда: бот на сервере + инструкция на CF Pages; людей привязывать `t.me/<bot>?start=<token>`, а не ником (ник не у всех, меняется, `getChat` отдаёт его только тем, кто уже писал); ссылку доставлять deep link `hiddify://import/<url>` и QR — один тап, а не «вставь URL». Детали, зоны/регистраторы, Cloudflare Tunnel для WebUI — `references/delivery-channel.md`.

## Failover — off, deliberately

The owner removed automatic failover: `vpn-failover.timer` is `disabled`/`inactive` and the default route is pinned to `direct`. Do not re-enable it without an explicit request. Rationale: a silent flip to `direct` keeps the internet alive but leaves geo-gated services refusing in a way that looks like the tunnel works ("connected, but Gemini says no"), which is harder to diagnose than a dead tunnel. With the timer off an exit outage now costs only the scenario it carries — Google/Gemini falls from `fr` to the
`fi` fallback and then fails loudly, while everything on `direct` is untouched.

`failover.py` and the unit files stay on disk and in the repo, unwired — re-enabling is `systemctl enable --now vpn-failover.timer`. If a probe is ever restored, keep the cadence irregular (`RandomizedDelaySec=300` on a 15-minute timer) so it does not read as a bot, and test the logic on a copy of the config, never against the live probe host.

## Traps worth memorising

The four that cost the most, verbatim from `references/pitfalls.md`:

- **Правка nginx, сделанная только в `/etc/nginx/conf.d/vpn-*.conf`, живёт до следующего `vpn-cfg apply`.**
  Тот запускает `apply_brand.py`, а он перегенерирует эти vhosts из своего шаблона — вместе с `location = /`.
  Ручная заглушка молча откатывается: ответ на `/` вернулся к прежнему короткому `ok` уже после проверки,
  и это увидел владелец, а не я. Любую правку этих двух vhosts вносить в шаблон `apply_brand.py` (и в копию
  `vpn-service/router/apply_brand.py`), затем `python3 apply_brand.py && nginx -t && systemctl reload nginx`.

- **Never dump an outbound as JSON.** Trojan credentials live in `settings.servers[].password`, VLESS in
  `settings.vnext[].users[].id` — a "show me the outbound" print leaks the provider's shared keys and a
  client UUID straight into the chat. Print tag, protocol, address:port and stream network only, and
  mask anything whose key matches `pw|password|id|key|token`.
- A user's "the site is down" on one host is rarely the tunnel: check whether the requests reached the app at all before rebuilding anything (`references/client-drop-triage.md`, section 4d). Also check that the name **exists**: under a fake-ip client a nonexistent host is handed a `198.18.x.x` and simply hangs, so the browser reports `ERR_TIMED_OUT` instead of "server not found" and the tunnel takes the blame for a bad URL — `dig +short @1.1.1.1 <host>` plus the zone's record list settles it in one step.
- Writing nginx config through `printf`/heredoc mangles quotes and backslashes (`\"$request\"`, `\\S`), and `nginx -t` then fails on a file that looks fine on screen. Write generated snippets with Python `write_text` (staging under `/tmp` + `install -m 644` when a direct write to `/etc/nginx` is refused), test, then reload — the same trap bites fail2ban filter regexes. Same reason a python heredoc embedded in a compound `cmd1 && python3 - <<EOF` block can silently produce a truncated file (16 bytes, no error): put the generator in its own file and run it.
