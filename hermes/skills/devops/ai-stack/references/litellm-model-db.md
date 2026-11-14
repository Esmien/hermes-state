# LiteLLM: модели живут в БД, а не в config.yaml

`ai/litellm/config.yaml` держит только настройки шлюза (`drop_params`, лимиты, fallback-политику).
Сами модели/группы — строки в `litellm_db`, поэтому правка YAML ничего не меняет, а после
восстановления из дампа модели приезжают целиком (и вместе с их багами).

## Где что лежит

```sql
SELECT model_name FROM "LiteLLM_ProxyModelTable";          -- группы/алиасы
SELECT model_id, litellm_params->'extra_headers' FROM "LiteLLM_ProxyModelTable" WHERE model_name='<group>';
SELECT credential_name FROM "LiteLLM_CredentialsTable";      -- ключи провайдеров
```

- Одна «модель» в `/model/info` = одно имя группы; внутри группы может быть **несколько деплойментов**
  (например OpenRouter и OpenCode), между которыми роутер раскладывает запросы.
- `litellm_params` частично зашифрован (`LITELLM_SALT_KEY`): поля `model`, `litellm_credential_name`,
  `custom_llm_provider` возвращаются как base64-мусор. **Определить провайдера деплоймента по SQL
  нельзя** — либо смотреть UI/API, либо применять правку ко всем деплойментам группы (для
  безвредных заголовков это нормально). То же с любым текстовым поиском по колонке
  (`ilike '%azure%'`, `? 'user_config'`, `~ 'os\.environ/'`): он ищет внутри шифротекста и даёт 0
  при любом реальном составе деплойментов, поэтому ноль здесь — не доказательство отсутствия.
  Проверять через `/model/info` (отдаёт расшифрованные параметры) или реальным вызовом.

## Симптом «модель флапает» — это деплойменты, а не провайдер

Если из 4 запросов 2 падают с `400 Request is missing x-opencode-session`, причина в том, что
один деплоймент группы — OpenCode Zen (требует заголовок `x-opencode-session`), а второй —
OpenRouter (заголовок не нужен). Роутер чередует их, поэтому ошибка выглядит случайной, а
fallback её не спасает: fallback срабатывает на сбой вызова, а не на 400 от апстрима.
Не лечить это ретраями в Hermes/клиенте — чинить деплоймент.

Лечение — дописать заголовок в `extra_headers` **каждому** деплойменту группы:

```sql
UPDATE "LiteLLM_ProxyModelTable"
SET litellm_params = jsonb_set(litellm_params, '{extra_headers}',
      coalesce(litellm_params->'extra_headers','{}'::jsonb)
      || '{"x-opencode-session":"litellm-service-session"}'::jsonb),
    updated_at = now()
WHERE model_name='service.deepseek/deepseek-v4.1-flash';
```

Лишний заголовок для OpenRouter безвреден, поэтому фильтровать деплойменты не нужно.
После правки — `docker compose -f ai/docker-compose.yml restart litellm` (конфиг моделей читается
на старте, из БД), затем проверить **серией из 4 вызовов**: одиночный запрос может попасть в
здоровый деплоймент и создать ложное «починилось».

## Проверка вызовом без утечки ключа

В образе `litellm` нет `curl`. Ключ не печатать — брать из окружения контейнера:

```bash
docker exec litellm python -c "
import json,os,urllib.request
req=urllib.request.Request('http://127.0.0.1:4000/v1/chat/completions',
  data=json.dumps({'model':'<group>','messages':[{'role':'user','content':'ping'}],'max_tokens':5}).encode(),
  headers={'Authorization':'Bearer '+os.environ['LITELLM_MASTER_KEY'],'Content-Type':'application/json'})
try: print(urllib.request.urlopen(req,timeout=90).status)
except Exception as e: print(getattr(e,'code',e))
"
```

Повторить 4 раза подряд; при правке заголовков ждать `200 200 200 200`.

## Провайдер, живувший в credential: как он устроен и что с ним стало

Провайдер может сидеть **не в `api_base` деплоймента**, а в credential
(`LiteLLM_CredentialsTable`), на который деплоймент ссылается через `litellm_credential_name`.
Тогда `WHERE litellm_params->>'api_base' ILIKE '%host%'` возвращает ноль строк, а `/model/info`
показывает `api_base: None` — искать надо по имени credential. Именно так устроен Tokenator.

