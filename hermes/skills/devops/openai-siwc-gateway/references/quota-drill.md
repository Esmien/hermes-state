# Учебный прогон квоты (сквозной, без ожидания реального отказа)

Квота не читается и не воспроизводится по заказу, поэтому отладка fallback-цепочки идёт инъекцией
того же события: второй экземпляр моста с `SIWC_FAKE_QUOTA=1` и своим портом
(`SIWC_PORT=4022 SIWC_BIND=172.17.0.1,127.0.0.1 python3 /root/siwc/gateway.py`) отдаёт ровно
реальную последовательность `response.created → in_progress → output_item.added → response.failed`,
но как HTTP 429. Дальше — временная подмена `api_base` у порядковой ноги на
`http://host.docker.internal:4022/v1` через `PATCH /model/<id>/update` (полный `litellm_params`),
**прогон через WebUI от лица владельца** и немедленный возврат `api_base` на 4010. Драйвер WebUI:
`assets/host/siwc/owui-e2e-quota.py` (JWT с `session_stamp` из таблицы `auth` + `mfa_verified`,
POST `/api/chat/completions`, модель `gpt-61-terra`) — запускать внутри контейнера
`open-webui`, JSON с uid/stamp/model подавать на stdin.

Что доказано этим прогоном: 3 хода в реальном чате, каждый дал **два** отвергнутых вызова
фейковой ноги (`responses failed before stream`) и ответ от `order=2` (OpenRouter) — в
спенд-логах `model_id` ноги OpenRouter, ни одной `failure`-строки у группы. После снятия подмены
order-1 снова отдаёт мост. Учесть: пока идёт прогон, рабочая нога фактически подменена.

**Chromium-сессия владельца без пароля:** cookie `token` серверу достаточно (API отдаёт 200), но SPA
сразу редиректит на `/auth` — она читает `localStorage.token`. Порядок: зайти на `/auth`, положить
JWT в `localStorage.token`, только потом открывать `/?model=<id>`. JWT — `{id, session_stamp, typ:
'session', mfa_verified: true, iat, exp}`, `session_stamp` берётся из таблицы `auth` в `webui_db`.
Ввод в чат — реальный ввод с клавиатуры: поле `#chat-input` это `contenteditable`, установка
`value` не работает; нужно `Input.dispatchMouseEvent` по центру + `Input.insertText` +
`Input.dispatchKeyEvent` Enter. Готовый драйвер — `assets/host/siwc/owui-chromium-e2e.py`
(venv с `websocket-client`, Chromium с `--remote-debugging-port`, `/json/new` только методом PUT).
