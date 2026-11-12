# Open WebUI internals: где живёт состояние и как его читать/править

Глубина к `ai-stack` SKILL.md: карта хранения состояния OWUI (`webui_db` + контейнер) и грабли, которые стоят лишних десяти инструментов. Схема песочниц — `sandbox-terminal.md`, обновление образа — `updates.md`.

## Карта состояния

| Что | Где |
|---|---|
| настройки инстанса (в т.ч. `terminal_server.connections`, `tool_server.connections`, `ui.*`, `task.*`) | таблица `config`, ключ → JSON в `value` |
| workspace-инструменты (Python-тулзы, «Image Ref Generator» и пр.) | таблица `tool`: `content` (исходник) + отдельная колонка `valves` (значения полей формы) |
| pipe-функции (модели-пайпы, напр. `enricher`) | таблица `function`: `content` (код) + `valves` (JSON с моделью/URL/ключами); в таблице `model` такая модель есть, но с **пустым `base_model_id`** и без `params->>'system'` |
| чаты | таблица `chat`, поле `chat` — JSON (id, title, models, messages, history, files, tags) |
| файлы/вложения | таблица `file` + диск `/app/backend/data/uploads` (в контейнере) |
| состояние сессии/выбора в UI | **не в БД** — `localStorage` браузера |

Читать БД: `sudo -u postgres psql -d webui_db -tAc "…"`.

## Никогда не выбирать значение целиком

`select value from config where key='ui.default_interface_settings'` вернул 227 КБ: внутрь JSON вшит `backgroundImageUrl` как base64-JPEG. То же у `settings` пользователя и у `tool.valves`.

Правило: сначала структура, потом точечное значение.

```sql
select jsonb_object_keys(value::jsonb) from config where key='ui.default_interface_settings';
select jsonb_object_keys(valves::json) from tool where id='<tool_id>';
select length(content), content like '%<маркер версии>%' from tool where id='<tool_id>';
```

Секреты (ключи в `valves`, токены в конфигах) в чат не выводить — только имена ключей и наличие.

## Персональный системный промпт и миграция

При инвентаризации промптов проверяй `user.settings::jsonb -> 'ui' ->> 'system'`, выводя только агрегаты по роли и длину, не тексты. Например: `select role, count(*), min(length(settings::jsonb->'ui'->>'system')), max(length(settings::jsonb->'ui'->>'system')) from "user" where coalesce(settings::jsonb->'ui'->>'system','') <> '' group by role;`. JSON null не является объектом: перед `jsonb_object_keys` проверяй `jsonb_typeof(...)='object'`.

При переносе в файлы сопоставляй `user.id` с `state.json` и проверяй принадлежность каталога, а не email; admin и pending могут не иметь песочницы. Сначала проверь полный перенос каждого промпта без обрезания и перезаписи существующего профиля, затем согласованно отключай пользовательские промпты и только после проверки очищай исходные значения. Не затрагивай админские промпты моделей в `model.params` и проверяй итоговый порядок системных инструкций на реальном запросе. `chat.system_prompt` — разрешение интерфейса/сохранения настроек; не считай его доказанной блокировкой system-сообщений через API. Источник: https://docs.openwebui.com/features/authentication-access/rbac/permissions

## Pipe-функция = модель без базовой модели

Модель с пустым `base_model_id` и пустым `params->>'system'` — это не «сломанный пресет», а pipe: поведение (и промпт) лежит в `function.content`, параметры — в `function.valves`. Смотреть так:

```sql
select id, type, is_active, length(content) from function order by length(content) desc;
select coalesce(valves::text,'<null>') from function where id='<pipe_id>';
```

`valves` содержат ключи провайдеров — печатать только имена полей и значения, не являющиеся секретами (модель, URL, лимиты, таймаут).

