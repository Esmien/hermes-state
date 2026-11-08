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

**sshd is first-match-wins, not last:** `50-cloud-init.conf` is read before
`60-cloudimg-settings.conf`, so a new `99-*.conf` does NOT fix an earlier value — verify with
`sshd -T`, never from the file alone, and reload (`sshd -t && systemctl reload ssh`), don't
restart.

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
- **Closing a port is a state change → gated.** Exact rules, blast radius
  («контейнеры из 172.18 не затронуты») and verification command, then wait for
  «Да».

## Cloudflare впереди (orange cloud)

Постановка CF, реальный IP в nginx, лимиты Free-плана, WAF по UA и риски — `ai-stack` →
`references/cloudflare-proxy.md`.

**CF скорит клиентский IP, а не наш сервер**, поэтому у сценария с watchdog должен быть один
стабильный выход. Детали и границы — [references/domain-migration-and-dns.md](references/domain-migration-and-dns.md).

## fail2ban и rate limiting nginx (установлены 2026-10-31)

- **fail2ban** 1.0.2, `active`/`enabled`: SSH-брутфорс был ~2.5k попыток/сутки.
  `/etc/fail2ban/jail.local`: `findtime=1h`, `maxretry=4`, `bantime=1d`,
  `bantime.increment` (factor 2) до 4 недель, `backend=systemd`,
  `ignoreip` = loopback + 10/8 + 172.16/12 + 192.168/16, `[sshd] mode=aggressive`.
  На 24.04 action — `nftables`: баны в `nft list table inet f2b-table`, **не** в
  `iptables -S INPUT`. Детали —
  [references/fail2ban-and-rate-limits.md](references/fail2ban-and-rate-limits.md).
- **nginx** — два набора зон, путать нельзя: `conf.d/zz-ratelimit.conf` по
  `$binary_remote_addr`, `conf.d/01-cf-client-ip.conf` по `$client_ip`; живой `ai.` —
  `webui_api_cf` 20r/s + `burst=240`, `llm.` — `burst=40`; у `app.esmien.ru` только `301`
  на `ai`, лимитов там нет. Зоны, `webui_signin`/`webui_signup`, подсчёт «ботов» за сутки
  и `return 403` на мусорные пути — [references/fail2ban-and-rate-limits.md](references/fail2ban-and-rate-limits.md).
- **Бёрст считай по стоимости одной загрузки SPA**, а не по «запросам в секунду»:
  один refresh — 40–60 запросов к `/api/`, `burst=30` выбирается одним открытием
  страницы, второй F5 — `429` при `200` на HTML и нулевых `limiting requests` в
  `error.log`; лечится `burst=120`, не отключением лимита —
  [references/fail2ban-and-rate-limits.md](references/fail2ban-and-rate-limits.md).

## Сканеры LLM-шлюза (`/v1/models` без ключа)

**Не читай это как поломку LiteLLM.** В UI гейтвея появляются тысячи красных `Failure`
с моделями вида `gpt-4o`, `claude-sonnet-*`, `mistral-small` и текстом про credential —
выглядит как «сломались наши ключи», а на деле это внешние боты ищут открытый LLM-прокси.
Признак: у запросов **нет ни `user`, ни alias ключа**, а статусы — только `401`/`429`.

Диагностика (read-only, минута), типовые пути сканеров, проверка мусора в
`LiteLLM_SpendLogs` и лечение двумя частями (fail2ban-джейл на access-лог `llm.` + чистка `DELETE FROM "LiteLLM_SpendLogs"
WHERE model=''` вместе с `litellm-spend-retention`) —
[references/fail2ban-and-rate-limits.md](references/fail2ban-and-rate-limits.md).

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
сторонах, иначе backend видит loopback. Подробности —
[references/ru-dpi-vpn-ingress.md](references/ru-dpi-vpn-ingress.md).

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
- **Fake-TLS (mtg) не переживает DPI — рукопожатие режется в середине**, маскировка
  под чужой домен и смена порта не помогают. Рабочий вариант — **VLESS + WebSocket +
  настоящий TLS**, TLS снимает nginx на нестандартном порту. Рецепт, ловушки и механика
  fake-TLS (`scripts/faketls-probe.py`) —
  [references/vpn-and-https-ingress.md](references/vpn-and-https-ingress.md).
- **Фолбэк и health-check владелец намеренно отключил**: «если упадёт — должно
  отваливаться явно». Второй порт входа (2087) при этом остаётся — он дешёвый и
  не маскирует падение выхода. Не возвращай `vpn-failover.timer` в строй сам.
- **Гео-заглушка Gemini снимается маршрутизацией на сервере**, но список доменов должен
  быть полным (`www.google.com`, `accounts.google.com`, `gstatic.com`, `googleapis.com`,
  `googleusercontent.com`); `googlevideo.com`/`youtube.com` в список не берём. Проверять
  авторизацией/отправкой сообщения, а не HTTP 200 —
  [references/ru-dpi-vpn-ingress.md](references/ru-dpi-vpn-ingress.md).
- **Клиентская подписка — по правилам владельца:** авто-группы DIRECT/REJECT/PROXY он
  считает мусором, `GEOSITE` не использовать, имена узлов с флагами стран (флаги он просит
  явно), GLOBAL из Clash не спрятать — советуй не-Clash клиент и режим «Правила»; подписка
  на 8443, не на 443. Маршруты, три формата подписки, `brand.json` и отзыв токена —
  [references/ru-dpi-vpn-ingress.md](references/ru-dpi-vpn-ingress.md).
- **Сертификат на новый домен — лимиты LE, ретрай и переключение в одном скрипте**; сейчас
  один `*.esmien.ru` (DNS-01 через Cloudflare) закрывает все хосты, новый поддомен = DNS +
  vhost. Рецепт и ловушка с `--dry-run` —
  [references/acme-and-cert-limits.md](references/acme-and-cert-limits.md).
- **«VPN не работает у владельца, а с мобильного работает»** — три пробы с его сети
  (`http://IP:8099` без редиректа, `https://IP:8098` без SNI, `https://домен:443`); не
  крути протоколы наугад. Плейбук с ловушками —
  [references/ru-dpi-vpn-ingress.md](references/ru-dpi-vpn-ingress.md).

Полная процедура (3x-ui API, диагностика Docker-подключений, MTProto, тесты с двух внешних
IP, перенос в recovery-репо) — [references/vpn-and-https-ingress.md](references/vpn-and-https-ingress.md).

## Related

- Which services exist, their ports and domains: `ai-stack` skill.
- Removing a container/image and reclaiming its disk: `vps-disk-reclamation` skill.
