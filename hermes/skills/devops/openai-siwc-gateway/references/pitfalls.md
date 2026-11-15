# Pitfalls

- **После перезагрузки хоста проверять оба bind, а не `systemctl is-active`.** Юнит стартует
  раньше, чем docker поднимает `docker0`, `bind(172.17.0.1:4010)` падает с `EADDRNOTAVAIL`,
  поток умирает молча — юнит остаётся `active`, `127.0.0.1:4010` отвечает, а LiteLLM получает
  `Cannot connect to host host.docker.internal:4010` / `Connect call failed ('172.17.0.1', 4010)`.
  Симптом со стороны клиента: модель группы падает с `InternalServerError`, а у групп без
  `router_settings.fallbacks` — сразу ошибка в чат. Лечение: `After=/Wants=docker.service`
  в юните **и** повтор bind в `serve()` (сеть может отстать и от этого). Проверка после
  любого reboot: `ss -ltnp | grep 4010` должен показать **две** строки (`172.17.0.1` и `127.0.0.1`).
  Копии юнита и `gateway.py` лежат в `vps-infra/assets/host/{systemd,siwc}/` (`auth.json` — нет).

- **`stream` must be read before you force it.** Setting `body['stream'] = True` and then
  deciding "client wanted a stream?" always answers False, so the gateway returns an
  aggregated JSON to a caller that expects SSE. LiteLLM reports it as
  `APIConnectionError: openai closed the responses stream before any terminal event` — 100%
  reproducible on `/v1/responses`, invisible on `/v1/chat/completions`.
- **Мост теряет всё, кроме текста.** `convert_messages()` в `gateway.py` склеивает
  content списком строк (`'\n'.join(p.get('text','') …)`) и выбрасывает `image_url`/`input_image`
  без ошибки. LiteLLM при этом отдаёт `supports_vision: true` (модель ведь зрячая), поэтому
  клиент не получает ни `400`, ни предупреждения: модель просто отвечает «изображение не
  прикреплено». Любая группа, чья живая нога — этот мост (и серая `chatgpt/` тоже), слепая
  к картинкам; `image-generator`/vision-модели на такой группе не работают.
- **Проверка «дошла ли картинка» — по `prompt_tokens`, не по ответу модели.** Один и тот же
  текстовый payload даёт одинаковое число токенов с картинкой и без, если её срезали:
  текстовый запрос `openai/<slug>` = N, тот же запрос с `image_url` = N (признак потери), а через
  зрячую ногу (`service.openrouter/<slug>`) = N + сотни токенов и правильное описание.
  Второй свидетель — `api_base` в `LiteLLM_SpendLogs`: `http://host.docker.internal:4010/v1`
  значит запрос ушёл в мост. Лечение: увести клиента на группу с реально зрячей ногой
  (или добавить проброс `input_image` в мост — только после проверки, что backend принимает
  картинки), а не чинить OWUI.
- **Always synthesise a terminal event.** If the upstream stream ends without
  `response.completed|incomplete|failed`, emit a synthetic `response.completed` yourself;
  otherwise the proxy turns a merely truncated answer into a hard error.
- **Upstream rejects `max_output_tokens < 16`**; clamp every `max_tokens`/
  `max_completion_tokens` to `max(16, int(value))`.
- **`/model/update` bookkeeping is treacherous.** Pass `model_info.id` and the full
  `litellm_params`; then re-read `/model/info` and assert `blocked` **per deployment id**.
  After a rename the flag can end up on the wrong row, which silently leaves the grey
  route live and looks like a gateway bug.
- **A leg without `order` stops existing once any sibling has one.** `get_order_filtered_deployments`
  (`litellm/utils.py`, called from the router's `async_get_healthy_deployments`) keeps only the
  deployments at the *lowest* `order` in the group and **drops every leg whose `order` is `None`**.
  Symptom: 100 % of a group's traffic lands on the backend you did not want, the other leg answers
  fine when called directly, and nothing in `/model/info` looks wrong. Read the orders per
  deployment id before diagnosing — `order` inside one group is a real priority ladder, it is only
  weaker than a separate fallback group when you need a *different provider* on the second rung.
  Fix by giving every leg a number (bridge `1`, grey `2`) or by blocking the leg you do not want.
- `ext_agent_host_id` must be a hyphenated **UUIDv4** with `urn:uuid:` prefix; a hex
  machine-id gives `invalid_authorize_request` / `param: ext_agent_host_id`.
- Host-ID and client-id must persist; restarting or re-signing-in must not mint a new host.
- Aggregate streamed responses from `response.output_item.done`; `response.completed.output`
  is **empty** even when the model answered — relying on it yields blank messages.
- `urllib.request` is easy to forget when only `urllib.parse` is imported; refresh then
  fails with a bare `AttributeError`.
- Restarting by `pkill -f <path>` misses a process started as `python3 gateway.py` from its
  own cwd — check `ss -lntp` before assuming the new build is live; an old instance keeps
  the port and the new one dies with `Address already in use`.
- Headless VPS: the loopback callback cannot be reached from the owner's browser. Either
  `ssh -L PORT:127.0.0.1:PORT` or have them paste the failing redirect URL; the code is
  single-use and short-lived.
- Authorize URLs and auth.json carry tokens — never echo them; scratch copies must be wiped.
- **The upstream stream can close early**: `openai closed the responses stream before any
  terminal event (response.completed...)`. It surfaces in LiteLLM as
  `MidStreamFallbackError` and looks like a route failure. Treat it as intermittent upstream
  behaviour: retry once inside the sidecar before reporting a defect.
