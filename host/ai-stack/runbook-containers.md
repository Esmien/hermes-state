# Runbook: восстановление упавших контейнеров

Хост `se-39766`. Симптом → команды → проверка «реально работает».
Про модели, ключи и маршруты LiteLLM — отдельный `runbook.md`. Здесь только контейнеры.

Правило №1: `Up 11 days` без healthcheck ничего не значит. Состояние контейнера = `State.Status` + `State.Health` + `RestartCount` + живой запрос.

## 0. Инвентарь (проверено 2026-10-23)

| Контейнер | Проект | Директория compose | restart | healthcheck | Проверка |
|---|---|---|---|---|---|
| `litellm` | ai | `/home/ai_service/ai-stack/ai` | always | да | `127.0.0.1:4000/health/liveliness` → 200 |
| `litellm-redis` | ai | то же | always | да | `docker exec litellm-redis redis-cli ping` → PONG |
| `open-webui` | ai | то же | always | да | `127.0.0.1:8080/health` → 200 |
| `searxng` | ai | то же | always | да (`/healthz`) | `127.0.0.1:8081/` → 200 |
| `open-terminal` | ai | то же | always | да (`/health`) | из сети stack-net: `http://open-terminal:8000/health` |
| `edge-tts` | — (**docker run**, без меток) | — | unless-stopped | да (TCP 5050) | из stack-net: `http://edge-tts:5050/v1/audio/voices` → 200 |
| `lyria-bot` | lyria | `/root/deploy/music_bot` | always | да (TCP 8000) | `127.0.0.1:8000/` (404 = жив) |
| `lyria-postgres` / `lyria-redis` / `lyria-rabbitmq` | lyria | то же | always | да | health |
| `lyria-generation-worker` / `-enricher-worker` | lyria | то же | always | да (TCP до `rabbitmq:5672`) | лог: `Listening started.` |
| `lyria-migrate` | lyria | то же | no | — | `Exited (0)` — **так и должно быть** |

Хостовые зависимости: `postgresql` (БД `litellm_db`, `webui_db`), `nginx` (3 vhost: `ai.` → :8080, `llm.` → :4000, `bot.` → :8000), `docker`.
`/etc/docker/daemon.json` (с 2026-10-23): `json-file`, `max-size 50m` / `max-file 3`, `live-restore: true` → рестарт демона контейнеры больше не гасит; ротация действует на контейнеры, **созданные после** изменения.

## 1. Триаж за 60 секунд

```bash
# 1. таблица состояния по всем контейнерам хоста (имя / статус / health / перезапуски)
for c in $(docker ps -aq); do
  printf '%-26s %s\n' "$(docker inspect -f '{{.Name}}' $c | tr -d /)" \
    "$(docker inspect -f '{{.State.Status}}{{if .State.Health}} {{.State.Health.Status}}{{else}} no-healthcheck{{end}} restarts={{.RestartCount}}' $c)"
done
# тревожно: Exited, Restarting, unhealthy, running но restarts>0.
# "running no-healthcheck" — не доказательство: проверять руками, §5.

# 2. почему — только ошибки, не весь лог
docker logs <c> --since 15m 2>&1 | grep -iE 'error|critical|traceback|refused|denied|no space' | tail -20

# 3. OOM? (для litellm это штатный путь: лимит 3.5g)
dmesg -T | grep -iE 'oom-kill|killed process' | tail -5

# 4. место — самая частая «внезапная» причина
df -h /; docker system df
```

## 2. Что означает состояние

| Видимое | Что это | Действие |
|---|---|---|
| `Exited (0)` у `lyria-migrate` | миграции отработали | ничего |
| `Exited (137)` / `OOMKilled=true` | убит по памяти | проверить `docker inspect <c> --format '{{.State.OOMKilled}}'`; штатно для litellm, поднимется сам |
| `Restarting`, `RestartCount` растёт | crash-loop, порт/конфиг/зависимость | смотреть лог, см. §3 |
| `Up (unhealthy)` | процесс жив, healthcheck не проходит | чаще зависимость (БД/Redis) или таймаут healthcheck |
| `Up` есть, healthcheck нет | доказательств нет | проверять руками, §5 |
| `Exited (1)` сразу после старта | конфиг/переменные/миграции | лог на строку с конфигом; см. §4 |

## 3. Дерево по причинам

1. **Зависимость лежит.** Порядок: `host postgresql` → `litellm-redis` → `litellm` → `open-webui`; для lyria: `lyria-postgres`/`lyria-redis`/`lyria-rabbitmq` → `*-worker`/`bot`.
   `systemctl is-active postgresql nginx docker`
