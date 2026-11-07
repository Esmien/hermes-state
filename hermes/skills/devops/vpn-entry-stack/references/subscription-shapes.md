# Subscription shapes (one node vs full list)

`make_sub.build()` picks the layout by the `kind` file in the token dir:

- `meta` (default; also what a missing `kind` means) — **one visible node** `🇪🇪 Эстония (все сервисы)` on `/general`. All routing (Google → FR/FI, `.ru` → RU host, everything else → direct) happens on the server, so the client has nothing to switch. This is the product: one server, no node shopping.
- `whitelist` — the LTE subscription: a group of ~9 provider nodes used to **bypass ISP white lists** when our own entry is blocked. It is a list on purpose — collapsing it to one node breaks its only job. Never "clean it up".
- `full` — opt-in legacy: 4 own routes + 2 by-IP duplicates + every provider node (≈25 entries). Only when explicitly asked.

Creating a user must write `kind=meta` for the main token (`make_dir(..., kind="meta")` in `users.py cmd_add`); forgetting it silently produces the 25-node legacy list, which is exactly how two profiles ended up with the wrong layout. Any new profile creation path must set the kind explicitly.

After changing kinds: `make_sub.py` then `make_pages.py`, then check that each main token has exactly one line in `list.txt` and each LTE token still has its provider list.
