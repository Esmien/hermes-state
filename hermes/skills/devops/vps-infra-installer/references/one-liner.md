# One-liner

**Владелец требует одну команду и уход.** Любая инструкция развёртывания подаётся как один
copy-paste блок; многошаговые «сначала склонируй, потом запусти с флагами» он отвергает
(«инструкция разворачивания ГОВНО»). Всё, что можно автоматизировать, автоматизируется в
`bootstrap.sh`, а не переносится в чат.

```bash
curl -fsSL https://raw.githubusercontent.com/Esmien/vps-bootstrap/main/bootstrap.sh | sudo bash
```

**Холодный полный прогон — ≈60 минут**, повторный `--yes` на живом стеке — ~15 с; отвечать
диапазоном с указанием, что входит (TLS, дампы, webui_data). Цифры брать из прогона
(`duration_sec` в `/var/lib/vps-infra/state.json`, метки времени в
`/var/log/vps-infra-install.log`), а не из памяти.

До запуска на машине лежит файл стартовых секретов (`/root/bootstrap.env`, иначе
`/tmp/bootstrap.env` или `./bootstrap.env`; путь можно задать `VPS_BOOTSTRAP_ENV`):

```
GITHUB_TOKEN=ghp_...        # НЕОБЯЗАТЕЛЕН: репозитории публичные, клон и реестр идут без токена
SECRETS_KEY=<пароль архива .env>
TG_FILE_TOKEN=123:AA...     # РЕАЛЬНЫЙ файл-бот: из него тянутся секреты и дампы
# необязательно:
BOT_TOKEN=... FILE_BOT_TOKEN=... HERMES_BOT_TOKEN=... WEBUI_URL=... EXTRA_ARGS="--skip tls"
```

Проверка стартовых секретов ругается **один раз и по всему списку** (все отсутствующие
переменные + какие ключи фактически есть); синонимы: `GITHUB_KEY`=`GITHUB_TOKEN`,
`FILE_BOT_TOKEN`=`TG_FILE_TOKEN`.

`bootstrap.sh` ставит git/curl/python3/openssl → клонирует репозиторий и вычищает токен из
`.git/config` → кладёт пароль архива в `/root/.secrets/offsite.key` (600) → запускает `install.py`
с готовым набором флагов. **stdout установщика через `tee` не прогонять:** труба лишает его tty,
и живой блок прогресса молча превращается в плоский поток строк. TLS по умолчанию пропускается
(`WITH_TLS=1` включает nginx/certbot, `BOOTSTRAP_DRY=1` — `--dry-run`). Флаги, логи и формат
ответа при падениях — [references/bootstrap-flow.md](references/bootstrap-flow.md).

**Прогресс — не поток строк:** под заголовком шага живёт блок последних 15–20 строк, заголовки
пройденных шагов остаются в истории (класс `Pane`, `NO_PANE=1` отключает). Арифметика курсора,
перехват вывода дочерних процессов и проверка отрисовки —
[references/installer-output-pane.md](references/installer-output-pane.md); правку панели без
такой проверки не считать сделанной.

**Канон `bootstrap.sh` — приватный `vps-infra`, публичная копия только для curl**; рассинхрон
ловит `maintainer/publish_bootstrap.py` (`--check` — exit 1). Публикацию проверять через GitHub
API, не через `raw.githubusercontent.com` (raw отдаёт CDN-копию до ~5 минут) —
[references/bootstrap-flow.md](references/bootstrap-flow.md).

`stdin` при `curl | bash` — это труба: скрипт делает `exec </dev/tty`, иначе вопросы
`install.py` получат EOF. Для Hermes установщик вызывается с `--non-interactive`, когда
терминала нет (`HERMES_INSTALL_ARGS` переопределяет).