2. **Конфиг подменился директорией.** Если `Source` в `.Mounts` начинается с `/mnt/host` — это известная ловушка (скилл `docker-compose-traps`): бинд-файл стал каталогом, лог `IsADirectoryError`, restart-loop. Лечится recreate из правильной директории на хосте, см. §4.
3. **Нет места.** Контейнер падает с `no space left on device` или БД не пишет. `df -h /`, `docker system df`, `du -sh /var/lib/docker/containers/*/*-json.log | sort -rh | head`.
4. **Образ пропал** (после prune/очистки кэша) → `docker compose build` (для собранных) или `pull` (для тянущихся). Не `run` вручную.
5. **Порт занят** после ручных запусков: `ss -ltnp | grep :<порт>`.
6. **Секрет/переменная пустая** (типично для lyria при recreate из чистого шелла) — см. §4.2.

## 4. Починка по проектам

### 4.1 `ai` (litellm, open-webui, searxng, open-terminal, litellm-redis)

```bash
cd /home/ai_service/ai-stack/ai
docker compose config -q                  # валидация YAML/интерполяции, перед любым up
docker compose up -d <service>            # один сервис; в фоне, затем ждать
```

- `.env` проекта читается автоматически, дополнительно ничего экспортировать не надо.
- `--force-recreate` нужен только после пересборки образа (`open-webui` = `esmien/webui:local`).
- Никогда не `up -d` из другого каталога и не через `/mnt/host/...` — daemon резолвит источники биндов на хосте и создаёт пустые каталоги.
- `deploy.sh` для одного контейнера не использовать: он по умолчанию восстанавливает БД из дампа.

### 4.2 `lyria` (bot, воркеры, postgres, redis, rabbitmq) — ЛОВУШКА

Compose-файл лежит в `infra/`, но **запускать надо из корня проекта** `/root/deploy/music_bot`: `/root/deploy/music_bot/.env` задаёт `COMPOSE_FILE=infra/docker-compose.yml` и `COMPOSE_PROJECT_NAME=lyria`, а также `${POSTGRES_PASSWORD}`, `${RABBITMQ_USER}`. Окружение само в шелл не попадает — его надо импортировать, иначе:

- из корня без `source` — compose не находит `infra/infra/docker-compose.yml` и падает;
- из `infra/` с `.env` вручную — имена становятся `infra-bot`, пароли пустыми, рядом появляется второй комплект контейнеров.

```bash
# ВСЕГДА в подоболочке: иначе COMPOSE_FILE и COMPOSE_PROJECT_NAME останутся в текущем шелле
( cd /root/deploy/music_bot && set -a && . ./.env && set +a && \
  docker compose config | grep -m1 container_name && \
  docker compose up -d --no-deps <service> )
```

Проверено 2026-10-23: после `source .env` в текущем шелле любая следующая compose-команда ломается — `cd /home/ai_service/ai-stack/ai && docker compose config` уходит в `infra/docker-compose.yml` от lyria и падает с `no such file or directory`. Если шелл уже «отравлен»: `unset COMPOSE_FILE COMPOSE_PROJECT_NAME`.

Проверка перед `up`: `container_name` = `infra-*` или ошибка «no such file» — **стоп**.
Значения из `.env` не печатать; точечные правки — `sed -i`.

### 4.3 `edge-tts` — вне compose

Контейнер создан вручную (`docker run`), меток compose нет, `env_file` нет, окружение — только образцовые переменные Python. Восстановление:

```bash
docker run -d --name edge-tts --restart unless-stopped \
  --network stack-net travisvn/openai-edge-tts:latest
# проверка: docker exec open-webui curl -s -o /dev/null -w '%{http_code}\n' http://edge-tts:5050/
```

Если контейнер ещё жив — сначала снять фактическую конфигурацию, а не угадывать:
`docker inspect edge-tts --format '{{json .Config.Cmd}} {{json .HostConfig.PortBindings}}'`, затем `docker rename edge-tts edge-tts.old` (после подтверждения) и запуск новой.

### 4.4 Хостовые сервисы

```bash
systemctl status postgresql nginx docker --no-pager | head -20
nginx -t && systemctl reload nginx
sudo -u postgres psql -d litellm_db -c 'select 1' >/dev/null && echo pg-ok
```

С 2026-10-23 `live-restore: true`: рестарт демона контейнеры не гасит. Если конфиг откатят или демон падал жёстко — `restart: always` поднимет всё, `edge-tts` (`unless-stopped`) тоже, если не был остановлен вручную. После любого рестарта демона проходить §5.

## 5. Проверка «действительно работает»

