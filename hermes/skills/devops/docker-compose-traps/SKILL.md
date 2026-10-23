---
name: docker-compose-traps
description: "Use when recreating stack containers via docker compose."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [devops, docker, compose, incidents, ai-stack]
---

# Docker / compose traps on this host

Companion to `ai-stack` (layout, services, per-service upgrade recipes). This skill is the short list of ways a container recreate silently breaks production here — read it before any `docker compose up -d`.

## When to Use

Any task that edits `docker-compose.yml`, adds/removes a bind mount, rebuilds an image, or recreates a container of the `ai` compose project (`/home/ai_service/ai-stack/ai`).

## Rule 0 — never recreate a stack container from the wrong shell or cwd

Always run compose from the project directory **on the host**:

```bash
cd /home/ai_service/ai-stack/ai && docker compose up -d <service>
```

### The `/mnt/host` trap (real incident, 2026-10-23)

- `open-terminal` mounts the host root at `/mnt/host` (`rw`), runs with `cwd=/mnt/host` and has `/var/run/docker.sock` passed through. An agent driving that web terminal sees `/mnt/host/home/ai_service/...` as a valid path.
- The compose CLI reads the file fine there, but the **Docker daemon resolves relative bind sources on the HOST**, where `/mnt/host` does not exist. Docker then **creates the missing source as an empty directory** and mounts a directory over a file.
- Symptom: `restart: always` crash loop, log says `IsADirectoryError: [Errno 21] Is a directory: '/app/config.yaml'`, `RestartCount` climbing, and a fresh tree dated minutes ago appears at `/mnt/host/...` on the host.

Diagnose before touching anything:

```bash
docker inspect <c> --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'
docker inspect <c> --format '{{.Created}} wd={{index .Config.Labels "com.docker.compose.project.working_dir"}}'
```

A `Source` starting with `/mnt/host` is the bug. Fix = rerun `compose up -d <service>` from the host project dir (this recreates with correct sources), then remove the auto-created empty `/mnt/host` tree **only after** confirming nothing else lives there. Recovery drill: `ai-stack` skill, `references/operations.md` → «Recreating a container after a config edit».

## The `lyria` project: run from the project root, source `.env` first

`/root/deploy/music_bot/.env` sets `COMPOSE_FILE=infra/docker-compose.yml`, `COMPOSE_PROJECT_NAME=lyria`, and the interpolated `POSTGRES_PASSWORD` / `RABBITMQ_USER`. Compose only reads it if it is in the environment. Two wrong ways that look right:

- from `/root/deploy/music_bot` **without** `source` — `COMPOSE_FILE` points at `infra/infra/docker-compose.yml`, command fails with no such file;
- from `infra/` — resolves `container_name: infra-bot` and blank passwords, so `up -d` creates a second set of `infra-*` containers with empty credentials next to the live `lyria-*` ones.

```bash
( cd /root/deploy/music_bot && set -a && . ./.env && set +a && \
  docker compose config | grep -m1 container_name && \
  docker compose up -d --no-deps <service> )
```

Always in a subshell: `COMPOSE_FILE` and `COMPOSE_PROJECT_NAME` persist in the calling shell and then redirect **every** later compose command — running `docker compose config` in the `ai` project afterwards dies with `infra/docker-compose.yml ... no such file or directory` (verified). If a shell is already poisoned: `unset COMPOSE_FILE COMPOSE_PROJECT_NAME`.

The `ai` project needs none of this — its `.env` sits in the compose directory and is auto-loaded. `lyria-migrate` sits at `Exited (0)` by design. Full per-container host inventory and recovery decision tree: `/home/ai_service/ai-stack/runbook-containers.md`.

## Before manual maintenance: pause the incident detector

`docker-autorecover.timer` (every 60 s) runs `docker-incident-detector.py`, which wakes a Hermes agent on any anomaly. It never acts on its own, but it will fire an incident and start a diagnostic agent under your hands mid-maintenance. Create the flag first, remove it only after the verify pass:

```bash
touch /var/lib/docker-autorecover/pause
# ...maintenance + verification...
rm /var/lib/docker-autorecover/pause
```

Allowlist `/etc/docker-autorecover.conf`, log `/var/log/docker-autorecover.log`, evidence `/var/lib/docker-incidents/`. Contract: `runbook-containers.md` §9; the incident-response workflow itself: skill `container-incident-response`.

## Restart loops: read the policy before "it fell over"

Every container here is `restart: always` (`docker inspect <c> --format '{{.HostConfig.RestartPolicy.Name}}'`), so a broken container restarts itself indefinitely and looks "up". Judge health by `State.Health.Status`, `RestartCount`, and a real request — not by `Up X minutes`.

```bash
docker inspect <c> --format '{{.State.Health.Status}} restarts={{.RestartCount}}'
docker logs <c> --since 5m 2>&1 | grep -iE 'error|traceback' | tail -n 20
```

