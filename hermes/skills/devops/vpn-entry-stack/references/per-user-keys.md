# Per-user keys and subscription tokens

Goal: each person gets their own UUID and their own subscription URL, so one leaked
link is revocable and revocation does not force anyone else to re-import.
The legacy global UUID (`/root/mtproto-faketls/ws-client-uuid`) stays in place —
the rollout is **additive**, never a credential swap.

## Files

- `/root/vpn-router/users.json` — 0600, gitignored, source of truth:
  `{"<name>": {"uuid": ..., "token": ..., "title": "Esmien VPN (<Имя>)", "created": "YYYY-MM-DD"}}`
- `/root/vpn-router/users.py` — `list` / `add <name> [--title ...]` / `url <name>` / `rm <name>` / `sync`
- `/var/www/esmien-sub/<token>/user` — name of the owner of this bundle (its presence flips the key)
- `/var/www/esmien-sub/<token>/title` — per-user profile title; wins over `kind`

## What `add` does, in this order

1. `uuid4()` + 18-char token (same charset as the other tokens).
2. Injects `{"id": uuid, "email": "<inbound tag>:<name>"}` into **every** vless inbound —
   all 24 inbounds, not just the four own routes, otherwise the user's bundle ships relay
   nodes (`/p<i>`) that refuse his key. Email must be unique per inbound+user: Xray keys
   per-user stats by email, so duplicates mix counters silently.
3. Writes `config.json`, then validates with the image — never the host binary:
   `docker run --rm --user 0:0 --entrypoint /usr/local/bin/xray -v /root/vpn-router/config.json:/etc/xray/config.json:ro ghcr.io/xtls/xray-core:latest run -test -c /etc/xray/config.json`.
4. Creates the token dir with `user` + `title`, runs `make_sub.py` (renders every dir),
   regenerates the title map via `apply_brand.write_title_map()`, `nginx -t` + reload,
   then `vpn-cfg apply` (it backs up and probes `/general /france /fi`).

`rm` removes the user's clients from all inbounds, parks the token dir under
`/var/www/esmien-sub/.disabled/<token>.<name>` (dot-dirs are skipped by both
`make_sub.py` and the title map), re-renders and applies. It never deletes data.

## How the key reaches the bundle

`make_sub.token_uid(token_dir)`: dir has a `user` file whose name is in `users.json`
→ that UUID; no `user` file → the legacy global UUID. That single function is what keeps
old bundles untouched while new ones carry different keys — do not duplicate the lookup
elsewhere, and never hard-code a UUID into `make_sub.py`.

## Blocking trap: pool rebuilds drop per-user clients

`import_sub.py` creates `/p<i>` inbounds with **only** the legacy client. A rebuild would
therefore publish relay nodes that answer the owner's old key and nobody else's — the
symptom is a user whose subscription lists every node but only the Estonia ones
authenticate. It now calls `apply_users(cfg, load_users())` right before writing the
config. Any other script that builds inbounds needs the same hook, or `users.py sync`
(idempotent, re-adds every missing client) must run immediately after it.

