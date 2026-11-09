# Sandboxed terminal for Open WebUI users

> **LEGACY (2026-11-09).** Общая песочница `open-terminal-sandbox` удалена по указанию владельца: контейнер, образ `esmien/open-terminal-arduino:local`, тома `ai_ot_sandbox_*`, каталог `sandbox_files`, утилита `sandbox-inbox`, блок в compose, исходники `ai/arduino-sandbox/`, соединение в WebUI и ключ в `.env`. Схема заменена на «контейнер на пользователя». Файл оставлен как история решений и грабель (cap_setgid, `.arduino15`, hardlink EXDEV, TMPDIR/noexec) — не восстанавливать по нему ту схему.

## Текущая схема: песочница на пользователя

| Что | Где |
|---|---|
| шаблон контейнера | `ai-stack/ai/sandbox-users/template.compose.yml` (в `vps-infra/assets/stack/…` через auto-sync) |
| provisioner | `/usr/local/bin/sandbox-provisioner.py` + `sandbox-provisioner.{service,timer}` (раз в минуту) |
| состояние и ключи | `/home/ai_service/sandbox-users/state.json` (0600, в git не идёт) |
| рабочие каталоги | `/home/ai_service/sandbox/users/<slug>` (uid 1000, 0700) |
| контейнеры | `ot-u-<slug>`, compose-проект `sb-<slug>` |
| соединения | по одному на пользователя в `terminal_server.connections`, имя `Песочница · <часть email до @>`, грант только ему, `chat_uploads: filesystem` |

Лимиты по умолчанию: 1.5 ГБ памяти + 0.5 ГБ свопа (`memswap_limit 2g`), 1 CPU, 256 процессов, `read_only`, `cap_drop ALL` + `SETGID`, не-root `1000:1000`. Квота каталога 2 ГБ (LRU по mtime), исключены `~/.local`, `~/bin`, `~/venv`, `~/.arduino15`, `~/Arduino`. Файлы удалённого пользователя живут 3 дня.

Операции:

- **Картинки из Image Generator** (`litellm_image_reference_generator_hy_image_3_5`, workspace-tool в БД) пишутся в `generated_images/` того пользователя, который вызвал тул: тул получает `/sandbox-users` (rw) и `/sandbox-state/state.json` (ro) из чего-то в compose, ищет свой каталог по user id/email, после записи делает chown 1000:1000. Если юзера нет в `state.json` (админ, аноним) — падает на старый `/app/backend/data/generated_images`. Исходник тула в репо: `ai/webui-tools/litellm_image_reference_generator.py`; правится он в БД `tool.content`, правку сразу дублировать в файл.

```bash
/usr/local/bin/sandbox-provisioner.py --dry-run        # что скрипт собирается сделать
/usr/local/bin/sandbox-provisioner.py --only <email>    # один пользователь
journalctl -u sandbox-provisioner.service -n 30 --no-pager
```

- **Изменить лимит одному** — править его запись в `state.json` (`mem`, `memswap`, `cpus`), следующий прогон пересоздаст контейнер.
- **Обновить образ всем** — править дайджест в шаблоне, затем `docker compose -p sb-<slug> up -d` для каждого (или дождаться прогона: `up -d` сам пересоздаст при смене образа).
- **Проверка живой песочницы** — IP из `docker inspect ot-u-<slug>`, ключ из `state.json`, дальше `curl -H "Authorization: Bearer <key>" http://<ip>:8000/files/cwd` (ожидается `cwd=/home/user/workspace`, `root.path=/home/user`).
- **Правка шаблона доезжает всем сама.** Provisioner каждый прогон делает `up -d`; compose пересоздаёт контейнер только при реальном изменении конфига, поэтому прогон без правок печатает «изменений: 0». `--force-recreate` не добавлять: он перезапускал бы всех раз в минуту и рвал живые сессии.
- **Добавить системный пакет всем** — только через пересборку образа; внутрь контейнера root не даётся.

