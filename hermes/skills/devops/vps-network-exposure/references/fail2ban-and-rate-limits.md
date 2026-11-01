# fail2ban и ограничения Nginx

## fail2ban

Конфиг `/etc/fail2ban/jail.local`, fail2ban 1.0.2 enabled. `[DEFAULT]`: `findtime=1h`, `maxretry=4`, `bantime=1d`, `bantime.increment` до четырёх недель, `backend=systemd` (нужен `python3-systemd`). `ignoreip` включает loopback и приватные сети 10/8, 172.16/12, 192.168/16, чтобы не банить Docker. `[sshd] mode=aggressive` ловит Invalid user и Failed password.

Ubuntu 24.04 использует nftables: `nft list table inet f2b-table`, а не `iptables -S INPUT`. Баны сохраняются в `/var/lib/fail2ban/fail2ban.sqlite3` и переживают рестарт. `fail2ban-client set sshd banip <ip>` и `unbanip`; старые попытки автоматом задним числом не банятся.

## Nginx rate limiting

Проверь живые конфиги: `/etc/nginx/conf.d/zz-ratelimit.conf` объявляет `llm_api` 10r/s, `webui_api` 8r/s, `conn_per_ip`. Для `llm.` серверный `limit_req zone=llm_api burst=40 nodelay` и `limit_conn 20`. Для `ai.` лимит только в `location /api/`: `burst=30`, `limit_conn 30`. Не ставь лимит на статику: одновременная загрузка чанков при F5 даёт 429. `limit_req_status 429` вместо 503.

При разделении 443 stream-прокси проверь реальный client IP и корректную защиту от подмены: [vpn-and-https-ingress.md](vpn-and-https-ingress.md). Проверь rate limit с независимых адресов. Конфиги и возможность восстановления сверяй с актуальным `vps-infra`, не полагайся на исторические записи.
