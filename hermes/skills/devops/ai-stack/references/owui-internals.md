# Open WebUI internals: где живёт состояние и как его читать/править

Глубина к `ai-stack` SKILL.md: карта хранения состояния OWUI (`webui_db` + контейнер) и грабли, которые стоят лишних десяти инструментов. Схема песочниц — `sandbox-terminal.md`, обновление образа — `updates.md`.

## Карта состояния

| Что | Где |
|---|---|
| настройки инстанса (в т.ч. `terminal_server.connections`, `tool_server.connections`, `ui.*`, `task.*`) | таблица `config`, ключ → JSON в `value` |
| workspace-инструменты (Python-тулзы, «Image Ref Generator» и пр.) | таблица `tool`: `content` (исходник) + отдельная колонка `valves` (значения полей формы) |
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
