# His repos — findings, contradictions, interview traps

Two repositories he offers for technical prep. Re-check the specific lines before quoting them; the structure below is what matters.

## erp_system_backend

**What it proves:** ~10.5k LOC, 38 test files / ~170 tests, ruff + pre-commit, CI with a Postgres service container, alembic, sentry, prometheus instrumentator, sqladmin, taskiq + RabbitMQ. Domain packages with Repository → Service → Transport, `core/uow.py` exposing one repository per domain, JSONB RBAC/ABAC policies with `AccessLevel` = ALL / PARTICIPANT / AUTHOR, JWT access tokens with a Redis blacklist keyed by `jti` and TTL equal to the remaining token life. bcrypt hashing and verification really are offloaded via `fastapi.concurrency.run_in_threadpool`, so the «unblock the event loop» claim is in the code, not only in the legend.

**Where a reviewer will attack:**

- `rbac_cache` caches one rule per `(role_id, business_element)` for `CACHE_TTL = 3600` with **no invalidation on policy write** → up to an hour of stale permissions. The strong answer is prefix invalidation on update; the honest answer is «только TTL», and it should be said before being asked.
- Debug lines in the cache decorator print `cached_data` (which is `None` on a miss) and the phrase «Кэш для правило» — do not describe this code as polished.

**Questions to prepare from his own code:** UoW transaction boundaries and where `commit` sits; JSONB policy lookup without a full scan; the race between a policy change and an already-issued token; behaviour when Redis restarts and the blacklist empties; the default thread-pool size under many concurrent logins; how ~170 tests isolate state (`pytest-xdist` is in the deps).

## async_spimex_parser

**What it proves:** ~3.7k LOC ETL (crawler → downloader → parser), 24 tests, a semaphore bounding downloads, `aiohttp` timeouts, manual retry with backoff, Redis-cached REST endpoints with a scheduled flush, CLI + REST interfaces, alembic, and a task state machine in `spimex_bulletin_tasks` next to `spimex_trading_results`.

**Contradictions with the «легенда» — name them, they are checkable in a minute:**

- The «карантин» table for unparsable rows **does not exist**: only two tables, and parse failures are handled locally (`InvalidFileName`, `IndexError/ValueError`). The story about a quarantine table must not be told at all.
- The README says the project is educational/research and not used commercially — it reads as a pet project and contradicts the «Банки.ру» label.
- `pool_size=100`, `max_overflow=250` against `max_connections=500`: timeouts were fixed by enlarging the pool. First thing a senior asks is how many engines and replicas exist and what was actually measured.

**What to tell instead:** idempotent re-parsing, the state machine, bounded concurrency, retry with backoff, and the cache-flush timing decision.

## Rule of thumb

His code helps him and his paperwork hurts him. Never propose improving the fiction to match the code — point at the two artefacts that contradict it and keep the technical prep on the parts that are real.


## Interview prep without artefacts

He has decided the repos are **not shown to employers** («коммерческий код» по легенде), so the useful deliverable is oral: three stories he can tell in depth without artefacts — очереди и DLQ с идемпотентностью, PostgreSQL под нагрузкой с цифрами, event loop и вынос CPU-bound работы. When he waves off depth («тонкие нюансы не спросят»), answer once with the posting's own checklist (if the ad names event loop/GIL, EXPLAIN, at-least-once vs exactly-once, DLQ, then that is the screen) and move on to the stories.

## Mock interview on his own code

When he says «попробуем» and asks you to choose the target, pick Lyria and pull questions from real identifiers in `/root/deploy/music_bot`, never from theory: per-domain aio-pika brokers and their DLQ, `prefetch_count`, the `bot:active_tasks:{instance_id}` registry, the composite index `(user_id, status, created_at)`, `attempt_id`/`delivery_attempt_id`, the 429/503 retry policy in `credits/service.py`. One block of 5–6 per message, «не знаю» explicitly allowed.

Known state: strong on retry taxonomy (4xx permanent, 429/5xx transient) — lead with that. Weak on AMQP delivery semantics, idempotency keys and B-tree prefix order; he thinks a free consumer picks up a hung one's unacked messages (it does not — only channel death or heartbeat timeout requeues). His answers come from the file, not the mechanism; say that plainly, give the mechanism in 3–4 lines, then re-ask a «что будет, если» follow-up. Do not grade pass/fail — the point is that «не знаю» is data.

`songai_dead_letters` has no consumer and no alert: dead letters vanish silently. Name it as a production gap and as the artifact worth building (consumer + DB record + alert + replay) — a better interview story than the theory he lacks.


## Design questions about his own code

Design questions about his own code («а есть практический, а не косметический смысл в X вместо Y?») get a practical-vs-cosmetic answer, not a survey of trade-offs. Name the mechanism in *his* code that would make the alternative matter — an import chain that drags infra, an `isinstance`, a second implementation, a test double that must subclass, a lock or a transaction boundary — and when none of them is present say plainly «менять не надо» and point at what is actually worth changing instead. A recommendation whose only argument is style reads to him as cosmetic advice, and he will call it out.