## Proof this is non-disruptive (cheap, do it every time)

    md5sum /var/www/esmien-sub/*/* > /tmp/subs_before.md5   # before touching anything
    python3 /root/vpn-router/users.py add <name>
    md5sum -c /tmp/subs_before.md5                          # legacy bundles must be byte-identical

Then probe the tunnel per key, per route: build a throwaway socks client
(`/usr/local/bin/xray run -c /tmp/cli<port>.json`), curl `https://ipinfo.io/json` through
it, kill by PID. Expected matrix for a new user:

- legacy key on `/general` → Estonia exit, the same IP clients had before;
- new key on `/general` → that same Estonia exit;
- new key on `/p15` → RU (Moscow) exit; new key on `/france` → FR exit.

Subscription side, one pass:

    curl -sS --resolve <host>:8443:127.0.0.1 -D /tmp/h -o /tmp/b https://<host>:8443/sub/<token>
    grep -i 'profile-title\|profile-update\|content-disposition' /tmp/h
    base64 -d /tmp/b > /tmp/l && grep -c '://' /tmp/l          # node count
    grep -c "$OLD_UUID" /tmp/l; grep -c "$NEW_UUID" /tmp/l     # must be 0 and N

A bundle carrying the *other* key is the single strongest check (legacy token: N old / 0
new, user token: 0 old / N new) — a wrong key silently authenticates the client as someone
else. Unknown token must answer `404`, and every title must be distinct so the owner can
tell profiles apart by suffix.

## Quotas, device limits, panels — say this plainly

- Traffic quota per user is the native part: add an `api` inbound on 127.0.0.1 plus
  `stats`/`policy`, read `user>>>email>>>traffic>>>uplink|downlink`, drop or disable the
  client over quota. Not wired up yet — nothing enforces volume today.
- **Device limit is not something Xray knows.** Without a panel the only proxy is counting
  distinct source IPs in the access log and kicking via the API — it under-counts several
  devices behind one NAT and over-counts a phone that legitimately rotates IPs. Offer it as
  coarse protection, never as a guarantee.
- Real HWID limits mean Remnawave/Marzban, which generate their own core config: the whole
  routing shape (per-inbound → exit, relayed `/p<i>`, RU split, Gemini rules) has to be
  re-ported into their template. That is a migration project, not a checkbox, and it
  brings back the public admin surface the owner deliberately removed with 3x-ui.
- Whitelist-kind bundles stay shared: they carry the provider's own links, so a per-user
  UUID is meaningless there and more tokens only spread the same shared key.

# Per-user keys

## Per-user keys

Per-person access means each person gets their own UUID and own token. There is **no shared key any more**: the legacy global UUID was deleted from every inbound on the owner's order, so every human — the owner included — authenticates with a personal key. `/root/vpn-router/users.py` owns accounts: `add <name>` injects a client into **every** vless inbound (today `/ws` and `/general` only), creates `/var/www/esmien-sub/<token>/{user,title}`, re-renders all bundles and applies. `users.json` (0600, gitignored) is the source of truth; `make_sub.py` picks a token dir's key from its `user` file, so a bundle can no longer carry a key that is not its own.

Roll it out **additively**: no credential swap, no re-import for existing clients. Snapshot `/var/www/esmien-sub/*/*` with `md5sum` first, prove the legacy bundles are byte-identical afterwards, then probe each key through each route. Full procedure, verification matrix, quota/device-limit reality: `references/per-user-keys.md`.

Rule: any script that builds inbounds (`import_sub.py`) must re-apply `users.json` before writing the config — otherwise new paths authenticate only the legacy UUID and a user's subscription lists nodes that refuse his key.

# Per-user keys (pairs: main + LTE)

## Per-user keys (pairs: main + LTE)

`users.json` (0600, gitignored) is the source of truth: `name → {uuid, token, token_lte, title}`. `users.py add <имя>` injects that UUID as a client into **every** vless inbound (`email = "<tag>:<имя>"`), creates two token dirs — main (files `user` + `title`) and LTE (`kind=whitelist`) — then re-renders subs, rewrites the title map, reloads nginx and runs `vpn-cfg apply`. `users.py rm <имя>` drops the clients and **parks** both dirs under `/var/www/esmien-sub/.disabled/<token>.<имя>`; `users.py sync` re-applies users.json after a pool rebuild (`import_sub.py` also calls it).

Rules that make it hold:

- A profile must never carry a UUID that some inbound already holds as another client: `apply_users` skips by id, so that person silently shares the other key and their traffic merges into a foreign stats row. `users.json[<name>]['uuid']` equal to a client id that is not `in-general:<name>` is the diagnosis — replace it with a fresh `uuid4()` and `users.py sync`. That is exactly how the owner once ended up riding the shared legacy key while believing he had his own subscription. Shared-key removal and proof that it is dead: `references/subscription-shapes.md`.
- `make_sub.py` picks the UUID per token dir: a dir with a `user` file uses that person's key, without one it falls back to `/root/mtproto-faketls/ws-client-uuid`. Adding a per-user key therefore leaves every already-issued bundle byte-identical — verify with `md5sum -c` before/after rather than by eye.
- `profile-title`/filename come from the dir's `title` file and its `kind`; the `(LTE)` filename is decided by `kind`, not by the title string, or an LTE name would download as `esmien-vpn`. Titles must stay distinct **and differ early**: the LTE bundle is `Esmien VPN LTE (Имя)`, never `Esmien VPN (Имя, LTE)` — clients truncate long profile names, and with LTE at the end both profiles look identical until expanded. `users.py retitle` rewrites the existing `title` files in place when the scheme changes.
- The LTE bundle carries the provider's raw «глушилки» links, so its *content* is identical for everyone — separate tokens give separate links, not separate credentials. Say that before promising isolation.
- Rollback of a single person is `users.py rm`; a full rollback of the whole feature is `vpn-cfg rollback` plus deleting the `user`/`title`/`kind` files.
- Account state is still spread over five places — `users.json`, `config.json`, a `kind` file per token dir, the stats state, and the generated pages — and the two bugs above (a profile built from the full node list, a page outliving its account) are both products of that split. The agreed direction is one admin API over SQLite with the xray config as a rendered artifact: field list, invariants and the secret-storage decision in `references/admin-api.md`.
- The roster (who has which token, page URL, and the operations cheat-sheet) lives in `/root/vpn-router/users.md` (0600) — deliberately **outside git**: the owner does not want the people list and their tokens pushed, even to the private repo. Code goes to `Esmien/vpn-service`; `users.json`, `users.md`, `pages_index.json` and the generated subscriptions/pages stay on the host.
