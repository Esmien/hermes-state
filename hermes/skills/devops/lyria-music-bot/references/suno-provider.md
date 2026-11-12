# Провайдер генерации Suno в боте `lyria`

Ветка `suno-impl` (разработка только в фича-ветке, каждый шаг — коммит). Ниже — раскладка модулей, политика ошибок и грабли, на которых уже спотыкались.

## Модули

- `src/core/config.py` — `GenerationConfig.GENERATION_PROVIDER` (`lyria|suno`, валидируется), `GENERATION_FALLBACK_TO_LYRIA`, блок `SunoConfig` (`SUNO_API_KEY`, `SUNO_BASE_URL`, `SUNO_MODEL=V6`, `SUNO_CALLBACK_URL`, `SUNO_POLL_INTERVAL_SECONDS=5`, `SUNO_TASK_TIMEOUT_SECONDS=300`, `SUNO_DOWNLOAD_TIMEOUT_SECONDS=120`, `SUNO_MAX_VARIANTS=2`).
- `src/domains/generation/suno.py` — чистая логика без сети: `compose_style`, `build_suno_request` (custom vs simple режим), `parse_task_id`, `parse_record`, `pick_tracks`, `detect_vocal_gender`. Тестируется без моков HTTP.
- `src/domains/generation/suno_client.py` — HTTP: создание задачи → поллинг `record-info` → скачивание всех клипов. Возвращает `list[bytes]` (все варианты), а не один трек.
- `src/domains/generation/service.py::run_generation` — возвращает `list[bytes]`; Lyria и MOCK-режим оборачивают один трек в список. Точка выбора провайдера и фолбэка живёт здесь.
- `src/domains/generation/worker.py` — сохраняет каждый вариант (`save_audio_to_storage(..., variant=N)` → `gen_<id>_vN.mp3`) и отправляет их отдельными аудио («Вариант 2/2»). Падение доставки второго варианта только логируется: основной уже у пользователя.

## Маппинг брифа обогатителя (8 полей) → Suno

- `genre_and_style` + `mood` + `instrumentation[]` + `tempo_bpm` + `vocal_style` + `language` → одна строка `style` (реально ~300 из 1000 символов). Порядок частей важен: при обрезке срезается хвост, поэтому `language`/`vocals` держать в конце осознанно.
- `lyrics` уходит как есть: Suno нативно понимает `[Verse 1]`, `[Chorus]`, `[Outro]` и обогатитель их уже проставляет.
- `song_structure` **намеренно не используется**: Suno не принимает прозу про аранжировку секций, только теги в лирике. Не «чинить» это, вставляя теги в начало текста — испортит структуру.
- `vocalGender` выводить **только из `vocal_style`**. Поиск маркеров в `lyrics` ломает всё: «Female» содержит «male», а «woman/женский» в куплете перебьёт баритон. Регексы — по границам слов, женские маркеры проверяются первыми.
- Есть бриф с `lyrics` → `customMode: true` (поёт наш текст); брифа нет → `customMode: false` и свободный `prompt` (≤3000).

## Политика ошибок и ретраев

- Ретраи только на временных ошибках: сеть, `408/425/429/5xx`. Для этого `retry=retry_if_exception(predicate)`: tenacity вызывает переданный `retry=` с `RetryCallState`, поэтому «голый» callable с аргументом-исключением молча не срабатывает.
- `_check_response` должен вызываться **внутри** ретраемого замыкания: `httpx` не кидает исключение на 429/503, он возвращает `Response`, и проверка снаружи декоратора = ноль ретраев на самых частых отказах.
- `status_code` ошибки брать из поля `code` ответа, а не хардкодить 400.
- Поллинг и скачивание — идемпотентные GET, их ретраить можно свободно; `ReadTimeout` при **создании** задачи не ретраить: задача могла создаться и списаться.
- Таймаут задачи (`SUNO_TASK_TIMEOUT_SECONDS`) → `GenerationTimeoutError`, и **фолбэка на Lyria нет**. Иначе после 5 минут ожидания оплаченной задачи бот молча генерирует вторую и списывает деньги дважды. Пользователю — ошибка с кнопкой повтора.
- Фолбэк на Lyria оставлять только для быстрых отказов: нет ключа/конфига, ошибка создания задачи, `FAILED`/`SENSITIVE_WORD_ERROR`.

## Обязательные проверки перед коммитом

1. **Все точки вызова.** Параметр, протянутый через `start_title_input`/`generate_and_send`, живёт в трёх местах `domains/generation/handlers.py` (`handle_title`, `handle_title_leave_as_is`, `retry_generation`). Пропущенная кнопка «Оставить как есть» отправляет `brief=None` → Suno уходит в simple-режим и поёт по английскому брифу Lyria.
2. **Ручные моки в тестах.** Смена типа возврата (`bytes` → `list[bytes]`) ломает `fake_run_generation` в `tests/integration/test_generation_worker.py`: `variants[0]` от `bytes` даёт `int`, а `variants[1:]` — по букве на «вариант». Грепать `fake_*` и `-> bytes` по всему тестовому дереву, а не только по упавшему шарду (интеграционные тесты не входят в `-m unit`).
3. **Байткод.** `git add -A` в этом репо тащит `__pycache__`: правила `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.ruff_cache/` обязаны быть в `.gitignore` (добавлены; `.pyc` вычищены из индекса). Перед коммитом — `git status --short | grep pycache`.
4. **README ↔ config.** Переменные окружения документируются в таблице README; после переименования настройки (`SUNO_VARIANT_INDEX` → `SUNO_MAX_VARIANTS`) старый ключ вычищать.

## Прогон тестов и линта (без локального venv)

```bash
docker run --rm -v /root/deploy/music_bot:/app -w /app python:3.12-slim bash -lc \
  "pip install -q poetry==2.4.1 ruff && poetry config virtualenvs.create false && \
   poetry install --with dev --no-root >/dev/null 2>&1; \
   ruff check --fix src; ruff format src; \
   python -m pytest src/domains/generation/tests/unit src/domains/enricher/tests/unit -m unit -q --no-cov"
```

`--no-cov` держит вывод коротким. Интеграционные тесты воркера запускаются без маркера и проходят на фейках: `pytest src/domains/generation/tests/integration/test_generation_worker.py -q --no-cov`.

## Живая проверка клиента из контейнера

```bash
docker exec -i lyria-generation-worker python - <<'EOF'
import core.config  # noqa: F401  — без этого циклический импорт core/__init__ → handlers
import asyncio
from domains.generation.suno_client import generate_song_suno

async def main():
    async def progress(stage, fraction):
        print(f"  {fraction:.2f} {stage}")
    audio = await generate_song_suno(prompt="brief", gen_id=999, on_progress=progress,
                                     brief={"lyrics": "[Verse 1]\nтест", "vocal_style": "Male Baritone"},
                                     title="проверка")
    print([len(item) for item in audio])

asyncio.run(main())
EOF
```

После правок `service.py`/`worker.py`/`handlers.py` пересобирать и пересоздавать оба образа: `docker compose build bot generation-worker` + `/root/.hermes/cache/scratch/recreate.sh <service>`. `enricher-worker` пересобирать только если менялись общие контракты (`src/shared/`).
