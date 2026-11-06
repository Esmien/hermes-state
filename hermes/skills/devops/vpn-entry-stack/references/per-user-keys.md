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
