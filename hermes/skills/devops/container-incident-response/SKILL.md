---
name: container-incident-response
description: "Use when a container fails or incident automation changes."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [devops, docker, incidents, monitoring, systemd, hermes]
---

# Container incident response (this host)

On a container failure the agent must **wake up and find the root cause**. The owner explicitly rejects blind `docker start` loops: they hide the cause and hide repeat failures. Fix only what cannot make things worse; the moment a fix needs a destructive step, stop and message him.

## When to Use

- A container on this host is down, restarting, unhealthy, missing from `docker ps -a`, or its `RestartCount` is climbing.
- A `docker-incident-*` unit fired, an evidence bundle appeared under `/var/lib/docker-incidents/`, or Telegram got an incident report.
- The incident pipeline itself is being changed: thresholds, allowlist, prompt, agent invocation, liveness timer, or the pause-flag contract.
- The owner asks for monitoring, auto-recovery, "поднимать без меня", or drills of the recovery path.

Operator runbook for the same territory, with the per-container inventory: `/home/ai_service/ai-stack/runbook-containers.md`.

## What already exists — inspect, don't rebuild

| Piece | Path |
|---|---|
| Detector (never touches containers) | `/usr/local/bin/docker-incident-detector.py` |
| Timer, every 60 s | `docker-autorecover.timer` → `docker-autorecover.service` |
| Agent launcher | `/usr/local/bin/docker-incident-agent.sh` |
| Allowlist + `:stateful` flags | `/etc/docker-autorecover.conf` |
| Evidence bundles | `/var/lib/docker-incidents/<ts>-<name>-<reason>/` |
| Detector state | `/var/lib/docker-autorecover/state.json` |
| Pause flag | `/var/lib/docker-autorecover/pause` |
| Log (decisions, launches, reports) | `/var/log/docker-autorecover.log` |
| Watchdog of the watchdog, 10 min | `docker-detector-liveness.timer` |
| Operator runbook | `/home/ai_service/ai-stack/runbook-containers.md` §9 |

Flow: timer → detector spots an anomaly → writes an evidence dir → `systemd-run` starts `docker-incident-<name>-<ts>.service` → that wakes `hermes chat` with the prompt → the report goes to Telegram from the shell script, not from the agent.

## Workflow when an incident is yours

1. **Read the evidence dir, not the chat.** `incident.json` first (status, health, RestartCount, ExitCode, OOMKilled, restart policy, image, how long down), then `logs.txt` (last 300 lines, timestamped), `oom.txt`, `disk.txt`, `host.txt`, `docker-journal.txt`.
2. **Decode the exit signature before theorising:** `137` + `OOMKilled=true` → memory limits / growth; `137` without OOM → external SIGKILL (stop timeout or someone's `docker kill`); `1` seconds after start → config, env, migrations; `143` → SIGTERM, a stop, not a crash; `Exited` with `RestartCount=0` under `always`/`unless-stopped` → Docker never restarted it, so it was stopped from outside — there is no crash to explain.
3. **Read `runbook-containers.md` §1–§5 and §8** (known noise) plus `docker-compose-traps` before any compose action. Separating benign noise from a real fault is most of the diagnosis here.
4. **Fix only the safe class:** `docker start` / `docker restart`; a compose edit with a `*.bak.<ts>` copy followed by a recreate of exactly one service; deleting your own temporary files. Before touching containers by hand, `touch /var/lib/docker-autorecover/pause`, and remove it after the verify pass.
5. **Verify like a user, not like Docker:** health status, the real endpoint (runbook §5 table), and no errors in logs for the last 3 minutes.
6. **Escalate instead of improvising:** `rm`/`docker rm`/`rmi`, `prune`, `down -v`, restoring a DB from a dump, editing `.env`, or any container outside the incident — stop and report what exactly is needed and why.

## Report format (goes to Telegram verbatim)

```
ОТЧЁТ:
причина: <one or two lines, mechanism not symptom>
что сделал: <one or two lines>
состояние: работает | требует человека — <what exactly and why>
```

Russian, terse, no command replay, no secrets (`.env`, tokens, keys stay out even when they sit in the logs). If the container recovered on its own, still name the cause.

## Honesty about indirect checks

Weak probes are labelled weak, in the report and in the docs: a worker healthcheck that only proves broker reachability does not prove the worker is working; a `404` on `/` can mean a healthy service with no root route. Never let a green checkmark stand for evidence you do not have.

## Drills — prove the pipeline, don't assume it

Full recipe in `references/detector-and-thresholds.md`. Short form: throwaway container with `--restart unless-stopped`, `docker stop` it (Docker does not auto-restart a manually stopped container, so it stays `Exited`), run the detector twice with `AUTORECOVER_CONFIG` pointed at a temp allowlist and `AUTORECOVER_EXITED_GRACE=5`, confirm the agent unit ran, that `agent.log` holds a reasoned report, and that Telegram logged `report sent ok=True`. Remove the test container yourself; never drill on a production container without asking the owner first. A synthetic container proves detection, evidence collection, wake-up and Telegram delivery — **not** the repair path: a nested agent correctly refuses to "fix" a container that is not a service (it reads the image, the compose labels and the restart policy, then escalates instead of running `docker start` on a throwaway `sleep`). Proving repair needs a real service plus the owner's explicit go-ahead for that downtime — ask for it, never self-approve the drill.

## Pitfalls

- **Sourcing an env file poisons the shell for later commands** (`COMPOSE_FILE`, `AUTORECOVER_*` test overrides). Run such exports in a subshell or `unset` them — otherwise the next unrelated `docker compose` command in another project resolves the wrong file.
- **The agent's output is buffered**: `agent.log` stays 0 bytes until the nested `hermes chat` exits. Poll the systemd unit state, not the file size.
- **A nested agent needs `/bin/bash script` under `systemd-run`** — the launcher is deliberately not `chmod +x` (no permission changes on this host), so invoking the path directly fails.
- **When the gateway itself is the patient** (`litellm`, `litellm-redis`), pass `-m emergency` so diagnosis does not depend on the broken component; the alias lives in `/root/.hermes/config.yaml`.
- **The detector is silent when healthy by design** — `--dry-run` printing nothing means no anomaly, not a broken script; confirm liveness via `state.json` age (<3 min).
- **A failure shorter than two detector ticks can pass unnoticed** if the container self-heals; acceptable, not a gap to engineer around.

## Support files

- `references/detector-and-thresholds.md` — anomaly conditions, debounce/cooldown numbers, evidence bundle contents, drill recipe.
- `references/agent-wakeup.md` — `systemd-run` + `hermes chat` invocation, prompt skeleton, report extraction, Telegram delivery.
