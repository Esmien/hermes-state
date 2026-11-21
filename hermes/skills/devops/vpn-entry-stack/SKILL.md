---
name: vpn-entry-stack
description: Use when editing or deploying the VPN entry stack.
version: 1.0.0
author: VPS Admin
license: MIT
---

# VPN entry stack (VLESS: WS+TLS / hysteria2 — Vision и REALITY сняты)

## When to Use

Load this before touching anything that serves VPN clients: adding or removing a route, moving the public host or certificate, regenerating subscriptions, or answering a "VPN keeps dropping / no internet" report. Also load it for «нас РКН забанят?» / «что делать, если заблокируют» — `references/blocking-risk.md`. Not for the AI services on the same host — that is `ai-stack`.

Treat claims that a port or protocol is blocked as hypotheses: correlate client tests with `stream-443.log` and the vhost log, verify the WS path, then compare networks when relevant. A successful test from one device or operator proves neither universal reachability nor DPI invisibility; genuine TLS can also be blocked.

## Safe rollout and scope

- Preserve the owner's current subscription nodes, names, links, routing and functioning UDP backup unless he explicitly orders removal. He removed the two manual Gemini/NL nodes; do not restore their public routes or subscription entries. Verify the live state before changing anything.
- При параллельном переезде сохраняй старые входы, ссылки и страницы до отдельного решения владельца. `share.esmien.com` работает параллельно `vpn.esmien.ru`: новый лендинг и подписка на TCP/443, старые на TCP/8443, UDP Hysteria обоих на 8443. `vpn-parallel-domain.service` (127.0.0.1:18744) динамически выдаёт актуальные страницы и три формата подписок с новым именем, перекодирует base64. Генератор `apply_brand.py` сохраняет оба SNI и раздельные nginx-сертификаты. Hysteria использует встроенный ACME DNS-01 и раздельные сертификаты по SNI; его конфиг содержит CF-токен и должен оставаться секретным. При изменении конфига сохраняй пустую строку после auth-блока — `hy2_users.py` ищет её как границу. Не прерывай тестовый DNS-01 посередине: временный TXT останется в Cloudflare и сорвёт повтор. Уже выпущенный общий сертификат навсегда остался в CT, хотя больше не обслуживает трафик. Проверяй страницы, три формата и реальные VLESS/Hysteria туннели на обоих доменах; локальный тест не доказывает доступность из сети клиента. Восстановление — README в vpn-service.
- When the owner requests private-first testing, stage the change separately and test only with his actual subscription and key; inspecting other profiles is fine, connecting with their keys is not. A localhost tunnel is not his device/network test. Deploy shared routing, ports or subscription changes only after his device validation unless he explicitly authorizes an immediate shared switch; report its blast radius. For a separate-port phone test, stage an isolated nginx listener and an owner-only subscription node, preserving his existing nodes and all other subscribers; verify local end-to-end first. Disclose if other valid keys also work, and after validation stop the listener, remove the temporary node and verify the port is closed. A different port validates the staged route, not actual production-port reachability or identical behavior.
- Before retiring a listener, inspect current published profiles **and** recent use: refreshed subscriptions do not prove that every manually imported or stale client has migrated. Inspect every SNI/vhost sharing the socket: deleting one DNS record does not close a port or disable other names. Treat TCP and UDP on the same number independently; preserve the owner's UDP backup when discussing TCP closure. State which legacy subscriptions and clients would break; a broad request to reduce exposure is not permission to cut them off.
- Before running `apply_brand.py`, inspect its actual side effects: it invokes subscription and page generators as well as rewriting nginx files. Disclose that scope, capture secret-safe before/after hashes when preservation matters, and suppress or sanitize generator output because it can contain subscription tokens. Report the script and outputs actually regenerated, not just «regenerated the template».
- For an audit constrained to the present server/ASN, work within that constraint and don't repeatedly offer excluded migrations. Do not re-open a risk the owner explicitly accepted as an action item without new evidence.
- Report what was actually applied, independently tested and still unverified; inspect the real failure behavior of RU relays before promising per-request `000` failover, since a balancer's health/fallback settings alone do not establish that behavior.

## Reporting to the owner

**Инструкции, ранбуки и планы — лесенкой, без жаргона.** Он прямо просил: «пиши такие вещи как дебилу, всегда». Значит: нумерованные шаги, в каждом — одно действие, затем что ты увидишь после него. Никаких «поднять nginx stream на прослойке» — «взять дешёвый сервер в другой стране, поставить туда nginx, который переливает пакеты на наш». Термин можно, но сразу с переводом в скобках. Аналогии допустимы и приветствуются («съёмная входная дверь», «киоск с бумажками»). Скомканный текст с пятью терминами в строке он считает бесполезным, даже если всё в нём верно.

He runs this stack himself and treats reports as noise unless they answer the question he asked:

- Answer in one line, then at most three or four bullets of substance. The payload — a new subscription URL, a login, a number — goes at the top, bare, without a lead-in.
- Do not replay the checks you ran, list the files you touched, or volunteer «две оговорки» nobody asked for. A long report earns «да как же ты достал», an invented label earns «не приши лишнее» — the fix is fewer words, not more explanation of the words.
- When he corrects a name or a label, use his string verbatim and change nothing else in that pass: «просто — Саша. И всё» means exactly that, not «Главный ключ (мой + Саша)».
- A destructive request stated plainly («снеси нахуй X») is a work order: do it, then say in one line what died with it and how it would come back. Do not re-ask and do not lecture about the risk first.
- «Пока ничего перманентно не меняй» — это не «ничего не делай»: меряй временным процессом на одноразовом порту (свой `xray run -c /tmp/…json`), потом погаси его, убери конфиг и в отчёте одной строкой напиши, что постоянного не тронуто. Отчёт без этой строки читается как «он там что-то переключил».
- He asks «почему» to get a cause, not a plan: explain the mechanism in two or three lines and stop. Make the obvious fix instead of offering it. **No closing tail** — a volunteered «делать?» / «скинуть?» in every message is what he calls «хвост рассуждений»; ask only when a real branch needs his decision, then exactly one question (style rules live in `telegram-gate-and-bots`).
- Short is the default, but an explicit «подробно, по-человечески, для дебилов» is a different order and wins: then give the long version — analogy first (electronics/repair lands well), then the chain of steps, then what we gain, what we do not, and what it costs. Do not answer a request for depth with a summary; equally, do not turn a one-line question into that essay.
- When he argues with a model of his own («это целый сервис, его не положат»), first name the half he is right about, then dismantle the wrong half with the mechanism and a number. If the number contradicts something you said earlier, correct yourself in one line and replace it with the measured fact — he checks arguments against data, and a retracted figure costs less than a defended one.
- **«Ты сам себе противоречишь» — это проверка, а не приказ отступить.** Он переспрашивает («так дырка или не дырка?», «исходя из твоих слов выше») каждый раз, когда вывод звучит мягче механизма. Не откатываться в «всё нормально»: назвать, что оба утверждения — причина и следствие одного механизма, и дать калиброванную формулу («дырка, компенсированная эксплуатацией, а не архитектурой»). Отступление здесь читается как «продавил» и обнуляет весь разбор.

- **«Напиши сообщение, чтобы я переслал» — это отдельный артефакт, а не выжимка отчёта.**
  Адресат не видел наш контекст: каждый пункт = «что видно снаружи» + «что сделать», без
  ссылок на наши скиллы, порты и договорённости; термины только с переводом в скобках;
  один пункт — одно действие; без оценок и морали. Сначала — что не так и почему это опасно
 (в одном предложении), потом список действий по важности. Владелец пересылает текст
 дословно, поэтому он должен быть самодостаточным. «Объясни простыми словами» — это ещё не
 заказ письма: если после разбора терминов он просит «сообщение целиком, чтобы переслать»,
 артефакт — письмо адресату, а не словарь определений.

## Layout

```
client -> nginx TLS on edge -> xray container (host network)
       -> direct, Gemini NL / Gemini-relay, or RU relays according to routing
```
Main WS profiles use 443; subscription delivery and UDP backup use 8443. Check live firewall and listeners before naming other ports as available: a socket may still exist while external ingress is filtered.

**Высокий случайный порт — не «палево», но и не защита.** Голый TLS на 10605/14308 не маркер: так выглядят миллионы игровых серверов, панелей и БД. Маркирует комбинация — TLS на высоком порту плюс сертификат бесплатного DDNS (`*.chickenkiller.com`, `*.mooo.com`) или чужого бренда (`*.google.com`, Apple EV на IP хостера): с 2026 автоматика сверяет «SNI ↔ владелец адреса». Что порт реально даёт — уход от волн, бьющих по TLS-хендшейку **именно на 443** (ноябрь 2025, февраль и май 2026). Чего не даёт — ничего против SNI-фильтра, детекта протокола по первым ~16 КБ и активного зондирования, которые порт не смотрят. Цена: часть сетей (корпоративные, гостиничные, иногда мобильные) пускает только 80/443, и «у клиента не подключается» там вероятнее, чем находка сканера. Решение владельца 19.11.2026: **443 остаётся основным**, 8443 и hysteria2 UDP — резерв; высокий порт допустим только как третий вариант в подписке, не вместо 443. От блока подсети/AS (волна с августа 2026) порт-диверсия не спасает вообще.

