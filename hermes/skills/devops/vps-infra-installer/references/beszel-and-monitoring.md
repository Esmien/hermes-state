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

- `.github/workflows/uptime.yml` в `vps-infra`: cron `*/10`, с раннеров GitHub
  3 попытки на адрес → при провале Telegram (secret `TG_BOT_TOKEN`, чат
  владельца). Живые пробы: `https://llm.esmien.ru/webui-health` (origin: nginx →
  WebUI) и `https://ai.esmien.ru/` (`200,403` — CF режет бота-раннера, это норма).
  Секрет ставится через API с libsodium sealed box (`pynacl` в отдельном venv,
  не системный); токен в логи не попадает — GitHub маскирует. Дрилл:
  `workflow_dispatch` с `extra_url=https://httpbin.org/status/500`, сообщение
  приходит с префиксом `[ТЕСТ]`.

### Проба обязана совпадать с allow-листом вхоста

Внешний вотчер стучится **тем же путём, который открыт снаружи**. Любая
закрытая дверь ломает вотчер молча и шумно одновременно: прогон падает, а в
Telegram летит «🔴 VPS не отвечает» каждые несколько часов — при живом хосте.

- Закрыв вхост (`allow 85.92.158.238; allow 127.0.0.1; deny all` +
  `error_page 403 = @drop` → `444`), сразу грепни, кто его щупает снаружи:
  `grep -rn 'https://<host>' /root/vps-infra/.github/workflows` и
  `grep -rn '<host>' /usr/local/bin/deadman-ping.sh /etc/deadman-ping.url`.
  Пробы двигаются в тот же коммит, что и запрет.
- Публичный путь у `llm.` — **только** `location = /webui-health { allow all; }`
  (→ `127.0.0.1:8080/health`, отдаёт `{"status":true}`). LiteLLM снаружи не
  виден вообще: его живость сторожит локальный `litellm-watchdog.timer`, поэтому
  из вотчера пробу `/health/liveliness` убрали, а не «починили ключом».
- **Добавлять новый `allow all` ради монитора — только по просьбе владельца:**
  публичный `/litellm-health` сводит на нет смысл закрытого вхоста. Ответ
  «мониторить LiteLLM снаружи нечем» честнее, чем тихо открыть дверь заново.
- Проверка, что видит посторонний, без выхода в интернет: `curl -sS -o /dev/null
  -w '%{http_code}' --resolve llm.esmien.ru:443:<свой публичный IP> https://llm.esmien.ru/health/liveliness`
  → `000` (обрыв по 444), а `/webui-health` → `200`. Запрос идёт с публичного
  адреса, которого нет в allow-листе, то есть проверяет именно правила nginx;
  сетевую доступность это не доказывает (см. `vps-network-exposure`).

### Прогнать и проверить воркфлоу без `gh`

`gh` на хосте нет, а токен уже лежит: `GITHUB_KEY` в
`/home/ai_service/ai-stack/ai/.env` (тот же, которым пушит
`vps-infra-push.service`). Читать его в чат нельзя — только в переменную.

```bash
T=$(grep -m1 '^GITHUB_KEY=' /home/ai_service/ai-stack/ai/.env | cut -d= -f2- | tr -d '"')
curl -sS -o /dev/null -w '%{http_code}\n' -X POST \
  -H "Authorization: Bearer $T" -H 'Accept: application/vnd.github+json' \
  https://api.github.com/repos/Esmien/vps-infra/actions/workflows/uptime.yml/dispatches \
  -d '{"ref":"main"}'                       # 204 = принято
sleep 30
curl -sS -H "Authorization: Bearer $T" \
  'https://api.github.com/repos/Esmien/vps-infra/actions/workflows/uptime.yml/runs?per_page=3'
```

Смотреть `status`/`conclusion`/`head_sha`: успех на **своём** коммите и есть
доказательство починки; «зелёный» прогон на старом sha ничего не проверяет.

- **`schedule` в GitHub не соблюдает `*/10`.** В реальности между плановыми
  прогонами бывают часы (наблюдались разрывы ~5 ч), поэтому тревога приходит с
  задержкой, а «проба падала каждый прогон» ≠ «каждые 10 минут». Для точного
  контура — healthchecks.io/deadman, не чаще cron.
- Новый файл воркфлоу начинает действовать только после пуша через
  `vps-infra-push.service` (прямой `git push` в `/root/vps-infra` не пройдёт:
  кредов в клоне нет) — и только если пуш прошёл по свежему `head_sha`.
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

## Текущая конфигурация Beszel, внешнего контура и TLS

- **Beszel** (шаг `beszel`): hub+agent в Docker, `/home/ai_service/beszel`,
  hub только на `127.0.0.1:8090` (наружу — через `mon.` vhost), связка через
  unix-сокет `beszel_socket/beszel.sock`, вместе ~20 МБ RAM. Без UI
  настраивается целиком через PocketBase API; `KEY` — публичный ключ хаба,
  `TOKEN` — UUID из `fingerprints` (без него агент вечно ловит 401), alerts
  (Status/CPU/Memory/Disk) создаются только вручную. Команды и грабли —
  [references/beszel-and-monitoring.md](references/beszel-and-monitoring.md).
- **Внешний контур**: `.github/workflows/uptime.yml` (cron `*/10`, curl
  `https://ai.esmien.ru/` (`200,403`) и `https://llm.esmien.ru/webui-health`
  (`200`), 3 попытки → Telegram; проба обязана жить на пути, открытом в
  allow-листе вхоста), дрилл через `workflow_dispatch` с
  `extra_url=https://httpbin.org/status/500` (сообщение с префиксом `[ТЕСТ]`).
  GitHub гасит `schedule` в публичном репо после 60 дней без активности —
  поэтому `uptime-heartbeat.timer` раз в месяц дописывает
  `maintainer/uptime-heartbeat.txt`. Второй контур healthchecks.io:
  `deadman-ping.sh` + таймер, ping-URL в `/etc/deadman-ping.url`.
- **TLS:** один wildcard `*.esmien.ru` (плюс apex), выпущенный через **DNS-01 Cloudflare** (`esmien-wildcard`, токен `/root/.secrets/cf.ini` 0600, плагин `certbot-dns-cloudflare`, хук продления перезагружает nginx). Новый поддомен = DNS-запись + vhost, certbot больше не запускается, квота Let's Encrypt больше не упирается. Старая зона `qd.je` **выведена из эксплуатации**: её DNS-провайдер перестал отвечать, vhost'ы и сертификаты удалены — не возвращай их в `legacy_hosts` и не чини их certbot'ом. Упор в квоту был нормой для неё, самописные ретрай-таймеры не ставить (решение владельца): выпуском занимается только `certbot.timer`.
