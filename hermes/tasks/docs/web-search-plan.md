# Поиск для WebUI: шим с руками + Хермес на эскалации (план, не реализовано)

Статус: **план**, согласован по смыслу с владельцем 2026-11-05. Ничего не реализовано.
Связанные документы: `tasks/docs/multiagent-tiers.md` (зоны доверия), `tasks/docs/modules-plan.md` (профили).

## Задача

Поиск в OWUI сейчас = сниппеты SearXNG. Страницы не открываются, поэтому модель отвечает
по 200-знаковым тизерам выдачи. Цель — качественнее, чем голый SearXNG, при этом SearXNG
остаётся фоллбэком, а не единственным источником.

## Факты, на которых держится план (проверено на живом стеке)

- **Шов есть.** OWUI умеет движок `external`: POST `{query, count}` на `EXTERNAL_WEB_SEARCH_URL`
  с `Authorization: Bearer <EXTERNAL_WEB_SEARCH_API_KEY>` → ждёт JSON `[{link, title, snippet}]`
  (`retrieval/web/external.py`). Другого способа подставить свой поиск нет.
- **Цепочки движков нет.** При ошибке `external` возвращает `[]`, без перехода на SearXNG.
  Значит фоллбэк реализуется **внутри** нашего сервиса, а не настройкой OWUI.
- **OWUI берёт только сниппеты.** `retrieval/web/searxng.py` читает `results[]` из JSON SearXNG
  (title/link/snippet), страницы не загружает вообще. Это и есть главная причина слабых ответов.
- **Вебхуки Hermes не подходят:** они асинхронные (запуск прогона + доставка в чат),
  синхронного JSON-контракта нет. Транспорт — свой HTTP-сервис.
- **Руки есть, и они не требуют LLM:**
  - `/root/.local/bin/lightpanda` 1.1.0 — движок по умолчанию (`browser.engine: lightpanda`), JS исполняет;
  - `/root/.hermes/tools/chromium-1208/chrome-linux64/chrome` — полноценный Chromium (рендер, скриншоты через `browser_vision`);
  - на хосте нет `curl_cffi`/`playwright`, `JINA_API_KEY` не задан.
