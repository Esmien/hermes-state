# Sandboxed terminal for Open WebUI users

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

The sandbox has full egress (`github`/`pypi`/`downloads.arduino.cc` all 200) and a real toolchain: `git`, `python3`, `pip3`, `gcc`, `g++`, `make`, `cmake`, `node`. User-space installs work without root: `arduino-cli core install/libus install`, `pip3 install --user`, `npm install --prefix ~/.local`. `apt` never works (read-only rootfs, no root) — if a task truly needs system packages, the hardening has to be loosened knowingly.

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

## Known limitation

There is **one container for all granted users** — everyone shares `/workspace` and sees each other's files, and an interactive session is not per-user. Per-user isolation means one container per user (or per group), each with its own volume; memory cost ~ the base image's idle footprint.

Also: the sandbox sits on `stack-net` like every other service, so a shell inside it can reach `litellm:4000`, `open-webui:8080`, `postgres:5432`. Nothing is reachable without credentials, but if that matters, give the sandbox its own network and attach only `open-webui` to both (recreate `open-webui` to change its networks).
