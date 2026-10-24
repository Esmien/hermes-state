# SearXNG (web search backend)

## Where it lives

- Compose service `searxng`, image `searxng/searxng:latest` (**rolling tag**, not pinned), `127.0.0.1:8081->8080`, on `stack-net`.
- Config mounted read-only: `ai/searxng/settings.yml`, `ai/searxng/limiter.toml`; `ai/searxng/engines/bing_direct.py` is still bind-mounted into `/usr/local/searxng/searx/engines/` but is **no longer referenced by settings** (Bing serves a JS/CAPTCHA shell to this IP since 2026-10-24). Unused module = harmless dead file; do not wire it back without re-proving `b_algo` results.
- Consumed by Open WebUI: `web.search.engine=searxng`, `web.search.searxng_query_url=http://searxng:8080/search?q=<query>`, `web.search.result_count=7`. OWUI appends `format=json`, `language`, `pageno`, `categories=''` itself — so `search.formats` must keep `json` and engines must live in category **general** to be used by OWUI.

## The trap that makes search look "dead": bans are keyed by Network object

In searxng 2026.10 `EngineProcessor.__init__` does:

```python
key = get_network(self.engine.name)
key = id(key) if key else self.engine.name
self.suspended_status = SUSPENDED_STATUS.setdefault(key, SuspendedStatus())
```

`network: direct` (or any named network in `outgoing.networks`) is **one shared `Network` object**, so every engine pointing at it shares a single ban timer: one 403/CAPTCHA suspends *all* of them for `ban_time_on_fail` (180 s), and the search returns a handful of results from whatever engine slipped through first. Symptom: after one captcha'd engine, every other engine answers `Приостановлено: <последняя причина>` in 0.0 s with no log line.

**Rule: never set `network:` on an engine. Set `proxies: {}` (direct) or `proxies: {all://: socks5h://...}` (Tor) per engine.** A `proxies` attribute makes `network.initialize()` build `NETWORKS[<engine name>]` per engine, so each engine gets its own ban bucket. Verified: with `proxies: {}` on every engine, one 429 on `brave` left google cse / github / seznam / yahoo untouched.

## Engine status on this host (verified 2026-10-24, image 2026.10.24)

Working, direct, no API key:

| engine | module | notes |
|---|---|---|
| `google cse` | `google_cse` | **the backbone**: 20 results in 0.3-0.5 s, no rate limit over 6 sequential queries; 2026.10 scrapes the CSE element JSON endpoint, `require_api_key: False` |
| `brave` | `brave` | 15-26 results, but 429 after ~10 queries in a few minutes → keep, it self-suspends and recovers |
| `stackexchange` | `stackexchange` | 9-10 SO/SE hits, gold for dev queries |
| `github` | `github` | 15-30 repos, unauthenticated rate limits |
| `seznam` | `seznam` | 7-10 results, works for both EN and RU |
| `yahoo` | `yahoo` | only 7 results — weak but a useful filler |
| `mwmbl` | `mwmbl` | tiny index but returns 200+ results on RU queries (ignores `results_per_page`) — keep with low `weight` |
| `arxiv`, `docker hub` | `arxiv`, `docker_hub` | niche; keep in categories `science` / `it`, never `general` |

Dead from this datacenter IP — do not re-enable without a fresh probe: `duckduckgo` (CAPTCHA on every request, direct and Tor), `bing` (JS+turnstile shell, `b_algo`=0), `google` html (403), `startpage` (CAPTCHA), `mojeek` (403, direct and Tor), `swisscows`/`luxxle`/`privacywall`/`yandex`/`baidu`/`quark`/`dogpile`/`fireball`/`tusksearch`/`neosearch`/`xprivo`/`grokipedia` (CAPTCHA or 429), `qwant`/`searchzee` (need extra `*_categ` attrs), `marginalia` (upstream `inactive: true`, needs API key).

Broken in upstream, not on our side: `wikipedia` engine hits the REST **summary** endpoint (`/api/rest_v1/page/summary/<title>`), not search — it returns 0 results for any keyword query and 404s on non-existent titles. `pypi` returns 0. `huggingface` ignores `results_per_page` and returns ~1000 results.

## Config rules

- Trim the engine pool with `use_default_settings.engines.keep_only: [...]` — otherwise `use_default_settings: true` enables ~80 upstream engines, each an extra request and an extra ban source.
- Overrides merge by engine **name**; to bring an upstream-`inactive` engine up you must set `inactive: false` (and `api_key` when required) — `disabled: false` alone does nothing and the engine is silently absent from `/config`.
- Engine names must not contain `_` ("Engine name contains underscore" → registration fails) and dotted names behave unpredictably; give every custom engine an explicit unique `shortcut` or the loader dies with `ambiguous shortcut` (worker crash loop, container flapping).
- Also missing `categories` on a custom-name engine crashes the worker: `is_engine_active` does `'onions' in engine.categories` → `TypeError: argument of type 'NoneType' is not iterable`.

## Audit — what "search works" actually means

