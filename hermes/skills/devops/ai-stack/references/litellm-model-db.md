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

## Как снести провайдера, который живёт в credential

Tokenator (бесплатный прокси) убран с хоста целиком 2026-11-06, и это показало типовую
ловушку: его деплойменты **не имели `api_base`** — адрес сидел в credential
(`LiteLLM_CredentialsTable`, имена `Tokenator 1f23/3e39/a2e3/c984`), а деплойменты
ссылались на него через `litellm_credential_name`. Поэтому `WHERE litellm_params->>'api_base'
ILIKE '%tokenator%'` возвращает ноль строк, а `/model/info` показывает `api_base: None`.

Порядок сноса:

1. `GET /model/info` → выбрать записи по `litellm_params.litellm_credential_name` (поле в ответе
   API читаемое, в БД — зашифровано). Для каждой группы проверить, остаётся ли живая нога.
2. `POST /model/delete {"id": ...}` по каждой такой записи — API применяет сразу, рестарт не нужен.
3. `DELETE /credentials/<url-encoded name>` — снести сами credential'ы.
4. Проверить эффект: `GET /model/info` (не должно остаться упоминаний), `GET /v1/models`
   (нет имён вида `free-*`), и по одному вызову каждой затронутой группы — оставшиеся ноги
   могут быть мёртвыми (`Model is unavailable`), тогда их надо перевести на рабочую модель
   через `/model/update` с полным `litellm_params` и `model_info.id`.

Перед удалением — дамп двух таблиц (`pg_dump -t LiteLLM_ProxyModelTable -t LiteLLM_CredentialsTable`),
удаление деплойментов через API необратимо.

## Что считать нормой после восстановления дампа

- `/model/info` отдаёт меньше записей, чем есть групп в БД (часть алиасов висит на мёртвых
  подписках) — это не потеря данных;
- число групп, ключей и строк `LiteLLM_SpendLogs` сверять с боевым: расхождение = дамп не доехал;
- мёртвые `chatgpt/*`-маршруты после переезда — ожидаемая картина (device-code login требует
  человека), их не «чинить» перезапусками.
