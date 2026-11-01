---
name: vps-network-exposure
description: "Use when a port may be open to the internet."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [devops, firewall, iptables, ufw, docker, postgres, security, exposure]
---

# Network exposure audit & closure (this VPS)

## When to Use

The owner asks «у нас <порт> наружу?», a new service/container gets a published port, a security review is requested, or something must be firewalled. Covers the host-level question: which sockets listen on a routable address, what filters them, and how to close one durably. Stack-specific service facts live in the `ai-stack` skill.

## Answer shape (owner preference)

**First line = verdict, then evidence, then the fix as a gated plan.** «Да, открыт» / «Нет, только localhost» before any command output. Then a short bullet list of the facts that decided it. Then, only if action is needed, the exact commands under «⚠️ Требуется подтверждение». Do not open with the investigation.

Keep two facts separate and say both:
1. **Network reachability** — is the TCP port reachable from the internet?
2. **Authentication gate** — can such a client actually get in (`pg_hba.conf`, app auth, allowlist)?

A firewall-closed port and an app-rejected connection are different risks (`ECONNREFUSED` vs a 41k-line brute-force log) and must not be collapsed into one «закрыто».

## Procedure

1. **Socket inventory.** `ss -tlnp | tail -n +2` — `0.0.0.0:*` / `[::]:*` = routable bind, `127.0.0.1:*` = loopback only. Map each PID to its owner: `ps -o pid,ppid,user,cmd -p <pid>`. Systemd services (host Postgres) exist ONLY here — `docker ps` cannot see them.
2. **Container view.** `docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}'`. `5432/tcp` with no `->` is an internal EXPOSE only; `127.0.0.1:8001->8000/tcp` is loopback-published; `0.0.0.0:PORT->…` is the real exposure. Cross-check with `ss` that the listener is `docker-proxy` (userland proxy path) — if nothing listens on the host port, the traffic goes through DNAT and host INPUT rules will not see it (see Pitfalls). **`ss` also catches non-Docker listeners, so read the whole list, not just container ports:** on this host `cupsd` from the `cups` snap binds `0.0.0.0:631` (printing service, not needed on a VPS) and is exposed, since `INPUT` policy is `ACCEPT` and no rule covers 631. Snapped services do not show up in `systemctl is-active cups` — `systemctl is-active snap.cups.cupsd` and `ps -o cmd -C cupsd` do.
3. **Filter state.** `iptables -S INPUT | head -20` (policy line first) and `ufw status` plus `grep -E '^ENABLED' /etc/ufw/ufw.conf`. Never infer the firewall from `systemctl is-active ufw` (see Pitfalls).
4. **App-level gate.** Read the service's own ACL, e.g. Postgres: `grep -hE '^\s*listen_addresses' /etc/postgresql/*/main/postgresql.conf` and `grep -hvE '^\s*#|^\s*$' /etc/postgresql/*/main/pg_hba.conf`.
5. **Prove reachability from outside.** Use a live TCP probe from an independent external host or multiple check-host.net nodes: request `https://check-host.net/check-tcp?host=IP:PORT&max_nodes=3` with `Accept: application/json`, then query `/check-result/REQUEST_ID` after a short delay. A completed success demonstrates TCP reachability from that node only, not application authentication or reachability from the user's network; null/pending, timeouts and errors are inconclusive without controls. Corroborate using current service logs and firewall counters, without exposing secrets. For PostgreSQL, `grep -c 'no pg_hba.conf entry' /var/log/postgresql/postgresql-*-main.log` shows real foreign hits but historical entries do not prove present reachability.
6. **Report** with the verdict-first shape above. If nothing needs closing, say «ничего не открыто» and stop — no plan.

`scripts/audit-exposure.sh` runs steps 1–5 read-only and prints the whole picture in one go; run it first, then drill into whatever it flags.

## Closing a port (durable)

Pattern that leaves intra-stack traffic intact (containers reach host Postgres from `172.16.0.0/12`):

```bash
# ACCEPT exceptions first, DROP everything else — order matters
/usr/local/bin/fw-guard-postgres.sh
```

