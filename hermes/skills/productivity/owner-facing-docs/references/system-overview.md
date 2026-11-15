# Shape that works for a system overview («покажи другу / коллеге»)

Same rules, different skeleton — the subject is the machine, not the owner. Order that read well end to end:

1. **Коротко** — one paragraph: what this server is, who it serves, what runs on it.
2. **Железо и состояние** — CPU/RAM/disk/uptime with the uncomfortable number stated (swap in use, disk at 73 %).
3. **Что запущено** — by role, not by container name; a role may be one line or five.
4. **Неочевидная механика** — the part a guest cannot guess: how a personal subscription becomes a normal API,
   how the tunnel survives DPI, why a service is pinned to one country. This is the section that makes the
   document worth reading, and the one that must explain the price of the trick, not just the trick.
5. **Что делает само** — by rhythm (minute / 10 min / 15 min / daily / weekly / boot), never by unit name.
6. **Данные и бэкапы** — table: what / volume / where / how often / retained; then the sentence that proves
   restore is exercised, not assumed.
7. **Восстановление** — measured step costs and a range; name the step that is slowest and why it is access.
8. **Безопасность** — perimeter first, then the sentence «за периметром» that a perimeter alone would hide.
9. **Границы** — conscious limits, framed as boundaries (see the standing rule above).
10. **Оценки по слоям** — table with a reason per score, one score visibly not 10.
11. **Что осталось** — exactly one action.

Redaction for this audience: no addresses, domains, paths, container names or ports; versions, counts, sizes,
minutes and score tables stay. Close the chat reply with an offer of the internal version — he may want it for
himself after seeing the redacted one.
