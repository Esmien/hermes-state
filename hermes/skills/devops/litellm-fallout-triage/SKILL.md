---
name: litellm-fallout-triage
description: "Use when LiteLLM alerts or model calls fail."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [devops, litellm, llm-gateway, incidents, monitoring]
---

# LiteLLM fallout triage (this host)

LiteLLM here is the single door every model call goes through (Hermes, Open WebUI, bots). When it lies down, everything downstream looks broken. The job is to name the **mechanism**, not to bounce the container until the red light goes off.

## When to Use

- Telegram shows «🔴 LiteLLM не отвечает» or «⚠️ LiteLLM: всплеск отказов».
- You were woken by a `litellm-incident-<ts>.service` unit with a prompt pointing at `/var/lib/litellm-incidents/<ts>-<reason>/`.
- A client (Hermes, Open WebUI, a bot) returns 5xx / "no healthy deployment" on model calls.
- The watchdog, its thresholds, or its agent wake-up are being changed.

Container-level questions (Docker states, restart policies, compose traps) belong to `container-incident-response`; routes and model quality to `llm-route-bench`.

## The pipeline — inspect, don't rebuild

| Piece | Path |
|---|---|
| Watchdog, every 60 s | `litellm-watchdog.timer` → `litellm-watchdog.service` → `/usr/local/bin/litellm-watchdog.py` |
| Wake-up launcher | `/usr/local/bin/litellm-incident-agent.sh` |
| Evidence bundles | `/var/lib/litellm-incidents/<ts>-<reason>/` |
| State | `/var/lib/server-monitor/litellm_watchdog_state.json` |
| Log | `/var/log/litellm-watchdog.log` |
| Pause flag (shared with container autorecover) | `/var/lib/docker-autorecover/pause` |
| Spend logs (source of truth) | postgres `litellm_db`, table `"LiteLLM_SpendLogs"` |

Flow: probe → alert to Telegram straight from the script (no LiteLLM, no Hermes in the path) → evidence bundle → `systemd-run` → `hermes chat -m emergency` reads the bundle, diagnoses, and posts the report. `-m emergency` matters: the normal route may be the patient.

Drill the whole chain without waiting for an outage: `python3 /usr/local/bin/litellm-watchdog.py --drill` (marked DRILL in Telegram, does not touch downtime state). `--no-send` prints instead of sending.

## Known noise — the trap that produced the false alarms (2026-11)

**The proxy writes its own admin/UI calls into `LiteLLM_SpendLogs` with `status<>'success'`, although no model was called.** Real example: `/v2/model/info`, `/get/user_banner`, `/model_group/info`, `/sso/get/ui_settings`, `/team/list`, `/get/latest_release_info`, `/azure/.env` — all from the web UI polling with a key from `172.18.0.1`. On a quiet 15-minute window that was literally the only traffic: 14 "failed" calls out of 15 → the watchdog screamed «93% отказов» while `acompletion` in the same 7 days was **5523 calls, 0 failures**.

Rule: **only call types that do not start with `/` are model traffic** (`acompletion`, `aembedding`, `aresponses`, `responses`, `arerank`). Everything starting with `/` is a proxy control endpoint. The error-rate probe therefore filters `call_type not like '/%' and call_type <> 'pass_through_endpoint'`. Do not narrow that filter back to a hand-written list of two endpoints — the UI grows new ones. Before believing any error-rate number, run the breakdown query below; a burst with `(без группы)` is always control traffic, never a model outage.

### Queries (read-only, no secrets)

```bash
# 1. Ratio by call type, 7 days — spots control endpoints inflating the count
sudo -u postgres psql -d litellm_db -tAc "select call_type, count(*) total, count(*) filter (where status<>'success') bad from \"LiteLLM_SpendLogs\" where \"startTime\" > now() - interval '7 days' group by 1 order by bad desc limit 15"

# 2. Real failures only (model was actually called)
sudo -u postgres psql -d litellm_db -tAc "select call_type, model_group, custom_llm_provider, count(*) bad from \"LiteLLM_SpendLogs\" where \"startTime\" > now() - interval '24 hours' and status<>'success' and coalesce(model,'')<>'' group by 1,2,3 order by 4 desc limit 15"

# 3. What the error text actually was (truncated on purpose)
sudo -u postgres psql -d litellm_db -tAc "select to_char(\"startTime\",'HH24:MI'), model_group, custom_llm_provider, left(response::text,180) from \"LiteLLM_SpendLogs\" where status<>'success' and \"startTime\" > now() - interval '6 hours' order by \"startTime\" desc limit 20"
```

