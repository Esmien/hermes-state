# Container memory troubleshooting (this VPS)

Use when asked "what is eating the RAM" or when a container's footprint looks wrong. Attribution first: never name a cause before the numbers do.

## 1. Host overview

```bash
free -h
ps -eo pid,ppid,rss,pmem,comm --sort=-rss | head -20
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}' | head -20
```

Map the biggest container to a host PID, then treat that PID as the root of the analysis.

## 2. Leak or static footprint?

```bash
pid=$(docker inspect <c> --format '{{.State.Pid}}')
awk '/VmRSS/{print $2}' /proc/$pid/status   # sample
grep VmSwap /proc/$pid/status
sleep 45
awk '/VmRSS/{print $2}' /proc/$pid/status   # sample again
docker inspect <c> --format '{{.State.StartedAt}} restarts={{.RestartCount}}'
```

- **RSS flat + long uptime + `RestartCount=0` ⇒ static allocator footprint, NOT a leak.** Do not propose a periodic restart; there is nothing to drain.
- RSS climbing between samples ⇒ real growth; then look at the live request path (open connections, fd count, `docker logs --tail 50`), not at the allocator.

## 3. Anonymous vs file-backed

```bash
grep -E '^Pss' /proc/$pid/smaps_rollup
```

- `Pss_Anon` is the heap/native-allocator cost; `Pss_File` is the resident cost of mapped libraries and data files.
- `Pss_File` of a few tens of MB with an `Pss_Anon` in the GBs means the loaded libraries are irrelevant — swapping to a smaller/slim image will **not** return RAM (disk only). State this, don't recommend the image swap as a memory fix.
- **Group `Rss:` lines by pathname and SUMMED per class — never read a single `Rss:` line as a distinct allocation.** A one-liner that takes `$6` as the name mis-attributes anonymous regions and prints the same shared library over and over with implausible sizes (a few-MB `.so` "holding" 100 MB). Anonymous regions are exactly the mappings with **no pathname**, plus the `[heap]`/`[stack]` labelled ones:
  ```bash
  /usr/bin/python3 -c "import re,collections;t=collections.Counter();n='ANON'\
  ;[ (n:=p[5] if len(p)>5 else 'ANON') if re.match(r'^[0-9a-f]+-',l) else None\
  ; t.__setitem__(n, t[n]+int(l.split()[1])) if l.startswith('Rss:') else None\
  ) for l in open('/proc/<pid>/smaps') for p in ([l.split()] if re.match(r'^[0-9a-f]+-',l) else [])]\
  print([(f'{v/1024:.0f} MB',k) for k,v in t.most_common(10)])"
  ```
  (Simpler and just as good: run the parse in `execute_code`/a scratch `.py` — nested comprehensions in a `-c` string are not worth the quoting risk.)

## 4. glibc arena signature

```bash
awk '/^[0-9a-f]+-[0-9a-f]+ /{split($1,a,"-"); sz=(strtonum("0x"a[2])-strtonum("0x"a[1]))/1048576; hdr=$0} /^Rss:/{if(hdr ~ /rw-p 00000000 00:00 0/) print sz, $2}' /proc/$pid/smaps | sort -rn | head -20
```

Tells to recognise: **many anonymous `rw-p` regions of ~64 MiB at a 64 MiB stride** (`HEAP_MAX_SIZE` is 64 MiB). That is glibc malloc's secondary arenas. Default cap is `8 × ncores` — on 4 cores, 32 arenas ≈ 2 GB held forever, and the driver is the process's **thread count** (in-process runtimes that spawn their own pool — PyTorch/libgomp intra-op, ctranslate2 — inflate it). Compare with `ls /proc/$pid/task | wc -l`.

Fix and its constraints:

- `MALLOC_ARENA_MAX=2` (1 also fine) in the container env. The dynamic loader reads it at process start, so it **requires a container recreate** — editing env on a running container is impossible.
- `OMP_NUM_THREADS=1` / `MKL_NUM_THREADS=1` cut the thread count that feeds arena creation; they also slow local CPU inference, so only use them when the heavy inference is remote.
- Add `mem_limit` to the service at the same time: the host's guard is a swapfile, and with `Memory=0` a spike kills whichever container the kernel's `oom_score` picks.

## 5. Probing a container that has no `ps`

Minimal (python-slim based) images have no `ps`. Walk `/proc` from the host using the container's init PID: read `/proc/<pid>/status` (`VmRSS`), `/proc/<pid>/cmdline`, and recurse through `/proc/<pid>/task/<pid>/children`. Write the walker to a scratch file and run it — building a multi-line script inline inside `docker exec sh -c '...'` through an f-string breaks on the braces/quoting.

## 6. open-webui config precedence (recurs here)

Container env shows `USE_EMBEDDING_MODEL_DOCKER`, `USE_RERANKING_MODEL_DOCKER`, `RAG_EMBEDDING_MODEL`, `WHISPER_MODEL`, `VECTOR_DB` — these come from the image's Dockerfile and `start.sh` reads only `USE_SLIM_DOCKER`, `USE_OLLAMA_DOCKER`, `USE_CUDA_DOCKER`, `WEB_LOADER_ENGINE`. The engines that actually run are the persistent config rows in `webui_db.config` (env is overridden). Query them before claiming which models are local:

```bash
sudo -u postgres psql -d webui_db -Atc "select key||' = '||left(value::text,140) from config where key ~ 'rag|embedding|rerank|stt|whisper' and key not like '%api_key%' order by key;"
```