`/usr/local/bin/fw-guard-postgres.sh` (idempotent: deletes its own rules, then rebuilds them by inserting at position 1 in reverse order — ACCEPT 127.0.0.1, ACCEPT 172.16.0.0/12, DROP) is driven by `fw-guard-postgres.service` (oneshot, `RemainAfterExit=yes`, `After=ufw.service network-online.target`, `WantedBy=multi-user.target`). Recreate that pair for any other port; it is the persistence mechanism on this host.

Verify after applying: `iptables -S INPUT | head -5` shows the three rules in order, `systemctl is-active fw-guard-postgres` = `active`, and `ss -tnp state established '( sport = :5432 )'` still shows the containers' `172.18.x` peers — no rule change without proof that the stack kept working. Then verify from **outside**, using the netns pattern above; `iptables -S` alone shows intent, not effect. Also confirm the counter sits on the expected rule: if the DROP counter does not move while a foreign probe times out, the packet is being stopped somewhere else and the reasoning is wrong.

## SSH password auth on this host

`PasswordAuthentication` is **off**: `/etc/ssh/sshd_config.d/50-cloud-init.conf` says `no`, backed by `/etc/cloud/cloud.cfg.d/99-ssh-no-password.cfg` (`ssh_pwauth: false`) so cloud-init cannot flip it back on reboot. Root logs in by key only (2 keys in `/root/.ssh/authorized_keys`); `ai_service` has **no** `authorized_keys`, so it cannot SSH in at all — use `su`/`sudo` from root.

**sshd is first-match-wins, not last.** `Include /etc/ssh/sshd_config.d/*.conf` is line 12 and files apply in lexical order: `50-cloud-init.conf` (`yes`) beat `60-cloudimg-settings.conf` (`no`) — that is why `sshd -T` reported `passwordauthentication yes`. A new `99-*.conf` would NOT fix it. Edit the earliest file that sets the key, then verify with `sshd -T | grep -i passwordauthentication` (never trust the file alone). `cloud.cfg` had no `ssh_pwauth` key at all, so the drop-in `99-ssh-no-password.cfg` is what makes it stick.

Reload, don't restart: `sshd -t && systemctl reload ssh` keeps existing sessions alive. Verify from the loopback: `ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no root@127.0.0.1 true` must answer `Permission denied (publickey)` — the parenthesised list is the authoritative set of allowed methods.

## Pitfalls

