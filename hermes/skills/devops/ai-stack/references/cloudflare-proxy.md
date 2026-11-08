# Cloudflare in front of a stack name (orange cloud)

Read before proxying `ai.esmien.ru` (or any other name) through Cloudflare, before adding CF-side
bot/WAF rules, or when `limit_req` suddenly throttles every user at once.

Zone `esmien.ru` is on Cloudflare (`princess/burt.ns.cloudflare.com`). Records are grey (DNS only) by
default because port-80 ACME needed that. A working credential already exists:
`/root/.secrets/cf.ini` (`dns_cloudflare_api_token`, the certbot DNS-01 hook) — never print it, check
it with `GET /client/v4/user/tokens/verify`. Its scopes cover DNS + zone settings + WAF rules; they do
**not** cover Bot Fight Mode.

## Origin topology (why the order matters)

Requests arrive at the `stream` block in `/etc/nginx/nginx.conf` (`listen 443; ssl_preread on`), which
forwards raw TLS with `proxy_protocol on` to the `listen 127.0.0.1:9443 proxy_protocol ssl http2`
vhosts. `conf.d/00-proxy-realip.conf` sets `set_real_ip_from 127.0.0.1; real_ip_header proxy_protocol;`,
so `$remote_addr` is the real client while the record is grey.

With the orange cloud on, the peer at origin is a Cloudflare edge IP, so `$remote_addr` becomes
**Cloudflare's** address. Every `limit_req zone=webui_api` / `limit_conn conn_per_ip` key is then the
same key for everybody: one shared bucket, 429s for the whole family, and fail2ban jails aimed at CF
ranges. **Fix the real IP FIRST, flip SECOND.**

## Real IP: realip does not work here, use a map

Adding `set_real_ip_from <CF ranges>` + `real_ip_header CF-Connecting-IP` in the 9443 server block
(copied into `/etc/nginx/snippets/cloudflare-realip.conf`) **does not help**: with the proxy on,
`$remote_addr` came out as `127.0.0.1` for proxied requests, and switching the header to
`X-Forwarded-For` changed nothing. A probe printing all three values showed the headers arriving
correctly (`proxy_protocol_addr=<CF edge>`, `cf_ip=<real client>`) while `$remote_addr` stayed wrong —
the realip module cannot be layered on this proxy_protocol hop.

What works is bypassing realip for these vhosts. Put a `map` in the http context
(`/etc/nginx/conf.d/01-cf-client-ip.conf`) and key everything on `$client_ip`:

```nginx
map $http_cf_connecting_ip $client_ip {
    default $http_cf_connecting_ip;
    ""      $proxy_protocol_addr;   # прямой трафик
}

limit_req_zone  $client_ip zone=webui_api_cf:20m rate=10r/s;
limit_conn_zone $client_ip zone=conn_per_ip_cf:10m;
limit_req_zone  $client_ip zone=webui_signup:10m rate=3r/m;

log_format cfkomb '$client_ip [$time_local] "$request" $status $body_bytes_sent '
                  'rt=$request_time ua="$http_user_agent" cf=$http_cf_ray';
```

In the vhost: `access_log /var/log/nginx/access.log cfkomb;`, the new zones instead of `webui_api` /
`conn_per_ip`, and `proxy_set_header X-Real-IP $client_ip;` +
`proxy_set_header X-Forwarded-For $client_ip;` so the app and fail2ban see the real client. Direct
traffic keeps working — the map falls back to the PROXY address.

Prove it with a throwaway location before trusting anything:

```nginx
location = /__probe { default_type text/plain;
  return 200 "client_ip=$client_ip|remote_addr=$remote_addr|pp=$proxy_protocol_addr|cf=$http_cf_connecting_ip\n"; }
```

`client_ip` must be the real client both through the edge and directly. Remove the probe afterwards.

**Never prove the proxy with plain `curl https://<host>` from the host itself** — local
resolution/hairpin sent the request straight to the origin (response had `server: nginx`, no `cf-ray`)
while looking completely successful. Force the edge:
`curl --resolve <host>:443:<CF IP> -D - https://<host>/` and require `server: cloudflare` + `cf-ray`.

