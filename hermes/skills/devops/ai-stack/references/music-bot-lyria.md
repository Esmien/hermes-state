# Music bot (lyria)

> Loaded from the `ai-stack` skill. Read this when the separate lyria deployment (its own Postgres/Redis/RabbitMQ).

## Music bot (lyria)

A second, self-contained deployment on the same host — aiogram Telegram bot + taskiq workers, images built locally (image name == container name).

| Container | Role |
|---|---|
| lyria-bot | Telegram bot + aiohttp webhook server on 127.0.0.1:8000 |
| lyria-generation-worker | taskiq consumer, generation queue |
| lyria-enricher-worker | taskiq consumer, metadata enrichment |
| lyria-postgres / lyria-redis / lyria-rabbitmq | its own datastore — `postgres:17-alpine`, `redis:7-alpine`, `rabbitmq:3-management` |

- **Its own Postgres** — `lyria-postgres`, credentials `lyria`/`lyria`, tables `generations`, `users`, `generation_feedbacks`. This is NOT the host Postgres and NOT `webui_db`/`litellm_db`; it is **not backed up** by the `postgres-backup` timers and not in `backups/postgres/`. Say so explicitly if the user assumes their music data is covered by backups.
- **Startup AMQP errors are expected and benign.** Workers boot before `lyria-rabbitmq` is accepting, so their logs contain an `aiormq.exceptions.AMQPConnectionError: [Errno 111] Connect call failed` traceback, followed seconds later by `Worker ... is listening for tasks...` and `Listening started.` — tenacity reconnects. Do NOT report these as a fault; judge worker health by the presence of the `Listening started.` line after them and by queue consumers, not by the traceback count.
- **Health check = consumers, not logs.** `docker exec lyria-rabbitmq rabbitmqctl list_queues name messages messages_unacknowledged consumers` — a healthy stack shows `1` consumer on `dev.generation.tasks` and `dev.enricher.tasks`, and `0` on every `dead_letter` queue. Anything sitting in `*_dead_letter` is a genuinely failed task worth surfacing. (`rabbitmqctl` can take ~10-60 s to answer — give the call a generous timeout.)
- **`generations` rows left in `pending` are not necessarily broken.** On a graceful restart, in-flight generations are often left as `pending` rows that no queue message backs, so they never drain on their own. They do not block the workers. Before treating them as a bug, check whether anything is actually queued (`messages` column above) and how old they are.
- Restart with `docker restart <container>`; there is no compose file and no systemd unit to use.
- **`edge-tts` runs on `stack-net` but belongs to neither this bot nor OWUI** — it is a leftover TTS attempt for Open WebUI; see "Media pipeline" above.
- **Song generation goes straight to OpenRouter, NOT through LiteLLM.** `src/domains/generation/service.py` POSTs `https://openrouter.ai/api/v1/chat/completions` with `stream: true, modalities: ["text","audio"], audio: {"format":"mp3"}` and the bot's own `OPENROUTER_API_KEY` — so songs never reach `LiteLLM_SpendLogs` and get no gateway limits or fallback. Enrichment *does* use the stack (`ENRICH_URL=https://ai.esmien.qd.je/api/v1/chat/completions`, model `enricher`), so one feature has two different routes to the same provider. If the user asks for unified spend/limits, name this split; routing generation through the gateway is a real change (streaming audio passthrough), not a config tweak.
- **The SSE audio assembly is the delicate part and it is already correct — do not "simplify" it.** Base64 is decoded incrementally with 4-char alignment kept between chunks, cumulative chunks are tracked by an `index`/`offset` cursor (falling back to length), `MAX_AUDIO_B64_LEN` is 40 MB with `MAX_SSE_LINE_LENGTH` deliberately larger (one cumulative line can carry the whole file), and a missing terminal `[DONE]` raises instead of yielding a truncated mp3. Saving is temp-file + atomic rename with sha256 stored, and delivery re-checks size and checksum. A review of this project should say so before listing gaps.
- **`AUDIO_STORAGE_PATH=/data/audio` has NO volume.** `docker inspect lyria-bot lyria-generation-worker --format '{{json .Mounts}}'` returns `[]` for both: mp3s live in the container's writable layer, so any rebuild wipes them while `generations` rows keep a dead `audio_path`, and nothing prunes the layer (~4 MB per song). This is the first structural gap to report — ahead of style remarks — and the fix is a named volume plus a retention sweep in the worker.
- **Credits are derived, not counted:** remaining songs = OpenRouter key balance ÷ `SONG_PRICE` (0.08) from `/api/v1/key`. Elegant, but it lies when the model price changes or the key has no spend limit.
- **Judge this project by its own data, not by vibes.** `docker exec lyria-postgres psql -U lyria -d lyria -tAc "select status, count(*) from generations group by 1"` plus the queue-consumer check above: a deployed-but-idle bot (all rows on one date, `0` messages queued, `1` consumer per queue) is ready, not broken, and "no generations in 72 h" means untested — never present it as a failure or as proof the pipeline works.

