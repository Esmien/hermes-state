---
name: vps-infra-installer
description: "Use when deploying or migrating this VPS from scratch."
version: 1.3.0
author: VPS Admin
license: MIT
platforms: [linux]
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

Репозиторий: `github.com/Esmien/vps-infra` (**публичный**, секретов внутри нет).
План перевода установщика на модули-профили (`core` / `agent` / `full`) и карта зависимостей
стека — `~/.hermes/tasks/docs/modules-plan.md` (документы задач живут в харнессе; в `vps-infra/docs/`
остаются только доки про саму инфраструктуру); в нём же открытые вопросы, которые решает владелец, а не агент.
Доступ к обоим репозиториям (токен не нужен), публичная копия `bootstrap.sh` и рабочие копии
на хосте — [references/bootstrap-flow.md](references/bootstrap-flow.md).

**VPN-вход в установщик не входит и входить не должен.** VLESS/WS+TLS, `vpn-router`, подписки —
самостоятельный проект `Esmien/vpn-service` (skill `vpn-entry-stack`). После переустановки сервера
`curl | bash` поднимает только AI-стек: туннель возвращается отдельным `deploy.sh`. Не обещать
владельцу «одна команда восстанавливает всё» — это две команды и два репозитория.

## Граница: харнесс или инфра

Перед тем как что-то создать, решить, где оно живёт — это правило владельца, а не вкусовщина:

- **Харнесс** (`~/.hermes`, бэкап в `Esmien/hermes-state`) — описания задач, планы, концепты,
  инструкции, скиллы, память. Это состояние агента.
- **Инфра** (`vps-infra` + `/etc` + `/usr/local/bin` + systemd) — скрипты, демоны, юниты,
  env-файлы с секретами, рантайм в `/var/lib/<name>`. Это разворачиваемое на новой машине.

Две проверки, которые решают спор за одну секунду: «переживёт ли это переустановку харнесса?» →
инфра; «это нужно агенту, чтобы понимать, как идёт работа?» → харнесс. Работающее, но лежащее в
`~/.hermes` — это и есть искомая «утечка ответственности».

Куда класть файл при переносе и как потом вычищать старый путь —
[references/migration.md](references/migration.md).

## One-liner

**Владелец требует одну команду и уход** — любая инструкция развёртывания подаётся как один вызов, без ручных шагов между.

Full text → [references/one-liner.md](references/one-liner.md)

## Выбор флагов: TUI-чек-лист (`FlagMenu`)

Запуск без аргументов даёт не анкету вопросов, а чек-лист флагов: ↑/↓/j/k — курсор, пробел —
галочка, Enter — подтверждение с готовой командой, `Y` — сохранить выбор в
`/etc/vps-infra/install-flags.json` и выполнить, `n`/Enter — назад (дефолт `n`), `q` — выход 130.
Строка списка — ровно «Описание (--флаг)». Меню только при пустом `argv`; пары
взаимоисключающих флагов гасят друг друга; `VPS_MENU_PRINT=1` — самопроверка без запуска.
Реализация (сырой `termios`, без curses) и проверка TUI pty-драйвером —
[references/cli-flag-menu.md](references/cli-flag-menu.md).

## Режимы

```bash
install.py                     # чек-лист флагов в TUI, затем обычный прогон
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
units → hardening → tls → verify → health → hermes → report`.

**Перед необязательным компонентом — два шага, не один.** `health` (контейнеры, HTTP,
`webui_db`/`litellm_db`, Redis) валит прогон, если критичный сервис молчит; затем вопрос
«Установить Hermes?» с дефолтом «да» (ответ «нет» → `/root/.hermes-skip`, позже
`--only hermes --hermes`). Детали — `references/installer-pitfalls.md`.

**Шага `postcheck` больше нет** (выпилен 2026-11-06 по решению владельца): одноразовый
`hermes-postcheck.timer` дублировал `verify`/`health`, срабатывал в самый холодный момент и
светил внутренности сервера всей группе. Проверка после установки — только `verify` + `health`,
разбор «как прошло» — по `REPORT.md` вручную. Не возвращать этот таймер без прямой просьбы.

`REPORT.md` в корне репо — единственный источник правды по чек-листу: владелец передаёт его
агенту фразой «проверь восстановление» (раздел 2) или «проверь бэкапы» (раздел 3). Оговорка в
нём обязательна: с `--skip-tls` нет nginx и сертификатов — такие пункты помечаются «шаг
пропущен», а не «плохо».

`--only`/`--skip` принимают имена шагов; неизвестное имя — ошибка.
`--skip preflight` вместе со `stack`/`secrets` разрешён и печатает, что
конфигурация берётся из уже существующих файлов.

**`hardening`** идёт до `tls` и ставит fail2ban + `python3-systemd`,
`/etc/fail2ban/jail.local` (sshd, `maxretry=4`/1ч, бан 1д, docker исключён из бана) и
`/etc/nginx/conf.d/zz-ratelimit.conf` (`llm_api` 10r/s, `webui_api` 8r/s). **8r/s при
`burst=30` мало для SPA** — на живом хосте поднято до `rate=20r/s` + `burst=120`; правя
`install.py`, поднимай и там, иначе переустановка вернёт баг. Проверка: `install.py check`
печатает `fail2ban: active` и `nginx rate-limit: да`. Детали —
[references/installer-pitfalls.md](references/installer-pitfalls.md).

## Сбор секретов и финальный отчёт