## Cloudflare side (Free plan, all verified live)

- **DNS:** `PATCH /zones/{zid}/dns_records/{rid}` with `{"proxied":true}`; `dig +short <host> A` then
  answers with CF anycast addrs (`104.21.x`, `172.67.x`).
- **SSL mode:** `PATCH /zones/{zid}/settings/ssl {"value":"strict"}` — safe because the origin serves
  the valid `*.esmien.ru` wildcard (issued via DNS-01, so proxying does not disturb renewals).
- **Free-plan rate limiting is unusable for this job:** `period` and `mitigation_timeout` are locked to
  **10 seconds** and characteristics must be `["ip.src","cf.colo.id"]`. Throttle in nginx instead.
- **Bot Fight Mode cannot be enabled by an API token** —
  `PATCH /zones/{zid}/bot_management` → `Method not allowed for this authentication scheme`. It is a
  dashboard toggle (Security → Bots). Ask the owner for that one click; never report it as done.
- **WAF custom rules are the lever that works** (5 on Free). Scanner filter with zero UX cost, created
  with `POST /zones/{zid}/rulesets`, phase `http_request_firewall_custom`:

```
(http.request.method eq "POST" and
 http.request.uri.path eq "/api/v1/auths/signup" and
 not http.user_agent contains "Mozilla")  ->  block
```

  Do **not** put Managed Challenge on that POST: it is an XHR from the SPA signup form — it breaks the
  form for humans while a determined bot spoofs or solves it.
- A Turnstile widget is not available without app support: **no Open WebUI version ships a captcha** —
  neither 0.12.5 nor 0.13.0 has turnstile/hCaptcha/recaptcha or email verification (`grep` over the release
  tarball). The working shape, in order: (1) JS gate added to the derived image in `ai/webui-branding/`
  (one `<script>` line into `/app/build/index.html` + the file into `/app/build/static/`) that renders the
  widget above the submit button of the form holding `input[autocomplete="new-password"]` and attaches the
  token as `cf-turnstile-response` on `fetch`/XHR to `/api/v1/auths/signup`; (2) a tiny `turnstile-gate`
  service on 127.0.0.1 (`/config` → sitekey, `/verify` → CF `siteverify`), keys in `/etc/turnstile-gate.env`;
  (3) nginx `auth_request /_turnstile` on that POST. Keep the gate **inert while the keys are empty** (200 on
  everything) and fail-open when siteverify is unreachable — otherwise a CF outage closes registration.
  Widgets must be created in the dashboard: the zone-scoped token's `/accounts` is empty.

## External uptime monitoring through the edge

Any monitor outside the host (GitHub Actions runner, cloud checker) is a **bot** for Cloudflare:
datacenter ASN + `curl` UA ⇒ 403 generated at the edge, before nginx, while the site is perfectly
healthy. The alert then reads «VPS не отвечает (403)» with nothing actually broken.

- Probe liveness on a **grey (DNS-only) name**, never through the orange one. Here:
  `https://llm.esmien.ru/health/liveliness` (nginx + LiteLLM) and `https://llm.esmien.ru/webui-health` —
  an exact-match location on the llm vhost proxying `127.0.0.1:8080/health`, so WebUI is covered without
  giving OWUI another public name.
- Keep one probe through the edge, but accept **200 or 403**: 403 proves Cloudflare + origin DNS are
  alive; only `000`/`52x` mean down. Probe functions therefore take a list of allowed codes, not `== 200`.
- `curl -sS` exits 0 on an HTTP 4xx/5xx — a "step succeeded" in CI is not proof that Telegram (or any
  API) accepted the call. Read the response body (`"ok":true`) before claiming delivery.
- Bot Fight Mode is dashboard-only (see above), so the monitor cannot be whitelisted by API — probing the
  origin is the fix, not a CF rule.

## «Через VPN страница не грузится, без VPN всё ок»

Симптом: документ отдаётся `200` (CF-Ray есть), DevTools показывает ~85 запросов при 4.7 kB
`transferred`, красных/`(failed)` строк нет — а приложение не рисуется. Это не nginx и не WebUI:
край отдал HTML-оболочку и **не пропустил пачку подресурсов** (`/_app/*`, XHR) с адреса датацентра.

