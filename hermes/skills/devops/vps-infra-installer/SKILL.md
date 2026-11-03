---
name: vps-infra-installer
description: "Use when deploying or migrating this VPS from scratch."
version: 1.1.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [devops, deploy, migration, postgres, docker, hermes]
---

# vps-infra installer (this VPS)

## When to Use

Нужно поднять инфраструктуру на чистом сервере, переехать на другой VPS,
или изменить сам установщик. Стек: PostgreSQL 17 + pgvector, LiteLLM,
Open WebUI, SearXNG, open-terminal, Redis, Nginx + Certbot, бэкапы,
Telegram-мониторинг, в конце — Hermes (хостовый режим).

Репозиторий: `github.com/Esmien/vps-infra` (публичный, секретов внутри нет).
Рабочая копия на этом сервере: `/root/vps-infra`. Живой стек —
`/home/ai_service/ai-stack`; его `deploy.sh` исторический и не покрывает
Hermes, бэкапы и мониторинг.

## One-liner

```bash
curl -fsSL https://raw.githubusercontent.com/Esmien/vps-infra/main/bootstrap.sh | sudo bash
```

`bootstrap.sh` ставит git/curl/python3 → клонирует в `/opt/vps-infra` →
`exec python3 install.py`. Аргументы пробрасываются через `bash -s -- …`.

## Режимы

```bash
install.py                     # интерактивно: домены, e-mail, внешние секреты
install.py --yes               # без вопросов, значения из существующих .env
install.py --reconfigure       # переспросить секреты (Enter = оставить как есть)
install.py --dry-run           # показать план, ничего не менять
install.py check               # read-only проверка живого стека
install.py export --with-data  # → /var/lib/vps-infra/vps-infra-bundle-*.tar.gz
install.py --bundle <path|url> --restore   # восстановление БД + webui_data
install.py --from-bot --restore --hermes --restore-hermes
install.py --skip tls,restore --only verify
install.py --secrets-from-bot --secrets-key /root/.secrets/offsite.key   # разложить .env из архива
install.py --secrets-archive <file.enc> --set WEBUI_URL=http://drill.local
install.py --bot-token … --file-bot-token … --hermes-token …             # тестовые боты
```

Шаги идут в фиксированном порядке, каждый идемпотентен:
`preflight → packages → users → stack → secrets → bundle → fetch → postgres →
network → images → migrate → restore → data → apps → notifications → beszel →
units → hardening → tls → verify → hermes`.

`--only`/`--skip` принимают имена шагов; неизвестное имя — ошибка.
`--skip preflight` вместе со `stack`/`secrets` разрешён и печатает, что
конфигурация берётся из уже существующих файлов.

**`hardening`** идёт до `tls`, ибо vhost'ы ссылаются на зоны: ставит fail2ban +
`python3-systemd`, пишет `/etc/fail2ban/jail.local` (sshd, `maxretry=4`/1ч, бан 1д,
инкремент до 4 недель, `ignoreip` включает 10/8 + 172.16/12 + 192.168/16 — иначе
забанит docker) и `/etc/nginx/conf.d/zz-ratelimit.conf` (`llm_api` 10r/s,
`webui_api` 8r/s, `conn_per_ip`) — **но 8r/s при `burst=30` мало для SPA**: одна загрузка Open WebUI стоит 40–60 запросов к `/api/`, второй F5 подряд уходит в 429 и страница выглядит «не открывается». На живом хосте поднято до `rate=20r/s` + `burst=120`; правя `install.py`, поднимай и там, иначе переустановка вернёт баг (`vps-network-exposure`, `references/fail2ban-and-rate-limits.md`). `vhost_ssl()` добавляет лимиты по порту
бэкенда: 4000 — server-level, 8080 — только `location /api/` (статика без
лимита, иначе F5 даёт 429 на чанках). Проверка: `install.py check` печатает
`fail2ban: active` и `nginx rate-limit: да`.

## Правила, которые нельзя нарушать

1. **Секреты только в .env.** `install.py` генерирует внутренние ключи
   (`token_hex(32)`) и спрашивает внешние (OpenRouter, Telegram, GitHub).
   Существующие значения переиспользуются: повторный запуск не меняет
   пароли и не разлогинивает. `install.json` токенов не содержит.
   **Исключение — `UI_PASSWORD`:** прогон установщика заменил его на
   сгенерированное значение (8 → 64 символа), остальные секреты остались
   прежними. `UI_PASSWORD` — пароль админа **LiteLLM**, а не Open WebUI;
   бот `owui-signup-approver` читает его для входа в WebUI, поэтому после
   любого прогона проверяй, что «отклонить» в боте работает: `signin failed:
   HTTP 400` в `/var/log/owui-signup-approver.log` = рассинхрон пароля
   (разбор и починка — skill `credential-login-verification`,
   `references/open-webui-auth.md`).