Грабли этой схемы:
- **Выбор терминала — только клиентский.** В 0.13.x `terminal_id` не пишется в БД (у чатов такого поля нет); фронт берёт его из `localStorage.selectedTerminalId` и шлёт в каждом запросе. Серверной настройки «терминал по умолчанию» нет. Решение у нас: `webui-branding/terminal-autoselect.js` (вставляется в `index.html` в Dockerfile) — если выбора нет и у пользователя ровно одна песочница, ставит её id и один раз перезагружает страницу. Проверка: `localStorage.selectedTerminalId` совпадает с `conn_id` из `state.json` — этого достаточно, фронт сам кладёт его в `terminal_id`.
- **Инжектированный на загрузку скрипт не видит токен: вход в SPA страницу не перезагружает.** Логин происходит внутри приложения, `localStorage.token` появляется позже, поэтому одноразовый код в `<head>` молча выходит и больше не зовётся. Такой скрипт обязан опрашивать появление токена (раз в ~1.5 с, до ~30 с) и срабатывать уже после входа; флаг «уже пытались» привязывать к отпечатку токена, а не к браузеру, иначе после перелогина логика не пересчитается. Признак, что скрипт вообще не отработал — нет его флага в `localStorage`.
- **Не выпускать JWT для проверки авторизации.** `create_token({'id': uid})` без `expires_delta` даёт токен без `exp` → 401 «Invalid token», а сервер не принимает и токен с `exp` (сессионная валидация). Проверять фронтовую логику без пароля и без LLM так: в открытой странице подменить `window.fetch` (вернуть фейковый `Response` со списком из одного терминала), положить в `localStorage.token` любую заглушку — скрипт сходит «в API», запишет `selectedTerminalId` и перезагрузится. Это проверяет весь путь: опрос токена, выбор, перезагрузка.
- **Malloc-тюнинг нужен и персональным песочницам, не только рут-терминалу.** Тот же образ и тот же Python: арены растут от **числа потоков при конкурентных запросах**, один юзер с парой команд их не создаёт (проверено: 5–15 потоков → 0 арен). В шаблоне стоят `MALLOC_ARENA_MAX=2`, `PYTHONMALLOC=malloc`, `MALLOC_TRIM_THRESHOLD_`/`MALLOC_MMAP_THRESHOLD_=131072`; читаются загрузчиком на старте процесса, поэтому правка требует пересоздания (provisioner сам делает `up -d` после изменения шаблона). Разница с прошлой войной: потолок `mem_limit` 1.5 ГБ означает, что даже настоящая утечка убивает свою песочницу, а не хост и не рут-терминал. Перемерять арены — `references/memory-troubleshooting.md` §4.
- **«У юзера терминал не активен» — сначала смотреть роль, потом фронт.** `role='pending'` песочницу не получает по правилу, таймер её гасит: `journalctl -u sandbox-provisioner.service | grep <slug>` покажет «остановлена песочница <slug> (роль pending)». Автовыбор в этом случае ведёт себя правильно — соединений 0, выбора нет. Проверять `select role from "user" where email=…` до любых правок скрипта; после перевода в `user` контейнер поднимается в пределах минуты.
- **Генераторы кладут файл на диск сами — модель не декодирует base64.** Байты в аргументе тула идут токенами: mp3 на 3 МБ ≈ 3.9 МБ base64 ≈ ~1 млн токенов, то есть путь `echo '<b64>' | base64 -d` годится только для мелочи. Правильно — в туле: получить b64/URL от модели-генератора, декодировать на сервере, записать в каталог юзера (`generated_images/`, для аудио/видео — `generated_media/`) с `chown 1000:1000` и зарегистрировать файл в OWUI, тогда в чате он и играет, и скачивается по `/api/v1/files/<id>/content`. Так уже работает `LiteLLM Video Generator (HeyGen)` (пишет MP4 + регистрирует файл) и Image Ref Generator; для музыки (`google/lyria-3-pro-preview` есть в LiteLLM) тула пока нет — base64 остаётся блобом в сообщении.
- `sync_assets.py` для `/usr/local/bin` и `/etc/systemd/system` работает по манифесту: новый файл сам не появится в репо — его надо один раз положить в `assets/host/{bin,systemd}`.
- `TMPDIR` из compose в окружение команд `/execute` не доходит (`echo $TMPDIR` пусто), но `HOME=/workspace` доходит; `/tmp` в контейнере — tmpfs с `noexec`.
- `POST /execute` с `curl` работает, а сборка запроса в `urllib` без явного `method='POST'` может отдать 405 — проверять curl'ом, прежде чем искать баг в API.
- В каждом рабочем каталоге есть `generated_images/` (видимая, 0700) — модели обязаны складывать туда все сгенерированные картинки; правило прописано в системном промпте. `ensure_dir` вызывается на каждом прогоне, так что новые служебные папки докатываются до существующих юзеров без пересоздания.
- **Ссылки на файлы в чате не работают для не-картинок.** WebUI сам заливает в хранилище только изображения из вывода инструментов (`![Output Image](...)` → `/api/v1/files/<uuid>/content`); для `.md`/`.csv`/архивов такого механизма нет, а open-terminal не умеет отдавать байты вообще. Поэтому в промпте стоит правило «путь + панель Файлы».
- В базовом образе `ghcr.io/open-webui/open-terminal` маршрут `/` отдаёт 404 (у старого arduino-образа отдавал флаги); флаги смотреть в `/openapi.json`.
- **Защита пакетных каталогов от LRU — только для верхнего уровня.** Условие должно быть `cur == path and entry.name in PROTECTED`; первая версия проверяла `os.path.dirname(cur) == path` и тем самым лезла внутрь `~/.local` и `~/.arduino15`, удаляя пакеты и тулчейны (снесла установку esp32 на 1 ГБ и сам `arduino-cli`). При жалобах «пропали пакеты» — смотреть `journalctl -u sandbox-provisioner` на строки про квоту.
- **Docker compose интерполирует `$VAR` в `environment:`** — `$HOME` в системном промпте превращался в `/root` хоста. В тексте промпта писать `~/.tmp`, не `$HOME/...`.
- Файловый браузер ищет папку пользователя так: `GET /files/cwd` → `root.path` (там `/home/user`), а содержимое — `GET /files/list?directory=/home/user` (параметр именно `directory`, не `path`).
- Окружение команд `/execute` — белый список (`HOME`, `PATH`, `OPEN_TERMINAL_*`): `TMPDIR` и `ARDUINO_DIRECTORIES_DATA` из compose до команд не доходят. Поэтому `/tmp` (tmpfs, `noexec`) валит сборки — в промпте есть подсказка `export TMPDIR=~/.tmp`.
- Arduino в персональной песочнице: `arduino-cli` статическим бинарём в `~/bin`, данные — в `~/.arduino15` (исключён из квоты); `core install esp32:esp32` ≈ 7.4 ГБ. Для таких юзеров порог алерта поднимается полем `protected_alert_bytes` в `state.json`.

