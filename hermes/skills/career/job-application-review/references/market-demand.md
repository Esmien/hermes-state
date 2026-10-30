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