2. **БД восстанавливаются только в пустые базы** или с явным `--restore`.
   Дамп старше 72 ч требует `--force-stale`. Bundle кладёт дампы в
   `backups/postgres/`, свежесть — по mtime.
3. **`:latest`-образы не обновляются**, если уже есть локально: повторный
   install не должен молча менять версии. WebUI-образ собирается, если его нет.
4. **Домен `bot.esmien.ru` — это lyria (бот с музыкой), не open-terminal.**
   Порт 8000 на хосте занят `lyria-bot`. open-terminal не публикует порт;
   health проверяется `docker exec open-terminal curl …/health`. Третий домен
   опционален (`extra_domain`), по умолчанию пуст.
5. Перед прогоном на живом сервере — `touch /var/lib/docker-autorecover/pause`,
   после проверки снять. Иначе детектор инцидентов поднимет агента.
6. `deploy.sh` из `/home/ai_service/ai-stack` исторический: не покрывает
   Hermes, бэкапы, мониторинг. Источник правды — этот репозиторий.
7. **Это recovery-артефакт для НОВОГО сервера, а не набор для раскатки на текущем.**
   Владелец ждёт правки в `/root/vps-infra`, а не деплой «сюда»: не предлагай
   установить новую версию установщика на живой хост по умолчанию. Если фича
   всё же требует живого изменения (например, без правки `monitor.py` бэкап не
   пишет `file_id` и автоматическое восстановление невозможно) — объясни это
   одной фразой, назови минимальный дифф и спроси разрешение отдельно, отделяя
   «что лежит в репозитории» от «что будет работать здесь».

## Переезд (проверенный порядок)

1. Одной командой: `bootstrap.sh | bash -s -- --from-bot --restore --hermes --restore-hermes`.
   `fetch` берёт последний набор дампов из файл-бота (реестр `file_id` → части →
   склейка → sha256), `hermes` + `--restore-hermes` разворачивает состояние из
   `Esmien/hermes-state` (config/SOUL/memories/skills/cron, `/usr/local/bin`,
   юниты, `/etc`, runbooks). Секреты тоже восстанавливаются: `--secrets-from-bot --secrets-key …`
   скачивает архив и раскладывает все четыре `.env` по местам; без этих флагов они спрашиваются заново.
2. Ручной путь (fallback): `install.py export --with-data` → перенос →
   `--bundle <path> --restore`.
3. DNS доменов → IP нового сервера **до** шага TLS, иначе certbot пропустит
   домен (оставит HTTP-vhost) — это не ошибка.
4. Первого админа Open WebUI на пустой БД создают через форму регистрации;
   на восстановленной БД пользователи уже есть.

### Прогон восстановления на чистой машине

Полный e2e без TLS делается на отдельной виртуалке, а не на живом хосте: Multipass с Ubuntu
24.04, клон репозитория с GitHub, `--secrets-from-bot` (архив `.env` раскладывается сам, руками
копировать нечего), все сторожа и Hermes поднимаются на **тестовых** токенах ботов.
Команды, чек-лист «что считается успехом» и грабли — [references/restore-drill.md](references/restore-drill.md).

Жёсткие правила этого класса работ: ничего не переносить руками кроме зашифрованного архива
секретов; живые токены ботов в прогон не давать (второй поллер крадёт `getUpdates` у боевого);
пропускается только TLS — остальные шаги идут как в бою.

### Бэкап БД через бота: как устроено и где ломается

- Бот **не читает свою историю чата**, поэтому единственная зацепка для
  восстановления — `file_id`, который вернул `sendDocument`. `monitor.py backup`
  пишет его в `backups/postgres/.tg-registry.json` (3 набора на базу), реестр
  уезжает в `hermes-state` как `host/backups/tg-registry.json`.
- Части дампа обязаны быть **≤18 МБ** (`TG_DOC_LIMIT = 18 MiB` в `monitor.py`):
  `getFile` отдаёт не более 20 МБ, части по 45 МБ из чата уже не скачать.
- Нет реестра — fallback `getUpdates`: переслать файлы бэкапа самому боту.
- `--from-bot` игнорирует проверку «дамп старше 72 ч» (источник выбран осознанно).
- Токен проверяется на форму `123456:AA…`: заглушка из `install.json`
  (`__stored_in_notifications_env__`) даёт понятную ошибку, а не 404 от Telegram.
- **Файлы пользователя едут отдельно от БД.** Псевдо-база `webui_data` в том же
  реестре — это tar.gz `uploads` + `generated_images` (~980 МБ, 55 частей), её
  пишет `webui-data-backup.timer` (Sun 04:00 UTC). `RESTORE_DBS` включает её
  (`webui_db`, `litellm_db`, `webui_data`), шаг `data` распаковывает архив в
  `WEBUI_DATA` (пропускает непустой каталог без `--restore`). Без этого шага
  bootstrap вернёт БД и конфиги, но не оригиналы файлов Knowledge.