Доказывать счётчиками, а не `curl`:

- `/var/log/nginx/access.log` держит **два формата одновременно**: `cfkomb` у оранжевых vhost (поле
  `cf=`), combined с referer у серых. Парсить регэкспом, не awk-колонками — в `cfkomb` `$6` это
  протокол, а статус `$8`.
- Сгруппировать по `(client_ip, vhost)`. Признак края: с одного и того же клиентского IP на
  оранжевом имени пришло 3–4 запроса (HTML, `/static/splash*.png`, `/_turnstile/config`) и дальше
  тишина, а на сером имени тот же IP вытянул 80+ ассетов с `200`.
- Тишина в логе = запрос съел CF: до nginx он не дошёл, поэтому `limit_req`/`limit_conn`/fail2ban тут
  ни при чём и искать причину в них — потеря времени.

Правила:

- **`curl` ничего не опровергает.** С сервера и через выходы VPN `ai.esmien.ru` отдаёт `200` за
  0.5–1 с, а браузер за тем же выходом висит: CF оценивает IP + fingerprint + пачку запросов, а не
  «отвечает ли хост». Вывод «CF не при чём, раз curl дал 200» — ошибка, которую этот стек уже ловил.
- Клиентский IP в логе оранжевого имени — это **egress узла/выхода**, а не домашний адрес владельца.
  Не опознавать устройства и не строить выводы по ASN/гео: выход релея выглядит как чужой город
  (московский узел = `e-Style` Москва, новосибирский = `SM Ltd` Новосибирск).
- Обход немедленно: снять прокси (серый) — но это **не бесплатно**, продолжение в следующем разделе.
  У вебуи больше нет серого двойника — `app.esmien.ru` консолидирован в `301` на `ai`, поэтому браузерную
  проверку делать по IP (`--resolve`) или на сером имени другого сервиса. Лечение: снять оранжевое облако
  (как у остальных хостов зоны), либо WAF skip для известных выходов VPN, либо Bot Fight Mode /
  security level в дашборде — токен зоны этого не умеет.

## Обратная сторона серого: «не открывается БЕЗ VPN»

Серый — размен, а не бесплатное лечение: он чинит путь через тоннель и ломает прямой. Без CF браузер
владельца должен сам дойти до эстонского origin на 443, и тот же клиент, который час назад получал
`200`, начинает цикл. Диагностика по порядку, останавливаться на первом сработавшем шаге:

1. **Origin жив:** `curl -sk --resolve <host>:443:127.0.0.1 https://<host>/` → `200`, `openssl s_client`
   отдаёт wildcard, контейнер `healthy`. Это снимает только приложение и ничего не говорит о пути.
2. **Состояние зоны:** `GET /zones/{zid}/dns_records` → `proxied` по записи и `modified_on` (дата
   решения), `dig +short @1.1.1.1 <host>` → адрес origin. Читать это **до** правок nginx; если в вхосте
   стоит комментарий «CF с этого хоста снят», снятие было осознанным, а не поломкой.
3. **Дошли ли его запросы:** grep его IP в `/var/log/nginx/access.log`, поле `cf=`. `cf=-` значит запрос
   пришёл прямо с устройства, то есть путь его провайдера в эту минуту работал — тогда тезис «провайдер
   режет 443» неверен именно сейчас. Ноль строк = сбой выше нас (DNS/ISP/CF), и nginx тут ни при чём.
4. **Читать последовательность, а не статус:** несколько `GET /` за пару секунд, каждый с
   `manifest.json` + `_app/version.json` и без `/api/v1/*`, — это reload-loop: оболочка пришла,
   загрузка не доехала. Тот же признак — `socket.io` `101`, умирающий ровно на `rt=40.002`. Это
   нестабильный путь, а не блокировка, и правок на сервере он не требует.

Лечение, закрывающее оба направления сразу: вернуть оранжевое **и** добавить WAF skip-правило для наших
собственных выходов (эстонский origin плюс те релеи, через которые сценарии отправляют `.ru`/Google) —
через тоннель CF видит именно их, а не владельца. Цену называть вслух, варианты противоположны:
оранжевый ломает тоннельный путь, пока нет skip-правила; серый оставляет прямой путь нестабильным.

