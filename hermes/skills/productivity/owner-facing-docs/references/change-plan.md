# Shape that works for a change plan / proposal

Trigger: «напиши подробно, понятным языком, какой у нас план, что делаем, как делаем, трейдоффы и результат». The subject is a change that does **not** exist yet: every claim is a claim about what will be built, so the document must survive being argued with line by line.

1. **Вердикт** — two or three lines naming the real cause, not the symptom («упираешься не в железо, а в отсутствие квот»).
2. **Что сейчас** — table of live numbers: what runs, its limits, what it actually costs.
3. **Что строим** — numbered list of the moving parts, one sentence each.
4. **Из чего состоит** — table «файл / юнит → что делает». Real paths, so he can check them afterwards.
5. **Как это работает по шагам** — the lifecycle, not the code: появился пользователь → пишет → удалили → ребут → что видит админ. Each step states what the user sees while it happens.
6. **Цифры** — before/after table for RAM, CPU, disk, time. Give the arithmetic (11 × 31 MiB), not the sum alone; he checks it.
7. **Трейдоффы** — table «решение / зачем / чем платим». The cost column is mandatory and never «немного»: a real number or a real consequence.
8. **Что это не решает** — mandatory section. Shared physical limits, shared disk, shared network, anything the design cannot fix. Without it the document reads as an advert and he discards it.
9. **Порядок работ** — phases, each with `Проверка:` (a command and its expected output) and the rollback once for the whole plan.
10. **Открытые решения** — numbered questions, each with a proposed default, so he can answer «1 — да, 2 — 1.5 ГБ» instead of writing prose. Only include a question whose answer changes the implementation.
11. **Оценка** — hours, split by phase, naming the phase that will eat them.

Rules for this shape:

- **Limits are numbers he chose, never adjectives.** «1.5 ГБ / 1 CPU на контейнер», not «разумные лимиты»; «храним 3 дня», not «недолго».
- **His conscious choices stay boundaries.** «Одна машина, без кластера» goes into границы, never into «что не решает» as a shortcoming.
- **Every number in the plan is measured before it is written.** Idle memory, image size, free disk, current caps — read them with a command; a plan built on remembered numbers gets rejected on the first check.
- **A rejected proposal is rewritten, not re-argued.** When he refuses a mechanism («даёшь всем рут»), replace the mechanism and say in one line what it costs instead of defending the old one.