**Правка valves — только через API, не SQL-ом:** `GET /api/v1/functions/id/<id>/valves` читает, `POST /api/v1/functions/id/<id>/valves/update` пишет (POST на `/valves` без `/update` отвечает `405`). API перезагружает значения в памяти процесса; правка строки в БД без рестарта контейнера не подхватится. Тело шлём целиком тем же объектом, что вернул GET (иначе теряются остальные поля).

**Аутентификация для этих ручек:** bearer = API-ключ админа из таблицы `api_key` (`select key from api_key where user_id='<admin uuid>';`) — он там в открытом виде. Самодельный JWT, подписанный `WEBUI_SECRET_KEY`, OWUI 0.13.3 отвергает (`401 Invalid token`): не тратить время на минт токена.

### Ключ OWUI — прод-секрет, а не тестовый креденшл

`api_key` — одна строка на юзера, и её читают сразу несколько внешних клиентов: кастом-провайдер Hermes (`HERMES_CUSTOM_127_0_0_1_8080_API_KEY` в `/root/.hermes/.env`) и обогатитель музыкального бота (`ENRICH_TOKEN` в `/root/deploy/music_bot/.env`, три контейнера). Поэтому:

- **`POST /api/v1/auths/api_key` — это РОТАЦИЯ**, а не чтение: старый ключ аннулируется мгновенно, Hermes и бот начинают получать `401`, в чате это выглядит как «ты сломал мне ключи». Для чтения — `select key from api_key where user_id=…` в БД; `GET /api/v1/auths/api_key` отдаёт замаскированное значение.
- Если ротация уже произошла: записать новый ключ `sed`-ом в оба файла (не печатая его), пересоздать `bot`/`enricher-worker`/`generation-worker` (env читается только при старте) и перезапустить Hermes — он держит старую копию в памяти процесса.
- Проверка живости — не `/api/v1/models` (он отдаёт `200` и при урезанном доступе), а реальный вызов: `POST https://ai.esmien.ru/api/v1/chat/completions` с `model: enricher` и этим токеном.

**Внутренние ручки ≠ OpenAI-совместимые.** `/api/chat/completions` и прочие `api.chat.*`-эндпоинты требуют живой человеческой сессии и на automation-токен отвечают `403`; для скриптов и проб использовать OpenAI-совместимый `/api/v1/chat/completions` (и `/api/v1/models`), который принимает тот же bearer.

### Кастомная модель = соединение + id в LiteLLM

Строка `model` в OWUI хранит `base_model_id` как `<prefix_id>.<model_name>` — префикс берётся из соединения (`openai.api_base_urls`/`api_keys`, поле `prefix_id`), а хвост обязан совпадать с `model_name` в LiteLLM. Префикс срезается перед вызовом, поэтому одна и та же группа живёт под несколькими id: `openai/…`, `other/…`, `chat./…`, `aider./…`. Отсюда две частые ошибки: правка маршрута «не подействовала», потому что модель смотрит в другую группу; и модель не видна, потому что группы нет в списке `models` у LiteLLM-ключа (у нас — ключ с алиасом `Other`). `capabilities.file_context=false` дополнительно вырезает вложения-документы до RAG, а `vision` не влияет на то, видит ли нога картинки — это свойство ноги, не модели.

**Восстановление удалённой строки `model`:** бэкап — `select to_jsonb(m) from model m where id='<id>'`. При вставке обратно `params` и `meta` приезжают **строками**, и если закастить их в `jsonb` как есть, внутрь ляжет JSON-строка: `params->>'system'` вернёт пусто, а модель будет выглядеть «без промпта». Перед вставкой `json.loads` → `json.dumps` → `::jsonb`.

**psql на хосте:** `su - postgres -c "psql -d webui_db -Atc \"select (params::jsonb)->>'system' …\""` ломается на вложенных кавычках и скобках. Писать SQL в `/tmp/q.sql` и звать `psql -f /tmp/q.sql` — тот же приём уже используется для длинных UPDATE.

## Минифицированный фронт не grep'ать широко