Keep `%api_key%` filtered out — those rows hold live provider keys. Usual shape here: embeddings and reranking external (`rag.embedding_engine=openai` → OpenRouter, `rag.reranking_engine=external`), TTS/image-gen external, and **STT local** (`audio.stt.engine=""`, `audio.stt.whisper_model`), which is what pulls the faster-whisper cache and loads ctranslate2 in-process. `rag.content_extraction.supported_media_mime_types` containing `audio/*` makes every audio ingest transcribe locally too.

## 7. LiteLLM: ~1.4 GB and no leak signature

Measured shape on this box (v1.105.1, single uvicorn worker, ~31 h uptime, RSS 1.38 GiB):

- `[heap]` (glibc brk) **~700 MB** + anonymous mmap **~650 MB**; **file-backed mappings only ~55 MB** (`Pss_File` idea, same conclusion). So the footprint is Python objects plus allocator retention — not libraries, not a file/page cache. `VmHWM` (peak) runs above the current RSS, so GC does return objects to the allocator, but glibc never hands arenas back to the OS: **RSS only drops on a restart.**
- Count the **Prisma query-engine child** as part of LiteLLM's cost — a separate node process (~50 MB) parented by the proxy, invisible in `docker stats` per-container breakdown but there in `ps`.
- `/app` config here carries **no `model_list` at all** — all ~120 models live in `litellm_db` (`STORE_MODEL_IN_DB=True`), so the router holds them plus the per-deployment router state.

Growth triggers to check, in this order:

1. **The DB→router model sync loop.** With `STORE_MODEL_IN_DB=True` the proxy periodically re-registers deployments; one broken row turns into a repeating `router.py:... - Error upserting deployment <name>: LLM Provider NOT provided` in the log **every 30 s (~2.9k/day)**, and every cycle rebuilds router objects and throws a traceback. Proving it is cheap: `docker logs litellm --since 24h | grep -c 'Error upserting'`. This path (`store_model_in_db`) is the one upstream users report as the biggest contributor.
2. **Prometheus callback.** `prometheus_client` is installed in the image, so metrics are live: every distinct model/key/team/user combination is a time series that is **never removed**, and `prometheus_metrics_ttl_seconds` is ignored once `PROMETHEUS_MULTIPROC_DIR` is set. Cardinality here is ~120 models × ~32 keys.
3. **Spend tracking.** `LiteLLM_SpendLogs` (~100k rows, ~13 MB/day) plus the daily aggregates, buffered through an in-memory queue before flush; `MAX_IN_MEMORY_QUEUE_FLUSH_COUNT` / `MAX_SIZE_IN_MEMORY_QUEUE` (defaults 1000) cap that buffer.
4. **Caches with no Redis.** Nothing in the compose file provides Redis, so the auth/user-key cache, router caches and the LLM-client cache (httpx pools per api_base+key) are all in-process.

Upstream acknowledgement worth quoting to the owner: the proxy is known to grow unbounded under steady traffic and never release without a restart (issues on 1.75 → 1.88 and later; fixes landed for cost-tracking stringification, the pass-through route re-registration leak and the retry leak). Practical mitigations, cheapest first: fix the failing deployment so the sync loop stops erroring (its provider prefix is missing, e.g. `grok-4.7` instead of `openai/grok-4.7`); set `MAX_IN_MEMORY_QUEUE_FLUSH_COUNT=5000` + `MAX_SIZE_IN_MEMORY_QUEUE=500`; bound Prometheus (TTL or disable the callback); keep the spend-log retention timer; last resort a periodic recreate — justified only when a sampling sweep shows RSS genuinely climbing.

### Commands

```bash
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}'
docker exec <c> sh -c 'cat /proc/1/status | grep -E "VmRSS|VmHWM|Threads"; cat /proc/1/smaps_rollup | head -8'
ps -eo pid,rss,cmd | grep -iE 'litellm|prisma'          # includes the Prisma child
```

- **`litellm_db` is on the HOST PostgreSQL** → `sudo -u postgres psql -d litellm_db -tAc "..."`. Do **not** target it through the lyria container: `docker exec lyria-postgres psql -U postgres -d litellm_db` fails with `FATAL: role "postgres" does not exist` (lyria's superuser is `lyria`, and that instance does not even hold this database). Table names need quoting (`"LiteLLM_ProxyModelTable"`, `"LiteLLM_SpendLogs"`); row counts per table come from `select relname, n_live_tup from pg_stat_user_tables order by n_live_tup desc`.
- **The litellm image has no `curl` and no bare `python`** — only `/app/.venv/bin/python`. So probe the proxy from the host against `127.0.0.1:4000`, or run the venv interpreter with `urllib` inside the container.
- **`py-spy` on the HOST can attach to the container's Python** (the pid is visible in the host pid namespace): `pip install py-spy` then `py-spy dump --pid <host pid>`. Read it for thread inventory, not for heap: thread names `ThreadPoolExecutor-0_N`, `litellm-logging_N`, `prisma-engine-waitpid-N`, `AnyIO worker thread` with **ever-increasing indices** mean threads are being recreated rather than reused; a stable set of 9–17 threads means the thread count is not your leak (compare against `/proc/<pid>/status` `Threads:`).
- **`docker exec litellm cat /app/config.yaml` shows the mounted config only** — if it has no `model_list`, model routing lives in the DB; say so instead of "the config has no models, something is broken".