## Отдача файлов пользователю: HTTP-раздачи нет

`open-terminal` умеет только JSON-API: `/files/read`, `/files/list`, `/files/write`, `/files/grep`, `/files/glob`. `/files/display` возвращает `{"path":…,"exists":true}` — метаданные, не байты, и маршрута, отдающего содержимое файла, в `/openapi.json` нет вообще. Отсюда два поведения, которые владелец приносит как «баги»:

- **Markdown-ссылка `[имя](путь)` не открывает файл.** Относительный URL уходит в SPA, маршрута нет → открывается пустой чат. В системном промпте должно стоять правило: давать абсолютный путь и отправлять в панель «Файлы», ссылки не лепить. Файл виден только через панель (она ходит в `/files/*` JSON'ом).
- **«Терминал выключен → ФС недоступна» — норма.** ФС живёт в песочнице, и инструменты `write_file`/`read_file` приходят с терминал-сервера: нет соединения — нет ни файлов, ни инструментов. Второй ФС внутри WebUI мы сознательно не держим.

Кликабельные ссылки = отдельный сервис-раздатчик (nginx-локейшн + проверка cookie сессии OWUI + отдача из каталога юзера): новая поверхность атаки (обход путей, кросс-юзер доступ) и лишний компонент в бэкапах. **Владелец это предложение отклонил** («оставляем как есть») — не пере­предлагать без его новой инициативы; штатный путь остаётся «путь текстом + панель Файлы».

**Не grep'ать минифицированный `/app/build` OWUI ради UI-строк** — один широкий запрос вернул 160 КБ кода и мусора. Строки ищутся в бэкенде (`/app/backend/open_webui/**`, например `routers/terminals.py`) или через `openapi.json`; для фронта — узкий `grep -o` по конкретному чанку.

`open-terminal` (the main one) is effectively host root: `user: 0:0`, host `/` mounted at `/mnt/host`, `/var/run/docker.sock` passed through. Never grant it to anyone but the owner. The second instance, **`open-terminal-sandbox`**, exists so ordinary WebUI users get shell/file/Arduino tools without any of that.

## What the sandbox is

| item | value |
|---|---|
| service / container | `open-terminal-sandbox` (compose project `ai`) |
| image | `esmien/open-terminal-arduino:local`, built from `ai/arduino-sandbox/Dockerfile` on top of `ghcr.io/open-webui/open-terminal:latest` |
| user | `1000:1000` |
| workspace | named volume `ot_sandbox_workspace` → `/workspace` (cwd), `ot_sandbox_home` → `/home/user` |
| mounts from host | `:rw` только личный каталог `/home/ai_service/sandbox_files` → `/workspace/inbox` (владелец uid/gid 1000, mode 0700; ни `/`, ни socket) |
| attachments | файлы из чата кладёт сам WebUI в `/workspace` (`chat_uploads: filesystem`). Хост-утилита `sandbox-inbox` — для ручной раскладки владельцем: копия в `/home/ai_service/sandbox_files` (→ `/workspace/inbox`), `chown 1000:1000`, `0600`, uuid-префикс срезается, при совпадении имени — суффикс `.N`; печатает путь и sha256. `sandbox-inbox --list` / `--clear <имя>`. |
| hardening | `cap_drop: ALL`, `cap_add: SETGID`, `no-new-privileges`, `read_only: true`, `tmpfs /tmp`, `mem 2g/2g`, `cpus 1.0`, `pids_limit 256` |
| key | `OPEN_TERMINAL_SANDBOX_API_KEY` in `ai/.env` |
| tools | `arduino-cli` 1.5.1 + core `arduino:avr` 1.8.8 baked into the image |

Verified after build: `id` → uid 1000, `CapEff` → 0, `/etc` read-only, no `/var/run/docker.sock`, `/home/ai_service` absent, `arduino-cli compile --fqbn arduino:avr:uno` on a blink sketch → 924 bytes.

## Вложения чата попадают в терминал сами — `chat_uploads`

Open WebUI умеет класть файлы из чата прямо в cwd терминала, без хост-стороны и без перепечатки моделью. Выключатель — `config.chat_uploads` в записи соединения (`terminal_server.connections`), значения `default` (файл остаётся в OWUI, в терминал не попадает) и `filesystem` (фронт делает `POST <terminal>/files/upload?directory=<cwd>` и кладёт файл в `/workspace`).

У `Песочница · Arduino` включено (`filesystem`) через админ-API, без рестарта:

```
POST /api/v1/auths/signin                 {"email": <admin>, "password": OWUI_ADMIN_PASSWORD}
GET  /api/v1/configs/terminal_servers     -> {"TERMINAL_SERVER_CONNECTIONS": [...]}
POST /api/v1/configs/terminal_servers     {"TERMINAL_SERVER_CONNECTIONS": [... с правленым config]}
```

POST заменяет весь список — только read-modify-write, никогда не собирать массив с нуля. Проверка серверной части без браузера: `curl -H "Authorization: Bearer <key из config>" -F file=@x http://open-terminal-sandbox:8000/files/upload?directory=/workspace` → `{"path":"/workspace/x","size":N}`.

Следствие: модель получает не текст в промпте, а файл на диске — читать его надо терминалом (`cat`/`head`), иначе она его «не видит». Хост-утилита `sandbox-inbox` остаётся для случая «владелец сам кладёт файл» (например, когда нужна побайтовая сверка с оригиналом).

## Two traps that cost a build + a crash loop

- **Файлы на хосте, скопированные в volume без смены владельца, для uid 1000 только на чтение.** `docker cp` сохраняет root:root 644, а `chown` внутри контейнера не работает даже от root (uid не мапится). Поэтому любые файлы в `/workspace/inbox` кладёт только `sandbox-inbox`; руками — `install -o 1000 -g 1000 -m 600 <src> <dst>`.
- **arduino-cli компилирует каталог, а не файл.** `compile /workspace/inbox/foo.ino` падает с `main file missing from sketch: /workspace/inbox/inbox.ino`: скетч-папка должна называться как `.ino`. Правильно: `mkdir -p /workspace/<name> && cp /workspace/inbox/<name>.ino /workspace/<name>/ && cd /workspace/<name> && arduino-cli compile … .`
- **`/tmp` в контейнере — tmpfs с `noexec`, а `arduino-cli` несёт PyInstaller-бутлоадер**, который распаковывается и маппит `.so` из `/tmp`: сборка падает с `[PYI-…:ERROR] Failed to load Python shared library … failed to map segment from shared object` (rc 255). `core list`/`lib list` работают — они не распаковываются. В compose задан `TMPDIR=/workspace/.tmp`, так что лечение встроено; build-path тоже держать на volume.
- **`cap_drop: ALL` alone breaks the image.** `/usr/local/bin/python3-ot` carries the file capability `cap_setgid=ep`; executing a file-cap binary requires that capability in the process permitted set, so with an empty set the entrypoint dies with `/usr/local/bin/python3-ot: bad interpreter: Operation not permitted` and `restart: always` turns it into a restart loop. Fix = `cap_add: ["SETGID"]` (bounding set `0x40`), nothing more.
- **`arduino-cli config init` does not create `~/Arduino`.** A `chown … /home/user/Arduino` in the Dockerfile fails (`No such file or directory`) unless that RUN does `mkdir -p` first.
- **A root-owned data dir makes core installs impossible for uid 1000.** The build installs `arduino:avr` as root, so `/home/user/.arduino15/staging/packages` is root-owned; a later `arduino-cli core install esp32:esp32` dies with `permission denied`. Root inside the container cannot fix it either — `cap_drop: ALL` removes `CAP_DAC_OVERRIDE` and `/home/user` is `0700`, so even `docker exec -u root` gets `Permission denied`. Two fixes: `chown -R 1000:1000 /home/user` at the end of the Dockerfile, and point `ARDUINO_DIRECTORIES_DATA` at the writable volume (`/workspace/.arduino15`) so installs never depend on the image's `/home/user` at all. Copy the baked tree once with `cp -a /home/user/.arduino15 /workspace/.arduino15` so the pre-installed cores survive the switch.

## What users can install on their own

The sandbox has full egress (`github`/`pypi`/`downloads.arduino.cc` all 200) and a real toolchain: `git`, `python3`, `pip3`, `gcc`, `g++`, `make`, `cmake`, `node`. User-space installs work without root: `arduino-cli core install/libus install`, `pip3 install --user`, `npm install --prefix ~/.local`. `apt` never works (read-only rootfs, no root).

**«Поставить пакет под задачу» is not a dead end — verified in a throwaway container under the real limits (`--read-only`, `--cap-drop ALL`, uid 1000):**

- `pip3 install --user requests` installs and imports (`requests 2.34.2`), as does `npm install --prefix ~/.local` and any static binary dropped into `~/bin`.
- `apt-get download` fails (`E: Unable to locate package`) — the image ships no package lists and the lists dir is read-only. `apt-get update` cannot fix it either.
- The working route for a system package: fetch the `.deb` straight from the pool and unpack it into the user's own tree — no root, no apt.
  ```bash
  U=$(curl -fsSL http://deb.debian.org/debian/pool/main/h/hello/ | grep -o 'hello_[^"]*_amd64.deb' | head -1)
  curl -fsSL -o p.deb "http://deb.debian.org/debian/pool/main/h/hello/$U"
  dpkg-deb -x p.deb ./pkg && ./pkg/usr/bin/hello      # Hello, world!
  ```
  `dpkg`, `dpkg-deb` and `curl` are in the image. Library deps then go through `LD_LIBRARY_PATH` into the extracted tree. Verified end to end with `hello 2.10-2`.

Policy the owner set for this: three tiers — (1) userspace installs are the model's job, so the system prompt must carry the `pip --user` / `npm --prefix` / `dpkg-deb -x` recipes, otherwise the model flails on `apt` and reports failure; (2) changes to the shared toolchain core are admin-only, never a model's decision; (3) a request queue into the core is deferred until users actually ask for system packages.

### Where the recipes live: the terminal's own system prompt

Do not put install rules into each model's system prompt — the owner rejected that outright («я же не буду каждой модели прописывать руками»). open-terminal serves its own: `OPEN_TERMINAL_SYSTEM_PROMPT` is returned by `GET /system` as `{"prompt": "…"}` with `{{os}}` `{{kernel}}` `{{arch}}` `{{hostname}}` `{{shell}}` `{{python_version}}` `{{home}}` expanded; `OPEN_TERMINAL_INFO` feeds `GET /info`, and `ENABLE_SYSTEM_PROMPT` (on by default) gates the route. Open WebUI fetches it — `backend/open_webui/utils/tools.py` → `get_terminal_system_prompt`, injected from `utils/middleware.py` — so one env var per container reaches **every** chat using that terminal, whichever model is selected. Verify with `curl -H "Authorization: Bearer <key>" http://<ip>:8000/system | head -c 300`.

What belongs in that text, at this stack's limits: the working directory is the only writable place; not root, so `sudo`/`apt`/`systemctl`/bare `pip3 install` are dead ends — stop and say so rather than improvise; the working install recipes; the 2 GB workspace cap with the warning that old files are deleted automatically; `/opt/toolchain` is read-only. A read-only `AGENTS.md` is only for coding agents launched *inside* the terminal — it is never the channel that reaches an OWUI model.

**LRU eviction must never touch installed tools.** The 2 GB per-user cap counts everything, but eviction skips `.local`, `venv` and `bin`: dropping a pip package because the files are old breaks a working setup. If those directories alone exceed the cap, alert the owner and let him decide.

### Probing the image without touching the live sandbox

Run a throwaway container from the same image: `docker run --rm --user 1000:1000 --read-only --entrypoint sh -v <hostdir>:/workspace --cap-drop ALL --cap-add SETGID -e HOME=/workspace -e TMPDIR=/workspace/.tmp esmien/open-terminal-arduino:local -c '…'`. Two traps: the image **entrypoint mkdirs `/workspace` and dies under `--read-only`** (`mkdir: cannot create directory '/workspace': Permission denied`), so `--entrypoint sh` is required; and a `mktemp -d` host directory is `700 root`, so `chmod 777` it first or uid 1000 cannot write and pip/tmp failures look like image bugs.

Core sizes are not small: `arduino:avr` 384 MB, `esp32:esp32` 6.2 GB after install (multiple Xtensa/RISC-V toolchains). `arduino-cli cache clean` removes ~1.8 GB of staged archives. Budget disk per platform.

## Wiring into Open WebUI (no restart needed)

Terminal servers live in DB key `terminal_server.connections` (table `config`, column `value`, JSON). The supported path is the admin API, and it **replaces the whole list**, so read it first and append:

```
POST /api/v1/auths/signin            {"email": <admin email>, "password": OWUI_ADMIN_PASSWORD}
GET  /api/v1/configs/terminal_servers
POST /api/v1/configs/terminal_servers {"TERMINAL_SERVER_CONNECTIONS": [...existing, new]}
```

`OWUI_ADMIN_PASSWORD` lives in `/root/.config/owui-signup-approver/env` (the `UI_PASSWORD` in `ai/.env` is LiteLLM's and will not sign in). The POST calls `set_terminal_servers()` itself, so the cache refreshes without touching the container.

**Access is granted per connection** in `config.access_grants`:

```json
[{"principal_type": "user", "principal_id": "<user uuid>", "permission": "read"}]
```

`principal_type` may be `user` or `group`; `principal_id: "*"` = everyone. **Empty or missing grants mean admin-only**, which is the safe default to leave in place.

Pass secrets without touching disk: build them on the host and hand them to the container as env (`docker exec -e K="$K"`). A `docker exec … python - <<'PY'` **without `-i`** silently reads an empty script and exits 0 — looks like success, prints nothing. And `printf … | docker exec -i python - <<'PY'` does not work either: the heredoc replaces stdin, so pipes and heredocs cannot coexist.

## Arduino reality check

- Compiles/verifies sketches and reports flash/RAM usage — that is the useful part on a VPS.
- **No flashing**: the board is not attached to the server, so `arduino-cli upload` has nothing to talk to. Upload only becomes real if a board is plugged into this host and mapped into the container, which re-opens a device-passthrough risk.
- Cores/libs are baked in, so offline compile works; `arduino-cli lib install` needs egress from the sandbox.

## Binding a model to the sandbox (so the terminal is always on)

Choosing a terminal inside a chat lasts only for that chat; to have it on by
default, the binding lives on the model row in `webui_db`:

- **`meta.terminalId`** = the connection id from `terminal_server.connections`.
  That is the whole switch — the frontend preselects the terminal for every chat
  with that model.
- **`base_model_id` is prefixed**: OWUI stores `chat.<litellm_group>`, e.g.
  `chat.openai/gpt-6.1-sol`. The gateway group is the part after the dot; do not
  look for a LiteLLM group literally named `chat.openai/…`, it does not exist.
- **Effort control** lives in `params.model_controls` — one control, options
  carrying `reasoning_effort` (`medium` / `high` / `xhigh` / `max`), the default
  pointing at the middle option. Levels and their measured scaling:
  `references/chatgpt-subscription.md` § Reasoning effort.
- **Bind a dedicated model, not a shared one.** A terminal bound to a model every
  user sees is still gated by `access_grants`, so the others get a model whose
  tools fail — one copy of the model per audience costs nothing and avoids that.
- A ready system prompt for an MCU assistant (`/workspace`, compile-before-answer,
  edge-case pass, no fake «прошил»): `templates/mcu-assistant-system-prompt.md`.

**Когда привязки к модели нет, выбор терминала — клиентский.** Фронт шлёт `terminal_id: $selectedTerminalId` в каждом запросе чата, а инициализирует его из `localStorage.selectedTerminalId` (`Md.set(features.enable_tool_servers ? localStorage.selectedTerminalId ?? null : null)`), дальше подписка пишет выбор обратно в localStorage. Сам чат `terminal_id` в БД не хранит (`select count(*) from chat where chat::jsonb ? 'terminal_id'` → 0), поэтому глобальной ручки «включить всем» нет: выбранный один раз терминал липнет к браузеру, а новый юзер или другой браузер открывает чат с выключенным терминалом — и `write_file`/`read_file` у модели отсутствуют, файлы сохранять некуда. Лечится двумя путями: привязать соединение к модели (`meta.terminalId`, штатный) или патчить фронт в `webui-branding` (по слову владельца; механика — `owui-internals.md`).

## LEGACY: one container for all granted users

> Относится к удалённой общей песочнице; текущая схема — контейнер на пользователя (см. «Текущая схема» выше). Оставлено как история решений.

Everyone shared `/workspace` and saw each other's files, and an interactive session was not per-user. Check the blast radius before planning anything: `access_grants` on the connection, read from `select value from config where key='terminal_server.connections'` — `principal_id: "*"` means **every account** on the instance has the sandbox, not just a couple of people. Narrowing `"*"` to the users who actually need it is the cheapest risk reduction available and touches no image.

**The shared sandbox belongs to Игорь, not the owner** (`4848481@gmail.com`, uuid `5760a2b9-fd5f-4d59-96d4-d595f18fb578`, role `user`, created 2026-10-29); the owner's decision is that its `access_grants` become Игорь-only. Its `/workspace` is ~6.7 GB: keep `.arduino15` (~6.3 GB, the toolchain) and `Arduino/` (~49 MB, libraries) plus `~/.local` pip installs; purge the ~350 MB of builds (`school_bell_hybrid_build`, `bell_review_build`, `bell_timer_check`), `.tmp`, `bench*`, sketches, `*.py` drafts, logs, and the duplicate 384 MB `.arduino15` under `/home/user` in the home volume.

## Per-user separation: what upstream offers, and the owner's gate

`open-terminal` has a native multi-user mode (`OPEN_TERMINAL_MULTI_USER=true`); Open WebUI sends `X-User-Id` on every terminal request (`routers/terminals.py`, `utils/terminals.py`), so the server maps each id to its own Linux account: `useradd -m`, home `/home/<sanitized-id>` at mode `2770`, command and file I/O through `sudo -u`. Files and cwd become per-user, cross-user reads get `Permission denied`.

**The owner rejected it — do not propose it as the fix.** It requires the container to run as `user: 0:0` (provisioning needs privilege inside), so every sandbox user sits behind a root process; upstream's own CAUTION says it is not a security boundary and that a determined user reaches root, and one bad prompt can exhaust the shared 2 GB / 1 CPU for everybody. "Люди, которые случайно могут неправильным запросом положить сервер" is the owner's exact objection. Separation for non-owner users therefore means **one container per user** (own volume, hardening intact: non-root, `cap_drop: ALL`, `read_only`, no docker.sock), or per group when trust is shared; a bad prompt then burns only its own container.

Costs, so the plan is concrete: each idle container ~30 MiB live (the current sandbox reports 30 MiB) against `mem_limit`/`cpus` which are ceilings, not reservations; image layers are shared on disk (one 6 GiB copy regardless of container count); per-user arduino cores come from **hardlinks inside one filesystem**, not `cp -a` copies, or 11 users pay 384 MB each.

### Approved design and decisions (owner, 2026-11-09)

Deployed shape: a template compose + `state.json` (0600, never in git) + a host provisioner on a 60 s systemd timer; the connection is added through the admin API only after the container is `healthy`, with a grant on that one user and `chat_uploads: filesystem`; when the account disappears the connection and container go, the files stay **3 days** and are then removed. Role `pending` gets nothing — provisioning happens only after the account is accepted.

- **1.5 GB RAM + 1 CPU per container** (owner: 11 shares over 4 cores is fair-share, no need to throttle rarely-used users).
- **Swap must be enabled per container:** `memswap_limit: 2g` on top of a 1.5 GB limit. With `memswap_limit == mem_limit` docker gives the container no swap at all, so the owner's "swap absorbs a 4-user peak" only works after this change. Host swap is 4 GB with ~1 GB already used, `swappiness 10` — a peak buffer, not a guarantee for all 11 (11 × 0.5 GB of container swap > the ~3 GB free).
- **Disk: LRU cap of 2 GB per user**, accounting excludes the shared toolchain, eviction by `mtime` (`relatime` makes atime useless), TG warning at 1.8 GB and a report of what was removed. Never wipe silently.
- **Shared toolchain is a read-only bind mount**, not `cp -al` into each workspace: one host directory with packages/binaries/cores mounted at `/opt/toolchain` plus `PATH`/`PYTHONPATH`. Hardlinks only where a writable copy is unavoidable (`ARDUINO_DIRECTORIES_DATA`). Owner's "service container as the system core" idea survives in this form; copies drift in version, a mount cannot.
- **Keep that mount out of the user's home.** `FILE_BROWSER_ROOT=home` makes the file browser list whatever sits in the home directory, so a toolchain mounted there shows a `system` folder to every user — the owner's rule is that a user sees exactly one directory, his own. Mounting at `/opt/toolchain` also hides the junk left inside the core: the core container gets no grants, so its `/workspace` stays an archive nobody browses.
- **The existing sandbox becomes the core as it is; Игорь gets a new empty container.** Nothing is recompiled for the toolchains, but his old work is **deleted, not archived** — owner's rule: «мусор Игоря НЕ СОХРАНЯЕМ, УДАЛЯЕМ», and «в ядре не должно быть никаких пользовательских файлов, это же ядро, только бинари». After the purge the core volume holds only `.arduino15` (6.3 GB: `arduino:avr` 259 MB, `esp32:esp32` 6.0 GB, `builtin` 17 MB), `Arduino/libraries` (~49 MB) and the empty `inbox`/`uploads` mount points; everything else (`*.ino`, `bench*`, `bell_*` builds, `.tmp`, logs, drafts, `~/.cache`) is gone. To him it still looks like a cleanup with the functionality preserved.
- **Idle cost of staying always-on** is ~30 MiB per container, so the aggregate is trivial; the real risk is disk (a user filling `/workspace`) and the VM's shared memory ceiling, not the number of containers.

### Verified probe for multi-user mode (throwaway container, never the live sandbox)

```bash
docker run -d --rm --name ot-mu-probe --user 0:0 --cap-drop ALL \
  --cap-add CHOWN --cap-add SETUID --cap-add SETGID --cap-add FOWNER --cap-add DAC_OVERRIDE \
  --security-opt no-new-privileges:true \
  -e OPEN_TERMINAL_MULTI_USER=true -e OPEN_TERMINAL_API_KEY=probe -e TMPDIR=/tmp \
  esmien/open-terminal-arduino:local
IP=$(docker inspect ot-mu-probe --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
curl -s -H 'Authorization: Bearer probe' -H 'X-User-Id: aaaa1111' http://$IP:8000/files/cwd   # {"cwd":"/home/aaaa1111",...}
```

- Exactly those five capabilities are needed: `useradd` writes `/etc/{passwd,group,shadow}` (so `read_only: true` must go), `chown` needs `CHOWN`, `sudo -u` needs `SETUID`/`SETGID`, `CAP_DAC_OVERRIDE` and `FOWNER` for the non-`-R` ownership fixes. Any smaller set fails at provisioning, not at boot.
- `/execute` returns only an id; read the output from `/root/.local/state/open-terminal/logs/processes/*.jsonl` inside the container and match the newest file — the process-list endpoint is unreliable for retrieving output.
- `sudo: unable to send audit message: Operation not permitted` in the output is benign noise under `no-new-privileges`, not a failure.
- Arduino under multi-user mode: `/usr/local/bin/arduino-cli` works for a provisioned user, but `/home/user/.arduino15` is `0700 user:user` → `Permission denied`, and the compose `ARDUINO_DIRECTORIES_DATA=/workspace/.arduino15` is not writable by them. Needs a `/etc/skel` toolchain plus a per-user data dir, and a per-user `TMPDIR` (`/tmp` is `noexec`, arduino-cli cannot build there) — i.e. real image work, not one env var.

### Per-user container template — verified end to end

One compose file per user, rendered from `${SB_SLUG}` / `${SB_KEY}` / `${SB_DIR}` (plus `SB_MEM`, `SB_MEMSWAP`, `SB_CPUS`), project `sb-<slug>`, container `ot-u-<slug>`; an optional `-f override-arduino.yml` adds `ARDUINO_DIRECTORIES_DATA=/workspace/.arduino15` and `ARDUINO_DIRECTORIES_USER=/workspace/Arduino` for the one user who needs the cores.

```yaml
user: "1000:1000"; command: ["run", "--cwd", "/home/user/workspace"]
mem_limit: 1536m; memswap_limit: 2g; cpus: "1.0"; pids_limit: 256
cap_drop: ALL; cap_add: [SETGID]; no-new-privileges; read_only: true
tmpfs: /tmp:size=256m,mode=1777
volumes: ["${SB_DIR}:/home/user/workspace"]
environment:
  OPEN_TERMINAL_FILE_BROWSER_ROOT: /home/user  # корень браузера → видна ровно одна папка workspace
  HOME: /home/user/workspace        # pip --user → .local внутри собственной квоты
  TMPDIR: /home/user/workspace/.tmp # /tmp is noexec; сборщикам нужен exec
  PATH: /home/user/workspace/.local/bin:/home/user/workspace/bin:/usr/local/bin:/usr/bin:/bin
  MALLOC_ARENA_MAX: "2"          # иначе glibc нарежет вторичные арены по 64 МиБ
  PYTHONMALLOC: malloc
  MALLOC_TRIM_THRESHOLD_: "131072"
  MALLOC_MMAP_THRESHOLD_: "131072"
  OPEN_TERMINAL_SYSTEM_PROMPT: | …recipes for the model…
networks: [stack-net]      # external: true
```

Probe after `up -d` + `healthy` — reach the container by IP, the host cannot resolve `stack-net` names:

- `/files/cwd` → `{"cwd":"/home/user/workspace","home":"/home/user/workspace","root":{"path":"/home/user","label":"user"}}`. Корень браузера задаёт `OPEN_TERMINAL_FILE_BROWSER_ROOT` (без него это cwd), поэтому рабочий каталог монтируется на уровень ниже корня и пользователь видит ровно одну папку `workspace`. Служебных каталогов в рабочем каталоге не создавать — пустой `bin` он увидит в витрине; `TMPDIR` держать в дот-каталоге.
- `/execute` with `id; grep CapEff /proc/self/status; touch /etc/x; ls /var/run/docker.sock` → uid 1000, `CapEff: 0000000000000000` (children run with an empty permitted set even though `cap_add: SETGID` is required for boot), `Read-only file system`, no socket.
- `pip3 install --user requests` → imports (`2.34.2`); on the arduino overlay `arduino-cli core list` shows `arduino:avr 1.8.8` + `esp32:esp32 3.3.12` and `compile --fqbn arduino:avr:uno` prints `Sketch uses 444 bytes (1%)`.

Pitfalls specific to this shape:

- **Hardlinks cannot cross mount points inside a container.** `cp -al /opt/toolchain/arduino/. /workspace/.arduino15/` fails per file with `Invalid cross-device link` even though both paths are on `/dev/sda1` — two bind mounts are two devices to the kernel. Do it **on the host**, between the volume's `_data` directory and the user's bind directory (`cp -al /var/lib/docker/volumes/<vol>/_data/.arduino15 <userdir>/`): no mount boundary, and 6.3 GB of cores is not duplicated.
- **Anything hardlinked into a workspace inflates `du` without inflating disk.** That user reports 6.3 GB in his directory while `df` does not move. Quota/LRU accounting must exclude `.arduino15` and `Arduino` in addition to `.local`, `venv`, `bin`, or the cleaner deletes the toolchain and frees nothing.
- **`docker compose down` needs the same `${SB_*}` variables as `up`.** Without them interpolation gives `invalid spec: :/workspace: empty section between colons` and the project is never torn down — pass the identical env (or a per-project env file) to every compose call.
- **With `HOME=/workspace`, open-terminal writes its process logs to `<userdir>/.local/state/open-terminal/logs/processes/*.jsonl`.** Read them from the host bind directory; the `/root/.local/...` path used by the production sandbox does not exist here.

Also: the sandbox sits on `stack-net` like every other service, so a shell inside it can reach `litellm:4000`, `open-webui:8080`, `postgres:5432`. Nothing is reachable without credentials, but if that matters, give the sandbox its own network and attach only `open-webui` to both (recreate `open-webui` to change its networks).

## When to read this file (annotated index entry, moved from SKILL.md)

- `references/sandbox-terminal.md` — **Песочница `open-terminal-sandbox` для пользователей WebUI** (не-root, read-only, arduino-cli; подключение через `terminal_server.connections` + access_grants; привязка модели через `meta.terminalId`; ловушки `cap_setgid`, root-овский `.arduino15` и heredoc). Готовый системный промпт MCU-ассистента: `templates/mcu-assistant-system-prompt.md`.

## `scripts/probe-owui-terminal.py` (index entry, moved from SKILL.md)

- `scripts/probe-owui-terminal.py` — **end-to-end terminal probe** (admin login → feature flags → real `run_command` → `/execute` evidence in open-terminal logs, cleans up its chat). Run after any Open WebUI update.
