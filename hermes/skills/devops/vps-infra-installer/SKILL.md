---
name: vps-infra-installer
description: "Use when deploying or migrating this VPS from scratch."
version: 1.0.0
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
Рабочая копия на этом сервере: `/root/vps-infra`.

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
install.py check               # read-only проверка живого стека
install.py export --with-data  # → /var/lib/vps-infra/vps-infra-bundle-*.tar.gz
install.py --bundle <path|url> --restore   # восстановление БД + webui_data
install.py --skip tls,restore --only verify
```

Шаги идут в порядке `preflight → … → hermes`, каждый идемпотентен.

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
4. **Домен `bot.esmien.qd.je` — это lyria (бот с музыкой), не open-terminal.**
   Порт 8000 на хосте занят `lyria-bot`. open-terminal не публикует порт;
   health проверяется `docker exec open-terminal curl …/health`. Третий домен
   опционален (`extra_domain`), по умолчанию пуст.
5. Перед прогоном на живом сервере — `touch /var/lib/docker-autorecover/pause`,
   после проверки снять. Иначе детектор инцидентов поднимет агента.
6. `deploy.sh` из `/home/ai_service/ai-stack` исторический: не покрывает
   Hermes, бэкапы, мониторинг. Источник правды — этот репозиторий.

## Переезд (проверенный порядок)

1. Одной командой: `bootstrap.sh | bash -s -- --from-bot --restore --hermes --restore-hermes`.
   `fetch` берёт последний набор дампов из файл-бота (реестр `file_id` → части →
   склейка → sha256), `hermes` + `--restore-hermes` разворачивает состояние из
   `Esmien/hermes-state` (config/SOUL/memories/skills/cron, `/usr/local/bin`,
   юниты, `/etc`, runbooks). Секреты не восстанавливаются — спрашиваются заново.
2. Ручной путь (fallback): `install.py export --with-data` → перенос →
   `--bundle <path> --restore`.
3. DNS доменов → IP нового сервера **до** шага TLS, иначе certbot пропустит
   домен (оставит HTTP-vhost) — это не ошибка.
4. Первого админа Open WebUI на пустой БД создают через форму регистрации;
   на восстановленной БД пользователи уже есть.

### Бэкап БД через бота: как устроено и где ломается

- Бот **не читает свою историю чата**, поэтому единственная зацепка для
  восстановления — `file_id`, который вернул `sendDocument`. `monitor.py backup`
  пишет его в `backups/postgres/.tg-registry.json` (3 набора на базу), реестр
  уезжает в `hermes-state` как `host/backups/tg-registry.json`.
- Части дампа обязаны быть **≤18 МБ**: `getFile` отдаёт не более 20 МБ, части по
  45 МБ из чата уже не скачать (`TG_DOC_LIMIT` в `monitor.py`).
- Нет реестра — fallback `getUpdates`: переслать файлы бэкапа самому боту.
- `--from-bot` игнорирует проверку «дамп старше 72 ч» (источник выбран осознанно).
- Токен проверяется на форму `123456:AA…`: заглушка из `install.json`
  (`__stored_in_notifications_env__`) даёт понятную ошибку, а не 404 от Telegram.

## Проверка

`install.py check` печатает контейнеры/health, число таблиц, локальные HTTP,
https-коды доменов и число активных таймеров, ничего не меняя.
Второй прогон `--yes` должен показывать «стек уже актуален / .env без изменений»
и укладываться в ~15 с; если он что-то «синхронизирует» — расхождение
репозитория и хоста.

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

## Подводные камни, найденные при сборке

- `curl | bash` забирает stdin: bootstrap делает `exec </dev/tty` последней
  командой (иначе вопросы install.py получают EOF). Проверять открытие tty
  надо в субшелле `( exec 3</dev/tty )`, иначе падает при запуске без терминала.
- `write_file` обязан быть бинарно-безопасным: в `assets/stack/webui-branding`
  лежат PNG, текстовый режим валит синхронизацию.
- Compose читает `ai/.env`; `WEBUI_URL` теперь оттуда, домен в compose не хардкодить.
- Тестовый `pg_dump` при каждом запуске не гонять: если свежий дамп < 1 ч — пропуск.
- `docker compose config -q` — дешёвая проверка интерполяции перед `up -d`.
- **Маска токена не должна возвращаться в `.env`.** `save_config()` пишет в
  `install.json` заглушку `__stored_in_notifications_env__`, а `prompt()` брал
  значение из cfg раньше, чем из `notifications/.env` — прогон `--yes` 2026-10-24
  записал заглушку как BOT_TOKEN/FILE_BOT_TOKEN и убил оба бота до повторного
  выпуска токенов в BotFather. Исправлено: `load_config()` чистит маску, `prompt`
  по умолчанию берёт `.env`, `step_secrets` не пишет заглушку.
- **`notifications/.env` обязан быть `0640 root:ai_service`.** `write_file` без
  `chown` оставил `root:root`, и юнит `postgres-backup-notify.service`
  (User=ai_service) падал с `PermissionError` — при этом таймер «успешно» шёл.
  Проверка: `systemctl status postgres-backup-notify` и
  `journalctl -u postgres-backup-notify --since -3d`.
- **Правки `assets/` в репозитории затираются `sync_assets.py`** (host → repo):
  пока `vps-infra-watch.service` активен, изменённый `assets/notifications/monitor.py`
  или `assets/host/bin/*.sh` вернётся к живому файлу через ~90 с. Правьте репозиторий
  при остановленном watcher'е и деплойте живые копии до пуша.
- **Прогон `install.py` перезаписывает `ai/.env` своим набором ключей:**
  старые ключи (`DOMAIN`, `POSTGRES_ADMIN_PASSWORD`, `BOT_DB_PASSWORD`)
  исчезают, новые (`WEBUI_URL`, `LITELLM_REDIS_PASSWORD`, `GITHUB_KEY`)
  появляются. Перед прогоном на живом сервере убедись, что рядом лежит
  снапшот `.env` (`backups/env.bak-<ts>`) — только сравнив с ним, потом
  докажешь, какой ключ ротировался и какой нет.