```bash
c(){ printf '%-12s %s\n' "$1" "$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$2")"; }
c litellm  http://127.0.0.1:4000/health/liveliness   # 200
c webui    http://127.0.0.1:8080/health              # 200
c searxng  http://127.0.0.1:8081/                    # 200
c lyria    http://127.0.0.1:8000/                    # 404 = жив
docker exec open-webui sh -c 'curl -s -o /dev/null -w "edge-tts %{http_code}\n" http://edge-tts:5050/; curl -s -o /dev/null -w "searxng %{http_code}\n" http://searxng:8080/'
docker inspect <c> --format '{{.State.Health.Status}} restarts={{.RestartCount}}'
docker logs <c> --since 3m 2>&1 | grep -iE 'alembic|migrat|error' | tail -n 10
```

Плюс настоящий запрос через прокси (модель отвечает) — по `runbook.md` §B.

## 6. Полное падение хоста — порядок подъёма

1. `postgresql`, `docker` (systemd поднимет всё `always` само).
2. Ждать health: `lyria-postgres`, `lyria-redis`, `lyria-rabbitmq`, `litellm-redis`.
3. `litellm` → `open-webui` → `searxng`/`open-terminal`/`edge-tts` → `lyria-bot`/воркеры.
4. `nginx` (`nginx -t` перед reload), `certbot` сертификаты.
5. §5 целиком. Затем бэкапы: `postgres-backup.timer`, дайджест в Telegram.

Полный деплой (только при реальной потере данных): `cd /home/ai_service/ai-stack && sudo ./deploy.sh` — восстанавливает БД из свежих дампов; `--skip-restore` если данные трогать нельзя.

## 7. Диск и логи

```bash
df -h /; docker system df
du -sh /var/lib/docker/containers/*/*-json.log 2>/dev/null | sort -rh | head -5
docker logs <c> --tail 100            # всегда с лимитом
```

Ротация включена в `/etc/docker/daemon.json` (50 МБ × 3 файла) и применяется к контейнерам, **созданным после** 2026-10-23. Проверка: `docker inspect <c> --format '{{json .HostConfig.LogConfig.Config}}'`; пустой `{}` = контейнер старше и пишет без ограничения — лечится recreate.

## 8. Известный шум — НЕ чинить

- `lyria-*-worker`: `AMQPConnectionError` на старте, дальше `Listening started.` — штатный ретрай до готовности rabbitmq.
- `open-webui`: `get_available_voices ... /v1/audio/voices -> 404` — edge-tts так отвечает на этот путь, не ошибка.
- `litellm`: `Error upserting deployment … LLM Provider NOT provided` для спящей строки БД — проверять по спенд-логам, а не по сообщению.
- `litellm` OOM-kill при спайке (лимит 3.5g, без свопа) — ожидаемое поведение с последующим авто-рестартом.
- `lyria-migrate` в состоянии `Exited (0)`.

## 9. Инциденты: детектор будит агента, агент разбирается

Схема (без человека в цикле, но и без тупого «перезапустить всё»):

```
docker-autorecover.timer (60 c)
   └─ docker-incident-detector.py     — заметил аномалию, собрал улики, поднял агента
        └─ docker-incident-agent.sh   — Hermes-агент: ищет ПРИЧИНУ, чинит или эскалирует
             └─ отчёт в Telegram
```

Детектор сам контейнеры не трогает вообще. Он фиксирует аномалию, выгружает доказательства в `/var/lib/docker-incidents/<ts>-<name>-<reason>/` (`incident.json`, `inspect.json`, `logs.txt`, `oom.txt`, `disk.txt`, `host.txt`, `docker-journal.txt`, `prompt.txt`, `agent.log`) и запускает агента отдельным systemd-юнитом `docker-incident-*`.

Что считается аномалией:

| Условие | Триггер |
|---|---|
| `Exited`/`dead` при `restart: always\|unless-stopped`, лежит ≥90 с, 2 проверки подряд | `exited` |
| `Restarting` с растущим `RestartCount` | `crash_loop` |
| `Up`, `health=unhealthy` 2 проверки подряд (БД/брокеры — 3) | `unhealthy` |
| Скачок `RestartCount` ≥2 между проверками (флаппинг между тиками) | `restart_flap` |
| Контейнер из allowlist отсутствует 2 проверки подряд | `missing` |

Что агент делает сам: `docker start`/`docker restart`, правка compose с бэкапом `*.bak.<ts>` и recreate одного сервиса, проверка результата по §5, разбор известного шума по §8.
Что только с разрешения владельца: `rm`, `docker rm/rmi`, `prune`, `down -v`, restore БД из дампа, правка `.env`, чужие контейнеры. Агент обязан в этом случае остановиться и объяснить в отчёте, что именно нужно.

Анти-спам и защита: 2 подтверждения подряд, кулдаун 20 минут на контейнер, одновременно не больше одного агента, стоп при диске ≥97% или неактивном `docker`. Агент запускается только по инциденту (не по расписанию) — платим за разбор, а не за тишину.

Ручные работы — обязательно пауза, иначе детектор поднимет инцидент под руками:

