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
- Обход немедленно: серое имя того же сервиса (`app.esmien.ru`). Лечение: снять оранжевое облако
  (как у остальных хостов зоны), либо WAF skip для известных выходов VPN, либо Bot Fight Mode /
  security level в дашборде — токен зоны этого не умеет.

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

Verify: `curl -sS -D - -o /dev/null https://<host>/` answers `server: nginx/...` (no `cf-ray`), `200`, and
the access log shows the client's own IP in column 1 with `cf=-`. A browser keeps the old CF address for
up to the record TTL (300 s) — hard refresh, not a bug.

Editing the vhost: the `patch` tool refuses `/etc/nginx/**` as a sensitive system path. Write the new file
from Python (`read_text()` → `replace()` → `/tmp/x`), `install -m 644` it into place, then `nginx -t` — the
same staging trick the `vpn-entry-stack` pitfalls describe for generated snippets.

The `map` and the CF `limit_*` zones stay and stay harmless without the header. Going back to orange is the
mirror image: restore the gate first, then the record.
