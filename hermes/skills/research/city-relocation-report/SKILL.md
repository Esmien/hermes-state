---
name: city-relocation-report
description: "Use when a family weighs a move between two cities."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Research, Relocation, Russia, Family, Report]
    related_skills: [ru-local-price-research, blocked-page-recovery]
---

# City Relocation Report

Task shape: "мы с семьёй думаем переехать из X в Y — сравни всё, оформи красиво,
чтобы читал(а) супруг(а)". The deliverable is a long Markdown FILE, not a chat answer:
verdict in chat in five lines, the reasoning in the file.

## When to Use

- Any "стоит ли переезжать в <город>" with a family attached (partner, school-age child,
  pets, work constraints).
- Two-city comparison where the user wants quality of life, not a single metric — for a
  single metric (пробки, цены, зарплаты) use `ru-local-price-research` instead.

## Procedure

1. **Collect numbers first, write second.** Pull the quantitative layer from the other
   skill's file — `skill_view(name='ru-local-price-research',
   file_path='references/city-comparison-ru.md')`: rent, real estate, ЖКХ, fares, climate
   normals, rail/flight. Two independent sources per headline figure; date every one.
2. **Fix the family's real constraints before drafting.** Age/grade of the child, number and
   kind of pets, remote vs office work and its time zone, whether they buy or rent, budget
   ceiling. These drive whole sections; a generic city review without them is useless.
3. **Write the file** to `/root/<city-a>-<city-b>-pereezd.md` (ASCII filename) and send it
   with `MEDIA:/root/...md`. Offer a PDF or one-screen version as a follow-up, do not
   produce both unasked.
4. **Chat reply stays short:** verdict, 4–6 bullets of the sharpest findings, the file. No
   retelling of the document in the message.

## Structure of the document (in this order)

Title + subtitle + "для кого и на какую дату" → how to read it (what is sourced, what is an
estimate) → TOC with anchors → **короткий вердикт** (6 bullets, one per major axis) →
portraits of both cities (one paragraph each) → **climate as felt, not as numbers**
(season-by-season table + daylight + allergies) → **money** (rent, purchase, ЖКХ, everyday
prices, monthly family budget with a total) → **housing and districts** of the destination
(price table by district, which district for a family with a school-age child) →
**transport** inside the city and between the two cities (time + price per mode) →
**school** (exam calendar, transfer timing, named strong schools, "уточнять адрес и
правила приёма") → medicine → ecology/health → leisure → work and time zone →
**pets** (transport arithmetic, rental reality, winter) → two honest plus/minus columns →
**criteria matrix with a score line** → **"что вы потеряете"** → **разведпоездка checklist
+ step-by-step plan with dates** → one-page summary → sources with dates and caveats.

## Rules that make it land

- **A verdict, not a survey.** The summary section must name a winner per axis and an
  overall recommendation with a condition attached ("переезжайте, если... / не
  переезжайте, если...").
- **"Что вы потеряете" is mandatory and concrete.** Losing light, sea on weekends, family
  five hours away, and a four-hour workday shift is what makes the document credible to a
  partner who has to live with the decision. Vague "некоторые неудобства" reads as
  marketing.
- **Mark estimates inline** `*(оценка)*` and keep sourced numbers unmarked; state the date
  and the source for every statistic. Mixing the two without labels destroys trust.
- **Money gets arithmetic, not adjectives.** A table of monthly expenses with a total per
  city beats any "дороже/дешевле". Add the one insight the numbers actually give (e.g. the
  resale-vs-newbuild inversion that makes the swap gain or lose square metres).
- **Timing advice follows the school calendar.** Transfers mid-year are the worst option;
  name the concrete window (summer before the exam year) and say why.
- **Pets are a logistics section, not a footnote.** Count seats/carriers against the actual
  number of animals and passengers, state the rental reality for many animals, and note
  seasonal transport risks.
- **Readability for a phone:** 2–3 column tables max, short paragraphs, emoji only as
  section icons, blockquote callouts for the two or three insights that matter.

## Pitfalls

- **Numbers from one site only.** Cross-check; two sources with different methodology that
  agree are what justify a figure in the verdict. Do not average Rosstat deals with listing
  asking prices.
- **Invented local specifics.** School rankings, hospital rankings, district reputations are
  the easiest place to hallucinate. Name candidates, add "уточнять", and never assign a
  school to a district you have not verified.
- **Pulling live schedules** from captcha-walled sites wastes turns; rail time/price and
  direct-flight existence come from server-rendered sources or dated press.
- **Timezone and remote work are a real cost, not trivia.** If the family earns from another
  region, spell out the shift in working hours and what it does to evenings.
- **Do not argue the owner out of a known decision.** No-fallbacks/no-limits style choices
  and past refusals stay out of the "minuses" list.

## Reference

- Numbers, sources and parsing recipes live in the `ru-local-price-research` skill:
  `skill_view(name='ru-local-price-research', file_path='references/city-comparison-ru.md')`.
