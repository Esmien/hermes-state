# Measuring what the market wants (RU, hh.ru)

> Read when he asks «а есть ли сейчас спрос на X», «стоит ли переучиваться», «что реально требуют» — instead of answering from general knowledge.

## Counting vacancies on hh.ru

`api.hh.ru` answers **403** to non-browser clients; `https://hh.ru/search/vacancy` answers **200** with a desktop UA. Use the site, not the API.

```python
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "ru-RU,ru;q=0.9"}
# text search (mentions anywhere) or search_field=name (title only)
url = "https://hh.ru/search/vacancy?" + urlencode({"text": q, "area": 1, "search_field": "name"})
count = re.search(r"Найдено\s*([0-9\s\u00a0]+)\s*ваканси", html)   # «Найдено 3 263 вакансии»
```

- **`search_field=name` is the number that matters** for «сколько таких ролей». Default full-text search returns 5–10× more: it matches any vacancy whose *description* mentions the word, which measures topic heat, not role volume. Report both and label which is which.
- **Vacancy ids** come from the serp HTML as `/vacancy/(\d{7,9})`; the detail page has `data-qa="vacancy-title"` and `data-qa="vacancy-experience"` (1–3 года / 3–6 лет), which is the honest answer to «есть ли вход для новичка». Salary is usually absent — say «вилка не указана» instead of estimating.
- **Description extraction:** the JSON-LD `JobPosting` block is cleanest when present; otherwise slice ~9 000 chars after `data-qa="vacancy-description"` and strip tags.
- **Sleep 0.5–1 s between requests** and keep the UA constant; bursts start returning captcha/403.

### Noise traps

- «агент» returns hundreds of **sales agents** (агент по недвижимости, страховой агент), not AI agents. Count role titles explicitly: `AI`, `LLM`, `AI-разработчик`, `AI-агент`, `AI Engineer`.
- «промпт-инженер» as a *title* is a handful of vacancies; almost every AI ad lists prompting as a skill, not a job. Do not present the title count as the size of the field.
- Roles are named inconsistently (AI/LLM Engineer, Разработчик AI-агентов, Middle Python/AI Developer), so name-search undercounts. Combine several spellings and say the method limitation out loud.

## What agent-oriented ads actually ask for

The recurring vocabulary is the useful part, because it is what the resume and the cases have to mirror:

- ядро корпоративного ИИ-ассистента; **MCP-инструменты**, вызов инструментов, REST/БД-интеграции;
- **агентные сценарии**: управление контекстом, структурированные ответы, многошаговые процессы;
- **интеграция LLM разных провайдеров** и оптимизация качества/стоимости;
- **планирование, оркестрация и выполнение задач агентом**; автономность в проде;
- backend на Python (FastAPI/async) плюс Kafka, gRPC, WebSocket, CI/CD.

## Mapping him onto it — and the honest caveats

His production contour covers almost every bullet: a live agent with tools and skills, LiteLLM as one routing point over many model groups, incident automation that launches an agent, backups/restore. That is rarer than a LangChain pet project, and it is the differentiator to lead with.

State the caveats in the same answer:

- AI roles still filter on years and teamwork; the entry is junior+/middle with 1–3 года in some ads, not a bypass.
- The document about his server is **not** the hiring artifact; a public agent-side project (MCP server + agent loop + tests), a Lyria repo with README/tests/CI, and 2–3 written cases are.
- Positioning to recommend: «Python/AI-разработчик, агентные системы» — not «Python-бэкендер», with infrastructure as supporting evidence.
- Lyria's open tail (uncommitted files) is the first thing to close before any of this is shown to anyone.

## Geography — «а не проще ли искать в городе X»

Area ids for `area=`: Москва **1**, Санкт-Петербург **2**, Новосибирск **4**, Краснодар **53**, Россия **113**. `api.hh.ru/areas/113` answers fine (only `/vacancies` is 403), so resolve a city id by walking the tree instead of guessing.

Compare on three numbers, never on a raw count alone:

- name-search count per city;
- `&schedule=remote` over РФ;
- **per-capita density** (count ÷ population) — 13 ads in a 1.6M city is thinner than 572 in 13M, and saying so out loud is what stops the «может, переехать» reflex.

Most remote ads carry the employer's city, not the work location (303 of 435 remote AI ads are labelled «Москва»), so «в городе X нет удалёнки» is the wrong conclusion to draw — the work is remote, the vacancy is just published where the legal entity sits. Say that explicitly when he reads a city count as a work-format count.

Filters that answer «есть ли вход»: `&experience=noExperience`, `&experience=between1And3`, `&experience=between3And6`. If the counter is missing from the HTML (`-1`), the page came back without it (captcha / rate limit) — pause 2 s and retry once; never report it as zero.

## Directions — QA, DevOps, AI, and what each entry filter really is

When he asks «а не податься ли в X», answer with counts **and** with the entry filter, because they differ per direction:

- **QA** — biggest pool, lowest bar, ручной QA takes a beginner in weeks; also the track most exposed to AI tooling. Offer it as a fallback with a trigger («если через N месяцев откликов ноль»), not as a plan.
- **DevOps** — smaller pool than AI (roughly 270 vs 570 name-search ads in Moscow), and the filter is **not years but k8s / Terraform / Ansible / cloud**. In DevOps those are the entry ticket; in AI roles Kubernetes is a plus (about half the AI ads mention it). Do not reuse the AI advice here — flip it explicitly, he will notice the contradiction otherwise.
- **AI / agent roles** — filter is years plus a demonstrable agent system, and that is where his contour is the differentiator.

**Trainee programmes are a cost, not a job.** «Месяц интенсива + стажировка 3–4 месяца 5/2, потом от 70 000 ₽ до вычета» for a DevOps «ученик» is a hiring-funnel business model; for someone with a live production contour it is a step backwards. Quote the net monthly, the months, and the fact that he already does the syllabus.

## «Это долго и сложно?» — time-to-competence

At 1–2 h/day, to *working* level (not mastery):

- **Prometheus + Grafana** — 1–2 недели; he already monitors, this is a top-up and an immediate resume line.
- **Сети** — 2–4 недели до «не плыву на собесе» (TCP/IP, DNS, TLS, tcpdump, nftables).
- **n8n** — 3–5 дней; a plus in ads, not a requirement.
- **ClickHouse** — 2–4 недели до базы (MergeTree, ORDER BY, партиции, TTL, materialized views); almost every ad wants it *on a project*.
- **«Глубокий» Linux** — years in the abstract, but 3–4 недели to interview level on named topics: systemd, cgroups, namespaces, proc, strace, I/O.
- **Kubernetes** — 2–3 месяца, the most expensive item; without a real cluster it stays paper.

Attach three rules to any such answer: **one topic at a time** (six in parallel = zero in three months), **one topic = one artifact** in the portfolio (a RAG demo with Grafana metrics covers three items at once), and a **decision deadline** — «если за две недели не начал k3s, направление не твоё» — so the choice closes instead of becoming another month of reading.
