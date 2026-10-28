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

## E2E прогон пользовательских сценариев

`scripts/lyria-e2e.py` — прогон всех юзер-стори без ручных нажатий: `python3 scripts/lyria-e2e.py` (~10 мин, ~$0.32 = 4 генерации; `--no-generate` — только бесплатные сценарии). Апдейты форжатся на `http://127.0.0.1:8000/webhook`, проверки — по БД `lyria-postgres` и логам.

**Механика форжа.**

- Секрет вебхука и `BOT_ACCESS_KEY` читать только через `docker exec lyria-bot printenv …` в память; в чат и логи не выводить. Заголовок — `X-Telegram-Bot-Api-Secret-Token`.
- `update_id` брать из своего диапазона (например 1_1xxxxxxxxx), чтобы не пересечься с настоящими апдейтами Telegram.
- Стикер в апдейте обязан иметь `type: "regular"` — без него aiogram падает на валидации Update (`message.sticker.type Field required`), и это выглядит как «бот упал на стикере», хотя виноват стенд.

**Грабли (проверено 2026.10):**

1. `callback.answer()` на форж-callback всегда даёт `query is too old` — у синтетического `callback_query` нет настоящего `query_id`. Хендлеры, где `answer()` стоит ДО полезной работы, обрываются: **«Подтвердить», «Без обогащения», «Оставить как есть»**. Обход: собрать состояние production-кодом (`save_enriched_prompt` + `_build_generation_prompt` + запись FSM `GenerationStates.waiting_for_title`) и отправить название обычным сообщением. Шаги, где `answer()` в конце (`fb:like/dislike/send/finish`) или после смены состояния (`prompt:edit`), проходят честно.
2. `docker logs` пишет в **stderr** — читать stdout+stderr, иначе лог пустой.
3. Событие обогащения (`Enrichment result delivered`) логирует **lyria-enricher-worker**, а не бот: ждать маркер в обоих контейнерах.
4. Ответы бота прочитать нельзя (Bot API не отдаёт историю чата). `editMessageReplyMarkup` годится как щуп: при `ok:true` возвращает `text`, но **снимает клавиатуру**; на сообщениях без клавиатуры отвечает `message is not modified` и текста не отдаёт. Читать только окно свежих сообщений и только один раз.
5. Точный последний `message_id` чата: `sendMessage` → взять `message_id` → `deleteMessage`. Бинарный поиск по id ненадёжен (дыры от удалённых) и попутно снимает клавиатуры.
6. Ждать `cancelled` нужно опросом до 60–90 с: после `/cancel` запись ещё остаётся `processing`, хотя отмена уже сработала.
7. Строки `Необработанная ошибка … query is too old` в логах — шум стенда, не баг бота: фильтровать при проверке «нет падений».

**Найденные дефекты (актуальны на 28.10.2026, отдельными задачами не закрыты):**

- 🔴 `/credits`, `/logout` и любая неизвестная команда в состоянии `waiting_for_idea` уходят в обогащение как текст песни: `handle_idea` ловит `F.text` без `NotCommand`.
- 🟠 Фантомные `pending`-записи: `approve` вызывает `save_enriched_prompt` (создаёт Generation), следом `generate_and_send` создаёт вторую. На каждый трек остаётся вечная PENDING-строка без аудио — поэтому «4 pending на 3 success» не означает оборванные генерации.
- 🟠 Отмена после старта запроса не экономит: статус `cancelled`, mp3 выбрасывается, но OpenRouter уже списал деньги (~$0.08; сверять `usage` из `/api/v1/key`).
- 🟡 Стикер/гифка в `waiting_for_idea` — тишина, никакой подсказки.
- 🟡 Антибрутфорс ключа: 5 ошибок → сообщение и сброс счётчика, кулдауна нет — перебор не ограничен по времени.
- ⚪ `AUDIO_STORAGE_PATH` без volume: mp3 живут только в слое контейнера.

**Проверки после прогона:**

```bash
docker exec lyria-postgres psql -U lyria -d lyria -tAc "select id,status,delivery_status,audio_size,title from generations where id>8 order by id"
docker exec lyria-postgres psql -U lyria -d lyria -tAc "select generation_id,is_liked,feedback from generation_feedbacks"
```

Баланс до/после — `docker exec lyria-bot printenv OPENROUTER_API_KEY` + `GET https://openrouter.ai/api/v1/key` (ключ в чат не печатать).

**Уборка:** после прогона в чате десятки тестовых сообщений, снятые клавиатуры и тестовые строки в БД (3 трека + фантомные pending). FSM чистить `/cancel`; чужому пользователю (`OTHER`), у которого тестировали доступ, вернуть `is_authorized=true` (скрипт делает это сам в S1/S11).

