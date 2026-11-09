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

## Known limitation: one container for all granted users

Everyone shares `/workspace` and sees each other's files, and an interactive session is not per-user. Check the blast radius before planning anything: `access_grants` on the connection, read from `select value from config where key='terminal_server.connections'` — `principal_id: "*"` means **every account** on the instance has the sandbox, not just a couple of people. Narrowing `"*"` to the users who actually need it is the cheapest risk reduction available and touches no image.

## Per-user separation: what upstream offers, and the owner's gate

`open-terminal` has a native multi-user mode (`OPEN_TERMINAL_MULTI_USER=true`); Open WebUI sends `X-User-Id` on every terminal request (`routers/terminals.py`, `utils/terminals.py`), so the server maps each id to its own Linux account: `useradd -m`, home `/home/<sanitized-id>` at mode `2770`, command and file I/O through `sudo -u`. Files and cwd become per-user, cross-user reads get `Permission denied`.

**The owner rejected it — do not propose it as the fix.** It requires the container to run as `user: 0:0` (provisioning needs privilege inside), so every sandbox user sits behind a root process; upstream's own CAUTION says it is not a security boundary and that a determined user reaches root, and one bad prompt can exhaust the shared 2 GB / 1 CPU for everybody. "Люди, которые случайно могут неправильным запросом положить сервер" is the owner's exact objection. Separation for non-owner users therefore means **one container per user** (own volume, hardening intact: non-root, `cap_drop: ALL`, `read_only`, no docker.sock), or per group when trust is shared; a bad prompt then burns only its own container.

Costs, so the plan is concrete: each idle container ~30 MiB live (the current sandbox reports 30 MiB) against `mem_limit`/`cpus` which are ceilings, not reservations; image layers are shared on disk (one 6 GiB copy regardless of container count); per-user arduino cores come from **hardlinks inside one filesystem**, not `cp -a` copies, or 11 users pay 384 MB each.

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

Also: the sandbox sits on `stack-net` like every other service, so a shell inside it can reach `litellm:4000`, `open-webui:8080`, `postgres:5432`. Nothing is reachable without credentials, but if that matters, give the sandbox its own network and attach only `open-webui` to both (recreate `open-webui` to change its networks).

## When to read this file (annotated index entry, moved from SKILL.md)

- `references/sandbox-terminal.md` — **Песочница `open-terminal-sandbox` для пользователей WebUI** (не-root, read-only, arduino-cli; подключение через `terminal_server.connections` + access_grants; привязка модели через `meta.terminalId`; ловушки `cap_setgid`, root-овский `.arduino15` и heredoc). Готовый системный промпт MCU-ассистента: `templates/mcu-assistant-system-prompt.md`.

## `scripts/probe-owui-terminal.py` (index entry, moved from SKILL.md)

- `scripts/probe-owui-terminal.py` — **end-to-end terminal probe** (admin login → feature flags → real `run_command` → `/execute` evidence in open-terminal logs, cleans up its chat). Run after any Open WebUI update.
