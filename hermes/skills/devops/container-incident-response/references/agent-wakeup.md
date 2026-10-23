# Waking the agent from a shell/systemd trigger

## Launch pattern

The detector must not block, and the agent run must survive the detector's exit, so the trigger goes through systemd instead of a child process:

```bash
systemd-run --collect \
  --unit=docker-incident-<container>-<epoch> \
  --property=Nice=5 --property=TimeoutStartSec=1800 \
  /bin/bash /usr/local/bin/docker-incident-agent.sh <incident_dir>
```

- `/bin/bash <script>`, not the script path: the host forbids `chmod` on operational scripts, so they carry no executable bit and a direct invocation fails.
- `--collect` removes the transient unit afterwards; the unit name is how you find the run later (`journalctl -u 'docker-incident-*'`).
- One incident at a time: the detector checks `systemctl list-units 'docker-incident-*'` for a running unit before launching. Two agents fighting over the same host is worse than a delayed diagnosis.

## The agent call

```bash
hermes chat --query-file "$DIR/prompt.txt" --oneshot \
  --run-budget 1200 --max-turns 80 -Q ${MODEL:+-m "$MODEL"} > "$DIR/agent.log" 2>&1
```

- `--query-file` avoids shell quoting entirely — the prompt is multi-line Russian with backticks, `<`, `>` and quotes.
- `--oneshot` + `-Q` gives one answer and exits; non-TTY would do it implicitly, but be explicit.
- `--run-budget` / `--max-turns` bound the cost of a runaway diagnosis; wrap in `timeout` as a second layer.
- `--yolo` is not needed: dangerous-command approvals resolve automatically in this non-interactive root session, and leaving approvals on keeps a second gate in front of destructive commands.
- `-m emergency` **only** when the incident is the gateway itself (`litellm`, `litellm-redis`) — the alias (`model.aliases.emergency` → opencode-go `deepseek-v4.1-flash`) is defined in `/root/.hermes/config.yaml` and does not depend on LiteLLM. For every other container the normal chain with its fallbacks is better quality.

## Prompt skeleton

1. State that this is an automatic wake-up and no questions will be answered.
2. Give the container, the detector trigger, and the evidence directory with a one-line description of each file.
3. Demand the **cause**, with the exit-signature map (137/OOM, 1-after-start, 143, RestartCount=0 → external stop).
4. Point at the runbook and at `docker-compose-traps`; tell it to separate known noise (§8) from a real fault.
5. Enumerate what may be done autonomously and what is forbidden without the owner (rm, prune, `down -v`, DB restore, `.env`, foreign containers).
6. Require the pause flag around manual container work.
7. Fix the output contract: last block is `ОТЧЁТ:` + `причина / что сделал / состояние`, Russian, terse, no secrets.

## Report delivery (from the shell script, not the agent)

```bash
report=$(python3 - <<'PY' … split on last 'ОТЧЁТ:' … PY)
# escape &, <, > then send as HTML <pre> via Bot API
```

- Split on the **last** occurrence of the marker: the agent often discusses the report format earlier in its answer.
- If the marker is missing (crash, timeout, rc≠0), send the tail of `agent.log` with the rc — a silent incident is worse than a bad report.
- Credentials come from `/home/ai_service/notifications/.env` (`BOT_TOKEN`, `BOT_OWNER`), read inside Python, never printed and never interpolated into a shell command line.
- Success line is `report sent ok=True` in the unit journal — that is the end-to-end assertion for the whole pipeline.
- Keeping delivery in the shell layer means the owner is informed even when the agent forgets to report, and the agent's own output stays auditable in `agent.log`.
