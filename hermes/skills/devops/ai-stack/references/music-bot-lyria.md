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

## Обогащение промпта (`enricher`): модель, формат Lyria, где править

Обогатитель — **не модель LiteLLM**, а workspace-модель Open WebUI: `webui_db.model`, id=`enricher`, `base_model_id`, `params->>'system'`, `params->>'temperature'`. Бот ходит в неё по `ENRICH_URL=https://ai.esmien.qd.je/api/v1/chat/completions` с `ENRICH_TOKEN` и `ENRICH_MODEL=enricher`.

- **Базовая модель: `chat.google/gemini-4-argon`, temperature 0.85.** На `claude-haiku-5.5` с temperature 0.3 русский стих был пресным и без метра, а ответ шёл ~50 с; gemini даёт ~8 с и заметно лучше держит рифму/слог.
- `params` — колонка типа **text**, не jsonb: обновлять через `jsonb_set(params::jsonb, …)::text`, иначе `operator does not exist: text ->> unknown`. `updated_at` — epoch bigint, обновлять в том же UPDATE.
- System-промпт обязывает модель использовать словари Lyria (жанры, инструменты, вокальные профили) и жёсткие правила стиха (куплет 4 строки, 7–10 слогов, ABAB/AABB, без саморифмы, припев меняется, штампы под запретом, блочная разметка `[Verse 1]`/`[Chorus]`). Текущая версия — `references/enricher-system.md`, старая (для отката) — `references/enricher-system-legacy.md`.

**Формат Lyria — главное.** Lyria 3 Pro принимает один английский бриф по формуле Google:
`[genre and style] + [mood] + [instrumentation] + [tempo and rhythm] + [vocal style & language] + [Lyrics: текст]`, слоты подписаны `Lyrics:` — под ним текст с секциями; бэки в скобках. Отправлять в модель JSON-блоб (как было до 28.10.2026) — потеря формата: модель видит структуру данных, а не музыкальное ТЗ.
Поэтому в `domains/enricher/handlers.py` есть `_lyria_brief_from_json()`: рендерит бриф из JSON-контракта в правильном порядке (жанр → настроение → инструменты → BPM → вокал/язык → Structure → Arrangement → `Lyrics:`), а `_build_generation_prompt()` сначала пробует его и только потом — старую обёртку. UI-предпросмотр продолжает работать на JSON, контракт валидатора не менялся.

**Главный принцип: энричер — аранжировщик, а не поэт.** Бот нужен владельцу, чтобы превращать **готовые стихи** в музыку, поэтому текст автора неприкосновенен: никакой переписи, никаких досозданных или размноженных строк, число строк в `lyrics` = числу строк автора. Припев (`[Chorus]`) — только если автор сам повторил строфу или помечал «припев». Правила стихосложения (слоги, ABAB) включаются только в Сценарии Б — когда на входе одна идея, а не текст.

### Финальная схема (состояние на 28.10.2026, 15:10 UTC)

| Что | Значение |
|---|---|
| Живой обогатитель | функция `enricher` (pipe), `is_active=t` |
| Модель для ручных тестов | `sound-producer` (base `other.google/gemini-4-argon`) — в живом пути НЕ участвует |
| Первый пайп | `lyria_enricher` — `is_active=f` (оставлен как история) |
| ENRICH_MODEL | `enricher` в `/root/deploy/music_bot/.env`, читают `bot` И `enricher-worker` |
| Argon | ключ подключения `other` (`openai.api_keys[4]`), модель `google/gemini-4-argon` на `litellm:4000` |
| Decider | ключ OpenRouter, `perplexity/pplx-decider-v1.2` |
| Рендер брифа | `_lyria_brief_from_json` в коде бота (коммит `d80d021`) |

**Бесплатная проверка перед тратой $0.08** (когда пользователь уже в `waiting_for_approval`): взять `enriched_prompt` из Redis FSM и прогнать через валидатор и рендер внутри контейнера — видно все 8 полей, число строк и готовый бриф без запроса в Lyria:

```bash
docker exec lyria-redis redis-cli get fsm:<uid>:<uid>:data > /tmp/fsm.json   # {"prompt":…,"enriched_prompt":"<json>"}
docker cp /tmp/fsm.json lyria-bot:/tmp/fsm.json   # затем valide + _build_generation_prompt(text=…)
```

Ожидаемо: `brief_has_json_leak: False`, `Lyrics:\n` присутствует, число строк lyrics = авторскому (режим poem) или 18–20 (режим idea).

**Быстрая диагностика живого пути** (`docker logs lyria-enricher-worker --since 10m`): строка `POST https://ai.esmien.qd.je/api/v1/chat/completions "HTTP/1.1 200 OK"` + `Enrichment completed` = пайп ответил; `Enricher returned None` = non-2xx (чаще всего воркер смотрит на выключенный/несуществующий id модели), а `Enrichment failure delivered (attempt=1/3)` = уже отдалось пользователю.

**Живой путь (с 28.10.2026, ночь): пайп `enricher`** — бот и воркер не менялись, `ENRICH_MODEL=enricher` теперь резолвится в OWUI-функцию, а не в модель. Схема: pplx-decider → `poem`/`idea` → **один** вызов `google/gemini-4-argon` с общей JSON-частью и одной из двух преамбул → санитайзер. Старая модель `enricher` переименована в `sound-producer` (её промпт — ручной стенд, не в живом пути).

