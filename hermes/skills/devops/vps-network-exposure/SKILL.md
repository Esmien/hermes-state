---
name: vps-network-exposure
description: "Use when a port may be open to the internet."
version: 1.3.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [devops, firewall, iptables, ufw, docker, postgres, security, exposure]
---

# Network exposure audit & closure (this VPS)

## When to Use

The owner asks «у нас <порт> наружу?», a new service/container gets a published
port, a security review is requested, or something must be firewalled. Covers the
host-level question: which sockets listen on a routable address, what filters
them, and how to close one durably. Stack-specific service facts live in the
`ai-stack` skill.

## Answer shape (owner preference)

**First line = verdict, then evidence, then the fix as a gated plan.**
«Да, открыт» / «Нет, только localhost» before any command output. Then a short
bullet list of the facts that decided it. Then, only if action is needed, the
exact commands under «⚠️ Требуется подтверждение». Do not open with the
investigation.

Keep two facts separate and say both:

1. **Network reachability** — is the TCP port reachable from the internet?
2. **Authentication gate** — can such a client actually get in (`pg_hba.conf`,
   app auth, allowlist)?

A firewall-closed port and an app-rejected connection are different risks
(`ECONNREFUSED` vs a 41k-line brute-force log) and must not be collapsed into one
«закрыто».

## Procedure (steps 1–5 are read-only)

1. **Socket inventory.** `ss -tlnp | tail -n +2` — `0.0.0.0:*` / `[::]:*` =
   routable bind, `127.0.0.1:*` = loopback only. Map each PID to its owner:
   `ps -o pid,ppid,user,cmd -p <pid>`. Systemd services (host Postgres) exist
   ONLY here — `docker ps` cannot see them.
2. **Container view.** `docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}'`.
   `5432/tcp` with no `->` is an internal EXPOSE only; `127.0.0.1:8001->8000/tcp`
   is loopback-published; `0.0.0.0:PORT->…` is the real exposure. Cross-check with
   `ss` that the listener is `docker-proxy` — if nothing listens on the host port,
   traffic goes through DNAT and host `INPUT` rules never see it.
   `ss` also catches non-Docker listeners, so read the whole list: snapped
   services (`cupsd` on `0.0.0.0:631` was found this way) do not appear in
   `systemctl is-active cups` — use `systemctl is-active snap.<name>.<svc>` and
   `ps -o cmd -C <bin>`.
3. **Filter state.** `iptables -S INPUT | head -20` (policy line first),
   `ufw status`, `grep -hE '^ENABLED' /etc/ufw/ufw.conf`. Never infer the
   firewall from `systemctl is-active ufw`.
4. **App-level gate.** Read the service's own ACL, e.g. Postgres:
   `grep -hE '^\s*listen_addresses' /etc/postgresql/*/main/postgresql.conf` and
   `grep -hvE '^\s*#|^\s*$' /etc/postgresql/*/main/pg_hba.conf`.
5. **Prove reachability with evidence, not with a guess.** Two honest signals:
   - **live external probe** — `https://check-host.net/check-tcp?host=IP:PORT&max_nodes=3`
     with `Accept: application/json`, then `/check-result/<REQUEST_ID>` after a
     short delay. Success proves TCP reachability from that node only; `null` /
     pending / timeout without a control is inconclusive.
   - **service log** — the authoritative «the internet really reaches this port»
     witness. For Postgres:
     `grep -c 'no pg_hba.conf entry' /var/log/postgresql/postgresql-*-main.log`
     (historically 41k lines, each with a real foreign source IP; expect 0 now
     that `fw-guard-postgres` drops the traffic), then bucket the sources:
     `grep -oE 'no pg_hba.conf entry for host "[0-9.]+"' <log> | awk '{print $NF}' | sort | uniq -c | sort -rn | head`.
6. **Report** with the verdict-first shape. If nothing needs closing, say
   «ничего не открыто» and stop — no plan.

`scripts/audit-exposure.sh` runs steps 1–4 plus the listeners/firewall/guard
state read-only and prints the whole picture in one go; run it first, then drill
into whatever it flags. It does not run the external probe of step 5.

## Closing a port (durable)

Pattern that leaves intra-stack traffic intact (containers reach host Postgres
from `172.16.0.0/12`):

