# Beszel, внешний мониторинг и TLS

## Beszel (шаг `beszel`)

Hub+agent в Docker, `/home/ai_service/beszel`, вместе ~20 МБ RAM. Hub слушает
только `127.0.0.1:8090` (наружу — через `mon.` vhost). Связка hub↔agent — unix
сокет `beszel_socket/beszel.sock`, поэтому TCP-порт агента наружу не нужен.

**Без UI всё настраивается через PocketBase API** (superuser обходит rules):

```bash
# внутри контейнера hub: создать/обновить суперюзера (креды не выводить)
/beszel superuser upsert <email> <pass>
# затем POST /api/collections/users/auth-with-password → token
# коллекции: users, systems, fingerprints, user_settings, alerts
```

Грабли, на которые ушло время:

- `KEY` — это **публичный ключ хаба**: `ssh-keygen -y -f beszel_data/id_ed25519`
  (приватный ключ не выводить и не копировать в чат).
- `TOKEN` — UUID из коллекции `fingerprints` (поле `token`); его **генерит
  фронтенд** при создании системы, в `systems` его нет. Без fingerprints агент
  вечно ловит `401`.
- Notifications: `user_settings.settings` (внутри shoutrrr):

  ```json
  {"emails": [], "webhooks": ["telegram://<token>@telegram?chats=<id>&parseMode=HTML"]}
  ```

  Проверка: `POST /api/beszel/test-notification {"url": ..., "userId": ...}`
  токеном юзера (не суперюзера) → `{"err": false}` = доставлено. URL с токеном
  в чат и логи не писать.
- Алерты создаются только вручную: `alerts` = `{name: Status|CPU|Memory|Disk,
  value, min, user, system}`; без них графики есть, а тревог нет совсем.

## Внешний мониторинг (GitHub Actions + dead-man)

Внутренний мониторинг умирает вместе с хостом, поэтому внешний контур — снаружи:

- `.github/workflows/uptime.yml` в `vps-infra`: cron `*/10`, curl `https://ai.` и
  `https://llm.` с раннеров GitHub, 3 попытки → при провале Telegram (secret
  `TG_BOT_TOKEN`, чат владельца). Секрет ставится через API с libsodium sealed
  box (`pynacl` в отдельном venv, не системный); токен в логи не попадает —
  GitHub маскирует. Дрилл: `workflow_dispatch` с
  `extra_url=https://httpbin.org/status/500`, сообщение приходит с префиксом
  `[ТЕСТ]`.
- **GitHub отключает `schedule` в публичных репо после 60 дней без активности** —
  `uptime-heartbeat.timer` (раз в месяц) дописывает строку в
  `maintainer/uptime-heartbeat.txt`, watcher коммитит. Без этого монитор молча
  умирает.
- healthchecks.io как второй (более точный) контур: скрипт `deadman-ping.sh` +
  таймер уже стоят, нужен только ping-URL в `/etc/deadman-ping.url`. **Главная
  засада: регистрация там email-based (magic link), автоматически из консоли
  не создаётся.**

## TLS и квоты Let's Encrypt

- **`qd.je` — бесплатный домен-спейс: квота LE (50 сертификатов / 168 ч) общая
  для ВСЕХ его поддоменов и владельцев.** Первый выпуск может упереться в
  лимит — это норма, **самописные ретрай-таймеры не ставить** (решение
  владельца): выпуском и продлением занимается только `certbot.timer`, он
  повторяет до успеха.
- Нужен выпуск без лотереи — домен в своей зоне или другой ACME CA
  (Buypass Go 180 дней / ZeroSSL), там квота не общая.
- Проверка: `openssl x509 -enddate -noout -in <cert>` +
  `systemctl list-timers certbot`.
- DNS доменов → IP нового сервера нужно переключить **до** шага `tls`, иначе
  certbot пропустит домен и оставит HTTP-vhost (это не ошибка установщика).