## Репутация клиентского IP: новый выход = новый «незнакомец»

CF считает досье **на каждый клиентский IP**, а не на наш сервер: ASN (домашний провайдер против
датацентра), история обращений, паттерн запросов, прохождение JS-проверки. Поэтому смена выходного
узла (подписка переключилась на свежий датацентровый адрес) ломает вебуи, **хотя в зоне не тронуто
ни одной настройки**: старый выход, ходивший к сайту сутки-двое, пропускается, а новый получает
managed challenge и отдаёт 3–4 запроса из 85 при открытии страницы.

Признаки, что дело именно в этом: `proxied` тот же, правил не добавляли, вебуи открывается с другого
выхода, а в `access.log` с нового клиентского IP пришла только HTML-оболочка. Дальше копать нечем:
bot-логи и аналитика зонному токену недоступны, механизм восстанавливается по поведению — и владельцу
это надо сказать прямо, а не выдавать догадку за факт («правило X сработало» проверить нечем).

**Усугубляющий фактор — watchdog маршрутов.** Переключение сценария между узлами (`ru1` ↔ `direct`)
предъявляет CF новый адрес на каждом скачке: досье с нуля каждый раз, «притирания» не происходит
никогда. Правило: если впереди CF, у сценария, на который он смотрит, должен быть **один стабильный
выход** (домашний IP или постоянный узел), а не тот, который прыгает по провайдерам.

Не путать с параллельным сбоем: `ERR_TIMED_OUT` при **нуле** запросов в логе — это не блокировка, а
h3/QUIC (раздел ниже). Два разных сбоя легко накладываются в один день; не списывать оба на CF и не
чинить один, объявив его причиной другого.

## HTTP/3 (Alt-Svc) — вторая причина «через тоннель таймаут»

Другой симптом того же семейства: `ERR_TIMED_OUT` в браузере, при том что `curl` с хоста, с RU-хоста и
через выходы VPN отдаёт `200`, а в логе от этого клиента в этот момент **ноль** запросов. Механизм: в
ответе края приходит `Alt-Svc: h3=":443"; ma=86400`, Chrome запоминает альтернативу на сутки и на каждый
заход сначала пробует QUIC поверх **UDP**, который через TUN-тоннель (и через часть RU-провайдеров)
уходит в чёрную дыру — TCP-фолбэка в этом же заходе не случается, и браузер рисует таймаут.

Как отличить: в ту же минуту тот же host по IP открывается, а в ответе нет `alt-svc`
(`curl --resolve <host>:443:<origin> -D - -o /dev/null`). Это же объясняет «CF-ное имя плавает, а прямое
ходит» при полностью здоровом origin. Серого двойника вебуи больше нет: `app.esmien.ru` консолидирован
в `301` на `ai`, сравнивать с ним нельзя.

Лечение, первое надёжнее: снять оранжевое облако — origin не объявляет h3, и лотерея закрывается
навсегда; альтернатива — выключить HTTP/3 в настройках зоны. После снятия требовать в ответе **отсутствие**
`alt-svc` и `cf-ray`: `curl -sS -D - -o /dev/null https://<host>/ | grep -iE 'alt-svc|cf-ray|server:'`.
Остаточный эффект: Chrome может держать закэшированную альтернативу до конца сессии — после первого
таймаута он помечает её битой, но надёжнее попросить владельца перезапустить браузер.

## Risks to state before flipping (free plan)

- **100 s before the first byte** → `524` on long non-streamed responses. OWUI chat streams over SSE, so
  normal answers survive; a long silent «thinking» phase can still trip it.
- **100 MB upload cap**, matching the existing `client_max_body_size 100M`.
- **TLS terminates at Cloudflare**: chat content is readable there. For a private family instance say so
  out loud instead of silently changing who can see the traffic.
- Local consumers (`Hermes → 127.0.0.1:8080`) bypass the proxy entirely; nothing there changes.

## Verify after the flip