### Beszel, внешний мониторинг, TLS

- **Beszel** (шаг `beszel`): hub+agent в Docker, `/home/ai_service/beszel`,
  hub только на `127.0.0.1:8090` (наружу — через `mon.` vhost), связка через
  unix-сокет `beszel_socket/beszel.sock`, вместе ~20 МБ RAM. Без UI
  настраивается целиком через PocketBase API; `KEY` — публичный ключ хаба,
  `TOKEN` — UUID из `fingerprints` (без него агент вечно ловит 401), alerts
  (Status/CPU/Memory/Disk) создаются только вручную. Команды и грабли —
  [references/beszel-and-monitoring.md](references/beszel-and-monitoring.md).
- **Внешний контур**: `.github/workflows/uptime.yml` (cron `*/10`, curl `ai.` и
  `llm.`, 3 попытки → Telegram), дрилл через `workflow_dispatch` с
  `extra_url=https://httpbin.org/status/500` (сообщение с префиксом `[ТЕСТ]`).
  GitHub гасит `schedule` в публичном репо после 60 дней без активности —
  поэтому `uptime-heartbeat.timer` раз в месяц дописывает
  `maintainer/uptime-heartbeat.txt`. Второй контур healthchecks.io:
  `deadman-ping.sh` + таймер, ping-URL в `/etc/deadman-ping.url`.
- **TLS:** один wildcard `*.esmien.ru` (плюс apex), выпущенный через **DNS-01 Cloudflare** (`esmien-wildcard`, токен `/root/.secrets/cf.ini` 0600, плагин `certbot-dns-cloudflare`, хук продления перезагружает nginx). Новый поддомен = DNS-запись + vhost, certbot больше не запускается, квота Let's Encrypt больше не упирается. Старая зона `qd.je` **выведена из эксплуатации**: её DNS-провайдер перестал отвечать, vhost'ы и сертификаты удалены — не возвращай их в `legacy_hosts` и не чини их certbot'ом. Упор в квоту был нормой для неё, самописные ретрай-таймеры не ставить (решение владельца): выпуском занимается только `certbot.timer`.

## Проверка

`install.py check` печатает контейнеры/health, число таблиц, локальные HTTP,
https-коды доменов и число активных таймеров, ничего не меняя.
Второй прогон `--yes` должен показывать «стек уже актуален / .env без изменений»
и укладываться в ~15 с; если он что-то «синхронизирует» — расхождение
репозитория и хоста.

**Проверка `--from-bot` без трафика в Telegram** — `scripts/mock-botapi.py`:
поднимается локальный Bot API (`sendDocument`/`getFile`/`getUpdates`), и тест
проходит весь путь «загрузка → реестр → скачивание → склейка → sha256», включая
отказ на части >20 МБ, не отправляя ни одного файла владельцу. Обязательные
кейсы: путь через реестр, fallback `getUpdates`, guard 20 МБ, заглушка токена.
Живой drill (настоящий Telegram) — отдельно и по разрешению: либо `--infra-dir /tmp/<name>`,
либо полноценный прогон на отдельной виртуалке (см. «Прогон восстановления на чистой машине»).

## Авто-коммит и пуш (копия логики hermes-state)

Репозиторий обновляется сам по факту правки, без таймера:

| item | path |
|---|---|
| watcher | `maintainer/vps-infra-watch.sh` → `/usr/local/bin/`, unit `vps-infra-watch.service` |
| one-shot | `maintainer/vps-infra-push.sh` → `/usr/local/bin/`, unit `vps-infra-push.service` |
| sync хоста → assets | `maintainer/sync_assets.py` (без `.env`, тестов, `__pycache__`, `_state_snapshot`, `out`) |
| lock / лог | `/var/lib/vps-infra-autopush/push.lock`, `/var/log/vps-infra-autopush.log` |

Перед коммитом push-скрипт **валидирует** дерево (`py_compile install.py`,
`bash -n bootstrap.sh`, `docker compose config -q` на фиктивных секретах) и
сканирует на секреты — при находке коммит отменяется. Коммит — только при
реальных изменениях; push с catch-up и алертом в TG (троттлинг 30 мин).

- Правка `maintainer/*.sh|service` в репо не действует, пока не сделан
  `install -m 755 … /usr/local/bin/` + `systemctl daemon-reload` (сами себя
  скрипты не копируют).
- После установки — `systemctl enable --now vps-infra-watch`; старт сервиса
  делает догоняющий пуш.
