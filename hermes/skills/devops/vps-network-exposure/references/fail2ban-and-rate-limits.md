# fail2ban и ограничения Nginx

Обе меры поставлены 2026-10-31 после реальных инцидентов: SSH-брутфорс
(~2.5k попыток/сутки) и L7-флуд (200 rps на живом nginx → CPU в ноль без
взлома).

## fail2ban

`fail2ban` 1.0.2, `active` + `enabled`. Конфиг `/etc/fail2ban/jail.local`
(перекрывает `jail.conf` и `jail.d/defaults-debian.conf`, где `sshd` уже
включён).

- `[DEFAULT]`: `findtime = 1h`, `maxretry = 4`, `bantime = 1d`,
  `bantime.increment = true` (`bantime.factor = 2`, `bantime.maxtime = 4w`),
  `backend = systemd` (нужен пакет `python3-systemd`),
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
  `journalctl -u fail2ban --since -1d`.

## Rate limiting nginx

Зоны объявляет `/etc/nginx/conf.d/zz-ratelimit.conf` (include раньше
`sites-enabled`):

```nginx
limit_req_zone  $binary_remote_addr zone=llm_api:10m    rate=10r/s;
limit_req_zone  $binary_remote_addr zone=webui_api:10m  rate=8r/s;
limit_conn_zone $binary_remote_addr zone=conn_per_ip:10m;
```

- `llm.` (`sites-available/llm.esmien.qd.je`): `limit_req zone=llm_api
  burst=40 nodelay` + `limit_conn conn_per_ip 20` на весь server.
- `ai.` (`sites-available/ai.esmien.qd.je`): лимит **только в `location
  /api/`** (`burst=30`, `limit_conn 30`); статика (`/_app`, `/assets`,
  `/static`) идёт через `location /` без лимита — иначе массовая загрузка
  чанков при F5 даёт 429 и страница перестаёт грузиться. Правя конфиг, не
  поднимай лимит на `/`.
- `limit_req_status 429` (по умолчанию 503 — для клиента неотличимо от «упало»),
  `limit_req_log_level warn`.
- Проверено: 60 параллельных → 37×200 / 23×429 на `ai/api`; 80 → 53×200 /
  27×429 на `llm`; через 3 с снова 200; все контейнеры healthy, статика 200.
- **В `vps-infra` этих конфигов нет** — `install.py` генерирует nginx-вхосты
  кодом (и добавляет лимиты по порту бэкенда). После переезда лимиты надо
  переприменять; кандидат на перенос в репо.
- Проверка после правки: `nginx -t` → `systemctl reload nginx` (не restart),
  затем замер с независимого адреса, а не из контейнера на том же хосте.

При разделении 443 stream-прокси проверь реальный client IP и защиту от
подмены: [vpn-and-https-ingress.md](vpn-and-https-ingress.md). Конфиги и
возможность восстановления сверяй с актуальным `vps-infra`, а не с записями.