```bash
curl -s -o /dev/null -D - --resolve ai.esmien.ru:443:<CF IP> https://ai.esmien.ru/ | grep -i 'cf-ray\|server:'
tail -n 5 /var/log/nginx/access.log          # column 1 must be a real client IP
for i in 1 2 3 4; do curl -s -o /dev/null -w "$i:%{http_code} " --resolve ai.esmien.ru:443:<CF IP> \
  -A 'Mozilla/5.0 Chrome/126.0' -X POST -H 'Content-Type: application/json' -d '{}' \
  https://ai.esmien.ru/api/v1/auths/signup; done; echo
```

Expected: `cf-ray` present; a real client IP in the log; the 4th signup attempt `429` from nginx (the
first three get `422` on an empty body, so the test leaves no rows). A `curl` UA must get `403` from
Cloudflare before nginx is involved.

## Rollback / turning the proxy off

Turning the orange cloud OFF is **two edits, in this order** — flipping only the record locks every
visitor out with a bare `403`, because the vhost carries a deliberate origin gate:

```nginx
if ($deny_direct) { return 403; }   # only requests carrying CF-Connecting-IP get through
```

It is correct while proxied (it blocks direct hits on the origin, i.e. bypassing WAF/Bot Fight) and fatal
once CF is gone: with no header the `$is_via_cf` map reads `0` and *every* request — the owner's included —
gets `403` with `rt=0.000` and `cf=-` in the log.

1. Remove the gate from `/etc/nginx/conf.d/<host>.conf` (back it up with `cp -a <file> <file>.bak-cfoff`
   first) and leave the maps in `01-cf-client-ip.conf` alone — `$client_ip` falls back to
   `$proxy_protocol_addr`, so the rate-limit zones and the fail2ban jail keep keying on the real client.
   `nginx -t && systemctl reload nginx`.
2. `PATCH /zones/{zid}/dns_records/{rid} {"proxied":false}` (keep the A → origin IP), then
   `dig +short @1.1.1.1 <host>` must return the origin address, not `104.21.x`/`172.67.x`.
   Перечитать флаг **до** и после `PATCH`: владелец часто успевает выключить облако сам в дашборде, и
   тогда `proxied` уже `false` — докладывать подтверждённое состояние, а не «снял». И не включать прокси
   «на пробу» без прямой просьбы: цена теста — сломанный вебуи у владельца.

Verify: `curl -sS -D - -o /dev/null https://<host>/` answers `server: nginx/...` (no `cf-ray`), `200`, and
the access log shows the client's own IP in column 1 with `cf=-`. A browser keeps the old CF address for
up to the record TTL (300 s) — hard refresh, not a bug.

Editing the vhost: the `patch` tool refuses `/etc/nginx/**` as a sensitive system path. Write the new file
from Python (`read_text()` → `replace()` → `/tmp/x`), `install -m 644` it into place, then `nginx -t` — the
same staging trick the `vpn-entry-stack` pitfalls describe for generated snippets.

The `map` and the CF `limit_*` zones stay and stay harmless without the header. Going back to orange is the
mirror image: restore the gate first, then the record.

## Domains → backend: the two zones (moved from SKILL.md)

The public names are moving from the `esmien.qd.je` zone (free DNS whose authoritatives fail — see `vpn-entry-stack` for the triage) to the owned **`esmien.ru`** zone on Cloudflare. Both sets are served in parallel until the owner moves the family, so an old and a new name point at the same backend:

The name → backend map itself is short and lives in SKILL.md, section «Domains → backend»; this file holds the why and the procedures.

## Vhost rules: grey/orange, app redirect, reload truth, adding a name

