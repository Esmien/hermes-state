# Open WebUI: фоновые задачи (заголовки, теги, follow-up, query)

Детали к вопросу «не генерируются заголовки / теги / follow-up». Четыре задачи —
четыре независимых конфига (`task.title.*`, `task.tags.*`, `task.follow_up.*`,
`task.query.*`), но один код-путь и одна логика ошибок: сбой никогда не пишется
в лог как ошибка, он молча уезжает в фолбэк. Поэтому сначала исключаются
условия «задача вообще не запрошена», и только потом ищется модель.

## Порядок разбора (не перескакивать)

1. **Пришёл ли запрос задачи?** Задачи просит фронтенд: в теле
   `/api/chat/completions` приходит `background_tasks: {title_generation: true}`.
   Флаг строится из **личной** настройки пользователя `settings.ui.title.auto`
   (ключ `title.auto`, при отсутствии — `true`). При `false` сервер не запускает
   задачу: ни строки в логе, ни записи в spend-логах LiteLLM. Проверка:
   ```bash
   sudo -u postgres psql -d webui_db -At \
     -c "select settings::jsonb->'ui'->'title' from \"user\" where role='admin';"
   ```
   Лечить в UI (Settings → Interface → Title Auto-Generation): интерфейсные
   настройки OWUI дублируются в localStorage и перезаписывают БД при следующем
   сохранении, поэтому правка только в БД может не удержаться.
2. **Включена ли задача глобально?**
   ```bash
   sudo -u postgres psql -d webui_db -At -c \
     "select key, value from config where key like 'task.title.%';"
   ```
   Нужен `task.title.enable = true`.
3. **Несёт ли шаблон сообщение и контракт ответа?** Плейсхолдер `{{prompt}}`
   подставляется **только если он есть в шаблоне** (`replace_prompt_variable`
   ищет строку `{{prompt}}`); без него модель получает одну инструкцию без самого
   сообщения. И ответ обязан быть JSON: `middleware.py` вырезает подстроку от `{`
   до `}` и делает `JSONCodec.loads`, ожидая `{"title": "..."}`. Кастомный шаблон
   без требования JSON = ответ обычным текстом = пустой заголовок.
4. **Разрешается ли id модели?** `task.title.model` / `task.model.default` — это
   id моделей OWUI (пресеты вида `weak`, `approval`, `compacter` или id маршрута),
   а не обязательно имена групп LiteLLM. Если id нет в списке моделей пользователя
   (`GET /api/v1/models`), OWUI молча берёт модель чата. В `config` задачи лежат
   как `{model, model_external, params}`.
5. **Хватает ли `max_tokens`?** У рассуждающих моделей бюджет съедают
   reasoning-токены: при малом лимите ответ приходит с HTTP 200 и пустым `content`.
   Для задач держать параметры в сотнях токенов (в штатном конфиге — 2564).
6. **Может ли КОНКРЕТНЫЙ пользователь читать модель задачи и её базу?** Главная
   причина «у админа работает, у остальных нет»: у задачи модель `weak`, а доступ
   к моделям в этой версии OWUI грантовый (`access_grant`), и пресет, созданный
   админом, по умолчанию не виден никому, кроме него.

## Доступ к модели задачи (наиболее частая причина «у меня работает, у неё нет»)

В логах это единственный видимый след сбоя (у остальных веток — тишина):

```
WARNING open_webui.utils.models:check_model_access:548 - Model access denied:
  user_id='...' model_id='weak' reason=model_read_denied
WARNING open_webui.utils.access_control:has_base_model_access:351 - Model access denied:
  ... model_id='weak' base_model_id='service.deepseek/deepseek-v4.1-flash' reason=base_model_read_denied
```

Проверять **двумя** запросами — сначала сам пресет, потом его `base_model_id`:

```bash
sudo -u postgres psql -d webui_db -At -F' | ' -c \
  "select id, base_model_id from model where id='weak';"
sudo -u postgres psql -d webui_db -At -F' | ' -c \
  "select resource_id, principal_type, principal_id, permission from access_grant \
   where resource_type='model' and resource_id in ('weak','<base_model_id>');"
```

Публичный доступ — строка `principal_type='user', principal_id='*', permission='read'`
(так же выдано на рабочие пресеты вроде `deepseek-v41-flash`).

```sql
insert into access_grant (id, resource_type, resource_id, principal_type,
                          principal_id, permission, created_at)
values (gen_random_uuid()::text, 'model', 'weak', 'user', '*', 'read',
        extract(epoch from now())::bigint)
on conflict do nothing;
```

Выдать грант недостаточно: цепочка проверяется до базы. Если у пресета
`base_model_id = service.*` (внутренний маршрут шлюза, доступный только админу),
задача падает на `has_base_model_access`. Лечение — перевести базу пресета на ту,
которой пользователи уже пользуются в обычных чатах (`chat.*`), а не расширять
гранты на служебные маршруты:

```sql
update model set base_model_id='chat.deepseek/deepseek-v4.1-flash',
       updated_at=extract(epoch from now())::bigint where id='weak';
```

Проверка без ожидания пользователя — подписать JWT её `id` ключом `WEBUI_SECRET_KEY`
внутри контейнера и дёрнуть `POST /api/v1/tasks/title/completions` (префикс именно
`/api/v1/tasks`, на `/api/tasks` прилетает 405): в ответе должен быть
`{"title": "..."}`, а не `{"detail":"An internal error has occurred."}`.
Побочный эффект публичного гранта: пресет задачи появляется в списке моделей у
пользователя — это нормально, но владельца предупредить.

## Конфиг читается из БД на каждый вызов — перезапуск не нужен

`Config.get()` (`open_webui/models/config.py`) делает `db.get(Config, key)` при
каждом обращении, кэша `app.state` для `task.*` нет. Правка в `webui_db`
действует сразу: не перезапускать `open-webui` «на всякий случай» и не выдумывать
простой сервиса там, где хватает одного UPDATE.

Обновление шаблона (значение — JSON-строка):

```sql
UPDATE config SET value = to_jsonb($tpl$...$tpl$::text),
       updated_at = extract(epoch from now())::bigint
 WHERE key = 'task.title.prompt_template';
```

## Фолбэк, который маскирует баг

В `middleware.py` (блок генерации заголовка) любое исключение или неразборчивый
ответ дают `title = ''`, и чат остаётся/становится с **первым сообщением
пользователя в качестве заголовка**. Диагностический признак: в списке чатов
висят длинные фразы-вопросы дословно — это не «модель плохо ужала», это
несостоявшаяся генерация. Ошибок в логах при этом нет.

Заголовок генерируется **один раз** для сохранённого чата, на первом обмене;
старые чаты не перетитулуются. Не обещать владельцу «починится везде».

## Проверенный шаблон

```
Извлеки основную мысль из сообщения и ужми её в 2–4 слова.
Сообщение:
{{prompt}}
Отвечай только JSON без пояснений, без markdown и без кавычек вокруг всего ответа:
{"title": "заголовок"}
```

Проверка до правки в БД — прогнать шаблон через шлюз на нескольких реальных
сообщениях и распарсить ответ как JSON: дешевле, чем ловить фолбэк в UI. Годится искать `title` в `{...}`; модели отвечают чистым JSON.
