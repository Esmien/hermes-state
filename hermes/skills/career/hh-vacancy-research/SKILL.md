---
name: hh-vacancy-research
description: Use when researching RU job market or a vacancy on hh.ru.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [hh, vacancies, job-search, scraping, ru-market]
    related_skills: [city-relocation-report, job-application-review]
---

# hh.ru research

## When to Use

Владелец присылает ссылку на вакансию hh.ru, спрашивает про объём/требования/зарплаты/удалёнку на рынке РФ или сравнивает города по числу вакансий.

## Доступ
- `https://api.hh.ru/vacancies` → **403** с этого хоста (любой UA). Скрейпить HTML поиска.
- `https://api.hh.ru/areas/<id>` **работает** — брать id городов оттуда (Москва 1, СПб 2, Новосибирск 4, РФ 113, Новосибирская обл. 1202).
- Обязателен браузерный UA (`Mozilla/5.0 ... Chrome/126 ...`), иначе 403. `hh.ru/vacancy/<id>` отдаётся целиком, JS не нужен.

## Подсчёт вакансий
`https://hh.ru/search/vacancy?text=<q>&area=<id>[&search_field=name][&schedule=remote][&experience=between1And3|noExperience]`

Число — regex `Найдено\s*([0-9\s\u00a0]+)\s*ваканси`; в HTML есть шаблонные `Найдено {0}`, брать первый с цифрами.

- `search_field=name` — только заголовки (реальные роли); без него — любое упоминание в тексте, раздувает в 3–5 раз. Для оценки рынка давать обе цифры.
- `schedule=remote` — удалёнка; большинство помечено Москвой, это не значит «только Москва».
- Ловушки: «агент» ловит «агент по продажам»; «AI» ловит AI-тренеров, продажи, маркетинг. Выдачу смотреть глазами.

## Разбор вакансии
`https://hh.ru/vacancy/<id>`; поля: `data-qa="vacancy-title"` (h1), `vacancy-company-name`, `vacancy-experience`, `vacancy-salary` (часто пусто), `vacancy-description` (взять 9–12 КБ после маркера, вычистить теги).
Ссылки из выдачи: id через regex `/vacancy/(\d{7,9})` — href в разметке не парсится.

## Формат ответа владельцу
Вердикт первой строкой → цифры таблицей/bullets → маппинг «требуют → есть» → где провал → стоит ли откликаться → готовое сопроводительное (5–8 строк, без вранья про стаж).

## Контекст владельца
Python-бэкендер без коммерческого стажа, ищет с конца июля 2026. Сильное: прод-автоматика на агентах, LiteLLM, structured output/tool calling, Docker/Postgres/Redis. Дыры: LangGraph/LangChain, RAG (эмбеддинги, rerank), CI/CD, командное ревью, формальные годы. Аутсорс-стажёрки (Aston «ученик», 70k, 9–18 5/2) — шаг назад, не советовать.
