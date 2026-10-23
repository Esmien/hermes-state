---
name: job-application-review
description: "Use when a vacancy or resume is sent for a verdict."
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

## Answer shape — verdict first

Telegram, Russian, bullets (no tables), no preamble, no flattery.

1. **Что это** — 2–3 строки: продукт, роль, формат, деньги, локация/резидентство.
2. **Насколько ложится** — конкретные совпадения из его стека, а не «подходит по опыту».
3. **Чего не хватает** — честно, по пунктам, с оговоркой, закрывается ли это тестовым или это структурный пробел.
4. **Вердикт** — прямо: «честная вакансия без цирка» / «не работа, а подписка на жизнь» / «хуита-стартап». Он ждёт оценку, а не пересказ.

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

## Hard rules about experience

- **He has no commercial development experience.** Earlier resume versions listed invented employers and dates; he admits this himself and calls his level middle. Do not rewrite, thicken, or defend that history, do not reopen gaps in it, and do not rehearse answers for it.
- If he asks to make the «легенда» tighter (typically covered by «работал по аутстаффу»), **decline once**, briefly, and give only the verifiable reasons instead of moralising. Drop the arguments his setup defeats: a real intermediary that files ГПХ/НДФЛ reporting leaves СФР periods behind, so «нулевой стаж / нет ЭТК» does not hold; «коммерческий код под NDA, показать не могу» is a legitimate answer that closes the code question; tax reporting belongs to the counterparty, not the employer. What survives: the **named client brands** never confirm a subcontractor, the claimed dates must match the intermediary's reporting periods, and a МФО/МКК under ЦБ runs a compliance check as part of the funnel, not as a courtesy.
- Then immediately give the honest alternative: позиционирование «middle по навыкам, первый коммерческий найм», портфолио из прод-контура с цифрами, цель — небольшие продуктовые и аутсорс-команды, где решает тестовое.
- **Say it once.** After refusing, keep helping with the substance (resume structure, target list, what to study) — repeated moralising is the failure mode, not the refusal.
- Do not steer him to senior postings that assume 4–5+ years and microservice architecture; that is where a biography check is part of the funnel.

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

He has decided the repos are **not shown to employers** («коммерческий код» по легенде), so the useful deliverable is oral: three stories he can tell in depth without artefacts — очереди и DLQ с идемпотентностью, PostgreSQL под нагрузкой с цифрами, event loop и вынос CPU-bound работы. When he waves off depth («тонкие нюансы не спросят»), answer once with the posting's own checklist (if the ad names event loop/GIL, EXPLAIN, at-least-once vs exactly-once, DLQ, then that is the screen) and move on to the stories.

## Resume review checklist

- **Claimed total experience vs date arithmetic.** He under-claimed 3.5 years against dates that span 4 — a filter he fails for free.
- **Gap after the last role** — fill it with the real current work (his production contour), never leave a silent hole.
- **Vacancy keywords vs resume.** Brokers/DLQ, Linux/bash/network, code review/mentoring, k8s/gRPC: whatever genuinely exists goes in explicitly, because the keyword is the filter before any human reads it. His RabbitMQ+DLQ and Linux experience were missing entirely.
- **Artifacts that read as unedited:** empty section headers, truncated words, typos, contradictory dates.
- **No GitHub/portfolio link** — a minus that matters more when formal tenure is absent.

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