`grep -r` по `/app/build` даёт сотни килобайт кода в одном ответе и режет контекст. Инвентарь строк — только `-o` с узким шаблоном, остальное искать в бэкенде:

```bash
docker exec open-webui sh -c "grep -rhoE '\"[a-zA-Z_]*Term[a-zA-Z_]*\"' /app/build | sort | uniq -c | sort -rn | head -25"
docker exec open-webui sh -c "grep -rho '.\{160\}selectedTerminalId.\{200\}' /app/build | head -5"
```

Для API-поверхности терминал-сервера источник истины — `GET /openapi.json` из самого контейнера, а не бандл: там видно, что отдачи байтов файла нет (`/files/read` → JSON, `/files/display` → `{path, exists}`).

## Правка workspace-инструмента

Тул живёт в БД, а не в образе: при пересборке/откате образа он сохраняется, при восстановлении из чистой базы — нет. Порядок:

1. Скопировать текущий `content` в файл-бэкап (`/root/owui-tool-<name>-<версия>.py`).
2. Правку держать в файле репо (`ai-stack/ai/webui-tools/<name>.py`) — это единственная копия для восстановления; править и БД, и файл.
3. Заливать в БД одним `psql -f` с уникальным dollar-tag (`$pyfile_9f3c$…$pyfile_9f3c$`) — контент содержит `$`, кавычки и regex, обычный `-c` с quoting ломается.
4. Проверить: `length(content)` вырос ровно на патч, `content like '%<новая строка>%'` = t, `valves` не тронуты (их не перезаписывать — там ключи).
5. Синтаксис проверять на хосте `python3 -m py_compile` до заливки; в контейнере — `docker cp` + `python3 -c 'import importlib.util…'`, чтобы прогнать чистые функции (например резолв каталога) без вызова модели.

Тул исполняется **в контейнере open-webui под root** (`.Config.User = 0:0`). Всё, что он пишет в пользовательские каталоги, требует (а) bind-mount этого каталога в compose open-webui и (б) `os.chown(path, 1000, 1000)` после записи — иначе пользователь песочницы не сможет файл ни открыть, ни удалить. Fallback для пользователей без песочницы (админ, аноним) оставлять на прежний путь в `/app/backend/data`.

## Клиентское состояние ≠ серверное

Выбор терминала, темы, вкладок живёт в `localStorage`; в чате `terminal_id` не хранится вовсе (`select count(*) from chat where chat::jsonb ? 'terminal_id'` → 0). Отсюда: «включить всем» через БД нельзя, а серверная привязка есть только у модели (`meta.terminalId`). Подробности и последствия — `sandbox-terminal.md` § Binding a model.

## Патчи апстрима (фронт/бэкенд) — последний шаг

Родная ручка (env/конфиг/флаг) → замер → и только по слову владельца дериватив `webui-branding/Dockerfile`. Патч бандла или upstream-Python переживает обновление базового образа только если применён в сборке и **валит сборку** при несовпадении строки — иначе тихо ломает UI после бампа. Цена и формулировка для владельца — в SKILL.md «Answering the owner».

Инжект в `index.html` — единственный способ добавить своё поведение на фронте без правки минифицированных чанков: `COPY <script>.js /app/build/static/` + `sed` в тег перед `</head>` с `grep -q` в том же `RUN`. Статика из `/app/build/static` при старте копируется в `/app/backend/open_webui/static`, поэтому проверять надо оба пути и `curl /static/<file>.js` снаружи.

**Скрипт на загрузке страницы ≠ «после входа»:** вход в SPA не перезагружает документ, токен появляется в `localStorage` уже внутри приложения. Всё, что зависит от токена (свой fetch, выбор терминала, персональные запросы), должно опрашивать его появление; иначе у нового пользователя код не сработает ни разу, а в тесте с заранее засеянным токеном — сработает, и разница будет невидима. Симптом на скриншоте владельца: в `localStorage` нет флага скрипта вовсе.
