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
  безвредных заголовков это нормально).

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

## Что считать нормой после восстановления дампа

- `/model/info` отдаёт меньше записей, чем есть групп в БД (часть алиасов висит на мёртвых
  подписках) — это не потеря данных;
- число групп, ключей и строк `LiteLLM_SpendLogs` сверять с боевым: расхождение = дамп не доехал;
- мёртвые `chatgpt/*`-маршруты после переезда — ожидаемая картина (device-code login требует
  человека), их не «чинить» перезапусками.