Inspect the live inbounds, routing rules and generated subscriptions before editing paths; historical pruning notes can be stale. `/general` remains the internal main inbound; the owner's former manual `/france` and `/gemini` public entries were retired at his request, while internal inbounds and automatic Gemini routing remain. Do not restore the public entries or infer current behavior from an old path name or outbound label.

There is deliberately **no** RU-entry inbound: an earlier `/lte` route (`1.fan-video.study` → Selectel SPb → Helsinki, Google saw it as `ru`) was removed once it was clear the whitelist first hop has to be dialled by the client itself, never by this server. Whitelist entries ship as direct client links only — see `references/whitelist-mode.md`.

3x-ui is **not** part of the stack: container, volume, `/panel/` route, credentials file, panel vhost, its rate-limit zone and fail2ban jail were all removed. It managed two idle inbounds and could not express "this entry -> that exit", which is the whole point of the routing, so it was one public admin surface for nothing. `references/xui-panel.md` keeps only the CSRF/login knowledge in case a UI is ever reintroduced — do not bring a panel back off your own initiative.

Upstreams and enabled inbounds can change with blue/green and manual nodes. Inspect live config and `vpn-cfg status` before asserting that a path or inbound was removed; `in-france` and `in-test` are used by the owner's manual nodes.

Adding a route means four coordinated edits, in this order: append an inbound (`tag`, 127.0.0.1, next free port, same client id, `wsSettings.path`) to `config.json`, add the outbound and a routing rule keyed on `inboundTag` **before** the catch-all `tcp,udp → direct` rule, add `paths` + `upstreams` entries to `brand.json`, then `apply_brand.py && nginx -t && systemctl reload nginx && vpn-cfg apply` (not a bare `docker restart` — `apply` proves the routes answer and reverts a broken config). Verify by dialling the new path through the tunnel and checking the egress with ipinfo — not by reading the config back.

