# Подводные камни установщика

Детали к правилам и «дорогим» граблям из `SKILL.md`. Всё проверено на этом
хосте при сборке установщика; числа и симптомы — из реальных прогонов.

## stdin и запуск

- `curl | bash` забирает stdin: bootstrap делает `exec </dev/tty` последней
  командой, иначе вопросы `install.py` получают EOF и установка молча идёт по
  дефолтам.
- Открытие tty надо проверять в субшелле — `( exec 3</dev/tty )`, — а не
  напрямую: без терминала (CI, cron, ssh без `-t`) прямой тест валит скрипт.
- Аргументы пробрасываются через `bash -s -- …`; `bootstrap.sh` клонирует в
  `/opt/vps-infra` и делает `exec python3 install.py`.

## Файлы, секреты, права

- `write_file` обязан быть бинарно-безопасным: в `assets/stack/webui-branding`
  лежат PNG, текстовый режим валит синхронизацию (повреждённые файлы уезжают
  в репо).
- **Креды не вписывать в URL строкой вида `x-access-token:<TOKEN>@host`.** Такая
  строка при записи файла попадает под маскировку секретов и превращается в
  обрубок (`x-access-token:${GITH.../}`): файл остаётся валидным для `bash -n`,
  а на чистой машине клон падает с `bad substitution`. Авторизация — заголовком
  `git -c http.extraheader="Authorization: Basic $(printf '%s' "x-access-token:$TOKEN" | base64 -w0)"`;
  проверять фрагмент **исполнением** с подставным токеном, а не только `bash -n`.
- **Маска токена не должна возвращаться в `.env`.** `save_config()` пишет в
  `install.json` заглушку `__stored_in_notifications_env__`, а `prompt()` брал
  значение из cfg раньше, чем из `notifications/.env` — прогон `--yes` записал
  заглушку как `BOT_TOKEN`/`FILE_BOT_TOKEN` и убил оба бота до повторного
  выпуска токенов в BotFather. Исправлено: `load_config()` чистит маску,
  `prompt()` по умолчанию берёт `.env`, `step_secrets` заглушку не пишет.
  Симптом для диагностики: в журнале юнита `Telegram API HTTP 404`, а длина
  значения в `.env` (~31 символ) не похожа на токен (`<digits>:<35 chars>`).
- **`notifications/.env` обязан быть `0640 root:ai_service`.** `write_file` без
  `chown` оставил `root:root`, и юнит `postgres-backup-notify.service`
  (`User=ai_service`) падал с `PermissionError` — при этом таймер «успешно»
  шёл. Проверка: `systemctl status postgres-backup-notify` и
  `journalctl -u postgres-backup-notify --since -3d`.
- **Прогон `install.py` перезаписывает `ai/.env` своим набором ключей:**
  старые ключи (`DOMAIN`, `POSTGRES_ADMIN_PASSWORD`, `BOT_DB_PASSWORD`)
  исчезают, новые (`WEBUI_URL`, `LITELLM_REDIS_PASSWORD`, `GITHUB_KEY`)
  появляются. Перед прогоном на живом сервере убедись, что рядом лежит снапшот
  `.env` (`backups/env.bak-<ts>`): только сравнив с ним, потом докажешь, какой
  ключ ротировался, а какой нет. Сравнение — без вывода значений в чат.
- Compose читает `ai/.env`; `WEBUI_URL` теперь оттуда, домен в compose не
  хардкодить.

## Токены и доступ к репозиториям

- Репозитории `Esmien/vps-infra` и `Esmien/hermes-state` публичные: клон идёт по
  обычному https, реестр `file_id` берётся из
  `https://raw.githubusercontent.com/Esmien/hermes-state/main/host/backups/tg-registry.json`.
  Токен для прогона не нужен; он остаётся для пуша и для приватных форков.