```bash
touch /var/lib/docker-autorecover/pause
# ... работы + проверка по §5 ...
rm /var/lib/docker-autorecover/pause
```

Эксплуатация:

```bash
python3 /usr/local/bin/docker-incident-detector.py --status   # что видит детектор
python3 /usr/local/bin/docker-incident-detector.py --dry-run  # прогон без агента
tail -30 /var/log/docker-autorecover.log                      # решения детектора и запуски агента
ls -lt /var/lib/docker-incidents/ | head                       # история разборов
systemctl list-timers 'docker-*' --no-pager                    # оба таймера
```

Сторож за сторожем: `docker-detector-liveness.timer` (раз в 10 минут) проверяет, что детектор реально тикает (`state.json` моложе 10 минут и таймер активен), иначе пишет в Telegram — молчание детектора не должно выглядеть как «всё хорошо».

Проверено 2026-10-23 учебным прогоном: детектор поднял инцидент по остановленному тестовому контейнеру, агент прочитал улики (exit 137, `OOMKilled=false`, `RestartCount=0`), распознал синтетику, проверил прод по §5, разрушительных действий не совершал, отчёт доставлен в Telegram (`report sent ok=True`).

Ограничения: healthcheck воркеров lyria косвенный (доступность брокера); падение короче двух тиков детектора может пройти незамеченным, если контейнер поднялся сам.

## 9.1 Стоп-правила

- Не удалять тома и контейнеры (`docker rm`, `down -v`, `system prune -a`) — данные lyria и webui живут в них.
- Не восстанавливать БД из дампа «на всякий случай»: сначала §1–§5.
- Не пересоздавать контейнеры, которые не падали.
- Не печатать `.env`, ключи, токены; правки — `sed -i` по ключу.
- `docker run` мимо compose — только для `edge-tts`, остальное через compose.
- Любое удаление/перезапись/рестарт демона — только после подтверждения владельца.

## 9.2 Сторож качества поиска (SearXNG)

`searxng-quality.timer` (каждые 30 мин) → `searxng-quality-check.py`: делает два настоящих поиска — `google cse` на дев-запрос (порог ≥5 результатов) и общий поиск (≥10 результатов и ≥2 разных движка). Это закрывает слепую зону: контейнерный healthcheck, детектор и LiteLLM-watchdog зелёные даже когда поиск отдаёт пустоту.

- Алерт в Telegram после **2 неудачных прогонов подряд** (~1 час), повтор не чаще 6 ч, плюс сообщение о восстановлении.
- Если снапшот состояния Hermes не смог запушить коммит в GitHub, он висит локально: `hermes-state-watch.service` ретраит с бэкоффом 60→300 с, а сам снапшот на каждом прогоне сравнивает `ls-remote` с локальным HEAD и догоняет пушем (catch-up).
- Состояние `/var/lib/searxng-quality/state.json`, лог `/var/log/searxng-quality.log` (logrotate weekly ×8).
- Ручной прогон: `python3 /usr/local/bin/searxng-quality-check.py --no-send`; проверить доставку — `--test` (реальная отправка с пометкой «тест»); учебный отказ — `SQ_URL=http://127.0.0.1:4999/search SQ_STATE=/tmp/sq.json ... --test`.
- Пороги настраиваются env-переменными `SQ_MIN_CSE`, `SQ_MIN_TOTAL`, `SQ_MIN_ENGINES`, `SQ_FAILS`, `SQ_REALERT`.

Проверено 2026-10-24: штатный прогон 20 рез. (google cse) и 55 общих; имитация отказа (мёртвый порт) дала алерт с доставкой `SEND ok=True`, возврат к живому поиску — сообщение о восстановлении.

## 10. Состояние дыр (закрыто 2026-10-23)

Закрыто:

1. `litellm-redis` добавлен в `/etc/hermes-boot-expected-containers.txt`.
2. Healthcheck добавлены всем, кроме `lyria-migrate` (он и не должен быть живым): `searxng` → `/healthz`, `open-terminal` → `/health`, `edge-tts` → TCP 5050, `lyria-bot` → TCP 8000, оба воркера → TCP до `rabbitmq:5672`.
3. `/etc/docker/daemon.json`: ротация `50m × 3`, `live-restore: true`.

Осталось (осознанно или ждёт решения):

1. `edge-tts` живёт вне compose — создавался вручную при настройке, восстановление только командой из §4.3.
2. Healthcheck воркеров — косвенный (доступность брокера), зависший воркер с живым соединением он не поймает. Реальная проверка — лог `Listening started.` и очередь задач.
3. Ротация логов действует на все контейнеры (последние шесть `litellm`, `open-webui`, `litellm-redis`, `lyria-postgres`, `lyria-redis`, `lyria-rabbitmq` пересозданы 2026-10-23). Новый контейнер без явного `logging:` наследует `50m x 3` из `daemon.json`.
