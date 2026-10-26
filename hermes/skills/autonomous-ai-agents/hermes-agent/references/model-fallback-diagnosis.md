# Model fallback and stream-shape diagnosis

Use when the user says the wrong model answered («должен был ответить X, а ответил Y»), or a session header names a model they never configured.

## Confirm from the log, not the header

The `Model:` line in the system prompt is a snapshot from the last context rebuild, so a fallback that started mid-session appears there only after compression. The log is authoritative:

```bash
grep -n -B12 "Fallback activated" ~/.hermes/logs/agent.log | tail -40
```

Read three things per event: the `API call failed (attempt 3/3) error_type=... summary=...` warning, the `provider=/ base_url=/ model=` of every failed attempt, and the `Fallback <primary> → <fallback> (<provider>)` line. **Log timestamps are host-local** (MSK on this VPS, UTC in containers) — convert before matching an event to a chat turn, or you will blame the wrong turn.

Fallback is decided **per request**, not sticky: the next turn retries the primary from scratch, so one session can show some turns on the primary and later turns on the fallback.

## Resolve the configured chain

```bash
hermes config get model
```

Prints `default` (primary model), `provider`, `base_url`, `api_mode`, and an `aliases:` block — `aliases.emergency` is what Hermes falls back to. Keys live in `~/.hermes/.env`; when config stores `${VAR}`, the resolved name is usually `HERMES_CUSTOM_<host>_<port>_API_KEY` (host/port with dots and colons replaced by underscores). Never print the value; source the file in the shell instead:

```bash
set -a; . ~/.hermes/.env; set +a
```

## Classify the failure

- `APIConnectionError` — endpoint down or restarting. Transient; check the service, not the config.
- Auth error / 401 — wrong key for that `base_url`; the key in `.env` and the provider block disagree.
- **`EmptyStreamError: ... Provider returned an empty stream with no finish_reason` with `http_status=200`, `chunks>0`** — the endpoint streams bytes Hermes cannot parse. Typical cause: a proxy (Open WebUI, LiteLLM, custom gateways) that answers `/chat/completions` with **Responses-API events** instead of chat chunks — `data: {"type":"response.created","response":{"id":"resp_...","instructions":"..."}}`. There is no `delta.content` and no `finish_reason`, so the turn looks like an empty stream: three attempts, then fallback.

## Probe stream vs non-stream before touching config

```bash
curl -sN -X POST "$BASE/chat/completions" -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"<model>","stream":true,"max_tokens":200,"messages":[{"role":"user","content":"ok"}]}' | head -c 800
```

Repeat with `"stream":false` and parse the body. Interpretation:

- stream carries `type: response.*` events and no `finish_reason` → Responses-API events on a chat endpoint, i.e. the proxy's streaming branch, not Hermes.
- non-stream returns `finish_reason: "stop"` plus content → the request and the model are fine; only the streaming path is broken.
- both fail → go back to §Classify; it is not a stream-shape problem.

## Fix

- Check whether the proxy even has a Responses endpoint before proposing `api_mode: codex_responses`:

```bash
curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/responses" \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"<model>","input":"ok"}'
```

`405 Method Not Allowed` means that mode is unavailable — do not recommend it.
- Working escape hatch, documented in `config.yaml` for exactly this case: `hermes config set model.streaming false` (`model.streaming`, not `display.streaming`). Cost: no live token rendering; it applies to the whole agent, including subagents.
- The durable fix belongs on the proxy — convert Responses events into chat chunks in its streaming branch. Say that plainly instead of presenting a client-side workaround as the real fix.
- Config edits need the user's explicit approval on this VPS: propose the command, do not run it.

## Report shape

Verdict first («не другой моделью вместо, а fallback после трёх неудач»), then the log evidence with times, the mechanism in one paragraph, then the fix with its cost. He checks claims against the log — quote `error_type` verbatim and name the actual upstream model id returned by the endpoint.
