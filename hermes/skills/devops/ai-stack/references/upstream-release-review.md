# Reviewing an upstream release before applying it

Use when the user asks "what's in the new <component> release / should we update", or before applying any upgrade. The deliverable is a relevance-filtered summary plus an explicit "update or not?" question — **never update unprompted**; the user decides.

## 1. Current version actually running

| Component | How to read the RUNNING version |
|---|---|
| open-webui | `curl -s 127.0.0.1:8080/api/version` → `{"version":"..."}` |
| litellm | `docker exec litellm /app/.venv/bin/python -c "import importlib.metadata as m;print(m.version('litellm'))"` — no `pip`/`python`/`curl` on PATH in that image, and `litellm.__version__` does not exist |

These are the versions actually being served. An image tag (`:main`, `main-latest`) tells you nothing about the version, and `docker inspect --format '{{.Created}}'` gives the build date (the tag can point at a rebuild whose date ordering looks backwards against earlier pulls — never infer version ordering from it).

To read a tag's version **without touching the live container**, run the image's interpreter directly: `docker run --rm --entrypoint /app/.venv/bin/python <image>:<tag> -c "import importlib.metadata as m;print(m.version('litellm'))"`.

## 2. Latest upstream release + full changelog

```bash
# open-webui: newest tags with dates + full changelog (newest-first markdown)
curl -s 'https://api.github.com/repos/open-webui/open-webui/releases?per_page=8' \
  | grep -E '"(tag_name|published_at)"'
curl -sL https://raw.githubusercontent.com/open-webui/open-webui/main/CHANGELOG.md -o /tmp/owui_changelog.md

# litellm: newest tags with dates; per-release body (one or two backported PRs + links)
curl -s 'https://api.github.com/repos/BerriAI/litellm/releases?per_page=10' \
  | grep -E '"(tag_name|published_at)"'
curl -s 'https://api.github.com/repos/BerriAI/litellm/releases/tags/v<X.Y.Z>' \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['tag_name'],d['published_at']);print(d['body'][:3000])"
# each bullet is a PR: read its title + TLDR via
curl -s 'https://api.github.com/repos/BerriAI/litellm/pulls/<N>' \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['title']);print((d.get('body') or '')[:1200])"
```

For open-webui `read_file` the top ~140 lines — newest-first, one section per version; read only sections from the running version up to the newest.

**Litellm release numbering — stable vs pre-release.** Tags ending `-rc.N` or `-dev.N` are pre-releases; the newest *plain* `vX.Y.Z` is the newest stable. BerriAI's rolling `main-latest` image tag is built from the main branch, so it can serve a **dev** build ahead of the newest stable — check it (step 1's `docker run` probe) and if it does, recommend **pinning the compose image to the newest stable tag** instead of pulling the rolling tag. A patch-level stable bump usually carries only backports; read the two or three linked PRs, they are the whole delta.

**Fetch raw text with `curl`, not `web_extract`.** `web_extract` here is backed by SearXNG, a search-only backend, and returns "cannot extract URL content" for any URL. Use `curl` (or set `web.extract_backend` to firecrawl/tavily/keenable/exa/parallel if you want `web_extract`).

Similarly, when a check has to run **inside** a container, assume nothing is installed there: use that container's own interpreter (`/app/.venv/bin/python` for litellm) and stdlib `urllib.request` instead of `curl`/`wget`, and read secrets from the container's own env (`os.environ['LITELLM_MASTER_KEY']`) rather than passing them on the command line.

### Open WebUI preflight — will it build on OUR tree and fit OUR data?

Run these before recommending the bump; they turn "the changelog looks fine" into an actual risk statement.

1. **No alembic revision in the diff ⇒ no schema migration on start.** Compare the two tags and filter for migration files:
   ```bash
   curl -s 'https://api.github.com/repos/open-webui/open-webui/compare/v<old>...v<new>' -o /tmp/owui_cmp.json
   python3 -c "import json;d=json.load(open('/tmp/owui_cmp.json'));print(d['total_commits'],'commits');print([f['filename'] for f in d['files'] if 'migration' in f['filename']])"
   ```
   An empty list means the schema is untouched — say so in the review, it is the difference between a 5-minute pull and a migration window. The compare API caps at 300 files: when the count lands near that, cross-check `git/trees/v<new>?recursive=1` filtered on `backend/open_webui/migrations` instead of trusting the diff. Also print the changed `backend/` filenames: a rewrite of `models/<x>.py` plus its routers is the shape that carries data risk without a migration.
2. **A storage rewrite without a migration is still a data risk — measure the blast radius, do not read the diff.** Such changes ride in an existing JSON column, normalize lazily on read and are rewritten only when the row is next saved, so nothing breaks at boot. What decides the risk is how many rows we have: `sudo -u postgres psql -d webui_db -tAc "select count(*) from note;"`. Zero rows lets the whole feature be dismissed in one line; a large count makes it the headline risk.
3. **Check the rebrand's sed anchor in the target tag before promising the build succeeds.** `ai/webui-branding/Dockerfile` seds `    WEBUI_NAME += ' (Open WebUI)'` inside `backend/open_webui/env.py` and hard-fails via `grep -q 'rebranded: Esmien AI'` when the line moved:
   ```bash
   curl -sL https://raw.githubusercontent.com/open-webui/open-webui/v<new>/backend/open_webui/env.py | grep -n 'WEBUI_NAME'
   ```
   The four-space indent is part of the pattern — an upstream re-indent breaks the build, so fix the sed in the same change.