- **Маршрутизация:** `perplexity/pplx-decider-v1.2` через `https://openrouter.ai/api/alpha/decisions` (choice `poem`/`idea`). Замеры на 20 кейсах: явные 14/14, задержка 0.3–0.5 с, цена `$2.2e-06` за вызов, ошибок 0. На реальной неоднозначности модель сама отдаёт низкую вероятность («одна строка» → 0.55) — поэтому в пайпе порог 0.7 и **фоллбэк на `poem`** при любой ошибке/таймауте/низкой уверенности: худший исход — стих приняли за стих, а не переписали.
- **Ключи:** decider — OpenRouter-ключ; Argon — ключ подключения `other` из OWUI (`openai.api_keys[4]`), оба в valves пайпа и в `/root/.config/lyria-decider/` (600). LiteLLM не трогается: оба ключа уже имеют доступ к нужным моделям.
- **Правка кода функции в OWUI — кэш.** После create/update модели не видны в чате (`Model '' was not found`), потому что `process_chat` читает `app.state.OPENAI_MODELS`. Лечится `GET /api/models?refresh=true`, перезапуск не нужен.
- **Режимы:** `poem` — текст автора неприкосновенен, число строк равно авторскому, `[Chorus]` только если автор сам повторил строфу; `idea` — сочинение с нуля с метром/рифмой/запретом штампов. Общая часть (словари Lyria, схема JSON, орфография без ё) — **один экземпляр** `SHARED`, преамбулы только добавляются — копипаста промптов нет.

**Старая модель (на случай отката):** `sound-producer` в OWUI, haiku-5.5, temp 0.85 — если нужно вернуть односторонний путь, достаточно `ENRICH_MODEL=sound-producer` и пересоздать `bot` + `enricher-worker`.

**OWUI-Pipe `lyria_enricher` — выключен** (первая версия с критиком; исходник в `scripts/lyria-enricher-pipe.py`).

1. **Songwriter** (`google/gemini-4-argon`, temp 0.85, max_tokens 900) — пишет текст с тегами секций, 4 строки по 7–10 слогов, без штампов.
2. **Critic & producer** (та же модель, temp 0.25, max_tokens 1100) — правит метр/рифмы, собирает поля Lyria и отдаёт строгий JSON контракта бота.
3. **Санитайзер** — режет markdown, `json.loads`, дефолты для недостающих полей; если JSON не собрался — возвращает текст, и бот уходит в фоллбэк raw-строки.

Зачем max_tokens: без потолка Argon иногда генерил 60–90 с и упирался в `REQUEST_TIMEOUT_SECONDS=120` в `domains/enricher/service.py`; с потолком — 12–15 с.

**Управление pipe (API Open WebUI, админ-токен через `POST /api/v1/auths/signin`, пароль `OWUI_ADMIN_PASSWORD` из `/root/.config/owui-signup-approver/env`):**

```bash
# создание: type определяется автоматически по наличию класса Pipe/Valves
POST /api/v1/functions/create   {id, name, meta:{description,manifest}, content}
POST /api/v1/functions/id/<id>/toggle            # активировать — иначе модели не видно
POST /api/v1/functions/id/<id>/valves/update     # ВАЖНО: тело — ПЛОСКИЙ dict, не {"valves": {...}}
POST /api/v1/functions/id/<id>/update            # правка кода + commit_message = версия в истории
GET  /api/v1/functions/id/<id>/history           # внутренний git OWUI: parent_id, commit_message, diff
```

`valves/update` с обёрткой `{"valves": …}` молча возвращает `{}` и ничего не сохраняет — потом pipe падает с `Illegal header value b'Bearer '` (пустой ключ).

Ключ для pipe — отдельный LiteLLM-ключ, а не мастер: `POST http://127.0.0.1:4000/key/generate {"key_alias":"owui-lyria-enricher","models":["google/gemini-4-argon"]}`. Чужую модель такой ключ отдаёт `403`, что и нужно.

**Проверка pipe без Telegram:** `POST /api/v1/chat/completions` на `127.0.0.1:8080` с токеном бота (`ENRICH_TOKEN`) и `model=lyria_enricher` — свежий запрос и запрос с историей правок; оба должны дать JSON с 8 полями.

**Смена `ENRICH_MODEL` — это ДВА контейнера.** Обогащение выполняет `lyria-enricher-worker`, а не `lyria-bot`: он читает env один раз при старте. Пересоздал только `bot` — воркер продолжает ходить по старому имени модели и получает `Model not found`, а в логах это выглядит как `Enricher returned None` (сервис возвращает None на любой non-2xx). Пересоздавать оба: `up -d --no-deps bot enricher-worker`.

**Правка кода бота = пересборка образа** (код вшит, volume нет):

```bash
cd /root/deploy/music_bot/infra
docker tag lyria-bot:latest lyria-bot:rollback-$(date +%Y%m%d)   # откат
 touch /var/lib/docker-autorecover/pause
docker compose --env-file ../.env -f docker-compose.yml build bot
docker compose --env-file ../.env -f docker-compose.yml up -d --no-deps bot
rm -f /var/lib/docker-autorecover/pause
```

Compose-переменные `COMPOSE_PROJECT_NAME`, `REDIS_HOST` и прочие лежат в `/root/deploy/music_bot/.env`, а не в `infra/` — без `--env-file ../.env` подстановка молча врёт.

**Проверка промпта без Telegram:** вызвать обогатитель напрямую (`ENRICH_URL` + `ENRICH_TOKEN`, `model: enricher`) и глазами посмотреть JSON; затем проверить, что в `generations.prompt` лежит бриф, а не JSON (`select prompt from generations where id=…`).

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