`/healthz` and the docker healthcheck pass with every engine dead. Probe per engine and count results:

```bash
curl -s 'http://127.0.0.1:8081/search?q=fastapi+async&format=json&engines=google%20cse' | python3 -c "
import json,sys; d=json.load(sys.stdin); print(len(d['results']), d.get('unresponsive_engines'))"
```

- `engines=<name>` filters to one engine without touching settings — the only fast way to bisect.
- A shortcut (`!xx`) that returns results from a *different* engine means the shortcut is not registered at all.
- An engine present in `settings.yml` but absent from `GET /config` (field `enabled`) failed to register — read the startup log, don't trust the YAML.
- Confirm the consumer path once from inside OWUI (`docker exec open-webui python3` + `requests.get("http://searxng:8080/search", params={"q":..., "format":"json"})`).
- A burst probe (8 threads) creates its own 429s and false "dead engine" verdicts; probe sequentially with ~1 s gaps.

## Tor (not used by searxng any more, still running for other purposes)

All working engines go out **direct**; `outgoing.proxies` is intentionally absent. Tor stays installed and must stay healthy because the owner keeps it for other work.

- `systemctl is-active tor` lies: `tor.service` is the multi-instance *master* (`Type=oneshot`, `ExecStart=/bin/true`). The truth is `systemctl is-active tor@default` + `journalctl -u tor@default`.
- Boot-order bug (fixed): `SocksPort 172.17.0.1:9050` failed at boot with `Cannot bind ... Cannot assign requested address` **because tor started before docker had created `docker0`**, then `Start request repeated too quickly` left it dead until a manual restart. It is NOT about `docker0` being `NO-CARRIER` — once the address exists, binding to the admin-up bridge works fine. Drop-in `/etc/systemd/system/tor@default.service.d/10-after-docker.conf` adds `After/Wants=docker.service`, `StartLimitIntervalSec=0`, `RestartSec=5` and an `ExecStartPre` loop that waits (≤90 s) for `inet 172.17.0.1/16` on `docker0`.
- If searxng is ever routed through Tor again: `SocksPolicy` must accept the container subnet (`172.18.0.0/16` for `stack-net`), and Tor answers in 0.2-1.3 s, so `request_timeout: 10` is enough.

## Update (rolling image)

```bash
docker exec searxng cat /usr/local/searxng/searx/version_frozen.py | grep VERSION_STRING
curl -s https://hub.docker.com/v2/repositories/searxng/searxng/tags/latest   # digest + last_updated
curl -s 'https://hub.docker.com/v2/repositories/searxng/searxng/tags?page_size=10&ordering=last_updated'
```

Procedure: `docker tag searxng/searxng:latest searxng/searxng:rollback-<version>` **before** `docker compose pull searxng` (otherwise the old image is left dangling and there is nothing to roll back to), `touch /var/lib/docker-autorecover/pause`, `docker compose up -d --force-recreate searxng` (run it with `background=true` — the tool guard kills it as a "server process" in foreground), wait for `healthy`, then re-probe every engine: upstream bumps change engine modules and can silently drop ours.

## Failure modes and what they look like

1. Uniform `Приостановлено: …` in 0.0 s across unrelated engines → shared-`network` ban coupling (see above), not a real outage of each engine.
2. `ConnectionError: the server has disconnected` + `ошибка HTTP-соединения` → the engine is on the Tor network and the proxy is dead.
3. Silent 0 results with no entry in `unresponsive_engines` → custom engine parser broken (Bing) or engine semantically not a search (wikipedia summary). Check the target HTML directly from inside the container with `curl_cffi` from `/usr/local/searxng/.venv/bin/python` (plain `python3` has no `curl_cffi`).
4. Container flapping with `[ERROR] Unexpected exit from worker-1` → a settings error in one engine (missing `categories`, ambiguous shortcut, wrong `results_per_page`), visible only in the log at startup.
5. `X-Forwarded-For nor X-Real-IP header is set!` on every docker-network request → botdetection `ip_limit` without a valkey backend; cosmetic for a single-user instance.

## Quality watchdog (the only thing that proves search *works*)

`searxng-quality.timer` (every 30 min) → `/usr/local/bin/searxng-quality-check.py`: two real searches — `google cse` with a dev query (≥5 results) and an unfiltered general search (≥10 results from ≥2 engines). Alert to Telegram after 2 consecutive failures (~1 h), re-alert at most every 6 h, plus a recovery message. State `/var/lib/searxng-quality/state.json`, log `/var/log/searxng-quality.log`, thresholds via `SQ_MIN_CSE` / `SQ_MIN_TOTAL` / `SQ_MIN_ENGINES` / `SQ_FAILS` / `SQ_REALERT`. Drill an outage with `SQ_URL=http://127.0.0.1:4999/search SQ_STATE=/tmp/sq.json … --test` (fake dead endpoint, real Telegram send) — do not test by stopping the real container.

Container healthcheck, `docker-incident-detector` and the LiteLLM watchdog all stay green while every engine is dead; this timer is the only signal that the *search result* still exists.