- **Границы браузера (замерено):** `example.com` — ок; `reddit.com` — 403 и в curl, и в полном
  Chromium («You've been blocked by network security»); `avito.ru` — 439 «проблема с IP».
  То есть браузер снимает JS-стены и SPA, но **не снимает репутацию IP** датацентра и не решает
  интерактивные капчи. Не обещать «обход капч» ни в коде, ни в отчётах.
- `r.jina.ai` без ключа сейчас отдаёт заглушку (200 + «blocked» внутри) — как маршрут не считать.

## Архитектура (три слоя)

```
OWUI chat ── RAG_WEB_SEARCH_ENGINE=external ──► search-shim (127.0.0.1) ──► SearXNG
                                                   │  лестница извлечения (без LLM)
                                                   └─► эскалация: Hermes search-only
```

1. **Fast layer — `search-shim`** (свой сервис, non-root, только исходящий HTTP):
   переформулировки запроса → параллельный SearXNG → дедуп по домену → открыть топ-страницы
   лестницей ниже → ранжирование → `count` результатов с настоящими выжимками.
2. **Escalation — Hermes** (search-only инстанс): вызывается только когда лестница встала
   либо когда пользователь явно просит «копни глубже». Типизированная заявка
   `{query, failed_urls, budget}` → `{ok, results[], provenance}`.
3. **Fallback — SearXNG** внутри шима: таймаут/отказ → один обычный запрос → сырые сниппеты.
   Пользователь никогда не получает `[]`.

## Лестница извлечения страницы (детерминированная, общий бюджет ~8 с)

| # | Ступень | Чем | Когда |
|---|---|---|---|
| 0 | `curl` + десктопный UA | host curl | серверный HTML, дешёвый первый пробник |
| 1 | `lightpanda fetch --dump` | lightpanda | JS-страницы, быстро |
| 2 | Chromium `--headless --dump-dom` / CDP | chromium-1208 | тяжёлый JS, SPA |
| 3 | embedded state | html-парсер | `ld+json`, `__NEXT_DATA__`, `window.__INITIAL_STATE__` |
| 4 | API/RSS/sitemap-пивот | host curl | после 2–3 блокировок уходить с HTML на `/api/`, `/graphql`, `.json`, фид |
| 5 | Wayback (`available` + CDX) | archive.org | удалённое/пейвол; **провенанс = снимок на дату** |
| 6 | archive.today (ротация домены) | archive.ph/.md/.li/.is | пейволы, которых нет в Wayback; валидировать тело, не код |
| 7 | SearXNG сырые сниппеты | searxng | последняя ступень, гарантированный ответ |

Правила:
- валидировать **тело**, а не статус: 429/челлендж приходят как 200 + много КБ HTML
  (эвристики в скилле `blocked-page-recovery`);
- Google Cache мёртв, AMP-кеши отдают редирект-заглушку — не считать успехом;
- прокси-релеи не использовать (MITM, непроверяемый провенанс).

## Контракт шима

```
POST /search      {"query": str, "count": int}  ->  [{"link","title","snippet"}]
GET  /health                                  ->  {"ok": true, "searxng": "up|down"}
```
- Авторизация: Bearer `EXTERNAL_WEB_SEARCH_API_KEY` (новый ключ в `ai/.env` + `.env.example`).
- Жёсткий таймаут на запрос; при превышении — отдать то, что успели, + ступень 7.
- **Провенанс в snippet обязателен**: живая страница, отрендерено браузером, снимок от <дата>.
  Модель не должна выдавать снимок за свежие данные.
- Логировать ступень, сработавшую на каждой странице (это же — метрика качества).

## Доверие (граница из `multiagent-tiers.md`)

- Шим — не агент: фиксированный набор глаголов, ноль произвольных команд, non-root юзер,
  systemd с `NoNewPrivileges=yes`, без `docker.sock`, без доступа к `/root`.
- Эскалация в Hermes — **search-only**: toolset `[web, browser]`, без `terminal`/`file`,
  свой `HERMES_HOME`, свой пустой `skills/`, бюджет и таймаут на заявку.
- Root-инстанс Hermes в цепочку поиска не подключать.

## Работы

1. `search-shim`: FastAPI + `trafilatura`-подобное извлечение, лестница 0–7, health, логи ступеней.
2. Юнит `search-shim.service` (non-root, `ProtectSystem=strict`), регистрация в `deploy.sh` и
   `install.py` (модуль `full`/`tools`, не в `core`).
3. OWUI: `RAG_WEB_SEARCH_ENGINE=external` + `EXTERNAL_WEB_SEARCH_URL`/`..._API_KEY` в `ai/.env`.
4. Эскалация: search-only инстанс Hermes + типизированная заявка (JSON-схема + allowlist).
5. Метрики: доля страниц, открытых каждой ступенью; p50/p95 латентности; число эскалаций.
6. Сравнение качества: 15 запросов (RU/EN, новости, доки, товары, пейвол) — слепой A/B
   «сниппеты SearXNG» против «шим», оценка по фактам в ответе, а не по гладкости.
7. Приёмка: только после A/B переключать живой OWUI; откат — одна строка env + рестарт.

## Открытые вопросы

- Нужен ли `curl_cffi` (TLS-имперсонация Chrome) и/или FlareSolverr — решать по метрикам
  ступени 2, а не заранее.
- Эскалацию делать через отдельный инстанс Hermes или через MCP-сервер `lightpanda mcp`
  в самом шиме (без агента вовсе)?
- Сколько страниц открывать по умолчанию: 5 (быстро) против 8–10 (качество, +латентность).

## Сделано 14.11.2026: headless-браузер для WebUI

Промежуточный шаг до `search-shim`: у WebUI появился собственный браузер, поэтому страницы
из поиска и по прямой ссылке рендерятся с JS.

- Контейнер `playwright` (`mcr.microsoft.com/playwright:v1.60.0-noble`, `npx playwright@1.60.0
  run-server --port 3000`, `ipc: host`, в `stack-net`, портов наружу нет). Версия образа равна
  версии пакета `playwright` в образе WebUI (1.60.0) — при обновлении WebUI синхронизировать.
- Конфиг OWUI: `web.loader.engine=playwright`, `web.loader.playwright_ws_url=ws://playwright:3000`,
  `web.search.bypass_web_loader=false`. Поиск остаётся SearXNG.
- Проверка рендера: `POST /api/v1/retrieval/process/url` на `quotes.toscrape.com/js/` вернул
  10 цитат (1501 знак) — контент есть только после исполнения JS.
- Тул `web_browser` (`/app` Tool, публичный) с методом `browse_page(url, wait_for_selector, max_chars)`:
  подключается к серверу по WS, берёт `innerText` из `article`/`main`, отдаёт заголовок + описание +
  текст, обрезает по `max_chars`. Привязан к 26 моделям группы `chat.*` через `params.tool_ids`.
- Бэкапы: `docker-compose-before-playwright.yml`, `models-chat-params-before-tool.json` (0600).
- Откат: убрать `tool_ids`, вернуть `web.loader.engine=''`, `docker compose rm -sf playwright`.
