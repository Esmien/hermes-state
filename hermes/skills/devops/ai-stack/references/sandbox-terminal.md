# Sandboxed terminal for Open WebUI users

`open-terminal` (the main one) is effectively host root: `user: 0:0`, host `/` mounted at `/mnt/host`, `/var/run/docker.sock` passed through. Never grant it to anyone but the owner. The second instance, **`open-terminal-sandbox`**, exists so ordinary WebUI users get shell/file/Arduino tools without any of that.

## What the sandbox is

| item | value |
|---|---|
| service / container | `open-terminal-sandbox` (compose project `ai`) |
| image | `esmien/open-terminal-arduino:local`, built from `ai/arduino-sandbox/Dockerfile` on top of `ghcr.io/open-webui/open-terminal:latest` |
| user | `1000:1000` |
| workspace | named volume `ot_sandbox_workspace` → `/workspace` (cwd), `ot_sandbox_home` → `/home/user` |
| mounts from host | none (no `/`, no socket) |
| hardening | `cap_drop: ALL`, `cap_add: SETGID`, `no-new-privileges`, `read_only: true`, `tmpfs /tmp`, `mem 1g/1g`, `cpus 1.0`, `pids_limit 256` |
| key | `OPEN_TERMINAL_SANDBOX_API_KEY` in `ai/.env` |
| tools | `arduino-cli` 1.5.1 + core `arduino:avr` 1.8.8 baked into the image |

Verified after build: `id` → uid 1000, `CapEff` → 0, `/etc` read-only, no `/var/run/docker.sock`, `/home/ai_service` absent, `arduino-cli compile --fqbn arduino:avr:uno` on a blink sketch → 924 bytes.

## Two traps that cost a build + a crash loop

- **`cap_drop: ALL` alone breaks the image.** `/usr/local/bin/python3-ot` carries the file capability `cap_setgid=ep`; executing a file-cap binary requires that capability in the process permitted set, so with an empty set the entrypoint dies with `/usr/local/bin/python3-ot: bad interpreter: Operation not permitted` and `restart: always` turns it into a restart loop. Fix = `cap_add: ["SETGID"]` (bounding set `0x40`), nothing more.
- **`arduino-cli config init` does not create `~/Arduino`.** A `chown … /home/user/Arduino` in the Dockerfile fails (`No such file or directory`) unless that RUN does `mkdir -p` first.

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

## Known limitation

There is **one container for all granted users** — everyone shares `/workspace` and sees each other's files, and an interactive session is not per-user. Per-user isolation means one container per user (or per group), each with its own volume; memory cost ~ the base image's idle footprint.

Also: the sandbox sits on `stack-net` like every other service, so a shell inside it can reach `litellm:4000`, `open-webui:8080`, `postgres:5432`. Nothing is reachable without credentials, but if that matters, give the sandbox its own network and attach only `open-webui` to both (recreate `open-webui` to change its networks).
