---
name: ip-reputation-and-ban-risk
description: "Use when judging an IP's ban risk or reputation."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [devops, security, dnsbl, reputation, vpn, scanners, blacklist]
---

# Репутация IP и риск бана

## When to Use

Владелец приносит пачку адресов («серверы знакомого», кандидаты под VPN-выход) и
спрашивает «чистые ли», «как быстро уйдёт в бан», «можно ли гонять через них трафик» —
или просит прогнать **наш собственный** IP той же методологией и сравнить.

Не путать с `vps-network-exposure`: там вопрос «что у НАС слушает наружу и как это
закрыть», здесь — «что про этот адрес знают чужие и как скоро его забанят». Пересечение
одно: список открытых портов берётся тем же способом.

## Answer shape (owner preference)

**Первая строка — вердикт**, потом факты, потом что это значит на практике.
«По листам чисто, но маркер сетевой» / «уже в бане с первого дня» — до любых выводов
команд. Дальше плоские буллеты по адресам, без таблиц.

Обязательно разделяй и называй оба направления:

1. **наши баны** — кого банят мы (fail2ban, nginx limit_req), это наша гигиена;
2. **баны нам** — кто банит адрес (DNSBL, антифрод, капчи, DPI).

Одна цифра «N банов» без этого деления читается как поломка.

Честные оговорки пиши явно: «лист ответил пусто» ≠ «лист подтвердил чисто».
Если источник недоступен без ключа (Censys, AbuseIPDB, ipinfo privacy) — так и скажи,
и что именно прогнал вместо него. Не выдавай замену за оригинал.

## Procedure

### 1. Идентичность и кто за сетью

```bash
whois <IP> | grep -iE '^(netname|org-name|country|abuse-mailbox|created)'
dig +short -x <IP>          # PTR
dig +short <PTR>            # forward-confirm: должен вернуть тот же IP
```

Смотри на **разброс /24 внутри одной ASN** и даты `created`. Свежие блоки (последние
месяцы) в DE/NL/PL/US/SE под одним RU-владельцем = перепродажа адресов под прокси/VPN.
Имя ASN проверяй поиском: за ним часто стоит публичный сервис (AS41745 Baykov Ilya =
fineproxy.org, это же подтверждает комментарий DroneBL). Это и есть главный маркер —
сетевой, а не поштучный.

**Сначала определи наш собственный egress** (`curl -s https://ifconfig.me/ip` + его
whois/PTR): кандидат может оказаться в той же ASN, что и мы, и тогда сравнение «его
риск vs наш» — это не про сеть (она общая), а про адрес, экспозицию и чей трафик идёт
через выход.

### 2. DNSBL — только с контрольным запросом

`scripts/ip-reputation.py <IP...>` гоняет весь набор разом. Ключевое правило:
**перед выводами проверь, что Spamhaus отвечает**: `dig +short 2.0.0.127.zen.spamhaus.org`
должен вернуть `127.0.0.2`. Пусто = резолвер публичный (8.8.8.8/1.1.1.1) и Spamhaus его
режет, все пустые ответы по ZEN недействительны — пиши «нет данных».

### 3. DroneBL — постранично, а не только через DNS

DNS-запрос (`<rev>.dnsbl.dronebl.org`) отдаёт код листинга, но CIDR-листинги дают мало
информации. Нужна HTML-страница `https://www.dronebl.org/lookup?ip=<IP>` — там CIDR,
тип и комментарий, который часто прямо называет провайдера («VPN Service designed for
abuse: fineproxy.org»). Забирай через `scripts/ip-reputation.py`; если текст пустой —
открой страницу браузером.

### 4. Что видят сканеры

`https://internetdb.shodan.io/<IP>` — ports, tags, vulns, hostnames. Затем **перепроверь
порты живым connect**: индекс стареет, Shodan показывает уже закрытые порты и мёртвые
имена. `-a` в скрипте делает connect по списку типовых портов, баннер SSH, набор методов
аутентификации и TLS-сертификат.

### 5. Классификация для антифрода

