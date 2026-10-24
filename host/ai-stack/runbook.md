# Runbook: AI-стек на этом VPS

Короткая инструкция «что делать, если». Симптом → команды → как убедиться, что починили.

Упавшие контейнеры (весь хост: ai-стек, lyria, edge-tts) — отдельный `runbook-containers.md`.

## Карта системы

```
Open WebUI (127.0.0.1:8080) ─┐
Hermes gateway ──────────────┼─→ LiteLLM (127.0.0.1:4000) ─→ OpenCode Go / OpenRouter / прочие провайдеры
Telegram-боты, скрипты ──────┘        │
                                      └─→ litellm_db (PostgreSQL 17 на хосте)
```

Аварийный маршрут Hermes (когда LiteLLM недоступен):
`vps-admin-hermes` → `opencode-go/deepseek-v4.1-flash` (Go!) → `openrouter/deepseek-v4.1-flash` → `openrouter/anthropic/claude-haiku-5.5`.
Ключи аварийного маршрута лежат в `/root/.hermes/.env`: `OPENCODE_GO_API_KEY`, `OPENROUTER_API_KEY`.
Мы используем **только OpenCode Go**, не Zen.

## A. LiteLLM не отвечает

Признаки: сообщение вотчдога «🔴 LiteLLM не отвечает», Hermes пишет «⚠️ Model fallback: … using deepseek-v4.1-flash via opencode-go», ошибки 5xx у клиентов.

```bash
# 1. жив ли процесс и что с лимитами
docker inspect litellm --format 'status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{end}} restarts={{.RestartCount}}'
curl -s -o /dev/null -w '%{http_code}\n' -m 5 http://127.0.0.1:4000/health/liveliness   # ждём 200

# 2. почему упал — последние строки
docker logs litellm --tail 50 2>&1 | tail -30

# 3. если похоже на OOM (в логах kill / внезапный обрыв)
docker stats --no-stream litellm
dmesg -T | grep -iE 'oom|killed process' | tail -5

# 4. поднять
cd /home/ai_service/ai-stack/ai && docker compose up -d litellm
# проверка: health 200 + модели отвечают
```

Лимит памяти: `mem_reservation 3g`, `mem_limit 3.5g`, свопа контейнеру не даём (`memswap_limit: 3.5g`) — при спайке будет OOM-kill и авто-перезапуск (`restart: always`), это нормальное поведение, а не авария.

## B. LiteLLM отвечает, но модели падают

Признак: алерт «⚠️ LiteLLM: всплеск отказов».

```bash
# какие группы падают за последний час (битые /v1/models исключаем)
sudo -u postgres psql -d litellm_db -tAc "select coalesce(nullif(model_group,''),model), status, count(*), max(\"startTime\") from \"LiteLLM_SpendLogs\" where \"startTime\" > now()-interval '1 hour' and call_type not in ('/v1/models','pass_through_endpoint') and status<>'success' group by 1,2 order by 3 desc limit 10"

# здоровье деплойментов конкретной группы (мастер-ключ из ai/.env, в чат не выводить)
# curl -s 'http://127.0.0.1:4000/health?model=<group>' -H "Authorization: Bearer $LITELLM_MASTER_KEY"
```

Частые причины: выбиты все ключи группы (кулдаун 60 с, `allowed_fails: 2`), лежит upstream-провайдер, протух ключ в credential store (UI → Credentials). **Фолбэки на другие модели мы не включаем** — ошибка по группе должна всплывать клиенту.

## C. Hermes: оба маршрута (шлюз и аварийный) легли

```bash
hermes fallback list                 # что настроено
/model emergency                     # переключить текущую сессию на OpenCode Go (ручной аварийный режим)
hermes chat -q "Reply with exactly: OK" -m emergency   # проверка маршрута без сессии
```

Если ключ мёртв (401/403 в ответе) — заменить значение в `/root/.hermes/.env`
(`OPENCODE_GO_API_KEY` для Go-релея, `OPENROUTER_API_KEY` для второй ступени), затем
`/reload-skills` или новый сеанс, чтобы гейтвей перечитал окружение.
Базы: Go — `https://opencode.ai/inference/go/v1`, модель `deepseek-v4.1-flash`
(Go-релей требует заголовок `x-opencode-session` — Hermes добавляет его сам).

## D. Не хватает места / растёт БД

```bash
df -h /; sudo -u postgres psql -d webui_db -tAc "select pg_size_pretty(pg_database_size('webui_db'))"
systemctl start webui-compact-images.service     # сжатие base64-картинок в webui_db
systemctl start litellm-spend-retention.service  # чистка спенд-логов старше 30 дней
cat /var/log/webui-compact-images.log /var/log/litellm-spend-retention.log | tail -20
```

## E. Упал хост целиком

Аварийный маршрут Hermes тут не поможет — он на том же хосте. Порядок: поднять ОС → вернуть стек → вернуть данные.

```bash
cd /home/ai_service/ai-stack && sudo ./deploy.sh            # полный деплой, восстанавливает БД из свежайших дампов
# если данные трогать нельзя: sudo ./deploy.sh --skip-restore
ls -la /home/ai_service/ai-stack/backups/postgres/          # дампы: keep-newest-3 на каждую БД
```

Бэкапы делает `postgres-backup.timer` (02:30 UTC) + проверяет восстановлением `monitor.py verify` (03:15 UTC); ночной дайджест уходит в Telegram.

## Diag-шпаргалка

```bash
systemctl status litellm-watchdog.timer            # алерт о недоступности шлюза
cat /var/lib/server-monitor/litellm_watchdog_state.json; tail -20 /var/log/litellm-watchdog.log
docker compose -f /home/ai_service/ai-stack/ai/docker-compose.yml ps
sudo -u postgres psql -d litellm_db -tAc "select count(*) from \"LiteLLM_ProxyModelTable\""   # 120 деплойментов / 42 группы
hermes fallback list
```

## Чего не делать

- **Не включать `litellm_settings.cache: true`** — прокси-кэш ответов ломает агентские tool-calls.
- **Не настраивать фолбэки моделей внутри LiteLLM** — только аварийные маршруты на клиенте (Hermes).
- **Не «чистить дубликаты» в `LiteLLM_ProxyModelTable`** — одинаковые `model_name` это группы с разными ключами, они нужны все.
- Не трогать `.env` без нужды и никогда не печатать значения ключей в чат/логи.