Tokenator с хоста снимали 2026-11-06 днём (12 деплойментов + 4 credential'а) — и в тот же
вечер вернули по прямой просьбе владельца, только платный (`gemini-4-argon`), в группу
`google/gemini-4-argon`: четыре ноги `order=1` (simple-shuffle чередует четыре ключа),
OpenCode-нога `order=5` как следующий приоритет. **Это состояние — намеренное, повторно
«чистить» его не надо.** Проверено: 8 вызовов подряд разложились по всем четырём ключам,
ни один не ушёл в OpenCode.

Как добавлять ноги с ротацией ключей (процедура, проверенная на этом хосте):

1. `POST /credentials` на каждый ключ: `credential_values{api_key, api_base}`,
   `credential_info{custom_llm_provider: "openai"}`.
2. `POST /model/new` на каждую ногу: `model: "<имя модели у провайдера>"`,
   `custom_llm_provider: "openai"`, `litellm_credential_name`, `api_base`, `order: 1`,
   `timeout: 90`, те же `*_cost_per_token`, что у соседних ног группы.
3. Существующую ногу перевести на нужный приоритет — `POST /model/update` с ПОЛНЫМ
   `litellm_params` и `model_info.id` (иначе частичное тело молча оставит старое).
4. Проверять эффект серией из 8 вызовов: заголовки `x-litellm-model-id` и
   `x-litellm-model-api-base` показывают, какая нога ответила.

Замеры по этому провайдеру (2026-11-06): платный `gemini-4-argon` отвечает за 6–12 с против
3–4 с у OpenCode-ноги; `usage.prompt_tokens` он считает примерно вдвое больше реального
(944 символа → 752 против 375), поэтому по его `usage` нельзя судить ни о лимитах, ни о
деньгах. Free-пул (`free-*`) даётся только ключам с пополнением за последние 7 дней, иначе
`429 Free models are for active keys`. На синтетике из 9 задач платный аргон Токанатора
показал тот же результат, что легитимный маршрут (9/9), — признаков подмены слабой моделью нет.

## Новый алиас «под задачу» + доступ в существующий ключ

Алиасы для одного потребителя называем с префиксом назначения: `enrich/gemini-4-argon`, `enrich/anthropic/claude-sonnet-5.5`. Префикс — не косметика: на него завязывается виртуальный ключ (`models: ["enrich/..."]`), и потребитель физически не может позвать остальной каталог.

1. **Параметры донора читаем только через API.** `GET /model/info?model=<существующий алиас>` отдаёт расшифрованные `litellm_params` (`model`, `custom_llm_provider`, `litellm_credential_name`, `extra_headers`); в `LiteLLM_ProxyModelTable` те же поля зашифрованы, поэтому клонировать строку SQL-ом нельзя.
2. **Создание:** `POST /model/new` с `model_name`, `litellm_params` (донорские + `extra_headers` в стиле соседей) и ценами **внутри `litellm_params`** (`input_cost_per_token`/`output_cost_per_token`). Цены, положенные в `model_info`, принимаются с 200 и теряются — после создания сверить реальную сумму по заголовку `x-litellm-response-cost`, а не арифметикой по `usage`.
   **Правка уже созданного алиаса:** `PATCH /model/{model_id}/update` с `litellm_params` (+`model_info`). `POST /model/update` на v1.106.x отвечает `400 Authentication Error, model not found` при любом теле (`model_id`, `id`, `model_name`) — на него не тратить попытки, а `model_id` брать из ответа `/model/new` или из `/model/info`.
   **Заголовки под потребителя:** `extra_headers` — это подпись клиента, а не провайдера: `User-Agent: <потребитель>/1.0` (например `lyria-enricher/1.0`), и `x-opencode-session` в OpenRouter-ногу НЕ добавлять (он нужен только OpenCode-ногам; лишний владелец считает мусором).
   **`reasoning_effort: "low"` в `litellm_params`** — главный рычаг цены и латентности для «болтливых» маршрутов: один и тот же sonnet-алиас на дефолте выдал 11 918 output-токенов за 98 с (~$0.13 за песню), с `low` — 841 токен за 7.6 с (~$0.03). Ставить сразу для фоновых потребителей и проверять по `usage.completion_tokens`, а не на глаз.
3. **Добавить в существующий ключ:** `POST /key/update {"key": "<sk-...>", "models": [<полный новый список>]}`. Поле `models` заменяется целиком, а не дополняется — слать весь набор, иначе доступ к старым моделям отвалится. Новый ключ через `/key/generate` — только когда нужен отдельный потребитель; токен показывается один раз, сразу в `.env` (и бэкап `chmod 600`).
4. **Проверка:** вызов разрешённой модели — `200`, любой другой — `403` с `key_model_access_denied`. Это сработавшая защита, а не поломка ключа.
5. **403 у сервиса, который раньше работал** (пайп/бот/скрипт после переключения на новый алиас) — это ключ потребителя, а не новый алиас: у каждого потребителя свой виртуальный ключ со своим списком моделей, дополнить его `POST /key/update {"key_alias": "<потребитель>", "models": [<весь список>]}`. Искать по alias: в `/key/list` токены **хешированы**, префикс из конфига потребителя по ним не сопоставить — выручает список `models` (у какого ключа уже есть старый алиас той же задачи).

Долгие генерации проверять таймаутом клиента, а не только кодом ответа: тяжёлый алиас может отдавать валидный JSON через 100+ секунд, и тогда падает не LiteLLM, а HTTP-клиент сервиса.

## OpenRouter Decisions API через LiteLLM

Для Perplexity Decider проверяй отдельный протокол, а не chat completions: `POST /openrouter/alpha/decisions` на LiteLLM передаёт запрос в OpenRouter Decisions API. Тело содержит точный upstream `model`, `state` и именованные `questions`; `choice` возвращает выбранный вариант и вероятности в `answers`. Прогони несколько синтетических случаев и проверь HTTP, фактический выбор и `usage.cost`; короткий ответ обычной LLM не проверяет этот маршрут. Нативный `/v1/decisions` LiteLLM использует другую схему — не подменяй его payload-ом OpenRouter.

Для passthrough сопоставляй используемый credential с `/model/info`: `use_in_pass_through` влияет на выбор credential для общего маршрута, не только конкретного алиаса; перед изменением оцени влияние на другие вызовы. Доступ виртуального ключа проверяй по реальному upstream model ID в теле, а не предполагай, что alias деплоймента достаточен. После настройки проверяй read-back, фактический вызов и цену; не выводи ключи и пользовательскую память. Транзитный endpoint и служебные учётные данные согласовывай до изменений рабочего стека.

## Цены деплойментов: как аудитить и что считается «проставлено»

Цена живёт **на деплойменте**, а не на имени группы: в одной группе две ноги с разными
провайдерами, и `$0` в отчёте обычно означает «у этой ноги цены нет», а не «модель бесплатная».

- Ставятся только в `litellm_params` (`input_cost_per_token`, `output_cost_per_token`,
  `cache_read_input_token_cost`); то же в `model_info` принимается с 200 и молча теряется —
  подробности в `references/chatgpt-subscription.md`.
- Аудит — обход `/model/info`, а не список имён: для каждого деплоймента печатать
  `model_name | model_info.id | litellm_params.model | api_base | order | blocked | in | out`.
  Голое имя группы скрывает, что цены есть у одной ноги и нет у соседней.
- `blocked` — **отдельная колонка** `LiteLLM_ProxyModelTable.blocked` (`boolean NOT NULL default
  false`), в `model_info->>'blocked'` её нет (там пусто у всех строк). SQL-проверка:
  `select model_name, model_info->>'id', blocked from "LiteLLM_ProxyModelTable" order by 1;`
- Референс цены — каталог OpenRouter: `https://openrouter.ai/api/v1/models/<vendor>/<slug>/endpoints`
  отдаёт `model_id`, `context_length` и `pricing` по каждому провайдеру. Три правила чтения:
  головная цена в UI — не то же, что тариф конкретного провайдера за нашими ногами; при prompt
  выше порога (у GPT-6/6.1 — 272k, у Claude Haiku 5.5 — 100k) тариф удваивается; у картинок,
  TTS, музыки и reranker единица — изображение/песня/вызов, токенной цены там просто нет, и
  подставлять вместо неё «цену за токен» нельзя.
- **Чего нет в каталоге OpenRouter — тому цену не назначаем** (например `gpt-reserve`): slug
  отдаёт 404, значит цифру взять неоткуда, и любая догадка потом живёт в отчётах как факт.
- Лог `Billable request priced at $0 and logged as such (model_group=… provider=…) pricing entry
  '<uuid>' declares non-zero rates` — это про **деплоймент с этим uuid**: у соседней ноги той же
  группы суммы нормальные. Судить «цены не применились» по одной строке нельзя, нужно сверить
  сумму по `api_base`/`model` в `LiteLLM_SpendLogs`.

## Что считать нормой после восстановления дампа

- `/model/info` отдаёт меньше записей, чем есть групп в БД (часть алиасов висит на мёртвых
  подписках) — это не потеря данных;
- число групп, ключей и строк `LiteLLM_SpendLogs` сверять с боевым: расхождение = дамп не доехал;
- мёртвые `chatgpt/*`-маршруты после переезда — ожидаемая картина (device-code login требует
  человека), их не «чинить» перезапусками.
