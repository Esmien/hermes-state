# "VPN отваливается" — triage order

A drop report is answered with measurements, not with a guess. Prove the server end to end
first; only then look at the client. Each step below produces a number you can quote.

## 0. Resolution — check this before the tunnel

If the client shows **every node as `n/a`** ("ping doesn't even leave") and the entry log holds
**zero** packets from its IP — not few, zero — the fault is usually the name, not the tunnel. A
browser on the same phone may still open the entry URL because it serves a cached record while the
VPN app resolves fresh.

```bash
for r in 8.8.8.8 1.1.1.1 9.9.9.9; do echo -n "$r "; dig +short +time=4 @$r <host> A; done
dig +time=5 @8.8.8.8 $RANDOM.<zone> A            # never-used name: proves it is not caching
```

Resolvers disagreeing (`SERVFAIL` at Google/Quad9, an answer at Cloudflare) means the zone's
authoritative servers are failing, not that the record is missing — a missing record answers
`NXDOMAIN` even for a random name. Get the NS list from the delegation itself with `dig +trace`
(it can differ from what the provider's panel shows) and measure loss on each one:

```bash
for ns in dns1.provider.org dns2.provider.org; do ok=0
  for i in $(seq 5); do [ "$(dig +short +time=2 +tries=1 @$ns <host> A | head -1)" = "<expected ip>" ] && ok=$((ok+1)); done
  echo "$ns $ok/5"; done
```

A server answering 1–2 of 5 is the bug: validating resolvers collapse it to `SERVFAIL` for every
client, while caches keep the last good answer alive — the exact "browser opens, app can't ping"
split. Separately confirm the server itself is reachable (`check-host.net/check-tcp` on the entry
port; a dozen answering nodes means only the name is broken, so stop suspecting the ISP).

Mitigation while the zone is broken, both validated on this host:

- add duplicates of the main routes with `address = <server IP>` while `sni`/`host` stay the domain,
  so the certificate still validates — `make_sub.py` builds them as `<route> по IP`;
- serve the same bundle over plain HTTP on port 80 keyed by IP (`server_name <ip>`, same
  `$esmien_sub_*` maps) so a client that cannot resolve can still fetch a profile. Say plainly that
  this exposes the token and is temporary.

The durable fix is DNS-side: repoint the delegation to the NS that actually answers, or move the
zone to a provider with a working API. A free DNS provider is a single point of failure for the
whole entry; if its dashboard answers `403` from a datacenter IP, the owner has to change it by hand.

## 1. Server liveness

```bash
docker inspect vpn-router --format '{{.State.Status}} restarts={{.RestartCount}} {{.State.StartedAt}}'
systemctl is-active nginx
```

`running` with `restarts=0` and a start time from days ago means the container never died —
a crash loop would show a fresh `StartedAt` on every check.

## 2. End-to-end dial through our own entry

This is the definitive "is the tunnel itself broken" test: a local Xray client that speaks
VLESS+WS to `127.0.0.1:8443` with the live UUID, exactly like a real phone.

```python
import json, pathlib
uuid = pathlib.Path("/root/mtproto-faketls/ws-client-uuid").read_text().strip()
cfg = {"log": {"loglevel": "warning"},
 "inbounds": [{"tag": "s", "listen": "127.0.0.1", "port": 10888, "protocol": "socks",
               "settings": {"auth": "noauth", "udp": False}}],
 "outbounds": [{"tag": "proxy", "protocol": "vless",
   "settings": {"vnext": [{"address": "127.0.0.1", "port": 8443,
                             "users": [{"id": uuid, "encryption": "none"}]}]},
   "streamSettings": {"network": "ws", "security": "tls",
     "wsSettings": {"path": "/general", "headers": {"Host": "vpn.esmien.qd.je"}},
     "tlsSettings": {"serverName": "vpn.esmien.qd.je"}}}]}
pathlib.Path("/tmp/cli.json").write_text(json.dumps(cfg))
```

Start it as a tracked background process (never `nohup`/`setsid` — the tool refuses shell-level
backgrounding and it is easier to kill a tracked child), then measure:

```bash
curl -sS -m 60 --socks5-hostname 127.0.0.1:10888 -o /dev/null \
  -w 'code=%{http_code} speed=%{speed_download} B/s time=%{time_total}\n' \
  "https://speed.cloudflare.com/__down?bytes=20000000"
curl -sS -m 20 --socks5-hostname 127.0.0.1:10888 -o /dev/null \
  -w 'generate_204=%{http_code} time=%{time_total}s\n' http://connectivitycheck.gstatic.com/generate_204
curl -sS -m 25 --socks5-hostname 127.0.0.1:10888 https://ipinfo.io/json
```

Healthy on this host: 200 at tens of MB/s, `generate_204=204` in tens of ms, exit IP equal to
the route's outbound (EE for `/general`, Paris for `/france`). Also repeat 5–6 quick requests —
a tunnel that dies mid-stream shows 000/timeouts there even when the big pull succeeded.

## 3. Kill the test client before the next measurement

```bash
pkill -f "xray run -c /tmp/cli"; sleep 1; pgrep -af "xray run" | grep -v vpn-router
```

The only surviving process should be the container's own core. If another `xray run` is alive,
the next config you start **cannot bind the socks port**, exits silently in the background, and
all following curls answer through the *previous* config — which is how a healthy `/france`
route gets reported as exiting through EE. Symptom to recognise: the measured exit IP belongs
to a different route than the path you just configured.

Same trap in shell form: `pkill -f "<pattern>"` / `pgrep -f "<pattern>"` also match the shell
running the command, because the pattern sits in its own command line. The call kills itself with
SIGTERM and everything after it in the chain never runs. Build the pattern so it does not appear
literally (`p=$(printf 'hy2-test%s' '-client.yaml')`) or kill a PID you already know.

## 4. Count the client's reconnects

```bash
awk '$9==101 {print substr($4,14,5), $1}' /var/log/nginx/vpn-8443.log \
  | sort | uniq -c | sort -rn | head
ss -tn state established '( sport = :8443 )'
```

`101` is a completed WebSocket upgrade; field `$10` is the bytes the client got back.

| signal | reading |
|---|---|
| tens of `101`/min from one IP, zero established sockets from that IP | the device loses its network and the app retries in a loop |
| `101` with 0–200 bytes | the handshake completed, no data ever flowed |
| a few `101` per IP, long-lived established sockets, large `$10` | normal session |
| `499` on a path | client aborted; count per IP to see who is flapping |

Identify the device from its **subscription** line, not its WebSocket UA: Happ fetches
`/sub/<token>` as `Happ/4.12.0/ios/…` but opens the tunnel with a desktop Chrome UA, so a
"Windows Chrome" WS stream from a home IP is usually the owner's iPhone. Match the IP between the
subscription request and the `101` lines before blaming a device that is not even in the room.

## 4b. Session lifetime — the number that decides

`$request_time` on the vhost turns the log into a session histogram: an upgraded WebSocket writes
its line **when it closes**, and `rt` is the whole session lifetime. Define the format in a
`conf.d` file (it must sit in the http context), point the `access_log` line in
`apply_brand.py`'s template at it, then `python3 apply_brand.py && nginx -t && systemctl reload nginx`.

    log_format vpnx '$remote_addr [$time_local] "$request" $status $body_bytes_sent rt=$request_time urt=$upstream_response_time ua="$http_user_agent"';

Parse with a regex (`rt=([\d.]+)`), not awk columns — the custom format no longer matches the
combined layout and column-based counting silently reads the wrong field. Two shapes:

| rt | bytes | reading |
|---|---|---|
| ~0.1 s, on many paths at once | tiny | client health checks (url-test / auto-ping), not failures |
| 2–9 s, repeating, one path | same few KB each time | the tunnel stalls mid-transfer and the app redials |

## 4c. A stall after a few KB is an MTU blackhole, not DPI

Median session of a few seconds that keeps delivering the same ~3.8 KB (2–3 full packets), while
small requests and the server-side self-test are perfect, is the classic PPPoE path-MTU blackhole:
our 1500-byte packets are dropped on the client's line and the ICMP that would teach TCP the real
MTU never arrives, so the transfer dies once it outgrows the first packets. The discriminator that
separates it from provider filtering: the owner's **whitelist** subscription keeps working on the
same Wi-Fi, because whitelist traffic never touches our entry at all.

Clamp MSS on the entry ports (reversible, no speed cost, applies to all clients):

```bash
iptables -t mangle -A POSTROUTING -p tcp --sport 8443 --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1300
iptables -t mangle -A POSTROUTING -p tcp --sport 2087 --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1300
iptables -t mangle -S POSTROUTING | grep TCPMSS     # confirm, and persist if it works
```

Ask the owner to browse for a minute, then re-read the `rt` histogram — sessions should climb from
seconds to minutes. If they do not, the next split is by exit: dial `/general` (direct) instead of
`/france` to decide between the path and the borrowed exit, and never change both at once.

## 4d. Один сайт не открывается, остальное работает

Не запускать полный triage туннеля. Сначала — дошли ли запросы до приложения:

- Клиентский IP в логе приложения — это **egress узла**, а не домашний адрес пользователя (датацентр
  в чужом городе). Опознавать устройства по ASN/гео нельзя: московский узел выглядит как московский
  ISP, новосибирский — как новосибирский.
- Проверить конкретный выход без паролей и без контейнера: скопировать outbound из
  `/root/vpn-router/config.json` в socks-only клиентский конфиг (дословно, UUID не печатать),
  `xray run -c`, `curl --socks5-hostname`, гасить по PID.
- **Одиночный `curl` врёт.** Узел, который принимает первое соединение и перестаёт принимать
  следующие, на одном запросе выглядит здоровым. Мерить пачкой (~20 параллельных запросов на реальный
  ассет) и сравнивать с заведомо хорошим выходом в том же прогоне: 20/20 за 0.5 с — живой, 20/20
  `000`/таймаут — встал, 9/10 — деградировал. Повторить через пару минут, прежде чем объявлять узел
  мёртвым.
- Если до nginx запросы вообще не дошли, а тот же сервис на другом (сером) имени отдаёт всё — виноват
  край, а не туннель: Cloudflare режет пачку подресурсов с адресов датацентров, см. skill `ai-stack`,
  `references/cloudflare-proxy.md`. Симптом у пользователя: HTML приходит (`200`), DevTools показывает
  ~85 запросов при 4.7 kB transferred, красных строк нет, приложение пустое.

## 4e. UDP-узел (hysteria2) — свой порядок, логов nginx нет

У этого входа нет ни `access.log`, ни WebSocket-upgrade, поэтому привычные шаги 2 и 4 не работают.
Единственные следы — `journalctl -u hysteria-server` (`client connected {"id": "<name>"}`) и счётчики
xray `inbound>>>udp-in>>>traffic`.

- **Первым делом — пришёл ли хоть один пакет**, и только потом конфиг:
  `tcpdump -n -i <iface> 'udp and dst port 443'`. Фильтр по порту ловит и исходящие потоки к чужим
  CDN (любой QUIC к `:443`), а `-c` обрывает дамп на них, не дойдя до клиента — смотри источник в
  строке, а не только счётчик пакетов.
- **Локальный тест ничего не доказывает про внешнюю достижимость.** Клиент на том же хосте,
  целящийся в свой публичный IP, уходит через loopback: протокол и авторизация проверяются, но
  проходит ли UDP через провайдера — нет.
- **«Узел умер сразу после смены авторизации»** (единый пароль → `userpass`, ротация паролей) — это
  почти всегда устаревшая подписка, а не сервер. Симптом: приложение показывает мёртвый узел,
  сервер жив, в логах либо пусто, либо `client connected` с прежним `id`. Лечится переимпортом
  подписки у клиента; правка сервера тут только добавляет шума.
- Если пакеты приходят, id верный, а трафика нет — проверь хоп в xray: `ss -tn state established
  '( sport = :10809 )'` (релей) и рост `inbound>>>udp-in>>>traffic` после запроса.

## 4f. Скорость и задержка: сначала решить, какое плечо измерено

Владелец присылает скриншот спидтеста как доказательство «работает/не работает» — цифры читать по тому, какой выход обслужил замер.

- **Яндекс.интернетометр** меряет до российских серверов, то есть плечо «RU-выход → Яндекс», а не туннель: `.ru` у нас уходит на московский выход (`p15`), так что честный результат складывается из Краснодар → Эстония → Москва.
- **Задержка ~10 мс до Яндекса через туннель невозможна** — это признак, что замер шёл мимо (VPN выключен или клиент отправил домен напрямую). Два скриншота подряд могут быть двумя разными путями; сверять со счётчиками `p15`/`fr`, а не с цифрой на экране.
- Международную полосу мерить только зарубежным (speed.cloudflare.com, fast.com), а потолок сервера — локально (`curl -o /dev/null -w '%{speed_download}' 'https://speed.cloudflare.com/__down?bytes=50000000'`, на этом хосте ~180 МБ/с). Иначе узкое место ищут в Эстонии, когда оно в плече клиента или в зарубежном выходе.

## 4g. REALITY-вход: сначала выяснить, по какому узлу клиент вообще ходил

Когда REALITY — отдельный вход на :443 (SNI-маршрут через `nginx stream`), шаги 2 и 4 смотрят не туда:
у него нет ни `/sub/`, ни WS-апгрейда, а в access-логе xray только уже состоявшиеся соединения.
Первым делом — `stream-443.log`: в нём есть источник и SNI каждого TCP-соединения на :443.

```bash
grep '<client ip>' /var/log/nginx/stream-443.log | sed -E 's/.*sni=([^ ]*).*/\1/' | sort | uniq -c
grep '<client ip>' /var/log/nginx/stream-443.log | tail -5        # bytes_in/bytes_out/time
```

| сигнал | что значит |
|---|---|
| нет ни одной строки с камо-SNI (`sni=mts.ru`) от клиента | клиент к REALITY-узлу **не обращался**: в приложении устаревший профиль или выбран другой узел. Сервер тут ни при чём — не трогать конфиг |
| `sni=` пустой, `bytes_in=0`, `time=30.000`, десятки строк подряд | сокет открыт, ClientHello не пришёл: залипшее/недонастроенное приложение (или порт трогают пробой без TLS), а не блокировка нашего входа |
| `sni=` пустой, `bytes_in>0` | рукопожатие дошло, но SNI не распознан/не отправлен — смотреть, чем именно клиент открывает TCP |
| строки с камо-SNI есть, а в xray нет `reality-in` | рукопожатие разваливается дальше: смотреть `dest` и его повторы |

Дальше — свести по всем входам, какой из узлов подписки клиент реально использует: WS-вход виден как
`GET /general` → `101` в `/var/log/nginx/vpn-8443.log`, UDP-резерв — как UDP на :443 (`tcpdump` или
`client connected` в `journalctl -u hysteria-server`). Если клиент сидит на резервном узле — проблема
не в REALITY, даже если жалуется именно на него.

Серверную сторону доказывать двумя локальными клиентами, а не осмотром конфига: REALITY — xray-клиент
с `serverName=<camo>`, `publicKey`/`shortId` из `/root/.secrets/reality.key`, `address` = **публичный IP:443**
и `curl --socks5-hostname` через него; hysteria — клиент с `socks5.listen`, `obfs.salamander` и
`auth: <user>:<pw>` из `/etc/hysteria/config.yaml`, тем же curl. Оба живы (десятки миллисекунд, `200`)
⇒ виноват клиент/его путь, и следующий шаг — «обнови подписку», а не правка сервера.

Не путать: `rt=102.8` на строке `101` — это длительность WebSocket-сессии, а не задержка (см. 4b).

## 5. Verdict

- Container stable, self-test fast, `generate_204 = 204` → the tunnel is healthy; the drop is the
  **client's own link**. Say it with the numbers (restarts, MB/s, reconnects per minute) and point
  at the device: "switch to mobile data on weak signal", battery optimisation on the VPN app, the
  router's band/channel. Android only declares a Wi-Fi network "no internet" when the connectivity
  probe fails, and a passing 204 rules that mechanism out.
- Self-test fails or the exit IP is wrong → our side. Check rule order first (`inboundTag` rule must
  sit before the catch-all), then that the outbound itself answers when dialled directly (build a
  second client with only that outbound — no entry, no nginx).

A phone that has already fallen back to mobile data is a different network path: MTS mobile cuts
TLS harder than the home line, so a tunnel that will not recover on LTE is a separate finding, not
proof that the server is down.