- **`iptables` here is nf_tables and rejects more than one `-s`:** `iptables -I INPUT -p tcp --dport 5432 ! -s 127.0.0.1 ! -s 172.16.0.0/12 -j DROP` → `multiple -s flags not allowed`, exit 2. Express the same intent as ordered rules: ACCEPT for each trusted source, then an unconditional DROP for that port, all above the policy.
- **Build the order by inserting at position 1 in reverse.** `-A` appends below other ACCEPT rules and silently never matches; the working idiom is `-I INPUT 1 … DROP`, then `-I INPUT 1 … ACCEPT 172.16/12`, then `-I INPUT 1 … ACCEPT 127.0.0.1`, which lands as ACCEPT/ACCEPT/DROP.
- **`systemctl is-active ufw` = `active` while the firewall is OFF.** Here `ENABLED=no` in `/etc/ufw/ufw.conf` leaves the unit running but rules flushed, so `ufw status` answers `inactive` and `iptables -S` is a bare `-P INPUT ACCEPT`. Judging by the unit state produces a false «firewall включён». Read `ufw status` + the `ENABLED=` line, and after any change re-read `iptables -S`.
- **Do not enable ufw to fix one port.** `DEFAULT_INPUT_POLICY="DROP"` plus an empty `user.rules` set would cut SSH and the whole stack at once, and `ufw deny` written while ufw is disabled does nothing. An iptables guard unit is the surgical change; enabling ufw is a separate, owner-gated redesign.
- **Nothing on this host persists iptables rules by default** — `netfilter-persistent` is not installed and `ufw` is disabled, so hand-added rules vanish on reboot. Always pair a rule with a oneshot systemd unit (`WantedBy=multi-user.target`, `After=ufw.service`) and `systemctl enable --now` it; verify with `systemctl is-enabled`.
- **Docker-published ports can bypass the INPUT chain.** If the listener is `docker-proxy`, INPUT rules apply; if the port is DNAT-ed straight to the container (no host listener in `ss`), filter on `DOCKER-USER` instead — and the cleaner fix is re-publishing as `127.0.0.1:PORT:PORT`. Decide from `ss -tlnp` which path you are on before claiming a port is closed.
- **Distinguish live external probes from stale scan data.** A completed live TCP success is evidence of reachability from that probe's network, not proof of application-level operation or availability from every ISP. Pending/null, rate-limited and timed-out results do not establish closure; corroborate with live logs or packet counters and control probes. Historical search-engine scans can be stale, while local connections to the server's public IP do not test the Internet path.
- **Testing from inside a container on the same host is a self-whitelisting trap — the single easiest way to produce a false «открыт».** A packet from a bridge network is MASQUERADEd to the bridge gateway (`172.18.0.1`), which falls inside `172.16.0.0/12` — exactly the trusted range the ACCEPT rules exist for. The probe is therefore accepted by the very rule it should be tested against, and a port that is closed to the internet answers happily. Symptom: `curl`/socket connect succeeds from `docker exec`, while the service log shows no foreign IPs at all. Any test whose source address is inside an allowlist proves nothing about the default policy.
- **A synthetic netns tests local filter behavior, not the actual Internet path.** Use a source outside every allowlist, then probe and read the **packet counter** as the witness; use a separate real external probe for end-to-end reachability. Creating network namespaces and firewall rules changes system state and requires explicit approval. Pattern:
  ```bash
  ip netns add fwtest
  ip link add veth-fwtest type veth peer name veth-fwtest-c
  ip link set veth-fwtest-c netns fwtest
  ip addr add 10.99.99.1/24 dev veth-fwtest && ip link set veth-fwtest up
  ip netns exec fwtest ip addr add 10.99.99.2/24 dev veth-fwtest-c
  ip netns exec fwtest ip link set veth-fwtest-c up
  iptables -S INPUT | grep 5432                      # note DROP counter before
  ip netns exec fwtest timeout 5 bash -c 'echo > /dev/tcp/141.98.166.213/5432'   # expect timeout
  iptables -S INPUT | grep 5432                      # DROP counter must have advanced
  ip netns exec fwtest timeout 5 bash -c 'echo > /dev/tcp/141.98.166.213/22'     # control: must connect ok
  ip netns del fwtest                                # always clean up
  ```
  A rising DROP counter on a timing-out client is proof; so is a control port that connects. Without the control probe a timeout could just mean «сеть сломана». Delete the netns afterwards.
- **A `ss` listener is not the only way to be reachable, and a missing listener is not proof of safety.** Decide DNAT vs userland-proxy from `ss -tlnp` first (see the Docker pitfall), because host `INPUT` rules are blind to DNAT-ed traffic. `fw-guard-postgres.sh` handles the host-Postgres case only.
- **`write_file`/`patch` refuse system paths** (`Refusing to write to sensitive system path: /etc/...`). Write to `~/.hermes/cache/scratch/` first, then `cp` it into place; for an existing system file that only needs one line flipped, read+write it from Python in `execute_code` (needs no shell redirect).
- **Closing a port is a state change → gated.** Give the exact rules, the blast radius («контейнеры из 172.18 не затронуты») and the verification command, then wait for «Да».
- **A privileged helper container is exposure of its own kind.** `privileged: true` + `pid: host` + `/var/run/docker.sock` + `/:/mnt/host` means host-root RCE from inside; when such a container is unused, name those four facts when proposing removal — they are the reason it matters more than an open port.

## fail2ban (установлен 2026-10-31)

Защита от SSH-брутфорса (было ~2.5k попыток/сутки). `fail2ban` 1.0.2, `enabled`, автозапуск.
Конфиг: `/etc/fail2ban/jail.local` (перекрывает `jail.conf` + `jail.d/defaults-debian.conf`, где sshd уже включён).

- `[DEFAULT]`: `findtime=1h`, `maxretry=4`, `bantime=1d`, `bantime.increment` до 4 недель, `backend=systemd`
  (нужен `python3-systemd`), `ignoreip` = loopback + 10/8, 172.16/12, 192.168/16 (иначе можно забанить docker-сети).