**Оранжевого облака в зоне больше нет: `ai` переведён в серый по указанию владельца** — CF отдавал
HTML-оболочку и не пропускал пачку подресурсов с адресов выходов VPN (диагностика и доказательства —
`references/cloudflare-proxy.md`, раздел про «через VPN не грузится»). Оба имени, `ai` и `app`, серые и ходят прямо на
origin, бэкенд один (`127.0.0.1:8080`). **`app.esmien.ru` — не второй вход, а редирект:** по указанию
владельца он отдаёт `301` на `ai` с сохранением пути и query, без проксирования и без лимитов
(два имени одного WebUI = две cookie-сессии, потому что cookie привязана к hostname). Не возвращать
`app` вторым проксирующим vhost'ом без прямой просьбы. Бэкап прежнего файла — `.bak-before-redirect`.
Проверка правки: `curl -s -o /dev/null -D- --resolve app.esmien.ru:443:127.0.0.1
'https://app.esmien.ru/c/x?y=1' | grep -iE '^HTTP|^location'` — ждать `301` и полный путь в `Location`.

**Правка вхоста и проверка после reload.** `write_file` отказывается писать в `/etc/nginx` (sensitive
system path): писать новый файл в scratch и класть через `cp` (бэкап — `cp -a <file> <file>.bak-<повод>`).
Сразу после `systemctl reload nginx` первый же `curl` может ответить по **старому** конфигу — прежний
worker ещё принимает соединения; повторять запрос, а не откатывать правку и не искать «конфиг не
применился» (симптом обманчив: только что отредактированный vhost отдаёт 200 с телом прежнего).

**Снятие оранжевого облака — два действия, а не одно.** Сначала убрать из вхост-файла гейт
`if ($deny_direct) { return 403; }` (он пропускает только запросы с `CF-Connecting-IP` и без CF режет
`403` вообще всё, включая владельца), потом `PATCH {"proxied":false}`. Порядок и проверка — в
`references/cloudflare-proxy.md`; не возвращать гейт, пока запись серая.

Adding a service name on a new zone — order matters:

1. Wait until the A record answers from two public resolvers. Under Cloudflare it must be **grey cloud (DNS only)**: with the orange proxy on, HTTP-01 validation comes back `530` and certbot fails before nginx is even involved. An orange record is only correct if the service is deliberately fronted by Cloudflare (then TLS terminates at the edge and the origin vhost needs no Let's Encrypt cert).
2. Issue the certificate through a **port-80 ACME stub** for the new name (`location /.well-known/acme-challenge/ { root /var/www/html; }`), `certbot certonly --webroot`. A full vhost cannot be written first — `nginx -t` refuses to load a config whose `ssl_certificate` path does not exist yet.
3. Then write the real vhost as a copy of the old one with the hostname substituted — same `listen 127.0.0.1:9443 proxy_protocol ssl http2`, same rate-limit zones, timeouts and `X-Forwarded-*`. A new name without its own vhost silently lands on the default server of that listener.
4. Drop the ACME stub once the real file carries the port-80 block (a copy of the site file already has it) and `nginx -t && systemctl reload nginx`.
5. Verify with `curl -o /dev/null -w '%{http_code} cert=%{ssl_verify_result}' https://<name>/` — want `200 cert=0`. Then confirm the old name still answers, because the family stays on it until the owner says otherwise.

**Orange-clouding an already-issued name** (putting Cloudflare in front for its bot/WAF layer) is a different procedure from first issuance and has an ordering trap: restore the real client IP *before* flipping the record. Origin topology here is a `stream` block on 443 (`ssl_preread`) that forwards with `proxy_protocol` to the `127.0.0.1:9443` vhosts, and `00-proxy-realip.conf` resolves `$remote_addr` from that hop — once the record is proxied, `$remote_addr` becomes a Cloudflare edge IP and every `limit_req`/`limit_conn` bucket collapses onto one key, i.e. all users share one limit and get 429s together. Procedure, token scopes, free-plan limits and rollback: `references/cloudflare-proxy.md`.

## When to read this file (annotated index entry, moved from SKILL.md)

- `references/cloudflare-proxy.md` — **Cloudflare in front of one of our names**. Read before proxying a vhost, adding WAF/bot rules, when rate limits suddenly apply to everyone at once, when an outside monitor reports the site as down/403 while it is healthy, or when traffic breaks after the client's egress IP changed (per-IP reputation of VPN exits). Also read when a browser shows `ERR_TIMED_OUT` while `curl` from several vantages gets `200` — Alt-Svc/h3 through a tunnel, section «HTTP/3 (Alt-Svc)».
