# Decoy page and VPN-only access

## Dashboard access limited to the tunnel

- Put `allow 85.92.158.238; allow 127.0.0.1; deny all;` in the stats vhost (`:80` and the TLS block) and add `error_page 403 = @drop; location @drop { return 444; }` — an outsider then gets a dropped connection instead of a 403 that confirms the host exists.
- The VPN edge is the only address a tunnel client appears from, so the allowlist doubles as «only through our VPN». Verify both directions: direct `curl` → `000`/dropped, through a local xray client → `401`.
- **Add a routing rule `domain:stats.esmien.{com,ru} -> direct`** in `config.json`. Without it the request can leave through the NL/Gemini exit and arrive from a foreign IP, which the allowlist drops — the panel then «не открывается из туннеля» for no obvious reason.
- Trade-off to state plainly: when the VPN is down the dashboard is unreachable, including for the owner.

## Decoy instead of the nginx Welcome page

- A stock `Welcome`/stub page is the loudest «здесь ничего нет» signal. Proxy a real product login instead; the owner picked **LiteLLM `/ui/`** (title «LiteLLM Dashboard», no personal brand).
- **Проксировать в живую панель нельзя — только в изолированную копию статики.** Заглушка обязана быть настоящей, а рабочий LiteLLM не должен принимать снаружи ни одного запроса: скопированная сборка (`/var/www/llm-decoy/ui`, из контейнера `litellm`) отдаётся nginx-сервером `127.0.0.1:8092` (`conf.d/llm-decoy.conf`), и туда же уходят `/ui/`, `/litellm-asset-prefix/`, `/login`, `/sso/`, `favicon.ico` и `location /` у vision-fallback. Проверь все действующие вхосты и пути на отсутствие прокси в `:4000`: это изолирует заглушку от рабочего бэкенда, но не доказывает абсолютную безопасность всего сервиса. Пересборка после смены версии образа — `scripts/install-llm-decoy.sh` (копирует статику + ставит conf + reload).
- Вход отбивается **тем же ответом, что даёт настоящая панель**: `401` + `{"error":{"message":"Invalid credentials used to access UI. Check the password set for your user","type":"auth_error","param":"invalid_credentials","code":"401"}}` (162 байта; тело измерено на живом бэкенде, не придумано). В nginx это `return 401 '<json>'` в `location` с `default_type application/json` — `default_type` внутри `if {}` запрещён, поэтому не-GET/HEAD уходят через `error_page 418 = @decoy401;` в named-location.
- Locations needed, in this order: `= /` → `return 302 /ui/;`, `^~ /ui/`, `^~ /litellm-asset-prefix/` (all JS/CSS chunks live there — without it the page renders blank), `= /favicon.ico`, then the real `/u/`, `/sub/` and WS paths, `location /` last.
- Add `absolute_redirect off;` in the server block: nginx otherwise emits `Location: https://host:18443/ui/` and leaks the internal listener port (docs: `server_port` is the listening port, and 18443 is the loopback vhost behind the stream front).
- **Не закрывать `/ui/` через `limit_except GET HEAD { deny all; }`.** Это даёт `403` от nginx — не тот ответ, который видит брутфорсер у настоящей панели (там `401` с JSON). Пусть POST доходит до заглушки, она отвечает по-настоящему.
- **Patch the generator, not the file:** `vpn-443-in.conf` is written by `apply_brand.py` on every apply. Both the main vhost and the parallel one share the template, and `parallel_vhost` is derived from `main_vhost`, so one edit covers `.ru` and `.com`.
- **«Конфиг не применился» — сначала найди, какой server block отвечает.** Правка лежала в `vpn-443-in.conf`, а `/` отдавал старый `Welcome` из соседнего vhost'а-фолбэка на `127.0.0.1:8091`. Проверка за один шаг: `nginx -T | grep -n 'server_name <host>'` и лог именно того вhost'а (`vpn-443.log`); отсутствие запроса в нём означает, что ответил другой блок, а не что reload не сработал.
- The vision fallback (`127.0.0.1:8091`, what a browser sees when TLS on 443 is terminated by Xray) must show the same page; its `location /` proxies to the decoy `127.0.0.1:8092` (не в `:4000`), so unknown paths and hysteria auth probes get a plain `401` page-like answer instead of reaching the panel.
- **Рабочая панель закрыта как stats:** в `conf.d/llm.esmien.ru.conf` — `allow 85.92.158.238; allow 127.0.0.1; deny all;` + `error_page 403 = @drop; location @drop { return 444; }`. Единственное исключение — `= /webui-health` со своим `allow all;`: `ngx_http_access_module` наследует правила только если в location нет собственных, поэтому там публичный uptime-монитор продолжает работать. Проверь запрет с независимого внешнего источника и доступ через настоящий VPN-клиент; `curl --interface 85.92.158.238 --resolve …` проверяет только локальную обработку исходного адреса, а не внешний путь или сквозной туннель.

## Not doing: ALPN `h2` on 443

- A decoy that answers only `http/1.1` is slightly unlike a real site, but enabling `http2` on the 443 vhost is the wrong trade: a client that offers `h2` first negotiates it, and nginx cannot proxy a WebSocket upgrade over HTTP/2, so that user's tunnel dies. Our subscriptions pin `alpn=http/1.1`; saved/imported legacy configs do not.
- If it is ever revisited, change it together with the generated `alpn` in every subscription format and accept that anyone on an old imported profile breaks — say that price out loud instead of shipping h2 quietly.

## Hysteria masquerade

- Same surface, different protocol: without `masquerade` a stranger who speaks QUIC to the UDP port gets an empty/broken response, and pointing it at a socks proxy shows them a proxy. Point it at the nginx fallback: `masquerade: {type: proxy, proxy: {url: http://127.0.0.1:8091, rewriteHost: true}}`.
- **You cannot probe the masquerade with a plain HTTP/3 client** (aioquic, `curl --http3`): with `obfs: salamander` every non-salamander packet is dropped before TLS, so the handshake simply hangs. Test with the real hysteria client and a **wrong password**: the auth failure comes back as `authentication error, HTTP status code: <code>` and that code is the masquerade answer (404/405 = a web server that rejects the path/method).
