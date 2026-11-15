# Career-direction verdicts («я девопс или разраб?», «стоит ли учить X?»)

Same advisory work as a vacancy review, with a label instead of a posting read. Verdict in the first line — «разработчик с сильным инфра-уклоном», never «или/или» — then split the evidence in two: **есть, но недоказано** (код без команды, ревью, легаси, нагрузки) и **глубина есть, ширина нет** (инфра на одной ноде, без k8s/IaC/публичного облака). Close with what to do next, ranked.

- Judge against the **hiring funnel**, not his self-image: what a screener actually checks. «На DevOps не возьмут» он принимает только когда названа причина (одна нода, нет оркестрации, нет IaC) — называй её.
- **Never** list his deliberate choices as deficiencies (Prometheus off, no key limits, no fallbacks). If a deliberate choice really blocks a market, phrase it as missing *market* experience with X, not as a hole in his contour.
- Investment advice gets an **ROI ranking**, cheapest/most-differentiating first, one reason per line. For agent-oriented roles the order is: **evals + tracing** → один публичный агентский кейс с цифрами (тикетов/день, ₽ за прогон, точность) → MCP-сервер над своим стеком → k8s **последним**.
- Titles are marketing, not professions. «AI-driven разработчик» без одного кейса, выраженного как результат+число, ничего не продаёт — сказать это один раз и перейти к артефакту.
- **k8s — галочка про доставку, а не дифференциатор.** Когда он оправдан, k3d vs k3s, и проба хоста перед обещанием локального кластера: [references/market-demand.md](references/market-demand.md).

### Калибровка уровня: «я ведь зелёный джун?»

Он периодически сам поднимает тему — «джуны умеют то, что я сделал?», «я только что нашёл узкое место в чужом проекте, серьёзно?». Вердикт всегда **расщеплённый, а не ярлык**: «по объёму и сложности — мидл, по процессу — джун».

- **Ширина** — из его собственных артефактов, а не из похвалы: `/payment-service` (FastAPI, unit-of-work, транзакционный outbox, обязательный `Idempotency-Key` с конфликтом, воркер + брокер, ~5.3k строк, 95 тестов), `/root/deploy/music_bot`, и прод-контур VPS. Цифры называть — они проверяемы.
- **Процесс** — то, чего в соло-режиме не бывает и что добирается только в команде: ревью над тобой, чужая кодовая база, оценка сроков, дисциплина тестов под дедлайном, документация для незнакомых людей. Это не «мозги» — это среда; так и говорить.
- **Не поднимать самооценку до сеньора и не утешать.** Сравнение с типичным джуном (CRUD в готовом проекте, инфра — не его, `tcpdump` — мем) даёт больше, чем комплименты.
- **Найденное узкое место ≠ сделанная работа.** Кредит за мышление (отделил симптом от слоя, сам пришёл к очереди), но цена — доказательство числом: 50 параллельных загрузок, lag event loop и RSS, график до/после, issue/PR. Один такой полный цикл — артефакт для собеседования; три — смена ярлыка.