4. **A new feature that talks to open-terminal only works if our terminal image has the route.** The host cannot resolve the compose service name, so probe by container IP and print status codes only — never the connection key read from `webui_db` (`config` key `terminal_server.connections`):
   ```bash
   IP=$(docker inspect open-terminal --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
   # GET http://$IP:8000/files/cwd    -> 200 {"cwd": "/mnt/host", ...}
   # GET http://$IP:8000/files/upload -> 405 = route exists, 404 = missing
   ```
   `405` on a GET is the cheapest proof that the POST route exists. A `404` means the advertised feature (file/image copy into the terminal) is dead on our image — report that instead of listing the feature as a benefit. Note the cwd: `/mnt/host` is the host root, so such a feature writes into `/`.

## 3. Summarize for THIS stack, not the raw list

Group as **Added / Fixed / Changed**, and lead each item with a bold one-line gist so the user can skim. Then add a "what this means for our install" section. Rules:

- **Name the items that do NOT apply, explicitly.** Silence on an irrelevant section reads as an unfinished review. For this stack the recurring non-applicable block is anything Redis-related (`WEBSOCKET_REDIS_*`, room channels, Valkey, Redis Sentinel, tool-server caching) — no Redis is deployed here. Note that env-gated features ship **off by default** and require a websocket + HTTPS backend (HTTPS exists via nginx).
- **Flag behavior changes loudly** — they are the real update risk. Example class: a release that makes model-attached skills send their full instructions on every message (more prompt length; the fix is to remove skills pinned to models just to make them "available").
- Call out security/privacy fixes (audit-log coverage, OAuth token handling, SCIM, sharing regressions) even if the user did not ask — they drive the update decision.
- End with a clear update/not question. Do not touch the container in the same turn as the summary.

### Minor releases are huge — filter the bullet list, never read it

A LiteLLM **minor** bump can carry 500–600 PR bullets and a ~90 KB release body; opening PRs one by one (the patch-bump recipe above) does not scale. Parse the body programmatically instead:

```python
b = json.loads(subprocess.run(["curl","-s","https://api.github.com/repos/BerriAI/litellm/releases/tags/v<X.Y.Z>"],
                               capture_output=True,text=True).stdout)['body']
items = [l.strip() for l in b.splitlines() if l.strip().startswith('* ')]
# then: count, list bullets with ')!' (breaking), and grep the list by keyword groups:
#   prisma|migrat, spend|budget, cache, stream|finish_reason, passthrough,
#   responses|bridg, audio|voices, openrouter, /v1/models, allowlist|virtual key
```

Then open a PR body only for the handful of bullets that touch a path we actually serve. Print counts and the filtered lines, never the raw body.

### Judge relevance against OUR request path, not the changelog

Before writing "this fixes X", prove X is on a route our traffic takes:

```bash
sudo -u postgres psql -d litellm_db -tAc "select model_group, count(*) from \"LiteLLM_SpendLogs\" where \"startTime\" > now() - interval '7 days' group by 1 order by 2 desc limit 20;"
```

Here the traffic is plain **chat-completions** on `hermes.opencode/*`, `hermes/*`, `chat.opencode/*`, `tokenator/*`, `other.openrouter/*`, `deepseek/*`. So a release whose headline fixes are chat↔Responses bridge and Anthropic `/v1/messages` bridge bugs (gpt-5.x / codex-style upstreams) buys us **nothing** — say that plainly instead of listing them as benefits. `metadata::json->>'api_base'` is empty in this DB, so the spend log will not tell you the upstream; use the model-group prefix and `/v1/models` instead.

### Verify a claimed quirk fix in the source, not from the PR title

Titles are ambiguous ("honor unsupported reasoning effort" was Bedrock-only). Diff the file between the two tags with stdlib — no image pull, no container touch:

```python
old = urlopen("https://raw.githubusercontent.com/BerriAI/litellm/v<old>/litellm/llms/openrouter/chat/transformation.py").read()
new = urlopen("https://raw.githubusercontent.com/BerriAI/litellm/v<new>/litellm/llms/openrouter/chat/transformation.py").read()
print(''.join(difflib.unified_diff(old.decode().splitlines(), new.decode().splitlines(), 'old','new', lineterm='', n=1)))
```

And check whether a route exists at all via the tree listing (`git/trees/v<X.Y.Z>?recursive=1`, then substring-match paths — `[p for p in paths if 'voice' in p.lower()]`). Empty result = the endpoint is still unimplemented, regardless of what the changelog suggests.

**Answer workaround-by-workaround before recommending.** This stack carries three standing workarounds; a release review must state fixed / not fixed for each:
- `/v1/audio/voices` 404 (LiteLLM has no such route — Open WebUI noise) — check the tree for `voice`.
- `UnsupportedParamsError: openrouter does not support parameters: ['reasoning_effort']` on `api_base`-defined OpenRouter groups — workaround stays `drop_params: true` or a non-reasoning model; check the openrouter transformation diff.
- ghost models echoed from virtual-key `models` allowlists into `/v1/models` — repair is still manual `key/update`; grep the bullets for `allowlist|virtual key`.

A review that only lists nice-to-haves without saying "your workarounds remain" reads as a promise the release does not make.

## 4. Apply (only after the user says yes)

See the "Updating one container" section in SKILL.md for the backup → pull → recreate → verify sequence and its two generic traps (foreground guard on `up -d`; benign `audio/voices` 404 in the boot-log grep), plus its **"Updating LiteLLM"** subsection for the three LiteLLM-specific checks (probe the tag's version before pulling, pin a stable tag instead of rolling `main-latest` when the tag ships a dev build, verify with a real completion through the gateway). When the user says "update it if it's safe", report what the update would actually install and choose the newest **stable** release — an unreleased dev build is not "safe" and pinning it or rolling onto it is a decision the user did not ask for.
