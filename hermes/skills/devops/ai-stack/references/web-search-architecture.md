# Web search end to end (OWUI ↔ shim ↔ SearXNG ↔ Hermes)

Read when the owner asks for better web search than SearXNG, or when answers built on web search look shallow.

## What Open WebUI actually does

- Compose: `RAG_WEB_SEARCH_ENGINE: "searxng"`, `SEARXNG_QUERY_URL: "http://searxng:8080/search?q=<query>"`.
- The searxng path (`open_webui/retrieval/web/searxng.py`) reads the SERP JSON and keeps **title / link / snippet only** — result pages are never opened. That is the real ceiling on answer quality, not the engine's ranking.
- Installed engines (`retrieval/web/`): azure, bing, bocha, brave, duckduckgo, exa, **external**, firecrawl, google_pse, jina_search, kagi, linkup, mojeek, openserp, perplexity, searchapi, serpapi, serper, serphouse, serply, serpstack, sougou, staan, tavily, yacy, yandex, ydc. The module list is version-dependent — re-read it from the running image instead of trusting this line: `docker exec open-webui python3 -c "import open_webui.retrieval.web as w, pkgutil; print([m.name for m in pkgutil.iter_modules(w.__path__)])"`.
- **`external` is the only seam for a self-built search service.** Config keys `web.search.external_web_search_url` (`EXTERNAL_WEB_SEARCH_URL`) and `web.search.external_web_search_api_key`. Contract: `POST` JSON `{"query": str, "count": int}` with `Authorization: Bearer <key>`; the answer must be a JSON list of `{"link", "title", "snippet"}` — the first `count` are used. No chat answer, no markdown: a result list.
- **There is no engine chaining.** `search_external` catches every failure and returns `[]`; the chat then answers with no context. So «SearXNG как фоллбэк» is only real if the shim itself does the fallback.

## Latency: search sits in the answer's hot path

Web search runs synchronously *before* generation, so shim time is added to every first token. Design to a 5–6 s hard timeout, and on timeout/failure return a single plain SearXNG query rather than nothing. Anything agentic (multi-step, page reading with judgement) belongs behind an explicit user/tool action, not in this path.

## Hermes in this picture

- Hermes's own `web_search` backend is already SearXNG (`config.yaml`, `web_search … backend: searxng`). An agent adds **query variants + opened pages + judgement**, not a new data source.
- Hermes webhook routes are asynchronous (they trigger a run and deliver into a chat) — they cannot serve the synchronous `{query,count}` contract above.
- Anything an LLM adds here costs quota per search and 10–40 s per run. Put it on the rare branch, not on every message.

## Trust-zone constraint (do not skip)

OWUI chat is zone 2 in `multiagent-tiers.md`. Pointing it at the root agent (with `terminal`, `docker`) hands the chat zone root. If an agent is exposed to OWUI at all: non-root user, its own `HERMES_HOME` with an empty `skills/`, toolsets limited to `web_search` + `web_extract`, token auth, per-run budget.

## Plan (designed with the owner, not built yet)

```
OWUI  --external-->  search-shim (127.0.0.1)
                       1. 3-4 query variants (ru/en) -> SearXNG in parallel
                       2. dedupe by domain, rank
                       3. open top pages: curl+UA -> embedded JSON-LD/__NEXT_DATA__
                          -> API/RSS pivot -> lightpanda -> Chromium -> Wayback/archive.today
                       4. return count items with real page text in `snippet`
                       fallback: single SearXNG query, raw snippets
```

Steps 1–3 are deterministic HTTP and need no LLM, so they belong in the shim; the browser engines are invokable from a script (`lightpanda fetch --dump`, Chromium `--headless=new --dump-dom`) and do not require an agent run. Hermes is the escalation for the residue only: a per-site route nobody anticipated, an embedded-state blob that needs reading, or fact-checking across sources.

Measured boundary to state honestly instead of promising «обход капч»: a browser clears JS-only walls and SPAs, but **not** IP-reputation blocks — RU sites return «Доступ ограничен: проблема с IP» and Reddit «blocked by network security» to both lightpanda and a full Chromium from this host. Those pages are reachable only through archives or a non-datacenter egress.

Before/after evidence for any rollout: 10–15 real queries scored on «page opened?» and «did the snippet carry real page text?», plus how often the escalation branch fired.

The owner-facing plan — work items, trust-zone rules, acceptance criteria — lives in the harness: `~/.hermes/tasks/docs/web-search-plan.md` (board task #3). This reference holds the facts; that doc holds the plan. When the design changes, update both, and re-run `/usr/local/bin/hermes-state-backup.sh` so the repo copy matches the host.

## Answering the owner about web search

OWUI's built-in `searxng` path keeps only SERP `title/link/snippet` — it never opens the results, so
answer quality is capped by ~200-char teasers. Engines do not chain: when a custom/external search
fails, OWUI logs and returns `[]` and the model answers with no context. So «поиск получше» is a
page-fetching problem, not a model problem, and any «SearXNG как фоллбэк» must live INSIDE the
replacement service. Contract, hot-path budget, Hermes's role and the trust-zone caveat:
`references/web-search-architecture.md`.
