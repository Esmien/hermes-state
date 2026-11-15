---
name: job-application-review
description: "Use when a vacancy, resume, or take-home needs a verdict."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [career, resume, vacancy, hiring, advisory]
---

# Job Application Review

## When to use

The user drops an hh.ru (or any) vacancy link and asks «как это ложится на мой стек?» / «а это?» / «це шо за хуйня?», or sends his resume / «легенду» / a Google Doc and asks what is wrong with it or what to fix. This is advisory work, not engineering: the deliverable is a verdict he can act on, not research volume.

Same umbrella covers his **test assignments (take-home)**: he links a repo (usually `Esmien/...` with a ТЗ document) and asks «посмотри, как сделано». That is a code review for a hiring funnel, and the verdict decides whether it gets sent — see the take-home section below.

Also covers the **market question**: «а есть ли сейчас спрос на X», «стоит ли мне переучиваться», «проверь это направление». Do not answer from general knowledge — count real vacancies and read real requirements (`references/market-demand.md`), then map the findings onto his profile in the same reply.

His hh resume carries **invented employers and dates** (СКБ Контур, Банки.ру). He knows and admits it; he wants the honest verdict on the risk of a tenure check, and he does not ask for the history to be polished toward senior. Never moralise — advise on exposure and on what to do if it comes up.

## Answer shape — verdict first

Telegram, Russian, bullets (no tables), no preamble, no flattery.

1. **Что это** — 2–3 строки: продукт, роль, формат, деньги, локация/резидентство.
2. **Насколько ложится** — конкретные совпадения из его стека, а не «подходит по опыту».
3. **Чего не хватает** — честно, по пунктам, с оговоркой, закрывается ли это тестовым или это структурный пробел.
4. **Вердикт** — прямо: «честная вакансия без цирка» / «не работа, а подписка на жизнь» / «хуита-стартап». Он ждёт оценку, а не пересказ.

When he needs a cover letter, write four short paragraphs: three verifiable facts from his production contour (not «есть опыт»), then one honest line that he has no commercial tenure in hiring. Never open with «у меня нет коммерческого опыта, но» — that framing hands the recruiter the rejection before the second sentence.

## Getting the posting

hh.ru: `api.hh.ru` answers 403 to non-browser clients, the HTML page does not. Fetch with a desktop UA and parse the `application/ld+json` block whose parsed `@type` is `JobPosting` — full recipe (and the whitespace/key-order trap) in the `blocked-page-recovery` skill, §4. Then read:

- `title`, `description` (strip tags, `<li>` → dash), `hiringOrganization`, `jobLocation`, `applicantLocationRequirements`, `datePosted`, `validThrough`;
- **salary is not in the JSON-LD** even when the body states one — read the number from the description, and if there is none say «вилка не указана» instead of guessing;
- **report days left until `validThrough`** — an expired or eight-day-left posting changes the advice;
- `hiringOrganization` may be the legal entity, not the brand named in the body — name both.

## His real profile — use this, not what a resume claims

Python backend. **FastAPI is his main and favourite framework.** aiogram 3, async SQLAlchemy 2.0 + alembic, Pydantic, pytest, HTTPX/tenacity.

PostgreSQL on a practical-expert level (pgvector, EXPLAIN, indexes, connection pools, table sizes, `VACUUM FULL`, restore verification), Redis, **RabbitMQ via taskiq with `dead_letter` queues**, Docker/compose, Linux (systemd, nginx, TLS, backups), GitHub Actions.

Does **not** have: Kubernetes/Swarm, gRPC/AsyncAPI, microservice patterns (Saga, Circuit Breaker) as his own design work.

His real asset is a **live production contour on his own VPS** — LiteLLM gateway over 40+ model groups, Open WebUI, Telegram bots with queues/DLQ, monitoring, verified backups, DB optimisations measured in factors. That is his portfolio and its numbers are checkable; treat it as stronger than a pet project on paper, and say so.

He is also pushing a **second framing, and it is the stronger one today**: «обычные бэкендеры не нужны, нужны AI-разработчики» — people who ship working code with agents, integrate external model providers and orchestrate autonomous agents. The agent-oriented ads ask for exactly what his contour already does (MCP tools, tool calling, context management, multi-step scenarios, multi-provider LLM routing, planning/orchestration), so lead with «Python/AI-разработчик, агентные системы» and keep infrastructure as evidence, not as the headline. Do not sell it as a bypass of the years-of-experience filter — say that once and move on. How to measure the demand instead of guessing, and the vocabulary the ads actually use: `references/market-demand.md`.

## Career-direction verdicts («я девопс или разраб?», «стоит ли учить X?»)

Same advisory work with a label instead of a posting: verdict in the first line («разработчик с сильным инфра-уклоном»), never «или/или».

Full text → [references/career-direction.md](references/career-direction.md)

## Agency «переобучение» offers («выбирай: ИИ / 1С / расторжение»)

A «менеджер отдела трудоустройства» offering переобучение or расторжение is not a job offer — read it as a funnel, and answer in his interest.

Full text → [references/agency-offers.md](references/agency-offers.md)

## Hard rules about experience