Files: `/root/vpn-router/{config.json,brand.json,apply_brand.py,make_sub.py,make_template.py,import_sub.py,users.py,probe_sub.py,test_whitelist.py,gemini_geo_check.py,sub_expiry.py,route_ru.py,subs.json,users.json,failover.py,certbot_retry.py,provision_vpn_host.py}`, subscriptions in `/var/www/esmien-sub/<token>/`. Editing, applying and rolling back: `vpn-cfg` (`references/router-ops.md`). Per-user/route traffic counters and «кто пользуется подписками»: `references/usage-stats.md`;
сама панель (иконки/вёрстка, счётчики и смена адресов, генератор профилей) — `references/stats-dashboard.md`;
панель закрыта по IP (allow edge+loopback, снаружи `444`) и требует правила `stats.esmien.* → direct`. Прикрытие вместо `Welcome` — изолированная копия статики панели LiteLLM на `127.0.0.1:8092` (рабочий `:4000` с этих входов недостижим, любой вход → тот же `401`); маскарад Hysteria — `references/decoy-and-access.md`. **Счётчики не зависят от адресов**: они живут на `user>>>` и `outbound>>>`, поэтому смена входа или `sendThrough` ни одной строки не сбрасывает — меняется только смысл подписи («Эстония (основной)» = тег `direct`). Вёрстку панели проверять измерением (`--dump-dom` + метрики в `document.title`), а не скриншотом: headless Chromium держит ширину окна ~500 px и картинка врёт про обрезания. When a client reports that the VPN "keeps dropping": `references/client-drop-triage.md` — probe the server end to end before touching anything, and start with DNS: an entry whose name no longer resolves looks exactly like a dead VPN (app can't ping any node, browser still works from cache). **Один мёртвый вход ≠ мёртвый адрес:** прежде чем говорить «режут IP», сверить все входы в одном окне — если WS и UDP несут трафик, душат конкретный транспорт, а не адрес.

## Deploy / rebuild

The entry is deliberately one container plus flat files, so a fresh server is a script run, not a rebuild from memory:

```bash
bash assets/vpn/scripts/deploy.sh <domain> [email]     # nginx+stream, cert, container, vhosts, subs
python3 /root/vpn-router/import_sub.py <sub-file> [dead indices]
```

The VPN is its **own project**, not part of the AI-stack installer: the canonical repo is the private `Esmien/vpn-service` (`router/`, `nginx/`, `scripts/`, `systemd/`). A full server rebuild is therefore two steps — `install.py` for the AI stack, then `deploy.sh` from this repo for the entry; the bootstrap one-liner does not bring the tunnel back. After any structural change, regenerate the secret-free template with `router/make_template.py`, copy the live files into the repo, and commit — it must match the live host exactly. Runtime secrets stay out of git via `.gitignore`: `config.json` (client UUID), `users.json` (per-user UUIDs), `subs.json`, `whitelist_links.json`, `*.key`, `*.pem`, `*.enc`. Full procedure and pitfalls: `references/router-ops.md`.

The owner-facing counterpart is `/root/.hermes/docs/vpn-runbook.md`: scheme with real ports and paths, every design decision with its price, a nine-step rebuild with a check after each step, six diagnostic commands with a symptom table, and the pitfalls in `references/pitfalls.md`. It lives in the `hermes-state` snapshot, **not** in `vpn-service` (that repo takes only what actually runs on the host). After any structural change — a new port, path, scenario, timer or exit — update the runbook in the same pass; he asked for it so he can rebuild the stack by hand, and a stale runbook is worse than none.

## Changing the public host

For an explicitly authorized full cutover, move host, port, cert and subscriptions together: nginx server blocks, `brand.json` paths, regenerated subs and `vpn-cfg`'s own `HOST=` copy, then `apply_brand.py && nginx -t && reload && vpn-cfg apply` — a stale host copy makes `apply` probe the old name and revert a good config. For a parallel migration, do not replace the single global `host`: retain the old entry and delivery while adding the new one, with separately correct page and subscription links.

Full text → [references/changing-public-host.md](references/changing-public-host.md)

## Scenario routing / one-node subscription

**Правило «всё остальное» смотрит в `direct`, а не в релей.** Пока catch-all указывал на `fr`, каждый
сбой французского релея валил пачками весь неразобранный трафик — читается как «интернет не работает»,
а виноват один outbound.

**Google не делить между странами.** Весь Google-фронтенд (`google.com`, `googleapis.com`, `gstatic.com`,
`googleusercontent.com`, `withgoogle.com`, `google.dev`) идёт через **один** выход, а тяжёлое видео
(`googlevideo.com`, `ytimg.com`, `ggpht.com`, `gvt1/2`, `youtube.com`) — отдельным правилом **выше** него
на `direct`. Узкий список «только Gemini-хосты» (проверено, стоило полдня) ломает отправку сообщения:
веб-клиент тянет ещё `accounts.google.com`, `www/ssl/fonts.gstatic.com`, `ogads-pa`/`signaler-pa`/
`geminiweb-pa.clients6.google.com`, `ogs.google.com`; страница приходит с FR, а API уходит с EE — Google
отвечает `200` с ошибкой в теле, и UI показывает общий «ошибка 1» без адреса. Догонять список по одному
хосту бессмысленно: набор меняется, а цена одного промаха — тот же отказ.

**Gemini: NL-адрес — первый эшелон, Gemini-relay — второй.** Глобальное правило Google-цепочки
(`google.com|googleapis|gstatic|googleusercontent|withgoogle|google.dev`) смотрит в аутбаунд
`nl` (`freedom` + `sendThrough: 85.92.158.226`). При заглушке сторож переключает это правило
на `bal-google` (в разговоре — Gemini-relay: страна выхода плавает, на 19.11.2026 Сингапур,
`com.sg`/`SGP`). `fallbackTag` у `bal-google` = `fi`, не `blocked`. Видео
(`googlevideo|ytimg|ggpht|gvt1|gvt2|youtube`) остаётся на эстонском выходе.

Политика владельца: `141.*` засвечен и работает «пока не умрёт», NL берегут — в него идёт
минимум сервисов и минимум трафика (только Gemini-набор). Гонять через NL общий трафик,
видео или чужие сервисы нельзя; основным он станет **только** после смерти `141.98.166.213`.
Полная карточка (адреса, домены, порядок правил, сторож, быстрые проверки) —
[references/gemini-gate.md](references/gemini-gate.md).

`sendThrough` живёт **на уровне аутбаунда**, а не в `settings`: `{"tag":"nl","protocol":"freedom",
"sendThrough":"<ip>"}`. Внутри `settings` Xray 26.x его молча игнорирует — egress остаётся
прежним, и это легко принять за «IP не работает». Проверка одна: `curl --socks5-hostname` через
такой аутбаунд → `ipinfo.io/ip`, либо `curl --interface <ip> https://ipinfo.io/ip`.

Заглушку нельзя ловить словом «недоступно» и нельзя лечить `fallbackTag`: Gemini **всегда**
отдаёт `200` и непустую страницу (≈960 КБ) и в заглушке тоже. Маркер — ISO-код страны в
`this.gbar_`: рабочий NL даёт `"nl"` и `"NLD"`, эстонский/заглушка — `"ru"` и `"RUS"`.
`gemini_gate.py` + `vpn-gemini-gate.timer` (`OnUnitActiveSec=150min`, `RandomizedDelaySec=600`)
тянет страницу с привязкой к NL-адресу (`curl --interface`), читает этот маркер и при
заглушке/ошибке переводит глобальное Google-правило на `bal-google` через `vpn-cfg apply`;
возврат на `nl` — после **двух** здоровых проверок подряд. Тест логики без поломки:
`--pretend-stub`.

**Ручные узлы Gemini и NL удалены по просьбе владельца.** Публичные `/france` и `/gemini`
отключены в генераторе nginx, записи удалены из подписки. Внутренние инбаунды и правила
оставлены, чтобы не менять маршрутизацию основного узла. Не возвращать публичные пути без запроса.

**Имена узлов — контракт, диктует владелец.** У всех: `🇪🇪 Эстония (основной)` (VLESS WS
`/general`) и `🇪🇪 Эстония (запасной)` (hysteria2 UDP/8443; сам в интернет не ходит — отдаёт
трафик в loopback-SOCKS `udp-in` через `vpn-socks-relay`, то есть едет по тем же сценариям).
У владельца дополнительные ручные Gemini/NL-узлы удалены по его просьбе.

**В имени узла — только флаг, иначе в списке «две планеты».** Клиенты (Happ/Hiddify-класс)
делают аватарку строки из эмодзи, только если это **флаг**: любой другой эмодзи остаётся
в тексте названия, а рядом рисуется серая заглушка-глобус. `🌍 Gemini (UI VPN)` давал
ровно это — серый контурный глобус в квадратике плюс цветной 🌍 в строке. Выбор: флаг страны выхода
(`🇸🇬` — но он врёт, как только релей переехал) или **без эмодзи** (`Gemini (UI VPN)`). После
переименования путь не меняется, владельцу достаточно обновить подписку.

**Подписка называется UI VPN** — именно так, а не «левая» и не «провайдерская»: из неё приходят
релеи `fr`, `fi`, `p15`, `p17`.

**Релей `fr` на 19.11.2026 выходит в Сингапур** — Google на нём отдаёт `com.sg`/`SGP`, а не
`fr`. Рабочий выход, но не называть его французским; проверять страну, а не название.

**Trojan не несёт UDP — QUIC надо отбивать правилом.** `{"network": "udp", "port": 443,
"outboundTag": "blocked"}` ставится **до** доменных правил. Иначе HTTP/3 умирает на выходе молча:
страница грузится по TCP, а POST-запрос приложения уходит в никуда, и пользователь видит общий «ошибка 1»
без адреса. Диагноз — по логу клиента (`journalctl -u mihomo -n 25`): строки `[UDP] … --> *.google.com:443`
означают QUIC. Транспорт самого UDP-узла (hysteria2 на UDP/8443) это правило не задевает.

**Sniffing обязателен на каждом инбаунде, включая `udp-in`.** Без него домены не парсятся, ни одно
правило не совпадает и всё падает в catch-all: на UDP-узле Gemini не мог работать в принципе, а
выглядело как «сервер не пускает». Симптом в логах — соединения по `tcp:<ip>:443` без домена.

**Прежде чем менять маршрут — прочитать, каким он был, когда работало.**
`git -C /root/vpn-service log --oneline -- router/scenario_routes.py`, `git show <sha>^:router/scenario_routes.py`
и снимки в `/root/vpn-router/backups/`. Память подводит: «утренняя рабочая» схема в одном разборе гнала
через релей **весь** Google, а не только Gemini, и первый откат «к рабочему» сделал хуже. Один
эксперимент с маршрутом на гипотезу, со снимком, и возврат до следующего — каждый флип стоит владельцу
ручной проверки.

Server-side scenarios (Google→FR/FI, RU→Moscow or an owned RU box; YouTube deliberately rides the
Estonian exit) plus a subscription that exposes **one** node, and the jittered watchdog that falls
a dead scenario group back to Estonia: `references/scenario-routes.md`. Do not offer a user a
second node to tap **from a provider subscription** — that is provider traffic and ban risk, not a
feature. A second node that is our own transport (the UDP/hysteria2 fallback) or the legacy WS entry
is **not** shipped by default either: it appears only for token dirs carrying a `compat` marker, and
the default bundle carries exactly one node. Reason: a client that selects a throttled UDP node
concludes the whole VPN is dead and reports «не работает», while the server is fine — one node removes
that class of report entirely.

Two rules apply to every scenario edit: a balancer tag must also be listed in
`observatory.subjectSelector` (otherwise `leastPing` has no data for it and the matching requests
hang while every config check passes), and health checks must accept `2xx`/`3xx` through a URL
that answers *from that node's country* — a RU exit probed with `gstatic` reads permanently dead.
Full symptom list and fixes: `references/scenario-routes.md`.

When the RU scenario must stop depending on reseller relays, a small owned Russian VPS with a
VLESS+Reality inbound wired in as outbound `ru1` is the shape: provisioning, firewall allowlist,
IP-reputation acceptance test and rollback in `references/owned-ru-exit.md`; what to check on the
box before wiring it, and the exit-node pitfalls — `references/ru-exit-node.md`.

**`ru1` жив с 21.11.2026:** `217.197.114.197` (e-Style, Москва), VLESS+Reality, `dest` и
`serverName` — наш собственный `vpn.esmien.ru` (своё имя и серт вместо маски под
`www.microsoft.com`, которую владелец запретил как палево). 443 на хосте открыт только с
`141.98.166.213`; второй инбаунд `direct-client` на 8443 (публичный прокси с нашим UUID, без
логов и счётчиков) удалён — не возвращать. Путь проверяется без клиента: временный
`xray run -c` на хосте с socks-инбаундом и единственным outbound `ru1`, затем
`curl --socks5-hostname … https://ipinfo.io/ip` должен вернуть адрес этого хоста.

**Правка маршрута в `config.json` живёт меньше минуты.** `vpn-scenarios.timer` раз в 60 с
переписывает балансировщики из `scenario_override.json`, и он перекрывает `scenario_routes.py`.
Менять надо override (и `scenario_routes.py` — для чистого деплоя), затем
`systemctl start vpn-scenarios.service` и `vpn-cfg apply`; иначе `bal-ru` молча вернётся к
`['p15','p17']`, а `apply` отрапортует успех. Что узел реально несёт трафик, видно по счётчикам:
`docker exec vpn-router xray api statsquery --server=127.0.0.1:10185 -pattern "outbound>>>ru1"`.

**«Недоступный» узел может быть просто лежащей машиной.** `ru1` сняли 08.11.2026 коммитом «drop the
dead ru1 exit», а хост при проверке 21.11 оказался живым с uptime 11 дней — в день снятия он,
видимо, лежал. Перед выводом «умер» смотреть `ssh … uptime` и `systemctl is-active xray`, а не
только результат проб.

**`ru1` already exists — do not provision it again.** `217.197.114.197` = `esmien-vds`, e-Style ISP
Moscow (`ESTT-197114`), root over `/root/.ssh/id_ed25519_ru`, xray active on 443, UUIDs on both
sides identical (compare hashes, never print the id). It was pulled from the rotation on 08.11.2026
(`62198ff`, «drop the dead ru1 exit») as unreachable — but the box was simply down then and came back
~11.11, so «мёртвый» was a verdict on a single measurement. Before re-wiring, measure `uptime` and
TCP/443 instead of trusting the old conclusion. Its old config masked under `www.microsoft.com`,
which the owner has since banned; for a server→server leg carrying only RU traffic use our own
subdomain, own cert and an honest stub. Value of `ru1` is independence from `p15`/`p17` (Moscow /
Novosibirsk reseller relays), not stealth: the RU zone already exits from Russian addresses today,
so RU services never see our VPS — and `ru1` does nothing about the client→foreign-entry leg.

## Subscription

Main WS nodes in meta subscriptions use port 443 and `brand.json` paths.public_general; `apply_brand.py` maps the exact external path to Xray's internal /general on the active blue/green port. Legacy /general stays on 443 **and** 8443 and must stay: on 20.11.2026 four real clients were still tunnelling through it (≈1.1 GB that morning on 8443), so retiring it silently cuts people off. `/ws`, `/fi` and `/p1…/p23` were retired the same day (404 on 443/8443/2087; `/fi` and `/pN` had answered 502 for weeks because those inbounds no longer exist) via `RETIRED_PUBLIC` in `apply_brand.py`, with `brand.json` losing the dead paths. Owner manual /france and /gemini routes are retired. Delivery and UDP remain on 8443. Check the active colour and generated nginx vhost on every flip, and test owner path end-to-end. Do not test other users' credentials when the owner limits testing to his subscription.

`make_sub.py` renders three formats and nginx picks one by User-Agent (`00-esmien-sub-map.conf`): Clash/Mihomo → `clash.yaml`, sing-box → `singbox.json`, everything else → base64 `list.txt`. URL shape: `https://<host>:8443/sub/<token>` — preserve the configured subscription port; an independently working VPN tunnel on 443 does not establish that subscription delivery is configured there. The layout comes from the `kind` file in the token dir (`meta` = one node, `whitelist` = provider list, `full` = legacy 25-node list). **Только TLS:** подписка по `http://<IP>/sub/<token>` на :80 снята и заводить её заново нельзя — открытый текст отдаёт токен и весь список узлов любому на пути, а точечный блок 80-го убивает этот путь вслепую. Любой новый эндпоинт подписки/лендинга — только https на 8443.

Full text → [references/subscription-shapes.md](references/subscription-shapes.md)

## Вход на 443 по SNI — рабочий (Vision снят)

**Порт 443 на `edge` пускает в VLESS обычным TLS, без Vision.** Схема в три шага, вся живёт
в `apply_brand.py` (руками файлы не править — генератор перезапишет):

1. `nginx stream` (`/etc/nginx/stream.d/443-map.conf`) выбирает по адресу назначения и SNI:
   `edge` + `vpn.esmien.ru` → `127.0.0.1:18443`; `brand` → обработчик сайтов, другие имена
   на edge и имена на gemini отклоняются. Карта общая для 443 и 4443. Wildcard-сокет при этом
   остаётся слушать на gemini: отказ в stream — не закрытый TCP-порт.
2. `/etc/nginx/conf.d/vpn-443-in.conf` — `listen 127.0.0.1:18443 ssl proxy_protocol`:
   принимает PROXY-заголовок, терминирует TLS нашим wildcard и проксирует `/general`
   (`in-general`) плюс публичный alias подписки в порт активного цвета. Корень `/` редиректит
   на страницу входа-прикрытие (`/ui/`), всё прочее — `404`.
3. Клиенту достаточно того же узла с портом `443`: путь, SNI, UUID и серт не меняются.

**`/ws` снят с публичных входов 20.11.2026** (443, 8443, 2087 отдают `404`); инбаунд `ws-in`
и `/ws` в `brand.json` остались только как адресная книга loopback. Не возвращать локацию без
запроса: клиентов на этом пути не было, были только свои пробы.

Три ловушки, каждая съедает заход:

- **TLS внутри xray не поднимется: в контейнере нет `/etc/letsencrypt`.** Инбаунд с
  `security: tls` и путём хоста падает `failed to parse certificate … no such file`, а лечить это
  копированием серта в анонимные volume обоих цветов — лишняя работа, которая теряется при
  пересоздании контейнеров. Терминировать TLS в nginx (наш случай) или монтировать серт явно.
- **`proxy_protocol on` есть у всего stream-сервера, поэтому просто вернуть соединение в
  `edge:8443` нельзя** — тот vhost PROXY-строку не ждёт и отвечает `tls: first record does not
  look like a TLS handshake`. Принимающая сторона обязана объявить `ssl proxy_protocol`.
- **Генератор пишет карту и vhost'ы заново на каждом apply.** Строка SNI и файл vhost живут
  только в `apply_brand.py`; правка в `/etc/nginx` умирает на следующем `vpn-cfg apply`.
- **Проверяй и неизвестный, и отсутствующий SNI до и после ужесточения TLS:** на VPN-портах default vhost с `ssl_reject_handshake on` не выдаёт сертификат чужому имени. Сначала проверь корректный SNI в опубликованных профилях и владельческий туннель; старые импортированные профили всё равно могут отличаться. Сохраняй default vhost в генераторе и recovery-репозитории, а не только в `/etc/nginx`.

**Диагноз «443 не работает» начинается с лога, не с вывода о блокировке.** `stream-443.log`
даёт по IP клиента `sni=`, `bytes_in/out` и время; `vpn-443.log` — сам запрос (`GET /general`).
Запрос дошёл, TLS прошёл, а в vhost'е `404` ⇒ дело в пути/конфиге клиента; ни одной строки с его
IP ⇒ он вообще не ходил на этот вход (старый профиль) или его сеть режет порт — тогда проверять
браузером `https://<host>/` на нейтральную HTML-заглушку; проверка с самого сервера не доказывает доступность из сети клиента.

Ниже — исторический слой Vision и то, что осталось в файлах; новые входы по этой схеме не
возвращать без замера.

Почему Vision снят: у владельца после рукопожатия туннель не принимался (сервер отдавал TLS и молчал:
`in≈4KB out≈10KB`, 0.3 s, в `access.log` ноль строк `vision-in`) — та же заморозка, что у камо, только
на своём домене. Плюс отдельная ловушка: клиент **без `flow` на Vision-инбаунде не аутентифицируется
вовсе** (проверено: `с flow` → 200, `без flow` → `000`), а часть клиентов поле `flow` из ссылки
выбрасывает. Симптом «узел подключается и молчит» неотличим от блокировки.

Проверяй фактическую сгенерированную карту после изменений и при каждом flip: исторические сообщения генератора о REALITY не доказывают, что такой маршрут действительно существует.

**Фронт остался у nginx.** Xray не забирает 443: `stream`+`ssl_preread` просто маршрутизирует
по SNI, поэтому живой `stream-443.log` (реальный IP + SNI) сохраняется, а откат — это правка
двух файлов. Карта вынесена в `/etc/nginx/stream.d/443-map.conf`, `nginx.conf` подключает её
`include` внутри `stream {}`:

```
default -> 127.0.0.1:9443    # все vhost'ы, proxy_protocol; unknown SNI -> reject
```

Одна карта обслуживает **два** stream-сервера — `listen 443` и `listen 4443`: TCP/443 у части
операторов режется молча, и такому клиенту выдаётся вход на 4443.

- **Один вход на IP, и он не врёт про домен.** Два входа на одном адресе, из которых один
  заявляет чужой SNI, хуже одного честного: несовпадение SNI↔IP — готовая подпись подмены, она
  маркирует адрес, а блок по IP:порт убивает заодно чистый вход. Поэтому камо-REALITY с этого IP
  снят: `reality-in` удалён из `config.json`, камo-SNI из карты, узел из подписки. Маскарад под
  чужой домен возвращать **только на отдельном IP**; свой домен + свой серт + фолбэк-страница
  дают тот же эффект без подписи. **Решение владельца (20.11.2026): маска под чужой сайт — «лютое
  палево», не предлагать её как средство скрытности вообще** (ни REALITY, ни camel-SNI). Скрытность
  строим на своём имени, своём серте и честной заглушке; в отчётах о детектируемости REALITY не
  всплывает как «радикальный вариант», даже с оговорками.
- **У Vision своё имя, а не то, на котором висят vhost'ы.** `vpn.esmien.ru` на 443 обязан уходить
  в `default` — иначе отваливается legacy WS `/general`, которым ходят консольные клиенты.
  Поэтому SNI для Vision — отдельный поддомен (`edge.esmien.ru`, A-запись на наш IP через CF API).
  После любой правки карты проверять оба: `curl -o /dev/null -w '%{http_code}' --resolve
  vpn.esmien.ru:8443:<ip> https://vpn.esmien.ru:8443/ws` (и `/general`) → `400`, плюс Vision
  сквозным клиентом через `edge.esmien.ru:4443`.
- **TLS внутри Xray требует серта в контейнере.** Серты копируются в data-volume каждого цвета
  (`/usr/local/etc/xray/vision.crt|key`) хуком `certbot renew`; `validate()` в `vpn-bluegreen.py`
  обязан монтировать этот volume, иначе `xray -test` падает `no such file` и apply не переключает
  трафик. Проба здоровья: `security=tls` без `wsSettings` = TCP-connect, иначе HTTP-код 400.
- **На одном IP — один вход, и SNI должен совпадать с ним.** Чужой SNI (камо REALITY, mtg-подмена
  `www.cloudflare.com`) маркирует *адрес*, а не отдельный поток: заморозка бьёт по IP:порту и
  убивает заодно чистый вход. Итог на этой VPS: единственный маршрут в карте —
  `edge.esmien.ru → vision-in` (443 и 4443), всё остальное — vhost'ы или reject. mtg
  (MTProto-прокси) удалён: контейнеры `mtproto-faketls*` остановлены с `restart=no`, мост
  `127.0.0.1:10445 → 10443` убран из nginx stream. Его UUID переехал в
  `/root/.secrets/ws-client-uuid` (его читают `mkcli.py` и `make_sub.py`).
- **`:443` — не святое.** У части операторов TCP/443 к конкретному IP режется молча: клиент
  показывает `timeout`, а в `stream-443.log` трафик падает с 157 к 11 коннектов за 10 мин. Диагноз
  ставится сравнением: тот же хост на 8443 отвечает (303 ms) → это не сервер. Проверять
  доступность снаружи — `check-host.net/check-tcp?host=<ip>:<port>` (JSON: `request_id`, потом
  `/check-result/<id>`, есть узлы `ru1`/`ru3`); если из РФ открыто, а у клиента нет — виноват его
  оператор, но вход надо перевозить туда, где клиенты. nginx stream держит одну и ту же SNI-карту
  на **443 и 4443**; REALITY-узел в подписке смотрит на 4443, hysteria слушает UDP/8443.
  `v2rayNG` показывает `timeout` у hysteria-узла всегда — он не умеет пинговать QUIC, это не
  диагностика.
- **Как это выглядело с камо (если его когда-нибудь вернут — только на отдельном IP).** Симптом
  заморозки: узел один раз поднимается (`access.log`: одна строка `reality-in -> fr`), через минуту
  все новые коннекты приходят с `bytes_in=0` и висят 30 с. REALITY платит RTT до `dest` на каждом
  рукопожатии, за `mts.ru` сидит WAF и рвёт relayed-хендшейк (`REALITY: processed invalid
  connection … handshake did not complete successfully`; в `stream-443.log` при этом `sni=` и
  `in≈4KB out≈9.5KB`, в `access.log` ноль строк `reality-in`), `www.microsoft.com` даёт 0.7 s на
  рукопожатие, а клиентский `fp=ios` не проходит аутентификацию (0/3 против 3/3 у `chrome` и
  `safari`). Отбирать только харнессом `scripts/reality-camo-probe.py <кандидаты> --fp
  chrome,safari,ios` (временный сервер на каждого кандидата, живой вход не трогает); годится 5/5,
  4/5 — брак.
- **«Я обновил подписку» ≠ профиль обновился.** iOS-клиенты мержат узлы, а не перезаписывают их:
  после смены камо клиент продолжал стучаться со старым `sni=`, а в его списке новый узел висел с
  `latency n/a`. Проверять надо не дату в приложении и не слова, а `stream-443.log` его IP: с каким
  SNI стучится и сколько байт приходит; совпадение с камо - единственное доказательство, что клиент
  доехал до нового узла.
- **Vision-фолбэк обязателен.** TLS-сервер, который завершает рукопожатие и молчит, — сам по себе
  отпечаток. `vision-in` отдаёт всё, что не VLESS, в локальный nginx-стаб:
  `"fallbacks": [{"dest": "127.0.0.1:8091"}]` + `root /var/www/vpn-stub`, и браузер на
  `vpn.esmien.ru:443` получает валидный серт и обычную 200-страницу.
- **Порт для фолбэка выбирать по `ss -tlnp`, а не по памяти.** `127.0.0.1:8081` был занят SearXNG:
  фолбэк отдавал `200`, но это была чужая страница, и проверка «код 200» ничего не заметила.
  Сверять тело/размер ответа (`size=181` у заглушки), а не только статус.

- **Карту перегенерирует `apply_brand.py` (`write_stream_map`) при каждом flip.** Если этого не
  делать, после blue/green-переключения карта указывает на мёртвый цвет: WS работает, Vision висит —
  самый коварный симптом.
- **Инбаунд `vision-in`**: `127.0.0.1:10055` (+1000 для цвета b), `security=tls`, серт из
  `/usr/local/etc/xray/vision.{crt,key}`, клиенты клонированы из `ws-in` с `flow=xtls-rprx-vision`,
  `sockopt.acceptProxyProtocol: true` (nginx отдаёт PROXY-префикс), `fallbacks` → локальный стаб.
  `xray x25519`-ключи REALITY остались в `/root/.secrets/reality.key`, но входом не используются.
- **Удалённый узел обязан исчезнуть из всех генераторов.** `build_meta` собирал список
  `[r_link, v_link, ws_link]` и падал `TypeError: expected str instance, NoneType found` на первом же
  `None`: собирать пары `(link, name)` и фильтровать пустые, а не полагаться на порядок `if`-веток;
  то же для clash `proxies` и sing-box `outbounds`. `make_sub.py` запускать без `>/dev/null` и смотреть
  exit-код — при падении он оставляет старые файлы, и подписка выглядит «нетронутой».
- **`probe_direct` в `vpn-bluegreen.py` должен пропускать reality-инбаунды**: HTTP-GET там получает
  закрытие соединения, и apply навсегда остаётся с «N-1 из N отвечают». Для reality health = TCP connect.
  - **Пересборка доп. узлов не должна сносить чужие узлы.** `hy2_users.py` писал в `extra_nodes.json`
  ровно один узел и при каждом `--apply` стирал всё остальное — а там живут ручные узлы владельца
  (FR/NL для Gemini). Теперь скрипт сохраняет записи, чей `link` не начинается с `hysteria2://`.
  Любой новый генератор доп. узлов пишет по тому же правилу: прочитать список, заменить только своё.
  - **Маскировка по имени ключа не спасает в `extra_nodes.json`.** Там лежит `clash` — текстовый YAML
  блок, внутри которого `password:` и `obfs-password:`. Фильтр «скрыть ключи `password|id|token`»
  его пропускает и печатает пароли в чат. Печатать только `name`, схему ссылки и длины значений.
  - **`sendThrough` в `settings` аутбаунда игнорируется молча** — см. раздел про Gemini-гейт; проверять
  egress, а не конфиг.
  - **Свежий адрес в той же ASN приходит с чужой страной.** Новый /24 (US-регистрация, `IPbnb LLC`)
  Google и ip-api читают как `nl` (наследие Sentia на 85.92.0.0/16), ipinfo — как Keller, Texas,
  а `2ip`, `ipwho.is` и `ip.guide` — как **Эстония, Таллин** (добивают по ASN и соседям).
  Гео принадлежит блоку и вендору, единого источника нет: тот же сервер отдаёт `ru` с одного адреса
  и `nl` с другого. Не выводить страну из «сервер в Эстонии» — мерить `this.gbar_` с привязкой
  к конкретному IP. На вопрос «почему 2ip показывает Эстонию» отвечать механизмом (гео — чужая база,
  блок исторический, владелец новый) и одной строкой: для гейта важен только вердикт Google, а он `nl`.
  Чинить гео нечем — geofeed публикует владелец блока, не мы.
- **`xray -test` на хосте падает на `geoip:private` (`geoip.dat` лежит внутри контейнера)** — это не
  ошибка конфига; валидацию делает `vpn-cfg apply` внутри контейнера.
- **Логи:** пути в `config.json` ведут внутрь контейнера, `/var/log/xray` — docker-volume. Симлинк
  `/var/log/xray -> /var/lib/docker/volumes/<id>/_data` даёт хвост и logrotate на хосте (14 дней,
  `copytruncate`). **Симлинк долго смотрел в volume цвета `a`, а трафик нёс `b`:** `access.log` молчал
  сколько угодно долго, и вывод «клиент ничего не присылал» был ложью — у него в это время 700 живых
  запросов, а я успел на этом основании нагородить неверную диагностику. Теперь `_repoint_logs()` в
  `vpn-bluegreen.py` перевешивает симлинк после каждого flip. Для старых логов путь брать через
  `docker inspect vpn-router$([ $(cat /root/vpn-router/vpn-color) = b ] && echo -b) --format '{{range .Mounts}}{{if eq .Destination "/var/log/xray"}}{{.Source}}{{end}}{{end}}'`.
- **Один мёртвый вход ≠ блок адреса.** Прежде чем объявить «режут IP целиком», сверить с входами из
  того же окна времени: если WS на 8443 и hysteria несут трафик — адрес жив, душат конкретный класс
  транспорта (голый TLS с Vision), и лечится это выбором другого входа, а не переездом. Обобщение
  «раз три входа подряд умерли, значит адрес» уже стоило неверного вывода при живых WS и UDP.
- **Релей, живой по пингу, может рвать поток.** `fr` отвечал 53 ms и одновременно сыпал
  `grpc/encoding: failed to fetch hunk … RST_STREAM PROTOCOL_ERROR`; всё, что на него маршрутизировано,
  умирало пачками. Судить выход только пачкой реальных HTTPS через него (6–10 запросов, нужно 6/6), а
  не пробой `generate_204` и не ICMP.
- **Подписка несёт два узла, и оба — всем токенам** (решение владельца: разные эшелоны, каждый
  страхует другой): `совместимость` (WS 8443) и `UDP резерв` (hysteria2 8443/udp). Vision-узел снят
  18.11.2026 («вообще убирай»), REALITY — раньше; обратно не добавлять без просьбы. Гейтинг маркерами
  `compat`/`udp` тоже снят.
  «Клиент говорит, что VPN мёртв, а сервер жив» — читать `stream-443.log` по его IP: нет ни одного
  входа с нужным SNI ⇒ клиент к этому узлу не ходил вообще (устаревший профиль), а пустой `sni=` с
  `bytes_in=0` и `time=30.000` — это открытый сокет без ClientHello, тоже клиент.
  Порядок разбора — `references/client-drop-triage.md` → 4g.
- **Консольные конфиги под рукой:** `/root/vpn-router/cli/vision-10860.json` (SOCKS 10860, Vision) и
  `ws-10861.json` (SOCKS 10861, WS `/general`) — заново не генерировать, клиент забирает `scp`-ом.
  UUID в них — `ws-client-uuid`, и он обязан совпадать с инбаундом, к которому ведёт путь:
  `/ws` → `ws-in`, `/general` → `in-general`; чужой UUID даёт `000` на живом входе и выглядит как
  «WS сломался».
- **Откат:** `scripts/rollback-443-reality.sh` (снимок `pre-reality-*`: config, apply_brand,
  vpn-bluegreen, nginx.conf; отдельный снимок подписок; затем `apply` + `reload` + проверка).
  Проверка входов после любой правки фронта — `scripts/verify-443.sh`.
- **Голый IP не должен отвечать нами (18.11.2026).** Без явного `default_server` nginx отдавал
  любой неизвестный SNI первому vhost'у: снаружи это был серт `*.esmien.ru` и логин Open WebUI.
  Лечится `99-default-ssl-reject.conf`: `listen 127.0.0.1:9443 proxy_protocol ssl http2
  default_server; ssl_reject_handshake on;`. **Ловушка:** если в `listen` не повторить
  `proxy_protocol ssl http2` в точности как у остальных vhost'ов, nginx открывает второй,
  недостижимый сокет — конфиг валиден, а default не срабатывает и unknown SNI снова отдаёт 200.
  Симптом — `verify-443.sh` кажет `unknown SNI -> 200`. Плюс `server_tokens off` (в `http {}`).
- **Лишний узел в списке — это класс жалоб «ничего не работает».** Клиент выбирает нерабочий узел
  (замороженный UDP, устаревший WS, старый SNI) и делает вывод про весь VPN, хотя сервер жив.
  Поэтому у каждого узла в названии видно, что это запасной вход, а жалобу проверяют по
  `stream-443.log`/`access.log` его IP, а не по словам «обновил подписку».
- **Клиенты:** REALITY умеют v2rayNG, Hiddify, Streisand, Shadowrocket, NekoBox, mihomo/sing-box;
  старые Clash — нет. Подписка не переезжает: тот же `https://<host>:8443/sub/<token>`, тот же токен,
  те же UUID — клиент подтягивает сам (`profile-update-interval 12`).

Как это мерить снаружи и что реально скрытнее (Vision против WS+TLS, маска Apple, DDNS, панель) —
`ip-reputation-and-ban-risk` → `references/vpn-entry-stealth.md`.

## Deep dives (references)

- **Change the public host** — nginx, cert, `brand.json`, subscriptions and `vpn-cfg` host copy in one pass → `references/changing-public-host.md`
- **Per-user keys** — every person gets their own UUID and sub URL, so revocation touches nobody else → `references/per-user-keys.md`
- **Landing page per user (`/u/`)** — the page each user opens for their links → `references/landing-pages.md`
- **Usage stats** — per-user counters from the xray `StatsService`, «кто реально пользуется» → `references/usage-stats.md`
- **Blue/green** — applying a config change with no downtime → `references/blue-green.md`
- **Subscription expiry** — read it from the provider's `subscription-userinfo` header, not the panel; daily 07:00 UTC timer warns at 3/2/1 days → `references/subscription-expiry.md`
- **Upstream subscriptions** — relaying third-party nodes as exits → `references/upstream-subscriptions.md`
- **RU split** — banks / gosuslugi / VK / OZON / WB direct or via the RU exit → `references/ru-split.md`
- **Gemini / geo** — плашка о неподдерживаемой стране не доказывает ни проблему аккаунта, ни причину в IP: отдельно проверяй путь конкретного клиента и выходы. HTTP 200, текст сырого HTML и неавторизованный браузер не доказывают работу авторизованного Gemini. Маркер `this.gbar_` в теле — полезная эвристика, но не доказательство работы промптов. Проверка всех локально сохранённых узлов: `python3 /root/vpn-router/probe_gemini_pool.py --snapshot <снимок Xray>`; сверять полноту с актуальной подпиской, старый снимок может устареть. **`fallbackTag: blocked` на пользовательском сценарии — запрещён.** Проверено: пока селектор смотрел
на мёртвый узел, observatory выключал балансер и всё уходило в `blocked` — 16 строк
`gemini.google.com:443 [in-general -> blocked]` за минуту, то есть чёрная дыра вместо ошибки, а
клиент видит «ошибка при отправке» и винит аккаунт. Фолбэк сценария — всегда реальный выход (`fi`,
`direct`); «падать громко» даёт сам клиент, а не молчание. Пользователь требует не направлять весь
Google через релей; общие домены невозможно отделить по приложению только по имени.
- **Whitelist mode** — the LTE whitelist list goes to the client as links, never through this server → `references/whitelist-mode.md`
- **Borrowed exit** — a third-party subscription used as an exit → `references/borrowed-exit.md`
- **Routing watchdog** — a timer rewrites routing every minute; edits must survive it → `references/routing-watchdog.md`
- **«Нас не съели ли VPN-клиенты?»** — three measurements instead of guesses → `references/client-share-measurements.md`
- **Gemini / NL-гейт** — адреса, точный набор доменов, порядок правил, сторож и быстрые проверки → `references/gemini-gate.md`
- **Блокировка РКН** — пять ручек РКН (IP/SNI/диапазон/whitelist/**заморозка по пакетам**), замеры по 435 точкам и какие сети заморожены, триаж, переезд на новый IP, цена домена и общий IP с AI-стеком, проверка ASN/префиксов и спам-листов, почему CF перед VPN не защита, что даёт REALITY и почему сейчас не Hetzner/OVH → `references/blocking-risk.md`
- **Домен и доставка** — почему подписки надо вынести на отдельный регистрируемый домен, выбор зоны и регистратора, канал восстановления (бот + CF Pages + deep links), Cloudflare Tunnel для WebUI → `references/delivery-channel.md`
- **Второй публичный IP** — `/32` отдельным netplan-файлом, проверка снаружи, привязка egress к адресу (`sendThrough`) → `references/second-public-ip.md`
- **Адреса и роли** — brand / edge / gate, переезд входа, один серт на пул, вторая машина как edge → `references/address-roles.md`
- **Pitfalls** — the full list of expensive mistakes → `references/pitfalls.md`

## Certificates

Full text → [references/certificates.md](references/certificates.md)

## Client devices — always-on Linux desktop

The GNOME «Добавить VPN» dialog offers only OpenVPN / PPTP / WireGuard; our entry is VLESS over WS+TLS, so none of them apply and there is nothing to tick there. Do not answer that by adding a WireGuard/OpenVPN inbound to the server either — a new public surface with its own auth and none of the routing rules.

When the owner says he does not want to keep a client window open, the shape is a **daemon in TUN mode**, not a GUI app (Hiddify/v2rayA need the window; a local proxy on `127.0.0.1` only reaches apps that honour a system proxy). mihomo over the `clash.yaml` subscription is the cheapest base: that profile is already a complete config, so only a `tun:` block plus `dns.listen` get injected and can be re-injected on every refresh. Full recipe, systemd units, verification and pitfalls: `references/linux-always-on-client.md`; the GUI-free desktop variant (merge script, unit files, FlClash/`add route 0: file exists` trap) — `references/desktop-mihomo-tun.md`.

## UDP backup entry — Hysteria2 (UDP/8443)

TSPU freeze counts **packets in one TCP connection** (~25 packets / ~16 KB, ~8 on mobile) and hangs it in both directions; the connection does not reset, the app just waits. UDP is untouched by that rule, so a UDP transport is the only thing that survives once a network is frozen. Measured 10.11.2026 over 435 endpoints / 154 hosters: 87% pass from RU, the rest freeze — and the freeze is per **network/AS**, whole companies at once (OVH, Hetzner incl. US/SG, DigitalOcean, Vultr, BuyVM, Scaleway, Gcore-type nets frozen; HostHatch, FlokiNET, Psychz, Time4VPS, Serverius pass). Check the ASN before recommending any hoster, and never promise UDP as immunity: blocking all UDP is a one-line rule, they just have not paid the collateral cost yet.

Live shape: `hysteria-server.service` → `/usr/local/bin/hysteria server -c /etc/hysteria/config.yaml`, listen `:8443` **UDP** (было `:443` — у части операторов этот порт к нашему IP режется так же, как TCP), wildcard cert, `obfs: salamander`, masquerade proxied to the loopback decoy website (`http://127.0.0.1:8091` — the same login page a browser sees on 443), so a probe without the obfs password lands on a normal site instead of an empty response or a socks proxy. Secrets in `/root/.secrets/hysteria-owner.txt` (0600); repo carries `hysteria/config.example.yaml`, both units and `scripts/install-hysteria.sh` — a rebuild is `bash scripts/install-hysteria.sh` and it keeps existing secrets.

**Hysteria must not dial the internet itself.** A bare UDP entry puts every user in Estonia: Gemini refuses and Gosuslugi 403s, which reads as «UDP не работает». The fix is one hop: Xray gets a loopback SOCKS inbound (`tag: udp-in`, port 10089, `udp: true`) and hysteria's only outbound is `type: socks5 → 127.0.0.1:10809`. That 10809 is `vpn-socks-relay.py`, which re-reads `/root/vpn-router/vpn-color` on every connection and dials 10089/11089 — because `derive_b` shifts *every* inbound port by +1000, so a static socks port breaks silently on the next blue/green flip. With the relay, server-side routing is shared: Google → FR, `.ru` → Moscow, rest → EE. Verify by resetting xray outbound counters, pulling Gosuslugi and `generate_204` through the hysteria client, and reading `p15`/`fr` deltas — not by trusting the config.

Pitfalls that cost a restart loop each: v2.14 replaced ACL with expressions (`acl.rules: [{outbound: name, match: expr}]`) — `proxy(name)` legacy syntax dies with «outbound proxy not found»; and with no ACL at all the **first outbound in the list** takes everything, so a single `xray` outbound needs no rule. `vpn-bluegreen.py`'s linter demands `settings.clients` on every non-dokodemo inbound, so a noauth loopback socks inbound is rejected until `socks` joins that exemption.

**Узел «только мне» — это `extra_nodes.json` в каталоге его токена, а не общая подписка.**
Запись = `{name, link, clash}`: `link` — строка основного узла с заменённым портом, `clash` —
полный YAML-блок прокси. Собирать `clash` **литеральным шаблоном** (name/port/uuid/ws-opts),
а не вырезанием строк из `clash.yaml`: при вырезании легко оставить старое `name`, и в проксиях
оказываются две ноды с одним именем и разными портами, а в списке групп — одна. `list.txt`
хранится в base64 (Clash-клиенту отдаётся `clash.yaml`), поэтому перед правкой декодировать.
Проверка: у его токена узлов на один больше, у чужого — столько же, сколько было.

Per-token roll-out, never global: `python3 /root/vpn-router/hy2_users.py --apply` does the whole thing — `/root/.secrets/hysteria-users.json` is the source of truth (one password per person, `auth.type: userpass`, usernames transliterated), it rewrites every `meta` token's `extra_nodes.json`, rebuilds subs and restarts hysteria.

**Never print the auth block when checking it.** `grep -A12 ^auth:` dumps every password into the transcript — read the state file in Python and print usernames only. **Маскировать по имени ключа, а не по слову `password`:** блок устроен как `auth: → userpass: → <имя>: "<пароль>"`, поэтому регулярка вида `password\s*:` его не ловит и «структура без секретов» печатает пароли всех пользователей. Печатать только имена ключей, длины значений или `True`/`False`. **То же в `extra_nodes.json`:** узел хранится тремя ключами, и пароль живёт внутри YAML-блока под ключом `clash` (`password:`, `obfs-password:`), поэтому обход «печатать структуру по ключам и маскировать по имени» его не ловит и выдаёт пароль в чат. Этот файл читать счётчиками (`len(data)`, имена узлов, `bool(link)`), а содержимое `clash` не печатать никогда; если засветился — перевыпуск (`hy2_users.py --apply` после удаления записи), это один рестарт и одно обновление подписки.

**After any auth change, the symptom is a dead node, not a broken server.** Single password → per-user `userpass`, or a rotation, leaves every already-imported node holding a stale credential; the app reports timeout, the server is fine. Say «обнови подписку» before touching anything, and prove it with `journalctl -u hysteria-server` (`client connected {id: ...}`) plus xray's `inbound>>>udp-in>>>traffic` counters — a growing counter means the tunnel carries traffic. Triage order for this entry, including the tcpdump recipe and what a local loopback test does *not* prove: `references/client-drop-triage.md` §4e.

**Тестовый клиент собирать из самой ссылки подписки, а не руками.** `hysteria client` принимает
`server: hysteria2://user:pw@host:8443/?sni=…&obfs=salamander&obfs-password=…` — ровно тот разбор,
что у телефона. Самодельный конфиг с отдельными `auth:`/`obfs:` из серверного файла даёт
`failed to initialize client … authentication error, HTTP status code: 301`, и это не «сервер
сломался»: 301 — это отказ авторизации, который сервер уводит в masquerade-прокси (а тот
редиректит). Читать такой 301 как «креды или obfs не совпали», сверять хеши значений, а не
строки, и переходить на конфиг из ссылки, как только он понадобился.

`build_meta` appends the extra to `list.txt` and to clash `proxies`, so every file outside `extra_nodes.json`/`list.txt`/`clash.yaml` stays byte-identical — verify with a `diff -rq` against a backup before claiming nothing broke. Link shape: `hysteria2://<user>:<pw>@<host>:8443/?sni=<host>&obfs=salamander&obfs-password=<obfs>#name`. v2rayNG cannot read hy2 and just will not import that node; Hiddify, NekoBox, sing-box and Clash Meta can. `singbox.json` is not extended by extras — a sing-box user gets the TCP node only. The clash group is `type: select` on purpose: do not turn it into url-test without saying so, a silent path change is what makes «connected, but Gemini says no» invisible.

## Адреса и роли: brand / edge / gate

Один хост — несколько адресов, и у каждого своя работа. Алиасы фиксированы, ими пользуемся в
чате, ранбуке и правилах:

- **brand** `141.98.166.213` — сайт, WebUI, бот, LLM-гейт, SSH из РФ. **Ни одного VPN-входа.**
- **edge** `85.92.158.238` — адрес из пула, единственная точка входа VPN (nginx + hysteria).
  Расходник. Адреса и роли в машинном виде — `/root/vpn-router/addresses.json`, для человека —
  `## 0. Адреса и алиасы` в ранбуке; держать их равными, чтобы панель, чат и конфиги называли одно и то же.
- **gemini / gate** `85.92.158.226` — исходящий NL для Gemini и ручного NL-узла; цель — без публичных входов. Проверяй фактические wildcard-сокеты и firewall: отклонение на уровне nginx не означает отсутствие TCP-listener.

**Ловушка, обнуляющая схему:** `listen 8443 ssl` и `listen: :8443` слушают *все* адреса
машины, то есть gate сегодня тоже принимает входы — и бан входа по адресу уносит Gemini.
Проверять `ss -lntu` и сужать бинды до `listen <edge>:8443` / `listen: <edge>:8443`.

**Сузить бинд мало — нужен рестарт, а не reload.** `systemctl reload nginx` при переходе от
`0.0.0.0:8443` к `listen <edge>:8443` не перебиндит сокет: в `error.log`
`bind() failed (98: Address already in use)` → `still could not bind()`, reload возвращает success,
старые воркеры продолжают принимать на всех адресах, а `nginx -T` уже показывает новый `listen` —
конфиг врёт о реальности. Лечится `systemctl restart nginx` (секунда разрыва), и вот после него
`ss -lntH | grep :8443` покажет только `<edge>:8443`. Доказательство сужения — не текст конфига,
а отказ на старом адресе: `curl --resolve vpn.esmien.ru:8443:<brand>` → `000`, на `<edge>` → `200`.

**Сужение биндов живёт до первого `vpn-cfg apply`, если не поправлен шаблон.** `vpn-8443.conf`
и `vpn-2087.conf` генерирует `apply_brand.py` — правка только в `/etc/nginx/conf.d`
молча откатится к `listen 8443 ssl` в следующий же apply или blue/green flip, и gate снова начнёт
принимать входы. В том же заходе править шаблон (`grep -n 'listen' /root/vpn-router/apply_brand.py`)
и копию в `vpn-service/router/`, а после любого `apply` перепроверять `ss -lntu`: на `<gate>` и
`<brand>` не должно быть ни одного VPN-порта.

**Пул в одном `/24` — резерв от точечного блока IP, не от блока подсети.** Даже при использовании адресов по одному блок всего префикса затрагивает их вместе. Не выводи из нескольких точечных блоков, что следующим обязательно будет блок подсети; почтовый листинг также не равен сетевой блокировке.

**Вход без выхода — половина изоляции.** Пока `direct` ходит в мир с brand, «brand чист»
означает только «не принимает входы»: бан сайта по адресу уносит и выход всех клиентов.
Выход привязывается одной строкой в аутбаунде — `"direct": {"protocol": "freedom",
"sendThrough": "<edge>"}`; `domainStrategy` при этом обязан жить в
`streamSettings.sockopt.domainStrategy`, иначе привязка молча не работает. Полный рецепт и две
ловушки — `references/address-roles.md` §«Выход обычного трафика на edge».

**Плоский процесс на хосте (`sendThrough` к нему не относится) привязывается policy-маршрутизацией
по uid.** Для сервиса, который ходит в мир сам, а не через xray: `ip route replace default via <gw>
dev ens3 src <чужой-ip> table 200` + `ip rule add uidrange <uid>-<uid> lookup 200 priority 1000`,
пережить ребут — oneshot-юнит с `After=network-online.target`. Проверять `runuser -u <user> --
curl -s https://ipinfo.io/ip` (должен быть чужой адрес) **и** что root/остальные по-прежнему выходят
с brand. `curl --interface` в пробе доказывает только пробу — приложению нужно правило. Для
Google-сервисов адрес выбирать по маркеру `this.gbar_`, а не по ipinfo или Cloudflare trace: базы
расходятся, тот же IP у Cloudflare `EE`, а Google читает его как `ru`.

**После любой смены биндов проходить по всем пробам.** Health-check, который стучится в
`127.0.0.1:8443`, после сужения на `listen <edge>:8443` видит мёртвый порт, и `vpn-cfg apply`
откатывает рабочий конфиг без единой ошибки — правка выглядит как «не применилась». Проба
берёт адрес из `addresses.json[edge].ip`.

Полный разбор (переезд входа, один серт на пул, имя без DNS, вторая машина как dumb edge с
туннелем и direct-фолбэком, чего схема не лечит) — [references/address-roles.md](references/address-roles.md).

## Домен как точка отказа — доставку отделить от туннеля

Владелец считает так: адрес — расходник (DNS TTL 300, пять минут), а имя хуже, потому что вшито в профили; SNI-блок `esmien.ru` убьёт и вход, и `/sub/`, и потребует ручной раздачи. Сейчас оба висят на `vpn.esmien.ru` — одна точка отказа. Что из этого следует: подписки живут на **отдельном регистрируемом домене** (не поддомене — правила матчатся по корню), туннельное имя становится расходником, а клиенты сами подтягивают новый узел за `profile-update-interval 12`. Reality тут — бонус (убирает имя из SNI), не основа: от TCP-заморозки и блока ASN он не спасает. Выбор зоны: `.com`/`.org` (Cloudflare Registrar — продление = регистрация, ~$10–11); `.us` отпадает (nexus: нужно присутствие в США), `.рф`/`.su` — та же юрисдикция, от которой страхуемся, промо-зоны (`.online`, `.shop`, `.tech`) дают вилку «−98% на год → втрое на продлении». **Юрисдикция регистратора важнее цены:** российский регистратор (nic.ru, Beget, Рег.ру) работает по требованиям РКН напрямую — страховка, выданная той же стороной, от которой страхуемся; Cloudflare и Porkbun клиентов из РФ принимают, оплата иностранной картой проходит, а часть западных (Namecheap, GoDaddy) после 2022 РФ не обслуживает — проверять у конкретного до оплаты. Брать сразу на 2–3 года: скачок продления в неудачный момент — более вероятная авария, чем бан. Reality тут — бонус (убирает имя из SNI), не основа: от TCP-заморозки и блока подсети не спасает.

**Согласованная схема (пока не построена):** подписки раздаёт Cloudflare — R2 с теми же файлами + Worker, повторяющий логику nginx `/sub/` и его заголовки; узлы переезжают на `.com`; `.ru` остаётся авангардом-редиректором. Честные границы: **узлы переезжают бесшумно**, а **URL подписки без действия человека не переносится** (301 живёт только пока старое имя резолвится; сохранит ли клиент адрес после редиректа — зависит от реализации, для Happ не проверено). CF-канал туннель не прикрывает: он по-прежнему коннектится на наш IP напрямую, так что шанс бана по адресу не падает — падает время восстановления. Жёсткий дедлайн не про РКН: продление `esmien.ru`.

**Вход-прослойка вместо переезда.** Согласовано с владельцем: дешёвый зарубежный VPS (Литва/Эстония, Time4VPS/FlokiNET/HostHatch — только незамороженный ASN и не 41745) с голым nginx stream: TCP 8443 + UDP 443 → наш адрес. Клиент видит вход, эстонский IP из РФ больше не виден (плечо Литва→Эстония границу не пересекает), а сгоревший вход меняется за ~300 ₽ и десять минут вместо двухчасового переезда стека. TLS остаётся сквозным, сертификат и SNI не меняются. Транспортный лимит важнее RAM: 1 ГБ хватает, 1–2 ТБ трафика на восемь человек — нет. Такой же сервер **внутри РФ** входом ставить нельзя: он станет видимым адресом, РКН увидит плечо к зарубежу, а хостер убьёт аккаунт по abuse; в роли выхода для `.ru` он и так уже есть. **Настоящая причина отказа — юрисдикция, а не ТСПУ:** ру-хостер обязан подключаться к СОРМ и отрабатывать реестр анонимайзеров, прокси для третьих лиц нарушает его правила, а крупный (Selectel, VK Cloud) отработает письмо РКН за день — поэтому он худший выбор из всех, и аккаунт гасят без разговоров. Довод «зато вход в РФ не в блоклистах» верен и уже учтён: именно за него и платят этим риском. Вариант не переоткрывать, пока владелец сам не вернётся к нему.

**Симметрия двух схем снимает половину споров.** «Ру-вход → зарубежный выход» и наша схема решают одну задачу: ру-зона не выходит через заграницу. Разница только в том, на каком конце стоит российская железка — у чужой схемы на входе, у нас на выходе (`bal-ru`). Поэтому чужую схему не называть «неправильной»: она покупает страховку адреса и платит юрисдикцией, мы наоборот. И не продавать прослойку как решение: она переносит адрес, на который стучатся, на другой зарубежный и только удешевляет замену — клиент по-прежнему коннектится на зарубежный IP.

**Второй адрес от того же провайдера** — не замена прослойке: он спасает только от бана по конкретному IP, из сети и с машины не выводит. Как поднять, проверить и чем привязать к нему исходящий трафик — `references/second-public-ip.md`.

**Канал восстановления — отдельно от доставки.** Telegram-бот переживает бан нашего адреса (ходит в `api.telegram.org` исходящим — люди получают сообщение от Telegram), страница-инструкция на нашем домене — нет: она нужна именно в момент аварии. Отсюда: бот на сервере + инструкция на CF Pages; людей привязывать `t.me/<bot>?start=<token>`, а не ником (ник не у всех, меняется, `getChat` отдаёт его только тем, кто уже писал); ссылку доставлять deep link `hiddify://import/<url>` и QR — один тап, а не «вставь URL». Детали, зоны/регистраторы, Cloudflare Tunnel для WebUI — `references/delivery-channel.md`.

## Failover — off, deliberately

The owner removed automatic failover: `vpn-failover.timer` is `disabled`/`inactive` and the default route is pinned to `direct`. Do not re-enable it without an explicit request. Rationale: a silent flip to `direct` keeps the internet alive but leaves geo-gated services refusing in a way that looks like the tunnel works ("connected, but Gemini says no"), which is harder to diagnose than a dead tunnel. With the timer off an exit outage now costs only the scenario it carries — Google/Gemini falls from `fr` to the
`fi` fallback and then fails loudly, while everything on `direct` is untouched.

`failover.py` and the unit files stay on disk and in the repo, unwired — re-enabling is `systemctl enable --now vpn-failover.timer`. If a probe is ever restored, keep the cadence irregular (`RandomizedDelaySec=300` on a 15-minute timer) so it does not read as a bot, and test the logic on a copy of the config, never against the live probe host.

## Traps worth memorising

The four that cost the most, verbatim from `references/pitfalls.md`:

- **Правка nginx, сделанная только в `/etc/nginx/conf.d/vpn-*.conf`, живёт до следующего `vpn-cfg apply`.**
  Тот запускает `apply_brand.py`, а он перегенерирует эти vhosts из своего шаблона — вместе с `location = /`.
  Ручная заглушка молча откатывается: ответ на `/` вернулся к прежнему короткому `ok` уже после проверки,
  и это увидел владелец, а не я. Любую правку этих двух vhosts вносить в шаблон `apply_brand.py` (и в копию
  `vpn-service/router/apply_brand.py`), затем `python3 apply_brand.py && nginx -t && systemctl reload nginx`.

- **Снимаешь публичный путь — в том же заходе правь health-check.** `probe_nginx()` в
  `vpn-bluegreen.py` проверял `/general` **и** `/ws`; после снятия `/ws` любой `vpn-cfg apply`
  откатывал бы рабочий конфиг с «цвет не отвечает», и правка выглядела бы как «не применилась».
  Теперь проверяются ровно опубликованные входы: `/general` на 8443 и публичный alias на 443,
  оба должны дать `400`. Правило: health-check идёт по тому, что реально генерирует
  `apply_brand.py`, и меняется вместе с ним. Плюс шаблон 8443/2087 получил `location / { return 404; }` —
  иначе nginx на снятых путях лез в `/usr/share/nginx/html` и писал в error.log мусор.

- **Never dump an outbound as JSON.** Trojan credentials live in `settings.servers[].password`, VLESS in
  `settings.vnext[].users[].id` — a "show me the outbound" print leaks the provider's shared keys and a
  client UUID straight into the chat. Print tag, protocol, address:port and stream network only, and
  mask anything whose key matches `pw|password|id|key|token`.
- A user's "the site is down" on one host is rarely the tunnel: check whether the requests reached the app at all before rebuilding anything (`references/client-drop-triage.md`, section 4d). Also check that the name **exists**: under a fake-ip client a nonexistent host is handed a `198.18.x.x` and simply hangs, so the browser reports `ERR_TIMED_OUT` instead of "server not found" and the tunnel takes the blame for a bad URL — `dig +short @1.1.1.1 <host>` plus the zone's record list settles it in one step.
- Writing nginx config through `printf`/heredoc mangles quotes and backslashes (`\"$request\"`, `\\S`), and `nginx -t` then fails on a file that looks fine on screen. Write generated snippets with Python `write_text` (staging under `/tmp` + `install -m 644` when a direct write to `/etc/nginx` is refused), test, then reload — the same trap bites fail2ban filter regexes. Same reason a python heredoc embedded in a compound `cmd1 && python3 - <<EOF` block can silently produce a truncated file (16 bytes, no error): put the generator in its own file and run it.
- **Не читать секретный файл парсером, который эхом печатает строку.** `configparser.read()`
  на `/root/.secrets/cf.ini` (там нет заголовка `[section]`, только `key = value`) падает
  `MissingSectionHeaderError` и **цитирует первую строку файла в тексте исключения** — токен
  Cloudflare ушёл в чат именно так, без единой явной печати. Секреты доставать построчной
  регуляркой из текста, а любое исключение выводить одной строкой (`parse failed`), без
  `str(exc)` от чужого парсера. Засветилось — перевыпуск токена, а не «он же зонный».
- **Временный тестовый клиент гасить по порту, а не `pkill -f <имя конфига>`.** Шаблон совпадает
  с командной строкой собственного шелла (в ней тот же путь), и `pkill` убивает вызов вместе
  с ним: `exit -15`, вывод теряется, клиент остаётся жить. Правильно —
  `ss -lntp 'sport = :10895'` → вытащить `pid=` → `kill`; и поднимать его через
  `(nohup xray run -c ./c443.json > ./c443.log 2>&1 &)`, читая потом лог, а не wait-for-exit.
