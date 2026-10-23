# Detector: conditions, thresholds, evidence, drills

## Why the detector must not act

A watchdog that restarts on sight converts every root cause into a recurring symptom: crash loops look "fixed" between restarts, and the log evidence that explains the crash scrolls away. So the split is strict: the detector only observes, the agent decides. Keep it that way when editing — if a change makes the detector run `docker start`/`restart`, the design is broken.

## Anomaly conditions

| Condition | Trigger name |
|---|---|
| `Exited`/`dead`, `restart: always\|unless-stopped`, down ≥90 s, 2 checks in a row | `exited` |
| `Restarting` with `RestartCount` increasing between checks | `crash_loop` |
| `Up` + `health=unhealthy` 2 checks in a row (stateful containers: 3) | `unhealthy` |
| `RestartCount` jump ≥2 between two 60 s checks (flapping shorter than a tick) | `restart_flap` |
| Allowlisted container absent from `docker ps -a` twice in a row | `missing` |

Debounce matters more than sensitivity: one tick of an unhealthy reading is normal during startup, JIT warmup or a provider hiccup. Two consecutive observations is the floor for anything that ends in a wake-up.

## Guards

- per-container cooldown 20 min (`AUTORECOVER_COOLDOWN`);
- at most one diagnostic agent at a time (`systemctl list-units 'docker-incident-*'`);
- pause flag `/var/lib/docker-autorecover/pause` short-circuits the whole run;
- disk ≥97% or `docker` not active → alert, no wake-ups (restarting services on a full disk makes it worse);
- allowlist is the blast radius: nothing outside `/etc/docker-autorecover.conf` is ever inspected as an incident.

Env knobs used by drills only: `AUTORECOVER_CONFIG`, `AUTORECOVER_EXITED_GRACE`, `AUTORECOVER_UNHEALTHY_HITS[_STATEFUL]`, `AUTORECOVER_COOLDOWN`.

## Evidence bundle

`/var/lib/docker-incidents/<UTC ts>-<container>-<reason>/`

| File | Content | Why |
|---|---|---|
| `incident.json` | reason, detection time, status, health, RestartCount, ExitCode, OOMKilled, policy, image, seconds down | single machine-readable summary |
| `inspect.json` | full `docker inspect` (truncated) | limits, binds, env keys, labels |
| `logs.txt` | `docker logs --tail 300 --timestamps` | last words before death |
| `oom.txt` | kernel ring grep for oom-kill | distinguishes cgroup OOM from external kill |
| `disk.txt` | `df -h / /var/lib/docker`, `docker system df` | the most common sudden cause |
| `host.txt` | `systemctl is-active postgresql nginx docker`, uptime, free, failed units | dependency vs container fault |
| `docker-journal.txt` | `journalctl -u docker` lines for that container | daemon-side view, catches bind/start errors |
| `prompt.txt`, `agent.log` | what the agent was asked, what it answered | audit trail |

Bundle first, wake second: the agent must never have to reconstruct state from a container that a restart already changed.

## Watching the watchdog

`docker-detector-liveness.timer` (10 min) alerts when `state.json` is older than 10 min or the detector timer is inactive, throttled to one alert per hour. A silent detector and a healthy stack look identical otherwise — that false calm is the failure mode worth guarding.

## Drill recipe (safe, ~4 min)

```bash
# 1. throwaway container, policy that Docker honours
 docker run -d --name zz-agent-drill --restart unless-stopped alpine sleep 900
# 2. put it into Exited the way an operator would; Docker will NOT auto-restart it
 docker stop zz-agent-drill
# 3. temp allowlist + short grace so the detector fires immediately
 printf 'zz-agent-drill\n' > /tmp/drill.conf
 AUTORECOVER_CONFIG=/tmp/drill.conf AUTORECOVER_EXITED_GRACE=5 \
   python3 /usr/local/bin/docker-incident-detector.py      # twice, ~2 s apart
# 4. verify the pipeline
 systemctl list-units 'docker-incident-*' --all
 journalctl -u 'docker-incident-zz-agent-drill-*' -n 5 | tail -3   # expect: report sent ok=True
# 5. clean up your own artifacts
 docker rm -f zz-agent-drill; rm -f /tmp/drill.conf
```

Expect a *diagnostic* answer, not a fix, on a synthetic container — a correct agent refuses to "repair" something that is not a service and says so. To prove the fix path, drill on a real non-critical service (e.g. `searxng`) and ask the owner first: it costs a few minutes of that service being down.