- Быстрый тест без 90-секундного дебаунса:
  `QUIET=5 WATCH_LOG=/tmp/w.log /usr/local/bin/vps-infra-watch.sh &`, затем
  тронуть любой файл, подождать ~10 с и проверить `git -C /root/vps-infra log`.
- Синхронизация идёт только host → repo. Обратно (repo → живой стек) —
  только через `install.py`; не путать.
- Манифест синхронизации — сами файлы в `assets/host/{bin,systemd}` и
  `assets/host/open-terminal-config`. Новый скрипт/юнит появляется в репо
  только после того, как его туда положили; удалённый с хоста файл из репо
  не исчезает (удаления не пропагируются сознательно).
- **Таймер без своего `.service` не стартует:** `systemd` пишет `Refusing to
  start, unit X.service to trigger not loaded`, а `enable --now` при этом молча
  падает (`check=False`). `step_units` теперь сам добавляет `<name>.service`
  для каждого таймера, если такой файл есть в `assets/host/systemd/`. Симптом
  после добавления таймера в `CORE_TIMERS`: `is-enabled` = enabled,
  `is-active` = inactive.

## Подводные камни (самые дорогие)

- **Маска токена не должна вернуться в `.env`.** `save_config()` пишет в
  `install.json` заглушку `__stored_in_notifications_env__`, а `prompt()` брал
  значение из cfg раньше, чем из `notifications/.env` — прогон `--yes` записал
  заглушку как `BOT_TOKEN`/`FILE_BOT_TOKEN` и убил оба бота до повторного
  выпуска токенов в BotFather. Исправлено; симптом для диагностики — `Telegram
  API HTTP 404`, а длина значения в `.env` (~31 символ) не похожа на токен.
- **`notifications/.env` обязан быть `0640 root:ai_service`.** `write_file` без
  `chown` оставил `root:root`, и `postgres-backup-notify.service`
  (`User=ai_service`) падал с `PermissionError`, при этом таймер «успешно» шёл.
- **Правки `assets/` затираются `sync_assets.py`** (host → repo): пока
  `vps-infra-watch.service` активен, изменённый `assets/notifications/monitor.py`
  вернётся к живому файлу через ~90 с. Правь репозиторий при остановленном
  watcher'е и деплой живые копии до пуша.
- **`/etc/vps-infra/install.json` помнит прошлый `--infra-dir`.** Тестовый прогон оставляет там
  путь вида `/tmp/drill-bot`, и следующий запуск без `--infra-dir` читает `.env` из пустого
  каталога: `preflight` видит пустое окружение, шаблон падает с «в шаблоне не заполнены: […]».
  Перед любым прогоном сверять `infra_dir` в этом файле с `/home/ai_service/ai-stack`.
- **Ключ, которого нет в шаблоне, при восстановлении исчезает молча.** `step_secrets` рендерит
  `.env` из `assets/templates/ai.env.tmpl`, поэтому любой ключ живого `.env` вне шаблона теряется
  (так пропадали `ENABLE_DIRECT_INTEGRATIONS` и `OPEN_TERMINAL_SANDBOX_API_KEY` — ломалась
  песочница в WebUI). Перед прогоном: рендер шаблона значениями живого `.env` и сверка набора
  ключей — расхождений быть не должно.
- **Бэкап `.env` внутри синхронизируемого дерева = секрет в репозитории.**
  `sync_assets.py` исключает ровно имя `.env`, поэтому копия вида
  `.env.bak-<повод>` фильтр проезжает и уезжает в `assets/stack/`. Дальше
  `vps-infra-push.sh` сканирует дерево и обрывает процесс с «secret-like
  string(s) in repo» — пуш не проходит (скан идёт ДО `git add`, так что в
  историю ничего не попадает), но файл с ключами уже лежит в рабочей копии.
  Правило: бэкапы секретов держать ВНЕ синхронизируемых каталогов
  (`/root/private-backups/`, 600), а исключение расширить до «всё, что
  начинается на `.env`, кроме `.env.example`». Заодно: `.env.bak-*`, созданный
  рядом с `.env` при правке через скрипт, наследует его права не всегда —
  бэкап с `644` читаем всем пользователям системы.
- **`curl | bash` забирает stdin:** bootstrap делает `exec </dev/tty` последней
  командой, иначе вопросы install.py получают EOF. Проверять tty надо в
  субшелле `( exec 3</dev/tty )`, иначе падает при запуске без терминала.

Полный список (бинарно-безопасный `write_file`, `ai/.env` и `WEBUI_URL`,
пропуск `pg_dump` < 1 ч, `--only fetch` без `--infra-dir` и `GITHUB_KEY`,
`inotifywait` на каталоге, числа проверенного drill, перезапись набора ключей
в `ai/.env`) — [references/installer-pitfalls.md](references/installer-pitfalls.md).
Читай его перед запуском на живом сервере, изменением синхронизации или
восстановлением.
