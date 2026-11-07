# Subscription shapes (one node vs full list)

`make_sub.build()` picks the layout by the `kind` file in the token dir:

- `meta` (default; also what a missing `kind` means) — **one visible node** `🇪🇪 Эстония (все сервисы)` on `/general`. All routing (Google → FR/FI, `.ru` → RU host, everything else → direct) happens on the server, so the client has nothing to switch. This is the product: one server, no node shopping.
- `whitelist` — the LTE subscription: a group of ~9 provider nodes used to **bypass ISP white lists** when our own entry is blocked. It is a list on purpose — collapsing it to one node breaks its only job. Never "clean it up".
- `full` — opt-in legacy: 4 own routes + 2 by-IP duplicates + every provider node (≈25 entries). Only when explicitly asked.

Creating a user must write `kind=meta` for the main token (`make_dir(..., kind="meta")` in `users.py cmd_add`); forgetting it silently produces the 25-node legacy list, which is exactly how two profiles ended up with the wrong layout. Any new profile creation path must set the kind explicitly.

After changing kinds: `make_sub.py` then `make_pages.py`, then check that each main token has exactly one line in `list.txt` and each LTE token still has its provider list.

Symptom that starts this: the owner opens the app and sees a dozen country cards («почему я вижу много?»). Cause is always the same — the token dir has no `kind`, so `build()` fell through to the full list. Fix the dir, fix the creation path, then say what he will see after a refresh.

## Shared (legacy) key

Historically every inbound carried one extra client whose `email` equals the inbound tag (`in-general`, `ws-in`, …) — one UUID shared by the owner, a guest and any old link. It is **gone**, deleted on the owner's order («снеси нахуй»), and nothing re-creates it: `apply_users` only adds per-user clients and skips ids that already exist, so a rebuild does not bring it back.

Removal, in this order:

1. Back up `config.json` first; it is the live source of truth.
2. For each inbound, drop clients with `email == inbound['tag']` (23 of them in a 23-inbound vless set) and write the file back.
3. `vpn-cfg apply` — it lints, restarts the idle colour, probes 24/24 and flips. Removing clients needs no other bookkeeping; ports and routing are untouched.
4. Purge the row from stats state (`state["users"].pop("@legacy")` plus its `u:@legacy:*` counters), otherwise the historical total keeps a dead person on the dashboard forever.
5. Prove it is dead rather than assuming: build a throwaway client from the *old* UUID (read it out of the backup, never print it) on `/general`. A refused connection (`000`, curl exit 35) is the success signal.

Consequences to state in one line, not a paragraph: whoever still used that key is cut off and needs a personal profile; the dashboard loses the shared row.

## Owner's own profile — protected, reissue-only

The owner's row is not deletable. In `subgen_api.py` keep a `PROTECTED = {"Владислав"}` set: `POST api/del` answers **403** («только перевыпуск») for those names, and `POST api/reissue` exists instead. Reissue is `users.py rm <name>` followed by `users.py add <name>` — `cmd_add` refuses an existing name, so there is no single command that rotates uuid + tokens in place; two applies in a row are fine and take ~10–40 s. The response carries the fresh `page`/`sub`/`lte` links, and the UI prints them in the same block the generator uses, because the owner needs the new URL immediately (his old link is dead from that moment).