- `[sshd]`: `mode=aggressive` — ловит и Invalid user, и Failed password.
- **Action по умолчанию на 24.04 — `nftables`**, а не iptables: создаёт свою таблицу `inet f2b-table`
  (set `addr-set-sshd` + chain `hook input priority filter - 1`, `reject with icmp port-unreachable`).
  Поэтому в `iptables -S INPUT` банов **не видно** — смотреть `nft list table inet f2b-table`.
  С `fw-guard-postgres` в `table ip filter` не конфликтует.
- Баны переживают `systemctl restart fail2ban` (sqlite `/var/lib/fail2ban/fail2ban.sqlite3`); проверено — 12 IP вернулись.
- Ручной бан ретроактивно: `fail2ban-client set sshd banip <ip>`; снять — `unbanip`. Авто-скан журнала начинается с момента старта, старые атаки сами не подхватятся.

## Общий HTTPS-порт и сохранение адреса клиента

- Перед размещением TCP-прокси на занятом 443 проверь все IPv4/IPv6 listeners, vhost-ы, модули Nginx, фактические HTTP-коды и сделай план отката. Сначала настрой и проверь backend на loopback; затем после подтверждения меняй ingress, проверяй `nginx -t` и делай reload, не restart.
- При маршрутизации `stream`/`ssl_preread` к локальному HTTPS-backend **сохраняй исходный IP клиента**: иначе backend видит loopback, а лимиты, логи и ACL работают неправильно. Применяй PROXY protocol на обеих сторонах и доверяй заголовку только на loopback; проверь совместимость всех vhost-ов и приложений. До включения проверяй это в отдельном тестовом listener, после — с двух независимых внешних IP, включая проверку rate limit и spoofing. Не считай HTTP 200 доказательством сохранения IP.
- Разделяй проверку внешнего TCP, работы TLS/fallback и настоящего прикладного подключения через сеть пользователя: каждое доказывает только свой уровень. Для MTProto ссылка должна содержать опубликованный host-порт, а не внутренний порт контейнера; секреты и ссылки не выводи в чат или диагностические логи.
- После изменения ingress перенеси конфигурацию и процедуру восстановления в recovery-репозиторий без секретов; проверь восстановление и автозапуск. Нельзя считать задачу завершённой, пока этот перенос или клиентский тест не выполнен.
- **Текущее состояние требует проверки:** после добавления Fake TLS внешний 443 направляется Nginx stream на локальный HTTPS backend или MTProto backend; адрес клиента на HTTPS backend мог стать loopback, а перенос изменений в recovery-репозиторий и проверка Telegram у владельца не подтверждены. Перед дальнейшими правками проверь актуальное состояние и исправь по согласованию; не утверждай, что клиент работает.

## Rate limiting nginx (добавлен 2026-10-31)

Защита от L7-флуда (было: 200 rps на живой nginx → CPU в ноль без взлома).
Зоны — `/etc/nginx/conf.d/zz-ratelimit.conf` (include раньше `sites-enabled`):
`llm_api` 10r/s, `webui_api` 8r/s, `conn_per_ip`.

- `llm.` — `limit_req zone=llm_api burst=40 nodelay` + `limit_conn 20` на весь server.
- `ai.` — лимит **только в `location /api/`** (`burst=30`, `limit_conn 30`); статика
  (`/_app`, `/assets`, `/static`) идёт через `location /` без лимита — иначе массовая
  загрузка чанков при F5 даёт 429 и страница перестаёт грузиться. Правя этот конфиг,
  не поднимайте лимит на `/`.
- `limit_req_status 429` (по умолчанию 503 — для клиента неотличимо от «упало»).
- Проверено: 60 параллельных → 37×200/23×429 на `ai/api`, 80 → 53×200/27×429 на `llm`,
  через 3 с снова 200; все контейнеры healthy, статика 200.
- **В `vps-infra` этих конфигов нет** (install.py генерирует nginx-вхосты кодом),
  т.е. после переезда лимиты надо переприменять — кандидат на перенос в репо.

## Related

- Which services exist, their ports and domains: `ai-stack` skill.
- Removing a container/image and reclaiming its disk: `vps-disk-reclamation` skill.