- **He has no commercial development experience.** Earlier resume versions listed invented employers and dates; he admits this himself and calls his level middle. Do not rewrite, thicken, or defend that history, do not reopen gaps in it, and do not rehearse answers for it.
- If he asks to make the «легенда» tighter, **decline once**, briefly, give only the verifiable reasons instead of moralising, then give the honest alternative (позиционирование «middle по навыкам, первый коммерческий найм», портфолио из прод-контура с цифрами, цель — небольшие продуктовые и аутсорс-команды, где решает тестовое). **Say it once.**
- Which arguments a real intermediary defeats, what survives a tenure check, and why not to steer him to senior postings: [references/experience-claims.md](references/experience-claims.md).

## Reviewing his GitHub repos (interview prep)

He hands over his own repositories when he wants technical prep and asks to clone them into `/tmp` and review **one at a time** — respect that, and never dump code into context.

```bash
cd /tmp && git clone --depth 1 -q <url>
find . -name "*.py" -not -path "./.git/*" | xargs wc -l | tail -1      # LOC
find . -name "test_*.py" | wc -l                                       # test files
grep -rho "def test_[a-z_]*" --include="test_*.py" . | wc -l            # test count
sed -n '1,70p' pyproject.toml; ls .github/workflows                    # deps + CI
```

Then grep only for the claim under review: the RBAC cache decorator and its TTL, `pool_size`/`max_overflow`, semaphores/timeouts/retries, cache invalidation, and `__tablename__` whenever the legend names a table.

Deliver in this order: what the code proves (state plainly whether it is confident middle), then **3–6 questions an interviewer would land on, taken from his own code** — never generic theory. Per-repo findings and the legend↔code contradictions are in `references/repo-review.md`; re-read it before reviewing again so the same weak points are not rediscovered.

He has decided the repos are **not shown to employers** («коммерческий код» по легенде), so the useful deliverable is oral — three stories he can tell without artefacts, and the posting's own checklist when he waves off depth: [references/repo-review.md](references/repo-review.md).

## Mock interview on his own code

When he says «попробуем» and asks you to choose the target, pick Lyria and pull questions from real identifiers in `/root/deploy/music_bot`, never from theory: per-domain aio-pika brokers and their DLQ, `prefetch_count`, the `bot:active_tasks:{instance_id}` registry, the composite index `(user_id, status, created_at)`, `attempt_id`/`delivery_attempt_id`, the 429/503 retry policy in `credits/service.py`. One block of 5–6 per message, «не знаю» explicitly allowed. Do not grade pass/fail — the point is that «не знаю» is data.

His known state (strong retry taxonomy, weak on AMQP delivery semantics, idempotency keys and B-tree prefix order), the `songai_dead_letters` gap worth naming, and how to answer «ответ из файла, а не из механизма»: [references/repo-review.md](references/repo-review.md).

## Reviewing a test assignment (take-home)

Bring it up isolated (own compose project, non-default ports, `touch /var/lib/docker-autorecover/pause`) and grade what the task really tests, not the happy path.

Full text → [references/test-assignment-review.md](references/test-assignment-review.md)

## Resume review checklist

Read the **settings block before the body**. The hh PDF opens with the search settings, and they disqualify more applications than any sentence below them:

- **Локация, формат работы, готовность к переезду и командировкам.** «На месте работодателя» + «не готов к переезду» + «не готов к командировкам» from a regional city closes almost the entire market, because remote ads are the only ones that ignore geography. Name the switches to flip first — five minutes of settings beats any rewrite of the text.
- **«Резюме обновлено».** hh ranks by bump date; a resume untouched for months is at the bottom of the pile. Advise bumping every 3–4 days.
- **hh's own «Опыт работы — X лет Y месяцев»** against the years claimed in «Обо мне» and against the dates themselves. Then count the **gap after the last role** — empty months read as a red flag even when the reason is honest; fill it with the real production contour, never leave a silent hole.
- **Vacancy keywords vs resume.** Brokers/DLQ, Linux/bash/network, code review/mentoring, k8s/gRPC: whatever genuinely exists goes in explicitly, because the keyword is the filter before any human reads it. His RabbitMQ+DLQ and Linux experience were missing entirely.

Then the checks that need more words — cross-document contradictions, the missing LLM/agent vocabulary, artefacts that read as unedited, the absent GitHub link, and the sections that already work and must not be «improved»: [references/resume-review.md](references/resume-review.md).

## Red flags to name explicitly

- «Заплатим столько, сколько попросишь» with no range.
- 24/7 on-call or a six-day week on a fixed modest salary — price it as the real cost of the job, not as a «условие».
- «Обучение»/«стажировка», состоящая из прокачки персонажа или работы на аккаунте компании — это не вакансия разработчика, скажи это прямо.
- «Тест на внимательность» inside the description (e.g. generate an image with their bot and attach it) — without it the application is discarded; state that rather than treating it as a formality.
- Residential/country requirement, and a legal entity different from the advertised brand.

## Reading his documents

Public Google Doc as plain text, no browser needed:

```bash
curl -sL -A 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36' \
  "https://docs.google.com/document/d/<DOC_ID>/export?format=txt" -o /tmp/doc.txt
```

Keep the extracted text out of the chat: summarise, quote at most short fragments, and never dump contact details.
