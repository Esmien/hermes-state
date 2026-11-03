# fail2ban и ограничения Nginx

Обе меры поставлены 2026-10-31 после реальных инцидентов: SSH-брутфорс
(~2.5k попыток/сутки) и L7-флуд (200 rps на живом nginx → CPU в ноль без
взлома).

## fail2ban

**Jail по лог-файлу обязан объявить `backend = polling`.** В `jail.d/defaults-debian.conf`
глобально стоит `backend = systemd`, и jail, у которого указан только `logpath`, молча
смотрит в journal вместо файла: `fail2ban-client get <jail> logpath` отвечает «No file is
currently monitored», в `fail2ban.log` нет ни одной строки `Found`. Признак ровно этот:
`fail2ban-regex <log> <filter>` находит совпадения, а jail показывает 0 failed.

**Собственный адрес сервера игнорируется по умолчанию** (`ignoreself`), поэтому проверка с
хоста никогда не забанит — в логе будет `Ignore <ip> by ignoreself rule`. Чтобы доказать,
что jail живой: временно `ignoreself = false`, спровоцировать, увидеть бан, затем `unbanip`
и вернуть конфиг как был. Оставлять `ignoreself = false` нельзя — первый же всплеск 429 с
собственного адреса отрежет доступ.

**Регексп не гонять через shell/heredoc-слои:** `\S` легко доезжает как `\\S`, и фильтр
перестаёт совпадать. Достаточно `^<HOST> - - .+ "[^"]+" (401|403|429)` для combined-формата —
без единого бэкслеша.

`fail2ban` 1.0.2, `active` + `enabled`. Конфиг `/etc/fail2ban/jail.local`
(перекрывает `jail.conf` и `jail.d/defaults-debian.conf`, где `sshd` уже
включён).

- `[DEFAULT]`: `findtime = 1h`, `maxretry = 4`, `bantime = 1d`,
  `bantime.increment = true` (`bantime.factor = 2`, `bantime.maxtime = 4w`),
  `backend = systemd` (нужен пакет `python3-systemd`) — годится для journal-based
  jail'ов; для файловых см. правило `backend = polling` выше,
  `ignoreip = 127.0.0.1/8 ::1 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16` —
  иначе можно забанить docker-сети.
- `[sshd]`: `mode = aggressive` — ловит и `Invalid user`, и `Failed password`.
- **Action по умолчанию на Ubuntu 24.04 — `nftables`, а не iptables:** создаёт
  свою таблицу `inet f2b-table` (set `addr-set-sshd` + chain с
  `hook input priority filter - 1`, `reject with icmp port-unreachable`).
  Поэтому банов **не видно** в `iptables -S INPUT` — смотреть
  `nft list table inet f2b-table`. С `fw-guard-postgres` (`table ip filter`)
  не конфликтует.
- Баны переживают `systemctl restart fail2ban` (sqlite
  `/var/lib/fail2ban/fail2ban.sqlite3`) — проверено: 12 IP вернулись после
  рестарта.
- Ручной бан ретроактивно: `fail2ban-client set sshd banip <ip>`, снять —
  `unbanip`. Автоскан журнала начинается с момента старта: старые атаки сами
  не подхватятся.
- Проверка состояния: `fail2ban-client status sshd`,
  `fail2ban-client status <jail>`, `journalctl -u fail2ban --since -1d`.

## Rate limiting nginx

Зоны объявляет `/etc/nginx/conf.d/zz-ratelimit.conf` (include раньше
`sites-enabled`):

```nginx
limit_req_zone  $binary_remote_addr zone=llm_api:10m    rate=10r/s;
limit_req_zone  $binary_remote_addr zone=webui_api:10m  rate=20r/s;
limit_conn_zone $binary_remote_addr zone=conn_per_ip:10m;
```

- `llm.` (`conf.d/llm.esmien.ru.conf`): `limit_req zone=llm_api
  burst=40 nodelay` + `limit_conn conn_per_ip 20` на весь server.
- `ai.` / `app.` (`conf.d/ai.esmien.ru.conf`, `app.esmien.ru.conf`): лимит **только
  в `location /api/`** (`burst=120`, `limit_conn 30`); статика (`/_app`,
  `/assets`, `/static`) идёт через `location /` без лимита — иначе массовая
  загрузка чанков при F5 даёт 429 и страница перестаёт грузиться. Правя конфиг,
  не поднимай лимит на `/`.
- **Размер burst считается по цене одной загрузки SPA.** Открытие Open WebUI —
  это 40–60 запросов к `/api/` разом (модели, папки, аватарки, скиллы, сокет),
  поэтому `burst=30` выбирался одним refresh, второй F5 подряд попадал в 429, и
  фронтенд застревал на пустой странице. Симптом со стороны владельца —
  «сайт перестал открываться», хотя HTML отдаётся 200. Признак в логе: серия
  `429` на `/api/models`, `/api/v1/folders/shared`,
  `/api/v1/models/model/profile/image`; `limiting requests` в `error.log` при
  этом может не быть — ищи по коду в access-логе, а не по сообщению.
- `limit_req_status 429` (по умолчанию 503 — для клиента неотличимо от «упало»),
  `limit_req_log_level warn`.
- Проверено: 200 последовательных запросов на `/api/v1/config` после подъёма до
  `rate=20r/s burst=120` → 200×200, ни одного 429; раньше на этом объёме отказы
  начинались после тридцатого. Ботов лимит по-прежнему отсекает — они идут без
  пауз, а ведро восстанавливается по 20 в секунду.
- **В `vps-infra` этих конфигов нет** — `install.py` генерирует nginx-вхосты
  кодом (и добавляет лимиты по порту бэкенда). После переезда лимиты надо
  переприменять; кандидат на перенос в репо.
- Проверка после правки: `nginx -t` → `systemctl reload nginx` (не restart),
  затем замер с независимого адреса, а не из контейнера на том же хосте.

При разделении 443 stream-прокси проверь реальный client IP и защиту от
подмены: [vpn-and-https-ingress.md](vpn-and-https-ingress.md). Конфиги и
возможность восстановления сверяй с актуальным `vps-infra`, а не с записями.

## Реальный IP за stream-прокси

Цепочка `stream 443 → 127.0.0.1:<hop> → 127.0.0.1:9443` теряет адрес клиента на **каждом** лишнем хопе: nginx stream отправляет в PROXY-заголовке свой `$remote_addr`, то есть адрес предыдущего хопа, а не исходного клиента. Два хопа дают в логах `127.0.0.1` при живых `set_real_ip_from`/`real_ip_header proxy_protocol` в http-контексте.

Правильно — один хоп: `server { listen 443; ssl_preread on; proxy_pass <backend>; proxy_protocol on; }` прямо на TLS-листенер (`listen 127.0.0.1:9443 proxy_protocol ssl`). Бэкенд, который PROXY не понимает (mtproto/mtg), получает свой мелкий хоп-стриппер: `server { listen 127.0.0.1:10445 proxy_protocol; proxy_pass 127.0.0.1:10443; }` — принимает заголовок и отдаёт чистый TCP.

Проверка: запрос с внешнего адреса должен дать этот же адрес в `$remote_addr` access-лога. Если в логе `127.0.0.1` при рабочем сайте — PROXY-цепочка лишняя или не принимается на промежуточном листенере (`wrong version number` у клиента = заголовок уехал в TLS).