- Порядок получения реестра: `--tg-registry` → локальный
  `backups/postgres/.tg-registry.json` → raw.githubusercontent → GitHub API с
  токеном. API — последним: у него лимит 60 запросов/час на IP.
- Имена-синонимы принимаются на входе: `GITHUB_KEY` = `GITHUB_TOKEN`,
  `FILE_BOT_TOKEN` = `TG_FILE_TOKEN`. Установщик ждёт вторую пару, bootstrap-файл
  отдаёт первую — расхождение уже стоило одного пустого прогона.
- Fine-grained токен, выданный только на `vps-infra`, на чужой репозиторий
  отвечает **404, а не 403**. Если репозиторий когда-нибудь закроют, симптом
  будет тот же: реестр «недоступен», fallback `getUpdates` пуст (Telegram не
  отдаёт сообщения старше 24 ч), прогон падает с «в боте не нашлось дампов».
- Проверка стартовых секретов ругается один раз и по всему списку: печатает все
  отсутствующие переменные и то, какие ключи в файле фактически есть — иначе
  владелец правит файл по одной строке за прогон.

## Проверки и compose

- Тестовый `pg_dump` при каждом запуске не гонять: если свежий дамп < 1 ч —
  пропуск.
- `docker compose config -q` — дешёвая проверка интерполяции перед `up -d`
  (на фиктивных секретах, не на живых).
- Повторный `--yes` должен укладываться в ~15 с и не «синхронизировать» ничего;
  иначе расхождение репозитория и хоста, а не нормальный шум.

## Синхронизация host → repo

- **Правки `assets/` в репозитории затираются `sync_assets.py`.** Пока
  `vps-infra-watch.service` активен, изменённый `assets/notifications/monitor.py`
  или `assets/host/bin/*.sh` вернётся к живому файлу через ~90 с. Правь
  репозиторий при остановленном watcher'е и деплой живые копии до пуша.
- **`inotifywait` падает с rc=1 на несуществующем пути.** Добавление
  `.tg-registry.json` в WATCH до его создания оставило watcher в вечном retry
  и пропустило событие создания — реестр не уехал в снапшот. Следить надо за
  **каталогом** `backups/postgres`, исключив `\.dump$|\.dump\.part_|backup\.log$`.
- Удаления не пропагируются сознательно: файл, удалённый с хоста, остаётся в
  репо. Новый скрипт/юнит появляется в репо только после того, как его туда
  положили.
- Правка `maintainer/*.sh|service` в репо не действует, пока нет
  `install -m 755 … /usr/local/bin/` + `systemctl daemon-reload`.

## Реестр бэкапов и `--only fetch`

- **`--only fetch` без `--infra-dir`** читает `GITHUB_KEY` из
  `$INFRA_DIR/ai/.env` каталога-цели (пусто) — нужен fallback на штатный
  `/home/ai_service/ai-stack/ai/.env`, иначе реестр не находится и уходим в
  `getUpdates` с пустым результатом. Добавлен в `load_config()`.
- Реестр — `backups/postgres/.tg-registry.json` (3 набора на базу), в
  hermes-state уезжает как `host/backups/tg-registry.json`.
- Части обязаны быть ≤18 МБ (`TG_DOC_LIMIT`): `getFile` отдаёт не более 20 МБ.

## Проверенный drill (числа)

`monitor.py backup` → 7 частей по 16.2 MiB (`webui_db`, 113 MB) + 2 по 14.3 MiB
(`litellm_db`, 28.5 MB); реестр уехал в hermes-state; `install.py --only fetch
--from-bot` скачал 9 частей за 18 с, sha256 совпал с живыми дампами байт в байт,
`pg_restore --list` читает архив.

Повторять drill только в `--infra-dir /tmp/<name>`, а не в живом каталоге
стека. Без трафика в Telegram — `scripts/mock-botapi.py` (локальный Bot API;
кейсы: путь через реестр, fallback `getUpdates`, guard 20 МБ, заглушка токена).
