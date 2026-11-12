---
name: lyria-music-bot
description: "Use when touching the Lyria music bot or its enricher."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [devops, lyria, music-bot, openwebui, litellm]
---

# Lyria music bot (deploy/music_bot)

## When to Use

Любая работа с музыкальным ботом (контейнеры `lyria-*`): генерация, обогащение, деплой, вопросы про ударения, миграция на Suno, правка пайпа `enricher` в Open WebUI.

## Architecture — где что живёт

- **Бот** (`/root/deploy/music_bot`, проект compose `lyria`): `bot`, `generation-worker`, `enricher-worker`, postgres/redis/rabbitmq (TaskIQ).
- **Энричер НЕ в боте.** Промпт и логика обогащения живут в Open WebUI как **pipe-функция** `enricher` (таблица `function`, ~14.7 KB, `is_active=t`); модель OWUI `enricher` — это её pipe-модель. Рядом неактивный `lyria_enricher` (2-stage) — не трогать.
  - Валивы пайпа: `API_BASE_URL=http://litellm:4000/v1`, `API_KEY` (ключ LiteLLM с алиасом `Other`), `MODEL_POET`/`MODEL_PRODUCER`, `MAX_TOKENS=1200`, `TIMEOUT=110`. Меняются через `POST /api/v1/functions/id/enricher/valves/update` (обычный POST на `/valves` даёт 405).
  - Бот ходит в OWUI: `ENRICH_URL=https://ai.esmien.ru/api/v1/chat/completions`, `ENRICH_MODEL=enricher`, `ENRICH_TOKEN` = API-ключ OWUI (таблица `api_key`, plaintext).
- **Генерация идёт МИМО LiteLLM**: `src/domains/generation/service.py::generate_song_real` напрямую в `https://openrouter.ai/api/v1/chat/completions` с `OPENROUTER_API_KEY` и `MODEL_ID` (SSE, base64-дельты, `modalities: [text, audio]`). Единственная точка замены провайдера — `generate_song_real`; её вызывает только `run_generation`.

## Деплой: главная ловушка compose

`.env` содержит `COMPOSE_FILE=infra/docker-compose.yml` и `COMPOSE_PROJECT_NAME=lyria`. Запускать **только из корня репо**: `cd /root/deploy/music_bot && docker compose up -d --no-deps --force-recreate <service>`.
Если указать `-f infra/docker-compose.yml`, project dir = `infra/`, project name станет `infra` и поднимется **дублирующий стек** `infra-postgres/redis/rabbitmq` (имя из .env не подхватится). Убирается `docker compose -p infra -f infra/docker-compose.yml down --remove-orphans`.
`docker compose create` тянет зависимости (`lyria-migrate`) и падает на `No such image`; `create` не знает `--no-deps`.

## Обогащение: контракт

Валидатор бота (`domains/enricher/validator.py`) ждёт JSON: `genre_and_style, mood, instrumentation[], tempo_bpm, vocal_style, language, lyrics, song_structure[]`; вырезает диакритику и ё, регистр не трогает. Ответ не по контракту не падает — возвращается сырым текстом (`validate_enriched_prompt`), поэтому «кривой JSON» виден как текст в сообщении.

## Ударения: что проверено

- Промпт пайпа сохраняет авторский капс внутри слова как разметку ударения (`занОзою`).
- **Lyria 3 Pro капс игнорирует** — и без инструкции, и с системным сообщением «заглавная = ударный слог». Доки OpenRouter/Google не описывают управления произношением вообще (только язык промпта и `(...)` для бэков).
- Поэтому для Lyria остаётся: уходить от слов с плавающим ударением либо пробовать дефисную запись (`ЧЕ-тверть`) — не подтверждено.
- Если добавляешь системное сообщение в `generate_song_real`, помни: провайдер его принимает (HTTP 200), но эффекта на пение нет — не тратить на это время повторно.

## Suno как провайдер (проверено на живом ключе)

`sunoapi.org` — **реальный Suno**, но неофициальный прокси: треки открываются на `suno.com/song/<id>` под пул-аккаунтом, `model_name: chirp-hawk`, всегда 2 клипа на генерацию. Оператор — MIRA MUSE LLC, общий бэкенд с kie.ai/api.box; сканеры (ScamAdviser 16/100 и др.) плохие, партнёрства с Suno нет. Риск: забанят пул — сервис умрёт.

API: `POST https://api.sunoapi.org/api/v1/generate` (HTTP **200**, `data.taskId`; обязательны `customMode`, `instrumental`, `model`, `callBackUrl` — заглушка `https://example.com/callback` работает) → поллинг `GET /api/v1/generate/record-info?taskId=…` (`PENDING → TEXT_SUCCESS → SUCCESS`, ~40 с) → `data.response.sunoData[].audio_url` (их CDN `tempfile.aiquickdraw.com`, `audiostream.api.box`; скачивать сразу). Маппинг: стиль = genre+mood+instrumentation+tempo+vocal (≤1000 симв.), лирика как есть, `model=V6`, отмена у них невозможна — кредит списывается.

## Прочее

- Open WebUI: БД — Postgres `webui_db` на хосте (не sqlite: `webui_data/webui.db` — пустышка); модели в таблице `model`, системный промпт в `params->>'system'`.
- Репо бота — отдельный git-проект: правки кода согласовывать с владельцем, авто-синка нет.