`http://ip-api.com/json/<IP>?fields=country,isp,as,reverse,proxy,hosting,mobile`
(бесплатно, http, 45 запросов/мин). `hosting=true` и `proxy=true` — разные режимы
отказа, разбор — в
[references/blacklist-and-classifier-semantics.md](references/blacklist-and-classifier-semantics.md). Censys-аналог (`labels`) требует API-ключ: без него
`search.censys.io` и `platform.censys.io/api/v1` отдают 403 — предложи владельцу
добавить free-ключ и не выдавай Shodan за Censys.

### 6. Треды и агрегаторы

AlienVault OTX (`/api/v1/indicators/IPv4/<IP>/general`, поле `pulse_info.count`),
StopForumSpam (`https://api.stopforumspam.com/api?ip=<IP>&json`), Tor exit list,
агрегатор `https://raw.githubusercontent.com/stamparm/ipsum/master/ipsum.txt`
(grep по IP; 8 = в восьми листах). Пусто во всех трёх — хороший аргумент «не замечен».

### 7. Базовая линия для сравнения

Наш собственный хост: `fail2ban-client status sshd` (Currently/Total banned),
`sshd -T | grep -i passwordauthentication`, объём брутфорса
(`journalctl -u ssh --since "7 days ago" | grep -oE 'from [0-9.]+' | sort -u | wc -l`).
Это даёт владельцу масштаб «сколько шума в интернете вообще», а не абстракции.

### 8. Отчёт

Пер-IP буллеты + отдельный блок «что это значит»: как выход в интернет / как входной
узел / что дешевле починить. Хвоста-вопроса не писать.

## Питфоллы

- **Spamhaus через публичный резолвер = тихий пустой ответ.** Симптом: контрольный
  `2.0.0.127.zen.spamhaus.org` тоже пуст. Любой «чисто по ZEN» без контроля — ложный
  вывод; пиши «нет данных».
- **«Не в листах» ≠ чистый.** Свежий нетблок чист по определению: листы содержат только
  уже засвеченное. Отсутствие листинга ничего не говорит о будущем бане.
- **Per-IP DNS-запрос скрывает суть CIDR-листинга** — код есть, причины и провайдера нет;
  только HTML-страница показывает `/22` и комментарий.
- **UCEPROTECT L2/L3 — это не про адрес, а про сеть.** 127.0.0.2 на всех адресах одной
  ASN = листинг всей ASN. Для почтовых гейтов аргумент, для Cloudflare/Google — почти
  ничего. Не подавай это как «адрес грязный».
- **Shodan-индекс стареет в обе стороны:** порты могут быть уже закрыты, а имена —
  висеть после сноса DNS. Verify живым connect, прежде чем строить вывод.
- **Чужой (Apple, Microsoft) сертификат на хостинговом IP = TLS-проброс под маску, а не
  кража ключа.** Проверяется сменой SNI: если cert не меняется при `-servername
example.org`, сервер всегда пробрасывает в один апстрим. Для DPI/CT-сверки это палево,
  для «банов» — нейтрально; не называй это взломом.
- **Парольный SSH — это вход, а не шум.** Набор методов виден без попытки логина:
  `ssh -o PreferredAuthentications=none nobody@<IP>` → `Permission denied (publickey,password)`.
  Для своего хоста это повод закрыть пароль, для чужого — реальный вектор.
- **Секреты подписки в чат не выводить.** UUID/ключи из расшифрованного `vless://` в
  ответ не попадают: только структура (протоколы, порты, счётчики). Детали —
  [references/vpn-subscription-triage.md](references/vpn-subscription-triage.md).

## Related

- Порты, фаервол, входной VPN-стек этого хоста: `vps-network-exposure`.
- Общая оценка хоста (security/бэкапы/RTO): `vps-posture-assessment`.

Глубина: [references/blacklist-and-classifier-semantics.md](references/blacklist-and-classifier-semantics.md)
— что значит каждый лист, коды DroneBL, модель «как быстро наступает бан»;
[references/vpn-subscription-triage.md](references/vpn-subscription-triage.md) — разбор
подписки/ссылки, которую дали на проверку.