`bootstrap.env` не обязателен: нет файла → `INTERACTIVE=1`, токен файл-бота и пароль архива
спрашиваются через `/dev/tty`. Финальный шаг `report` (`--no-report`) шлёт архив `.env` боту
документом, ключ — отдельным сообщением; плейнтекст на диск не пишется. Детали —
[references/bootstrap-flow.md](references/bootstrap-flow.md).

## Правила, которые нельзя нарушать

1. **Секреты только в .env.** Внутренние ключи генерирует `install.py` (`token_hex(32)`),
   внешние спрашивает; существующие значения переиспользуются — повторный запуск не меняет
   пароли и не разлогинивает. `install.json` токенов не содержит. **Исключение —
   `UI_PASSWORD`** (пароль админа **LiteLLM**, не Open WebUI): после прогона проверять
   «отклонить» в `owui-signup-approver` (`signin failed: HTTP 400` = рассинхрон).
2. **БД восстанавливаются только в «пустые» базы** или с явным `--restore`. Пустота — **по
   данным, а не по схеме**: `migrate` идёт раньше и создаёт ~98 пустых таблиц. Считать строки
   в `"LiteLLM_VerificationToken"` (`litellm_db`) и `"user"` (`webui_db`), кавычки обязательны;
   дамп старше 72 ч требует `--force-stale`.
3. **`:latest`-образы не обновляются**, если уже есть локально. **Образ с `build:` в compose
   не тянется из реестра — только собирается** (`esmien/webui:local`,
   `esmien/open-terminal-arduino:local`); список — из `docker compose config --format json`.
4. **Установщик не знает ни о каких сервисах вне репозитория.** `extra_domain` опционален,
   порт 8000 не публикуется, health open-terminal — через `docker exec`.
5. Перед прогоном на живом сервере — `touch /var/lib/docker-autorecover/pause`,
   после проверки снять. Иначе детектор инцидентов поднимет агента.
6. `deploy.sh` из `/home/ai_service/ai-stack` исторический: не покрывает
   Hermes, бэкапы, мониторинг. Источник правды — этот репозиторий.
7. **Это recovery-артефакт для НОВОГО сервера, а не набор для раскатки на текущем.**
   Владелец ждёт правки в `/root/vps-infra`, а не деплой «сюда»; живое изменение — только
   после отдельного разрешения, с минимальным диффом и одной фразой объяснения.

Полные формулировки всех семи правил — [references/installer-pitfalls.md](references/installer-pitfalls.md)
→ «Правила, которые нельзя нарушать».

## Переезд

Хост сначала проверяется, потом оплачивается (домен, AS/префикс, выделенный IPv4, серверный ISO,
первый вход) — [references/host-provider-vetting.md](references/host-provider-vetting.md).
Дальше одна команда с `bootstrap.env`: `fetch` тянет последний набор дампов из файл-бота,
`--hermes --restore-hermes` разворачивает состояние из `Esmien/hermes-state`,
`--secrets-from-bot --secrets-key …` раскладывает четыре `.env`. Fallback — `export --with-data` →
`--bundle <path> --restore`. DNS доменов → IP нового сервера **до** шага TLS. Порядок и механика
бэкапа через бота — [references/migration.md](references/migration.md).

Прогон на чистой машине (Multipass, без TLS, на тестовых токенах) —
[references/restore-drill-entry.md](references/restore-drill-entry.md), команды и грабли —
[references/restore-drill.md](references/restore-drill.md).

## Проверка

**Любую правку установщика проверять на самом чистом доступном субстрате** — контейнер той же
Ubuntu для apt/пакетов/ключей, Multipass для полного прогона; «должно работать» не принимается,
а прогон, который лечили руками, не считается проверенным. Дисциплина проверки —
[references/restore-drill.md](references/restore-drill.md).

`install.py check` печатает контейнеры/health, число таблиц, локальные HTTP, https-коды доменов
и число активных таймеров, ничего не меняя. Полный чек-лист приёмки (TLS, уведомления,
свежесть и восстановимость копий, периметр, Hermes) — **`REPORT.md`**, раздел 1. Второй прогон
`--yes` должен показывать «стек уже актуален / .env без изменений» и укладываться в ~15 с; если
он что-то «синхронизирует» — расхождение репозитория и хоста.

**Проверка `--from-bot` без трафика в Telegram** — `scripts/mock-botapi.py` (локальный Bot API;
обязательные кейсы: путь через реестр, fallback `getUpdates`, guard 20 МБ, заглушка токена).
Живой drill — отдельно и по разрешению: либо `--infra-dir /tmp/<name>`, либо прогон на отдельной
виртуалке.

## Эксплуатация: синхронизация, мониторинг, бэкапы

Что установщик оставляет после себя и как это живёт дальше (sync с репо, мониторинг, бэкапы).

Full text → [references/operations.md](references/operations.md)

## Подводные камни

Самые дорогие грабли — с симптомами и правилом починки — в
[references/installer-pitfalls.md](references/installer-pitfalls.md) (маска токена в `.env`,
права `notifications/.env`, затирание `assets/`, `psql`-обёртка `pg_wrapper`, хуки `config.yaml`,
демо-скиллы Hermes, `/dev/tty` двумя `open()` и остальное).

**Читать перед запуском на живом сервере, изменением синхронизации или восстановлением.**
Пакеты, apt-ключи и зонды на чистой машине — [references/apt-and-fresh-host.md](references/apt-and-fresh-host.md).