```bash
# ACCEPT exceptions first, DROP everything else — order matters
/usr/local/bin/fw-guard-postgres.sh
```

`/usr/local/bin/fw-guard-postgres.sh` (idempotent: deletes its own rules, then
rebuilds them by inserting at position 1 in reverse order — ACCEPT 127.0.0.1,
ACCEPT 172.16.0.0/12, DROP 5432) is driven by `fw-guard-postgres.service`
(oneshot, `RemainAfterExit=yes`, `After=ufw.service network-online.target`,
`WantedBy=multi-user.target`). Recreate that pair for any other port; it is the
persistence mechanism on this host. Live state (2026-11-01): `iptables -S INPUT`
= ACCEPT 127.0.0.1/32 → ACCEPT 172.16.0.0/12 → DROP, unit `active`/`enabled`.

Verify after applying: `iptables -S INPUT | head -5` shows the three rules in
order, `systemctl is-active fw-guard-postgres` = `active`, and
`ss -tnp state established '( sport = :5432 )'` still shows the containers'
`172.18.x` peers — no rule change without proof that the stack kept working.
Then verify from **outside** (netns pattern in the reference); `iptables -S`
alone shows intent, not effect. Confirm the counter sits on the expected rule:
if the DROP counter does not move while a foreign probe times out, the packet is
stopped somewhere else and the reasoning is wrong.

## SSH on this host

`PasswordAuthentication` is **off**: `sshd -T | grep -i
passwordauthentication` → `no`; `/etc/ssh/sshd_config.d/50-cloud-init.conf`
says `no`, backed by `/etc/cloud/cloud.cfg.d/99-ssh-no-password.cfg`
(`ssh_pwauth: false`) so cloud-init cannot flip it back on reboot. Root logs in
by key only; `ai_service` has **no** `authorized_keys` and cannot SSH in at all —
use `su`/`sudo` from root.

**sshd is first-match-wins, not last.** `Include /etc/ssh/sshd_config.d/*.conf`
is line 12 and files apply in lexical order: `50-cloud-init.conf` must be the
file that sets `PasswordAuthentication`, because `50-*` is read before
`60-cloudimg-settings.conf`. A new `99-*.conf` would NOT fix a wrong earlier
value. Verify with `sshd -T`, never from the file alone. Reload, don't restart:
`sshd -t && systemctl reload ssh`. Loopback check:
`ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no root@127.0.0.1 true`
must answer `Permission denied (publickey)`.

Full detail (rule ordering, UFW, DNAT, netns drill, gated changes) —
[references/firewall-and-ssh.md](references/firewall-and-ssh.md).

## Pitfalls that produce wrong verdicts

- **`iptables` here is nf_tables and rejects more than one `-s`:**
  `! -s 127.0.0.1 ! -s 172.16.0.0/12` → `multiple -s flags not allowed`, exit 2.
  Express it as ordered ACCEPT rules plus an unconditional DROP.
- **Insert at position 1 in reverse** (`-I INPUT 1 … DROP`, then ACCEPT 172.16/12,
  then ACCEPT 127.0.0.1). `-A` appends below other ACCEPT rules and silently
  never matches.
- **`systemctl is-active ufw` = `active` while the firewall is OFF** —
  `ENABLED=no` leaves the unit running with rules flushed (`ufw status` =
  `inactive`, `iptables -S` = bare `-P INPUT ACCEPT`). And do not enable ufw to
  fix one port: `DEFAULT_INPUT_POLICY="DROP"` with empty `user.rules` cuts SSH
  and the whole stack at once. Nothing here persists iptables rules by default
  (`netfilter-persistent` absent) — a rule without a oneshot unit dies on reboot.
- **Docker-published ports can bypass `INPUT`.** If `docker-proxy` listens,
  `INPUT` applies; if it is DNAT-ed straight to the container (no host listener),
  filter on `DOCKER-USER` — and the cleaner fix is re-publishing as
  `127.0.0.1:PORT:PORT`. Decide from `ss -tlnp` before claiming «закрыто».
- **A probe from inside a container on the same host is the easiest false
  «открыт»/«закрыто».** Bridge traffic is MASQUERADEd to `172.18.0.1`, inside the
  trusted `172.16.0.0/12` — the probe is accepted by the very rule it should test.
  Symptom: connect succeeds from `docker exec`, service log shows no foreign IPs.