Quoting trap: `-tAc "…\"LiteLLM_SpendLogs\"…"` through a shell mangles the double quotes and postgres answers `relation "litellm_spendlogs" does not exist`. For anything longer than one line, write the SQL to a file under `/tmp` (`chmod 644`, the postgres user must read it) and use `psql -f`.

## Decision tree

1. **Container state first** (`docker inspect litellm`): `restarts>0` + `oom=true` → memory; `exited` under `always` → Docker gave up after repeated crashes; `Up (healthy)` + liveliness failing → hung process or upstream, not a crash.
2. **Liveliness vs readiness**: `/health/liveliness` 200 but `/health/readiness` not → the process is up but a dependency (redis, postgres, provider keys) is red. Redis is `litellm-redis`.
3. **Error text** from query 3: `AuthenticationError`/`401` → rotated or revoked provider key; `429`/`quota` → provider limit or exhausted plan (see `openai-siwc-gateway` for the ChatGPT-plan route); `no healthy deployment` → every deployment of that group is cooling down; `timeout`/`APIConnectionError` → provider reachability from inside the container.
4. **Provider reachability from inside**: `docker exec litellm python -c "import urllib.request;print(urllib.request.urlopen('https://api.deepseek.com', timeout=8).status)"` — a container without curl still has python in the LiteLLM image; if the host reaches the provider and the container does not, check the compose network/DNS, not the provider.
5. **Host resources**: `free -m`, `df -h / /var/lib/docker`, `systemctl --failed`. A full disk breaks postgres writes and shows up as model errors.

## Allowed vs escalation

Safe: `docker restart litellm`, waiting for a provider cooldown window to expire, deleting your own temp files. Wrap manual work in the pause flag (`touch /var/lib/docker-autorecover/pause`, remove it afterwards) so the alerting does not fight you.

Stop and report instead: editing `.env` / LiteLLM `config.yaml`, `docker rm`/`prune`, `down -v`, restoring the DB from a dump, touching any other container, changing model routes. Say exactly what is needed and why — the owner approves those himself.

## Reporting

```
ОТЧЁТ:
причина: <mechanism in one or two lines>
что сделал: <one or two lines>
состояние: работает | требует человека — <what exactly and why>
```

Russian, terse, no command replay, no secrets. «Ложная тревога от UI-эндпоинтов» is a perfectly good verdict when that is the truth — the fix then belongs to the watchdog filter, not to the gateway.

## Pitfalls

- **When the alert detail *is* a psql error, the ratio is still real.** `aggregate functions are
  not allowed in GROUP BY` comes from the watchdog's own enrichment query
  (`/usr/local/bin/litellm-watchdog.py`, `breakdown` ~line 184: it concatenates `count(*)` inside
  the SELECT and then `group by 1`). The 15-minute count/ratio is computed by a different, working
  query — so do not dismiss the alarm as noise, re-run the breakdown by hand.
- **`/model/update` / `/model/delete` + `/model/new` traffic in the gateway log means a route
  migration is in flight.** Bridge legs created without `api_key` produce
  `OpenAIError: The api_key client option must be set`, which the router turns into
  `RouterRateLimitError: No deployments available … cooldown_list=[]` → `429` to clients, and the
  spend log shows `model_group` = the affected group with `model_id` of a deployment that no
  longer exists in `LiteLLM_ProxyModelTable`. That is a config-side artefact of the migration, not
  a gateway outage — confirm with the ids and with `LiteLLM_SpendLogs.api_base`
  (`host.docker.internal:4010` = SIWC bridge), then re-verify with a real call.
- **`/model/info` masks `api_key`** — `MISSING` there proves nothing; read `LiteLLM_ProxyModelTable`
  or just call the model.
- **Do not trust the alert text's percentage alone** — it is a ratio, and with 10-15 calls in a window a couple of control-endpoint rows read as 90%. Always add the breakdown query before concluding.
- **`status<>'success'` is not "the model failed".** Check `coalesce(model,'')<>''` — empty model means the request never reached a provider.
- **`agent.log` is buffered** — the nested `hermes chat` writes on exit; poll the systemd unit, not the file size.
- **A nested agent must be launched as `/bin/bash script`** — the launcher is deliberately not `chmod +x` on this host.
- **Every early return must refresh the state file** — the liveness timer only looks at its age; a paused branch that skips `write_state()` produces a false «детектор мёртв» after the pause is lifted.
- **The pause flag mutes the watchdog on purpose** — a forgotten `/var/lib/docker-autorecover/pause` means a silent gateway. When a whole class of alarms vanished, check the flag before believing the health.