Known benign noise (do not "fix"): lyria workers' boot `AMQPConnectionError`; Open WebUI `get_available_voices ... /v1/audio/voices -> 404`; LiteLLM `Error upserting deployment … LLM Provider NOT provided` for a dormant DB row. Confirm the last one with spend history, not vibes.

## Editing a service — the safe sequence

1. Edit the file. **Git is the history**: the stack is a repo at `/home/ai_service/ai-stack` (local, no remote) owned by `ai_service` — run `sudo -u ai_service git status|add|commit`, because as root git aborts with `detected dubious ownership`. Timestamped `*.bak.<ts>` copies beside configs are junk: `.gitignore` already excludes them and the owner expects them deleted once the change is committed. Never stage `ai/webui-branding/_state_snapshot/` (it holds resolved secrets) or `ai/webui-branding/out/` (generated in the Dockerfile). Details: `ai-stack` → `references/repo-hygiene.md`.
2. `docker compose config -q` (validates YAML and interpolation) before touching the live container.
3. Recreate **one** service: `docker compose up -d <service>`. Run `up -d` with `background=true` in the tool and wait on the handle — the foreground guard rejects it as a long-lived process even though it returns instantly.
4. Verify: health `healthy`, `RestartCount` unchanged/0, `curl` the real endpoint, and a log grep for the service's own startup markers.

Never use `deploy.sh` to apply a one-service change: it **restores the newest DB dump by default**. `--skip-restore` exists but a full deploy is still the wrong tool here.

## House standard: healthcheck and logging

Every service in `ai/docker-compose.yml` carries the same shape — copy it instead of inventing values:

- `healthcheck`: `interval: 30s`, `timeout: 10s`, `retries: 3`, `start_period` by startup speed (20s normal, 60s `litellm`, 90s `open-webui`). Slow starters keep `retries: 5` **with an inline comment saying why** — an uncommented exception is how a config turns into folklore.
- `logging`: explicit `driver: json-file` + `max-size: "50m"` + `max-file: "3"` on **every** service, so rotation does not depend on the host `/etc/docker/daemon.json`. Daemon defaults are not retroactive: a container keeps the log config it was created with (`{}` = unlimited).
- **Probe the endpoint before writing the test.** Root `/` often answers 404 while a real route answers 200: `open-terminal` has `/health`, `searxng` has `/healthz`, `edge-tts` only serves `/v1/audio/voices` (200) with `/` at 404. `curl -f` fails on 404, so a wrong path marks a healthy container unhealthy.
- **Check which binaries the image has** before choosing the probe: `docker exec <c> sh -c 'command -v curl wget python3 nc'` — `searxng` has wget+python3 and no curl, `open-terminal` has curl, `edge-tts` and the lyria images have only python3.
- No HTTP endpoint at all (lyria workers are taskiq consumers) → a deliberately weak probe, labelled as such: `test: ["CMD", "python3", "-c", "import socket;socket.create_connection(('rabbitmq',5672),4)"]`. It proves broker reachability, not that the worker works; say so in the runbook.

## Memory limits need both numbers

`mem_limit` alone lets Docker grant `2 × mem_limit` of swap. Always set `memswap_limit` equal to `mem_limit` (see `litellm`: 3.5g / 3.5g) and verify:

```bash
docker inspect <c> --format '{{.HostConfig.Memory}}/{{.HostConfig.MemoryReservation}}/{{.HostConfig.MemorySwap}}'
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.swap.max   # expect 0
```

Changing limits requires a recreate (or `docker update --memory-swap` live).

## Other footguns that cost time here

- `docker exec` with a heredoc **needs `-i`** — without it the command exits 0 with empty output (looks like a silent success).
- Images pinned only by tag (`:main`, `:latest`) move under you. `webui-branding` and `litellm` are pinned deliberately (digest / `vX.Y.Z`) — keep it that way and read the release before pulling.
- `docker compose up -d --force-recreate` is required after an **image rebuild**, otherwise a stale container keeps the old image layer.
- Container-level settings compose can see (healthcheck, `logging:`, restart policy) are applied by a plain `up -d` — compose reports `Recreated`. **Daemon-level** settings (`/etc/docker/daemon.json`: log rotation, `live-restore`) are invisible to compose, so every existing container keeps its old config until it is explicitly recreated: check with `docker inspect <c> --format '{{json .HostConfig.LogConfig.Config}}'` (`{}` = no rotation) and use `--force-recreate` to fix.
- `docker restart` does not increment `RestartCount` (only policy-driven restarts do) — a `restarts=0` container may still have been restarted by hand. It also blocks for the container's stop timeout (~10 s by default) before returning.
- Any `set -a; . .env` poisons the calling shell for later compose work (`COMPOSE_FILE`, passwords); test-only `AUTORECOVER_*` overrides persist the same way. Run such exports in a subshell, or `unset` them before the next unrelated command.
- A bind mount over a single file must point at the file; if the source is missing Docker quietly substitutes a directory. Verify content after any recreate: `docker exec <c> head -c 60 <path>`.
- Secrets: compose reads `ai/.env`; never print it, never inline a key into a command line.