- **The only honest filter test uses a source outside every allowlist**, on the
  real path, with the **packet counter** as witness plus an allowed control port
  (a timeout alone may just mean «сеть сломана»). Block:
  [references/firewall-and-ssh.md](references/firewall-and-ssh.md#netns-drill).
- **Never conclude reachability from a third-party port-checker or a local
  `curl` to your own public IP** (exits via loopback, always succeeds). Shodan
  once reported `9223` while `ss -tlnp` and `iptables -t nat -S` showed nothing.
- **`write_file`/`patch` refuse system paths** (`Refusing to write to sensitive
  system path: /etc/...`): write to `~/.hermes/cache/scratch/`, then `cp`.
- **Closing a port is a state change → gated.** Exact rules, blast radius
  («контейнеры из 172.18 не затронуты») and verification command, then wait for
  «Да».
- **A privileged helper container is exposure of its own kind:**
  `privileged: true` + `pid: host` + `/var/run/docker.sock` + `/:/mnt/host` =
  host-root RCE from inside; name those four facts when proposing removal.

## Cloudflare впереди (orange cloud)

- **Поставить Cloudflare перед хостом** (фильтр ботов, скрыть origin, спам
  регистраций) — `ai-stack` → `references/cloudflare-proxy.md`: порядок «сначала реальный IP
  в nginx, потом переключить запись», почему `realip` в этой схеме
  (`stream` + `proxy_protocol`) не даёт верного адреса и что работает вместо
  него (`map $http_cf_connecting_ip`), лимиты Free-плана, WAF-правило по UA и
  риски (100 с → 524, 100 МБ на загрузку, TLS терминируется у CF).
- **CF скорит клиентский IP, а не наш сервер.** Смена выходного узла VPN (свежий
  датацентровый адрес) сама по себе даёт managed challenge на здоровом origin, а watchdog,
  дёргающий сценарий между узлами, предъявляет CF новый адрес на каждом скачке — репутация
  с нуля каждый раз. Если впереди CF, у сценария должен быть один стабильный выход.

## fail2ban и rate limiting nginx (установлены 2026-10-31)

- **fail2ban** 1.0.2, `active`/`enabled`: SSH-брутфорс был ~2.5k попыток/сутки.
  `/etc/fail2ban/jail.local`: `findtime=1h`, `maxretry=4`, `bantime=1d`,
  `bantime.increment` (factor 2) до 4 недель, `backend=systemd`,
  `ignoreip` = loopback + 10/8 + 172.16/12 + 192.168/16, `[sshd] mode=aggressive`.
  На 24.04 action — `nftables`: баны в `nft list table inet f2b-table`, **не** в
  `iptables -S INPUT`. Детали —
  [references/fail2ban-and-rate-limits.md](references/fail2ban-and-rate-limits.md).
- **nginx** — два набора зон, и путать их нельзя:
  `conf.d/zz-ratelimit.conf` ключует по `$binary_remote_addr` (`llm_api` 10r/s, `webui_api` 8→20r/s,
  `conn_per_ip`), а `conf.d/01-cf-client-ip.conf` — по `$client_ip` (CF-Connecting-IP либо PROXY
  address), потому что без этого за оранжевым облаком все клиенты сливаются в одно ведро. Живой `ai.`
  живёт на втором наборе: `webui_api_cf` 20r/s + `burst=240`, `limit_conn 60`, отдельные
  `webui_signin` 10r/m (burst 3) и `webui_signup` 3r/m (burst 2), плюс `if ($owui_banned_ip) → 403`
  из fail2ban-джейла `owui-auth`. `llm.` — server-level `burst=40 nodelay` + `limit_conn 20`.
  **У `app.esmien.ru` больше нет ни лимитов, ни проксирования** — это `301` на `ai` (одно приложение
  = один публичный hostname), поэтому искать там зоны и править их бессмысленно. Статика везде без
  лимита: одна загрузка SPA — 40–60 запросов к `/api/`, иначе второй F5 даёт 429.
  `limit_req_status 429`. В `vps-infra` зеркало есть только у `zz-ratelimit.conf` и
  `01-cf-client-ip.conf` — после переезда остальные вхосты надо переприменять.
- **«Нас атакуют боты» решается счётом за сутки, а не ощущением.** Сначала объём и состав:
  `grep -oE '"[A-Z]+ [^"]*" [0-9]{3}' /var/log/nginx/access.log | grep -oE '[0-9]{3}$' | sort | uniq -c | sort -rn`
  (регэкспом, а не по номеру колонки — в одном файле живут `cfkomb` и combined), затем топ путей у `404`
  и топ адресов у них. Картина «605 из 4682 за сутки, все на `/.env`, `/wp-config.php`,
  `/phpinfo.php`, `/storage/logs/laravel.log`, половина с одного IP» — это фоновый шум интернета,
  а не атака: 3 запроса в минуту не стоят ни WAF, ни оранжевого облака (оно же приносит
  репутационный challenge легитимному трафику — `ai-stack` → `references/cloudflare-proxy.md`,
  «Репутация клиентского IP»). Вердикт так и подавать: объём → что шумит → почему закрытый логин
  и гейт на входе уже держат риск. Дешёвое лечение без прослоек — `return 403` на мусорные пути
  (`/.env`, `/wp-*`, `/phpinfo.php`, `/*.log`, `/secrets.json`): снимает шум и чистит логи, где
  иначе настоящий вхосток прячется за сканерами.
- **Burst считай по стоимости одной загрузки SPA, а не по «запросам в секунду».**
  Один refresh Open WebUI — это 40–60 запросов к `/api/` (модели, папки,
  аватарки, скиллы, сокет). `burst=30` выбирается одним открытием страницы,
  второй F5 подряд уходит в 429, и владелец видит «сайт перестал открываться»,
  хотя HTML отдаётся 200 и канал в порядке. Признак в логе: серия `429` на
  `/api/models`, `/api/v1/folders/shared`,
  `/api/v1/models/model/profile/image`, при нулевых `limiting requests` в
  `error.log` (уровень warn пишется не туда, где его ищут). Лечится `burst=120`,
  а не отключением лимита.

## Сканеры LLM-шлюза (`/v1/models` без ключа)

**Не читай это как поломку LiteLLM.** В UI гейтвея появляются тысячи красных `Failure`
с моделями вида `gpt-4o`, `claude-sonnet-*`, `mistral-small` и текстом про credential —
выглядит как «сломались наши ключи», а на деле это внешние боты ищут открытый LLM-прокси.
Признак: у запросов **нет ни `user`, ни alias ключа**, а статусы — только `401`/`429`.

Диагностика (read-only, минута):

```bash
awk '{print $1}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -5
# по подозрительному IP — что просили и чем отвечали
grep -h "^<IP> " /var/log/nginx/access.log | awk '{print $7}' | sort | uniq -c | sort -rn | head
grep -h "^<IP> " /var/log/nginx/access.log | awk '{print $9}' | sort | uniq -c | sort -rn
# мусор в базе от неаутентифицированных попыток
sudo -u postgres /usr/lib/postgresql/17/bin/psql -X -tA -d litellm_db \
  -c "SELECT date_trunc('hour',\"startTime\"), count(*) FROM \"LiteLLM_SpendLogs\" WHERE model='' GROUP BY 1 ORDER BY 1 DESC LIMIT 6"
```

Что считать вердиктом: `200` есть только у `/health/liveliness` (он публичный по замыслу), всё
остальное — `401`/`429`. Тогда это не утечка и не сломанная авторизация, а мусорный трафик.
Типовая картина: десятки тысяч `GET /v1/models`, единичные пробы путей провайдеров
(`/cohere`, `/vllm`, `/vertex_ai`, `/azure_ai`, `/gemini`), `/key/info`.

Ущерб — не доступ, а шум: `LiteLLM_SpendLogs` копит сотни тысяч строк с `model=''`, они
раздувают базу и отчёты по расходам.

Лечение (гейтед, двумя частями):

1. fail2ban-джейл на access-лог `llm.`-хоста: `backend = polling`, фильтр
   `^<HOST> - - .+ "[^"]+" (401|403|429)`, `maxretry=30`, `findtime=5m`,
   `bantime=6h` + инкремент. Рецепт — `references/fail2ban-and-rate-limits.md`.
2. Чистка `DELETE FROM "LiteLLM_SpendLogs" WHERE model=''` и та же чистка в
   `litellm-spend-retention`, иначе мусор возвращается каждую неделю.

Не предлагать в качестве лечения «перевыпустить ключ OpenCode»: текст ошибки называет
credential, но запрос пришёл вообще без ключа — это ложный след, который уводит в
перевыпуск живых кредов.

## VPN и общий 443

Маршрутизатор — отдельный контейнер `vpn-router` (Xray, `--network host`, конфиг
`/root/vpn-router/config.json`, правка через `/usr/local/bin/vpn-cfg`:
`status`/`edit`/`apply`/`rollback`, `apply` сам делает health-check и откат).
3x-ui снесён целиком: панель не умеет описывать цепочки «вход → конкретный выход»,
а публичная админка — лишняя дверь. Туннель проверяется настоящим клиентом (HTTPS
через SOCKS), а `stream`/`ssl_preread` на 443 требует PROXY protocol на обеих
сторонах, иначе backend видит loopback.
HTTP 200 не доказывает ни сохранение client IP, ни доступ из сети владельца.
Один лишний хоп в PROXY-цепочке превращает все адреса в логах в `127.0.0.1` —
и fail2ban слепнет (подробно: [references/domain-migration-and-dns.md]).

- **Одно «Да» покрывает весь согласованный план.** Не возвращайся с «продолжать?»
  между шагами: остановка нужна только на деструктивном действии, которого в
  утверждённом списке не было.
- **Ссылки владельцу отдавай прямо в чат.** Он единственный пользователь этой
  инфраструктуры: `tg://proxy`, `https://t.me/proxy?…`, `vless://` со секретом
  на его собственный сервер — не секрет, который надо прятать. Отказ в стиле
  «получи на сервере» раздражает; отправлять владельца запускать
  `link.py`/`python3 …` вместо того, чтобы самому напечатать готовую строку, —
  тот же отказ. Печатай ссылку сам. Не выводятся только `.env`, приватные
  ключи, пароли БД и токены ботов.
- **Fake-TLS (mtg) не переживает DPI — рукопожатие режется в середине**
  (клиент отдаёт один MSS-сегмент ClientHello, ответа нет), поэтому маскировка
  под чужой домен и смена порта не помогают. Рабочий вариант — **VLESS +
  WebSocket + настоящий TLS**, TLS снимает nginx на нестандартном порту.
  Рецепт, проверка туннеля и ловушки (публикация порта из контейнера панели,
  обязательное правило `direct` по умолчанию в xray, недоступный отсюда WARP)
  — [references/vpn-and-https-ingress.md](references/vpn-and-https-ingress.md);
  механика fake-TLS и проверка рукопожатия без телефона — `scripts/faketls-probe.py`.
- **Гео-заглушка Gemini снимается маршрутизацией на сервере, но список доменов должен быть полным.** Раньше вывод был «только полный туннель», потому что правило покрывало один `gemini.google.com` — а вход в аккаунт и статика идут через `www.google.com`, `accounts.google.com`, `gstatic.com`, `googleapis.com`, `googleusercontent.com`. Любой непокрытый хост выходит через наш эстонский IP, Google присваивает ему `ru` (whois адреса, не геолокация машины), и страница отвечает «недоступно в вашей стране». Правило `domain:google.com` + эти домены на французский выход, поставленное выше правил по `inboundTag`, работает у любого клиента и без полного туннеля; `googlevideo.com`/`youtube.com` в список не берём, иначе видео ползёт через чужой релей. Проверять авторизацией/отправкой сообщения, а не HTTP 200 — 200 отдаётся и с заблокированного адреса.
- **Фолбэк и health-check владелец намеренно отключил**: «если упадёт — должно
  отваливаться явно». Второй порт входа (2087) при этом остаётся — он дешёвый и
  не маскирует падение выхода. Не возвращай `vpn-failover.timer` в строй сам.
- **Клиенту — бренд и маршруты «страна (назначение)», без мусора.** Один xray
  отдаёт несколько маршрутов: отдельные WS-inbound на loopback-портах
  (`/general` → `direct`, `/france` → зарубежный outbound, плюс отдельный
  `/test` → develop-полигон, чьё правило перенаправляется на новый outbound без
  касания живых маршрутов), правило по `inboundTag` ставится выше доменных.
  Клиенту — одна подписка (nginx `map` по User-Agent: clash / sing-box /
  base64-список), внутри одна группа и по узлу на маршрут.
  Авто-группы DIRECT/REJECT/PROXY владелец считает мусором, `GEOSITE` не
  использовать. Подписка должна открываться на рабочем порту (8443), не на 443.
  **GLOBAL убрать нельзя** — это встроенная группа ядра Clash/Mihomo, она есть в
  любом профиле; её видят все Clash-клиенты (FlClash, Verge, Stash), а Happ,
  Hiddify и v2rayN показывают только узлы подписки. Не обещай «спрятать», а
  советуй не-Clash клиент и режим «Правила» (в Global выбранный DIRECT = без VPN).
  Имена узлов — одинаковые во всех трёх форматах, **с флагами стран** и без
  длинных префиксов (`🇪🇪 Esmien EE (General)` / `🇫🇷 Esmien FR (Gemini)` /
  `🛠 Esmien TEST (Develop)`): флаги владелец просит явно, убирать их не надо.
  Заголовки `profile-title: <brand>` и `profile-update-interval` в ответе
  подписки дают клиенту имя бренда вместо домена. Если после обновления подписки
  флагов не видно — это клиент теряет процент-кодированный emoji в fragment
  (Happ так умеет); со стороны подписки это не лечится, предлагай Hiddify/Streisand.
  **Хост, сертификат, порты, пути и upstream'ы держи в одном `brand.json`**, а
  nginx-конфиги и подписки генерируй скриптом: смена домена тогда — правка одной
  строки, а не охота за захардкоженным именем по конфигам, ссылкам и подпискам.
  Рецепт, проверка форматов и отзыв токена —
  [references/ru-dpi-vpn-ingress.md](references/ru-dpi-vpn-ingress.md).
- **Сертификат на новый домен — это лимиты, ретрай и переключение в одном скрипте.**
  Бесплатные суффиксы (`*.qd.je`) делят один счётчик LE на всех, поэтому выпуск
  падает с `retry after <UTC>`; ждать надо до этой метки + 3–4 с, перечитывая её
  каждую попытку, и в том же скрипте после успеха переписать `brand.json`,
  перегенерировать nginx и подписки. Wildcard требует DNS-01, то есть DNS-API,
  которого у бесплатного регистратора может не быть.
  Сейчас один `*.esmien.ru` (DNS-01 через Cloudflare, зона у владельца) закрывает
  все хосты: новый поддомен = DNS-запись + vhost, certbot больше не нужен.
  Рецепт, токен, хук продления и ловушка с `--dry-run` —
  [references/acme-and-cert-limits.md](references/acme-and-cert-limits.md).
- **Диагностический пробник — временный артефакт.** Пробные vhost'ы на 8097/8098/8099
  и тестовые контейнеры на 8444 после разбора надо снимать: они остаются
  слушать мир и через месяц числятся как «а это что?». Перед удалением проверь,
  что это действительно твой пробник (`ss -tlnp` → PID → `ps -o cmd`).

Полная процедура (3x-ui API, диагностика Docker-подключений, MTProto, тесты с
двух внешних IP, перенос в recovery-репо) —
[references/vpn-and-https-ingress.md](references/vpn-and-https-ingress.md).

- **Если «VPN не работает у владельца, а с мобильного работает»** — не крути
  протоколы наугад и не переключай подозрения на сервер. Разделяй переменные
  тремя пробами с его сети: `http://IP:8099` (без редиректа), `https://IP:8098`
  (TLS без SNI) и `https://домен:443`. Открылись первые две — режется 443,
  лечится переносом сервиса на нестандартный порт; не открылась ни одна — блок
  по IP, нужен CDN или новый адрес. Плейбук с ловушками (redirect делает пробу
  бесполезной, WARP обычно мёртв с VPS, `qd.je` не принимается Cloudflare,
  Happ-десктоп не ест ссылку — отдавай файлы) —
  [references/ru-dpi-vpn-ingress.md](references/ru-dpi-vpn-ingress.md).

## Related

- Which services exist, their ports and domains: `ai-stack` skill.
- Removing a container/image and reclaiming its disk: `vps-disk-reclamation` skill.
