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

When the question becomes "should all of this live in one service instead of these scripts", see `references/control-plane.md`.

## Client TLS fingerprint lives in every builder, not in one

The transport is only half the fingerprint: a client that offers a default Go/`xray` ClientHello is visible to DPI without any SNI. Pin `chrome` in **all four** independent places `make_sub.py` builds nodes, because they do not share code:

- raw `vless(...)` links (`list.txt`) — query params `fp=chrome`, `alpn=http/1.1`;
- `clash_proxy` / `clash_proxy_from_link` — `client-fingerprint: chrome`;
- `sb_link` and `sb_ours` (sing-box outbounds) — `tls.utls = {enabled: true, fingerprint: chrome}` plus `tls.alpn`;
- the main `build()` out dict for the WS node — same `utls`, and this is the one that actually ships to most tokens.

Patching one builder feels done and is not: the served `singbox.json` kept a bare `{"enabled": true, "server_name": …}` through two regeneration rounds. Verify in the **served files** after `python3 make_sub.py`, not in the source: decode `list.txt` for `fp=`, read `singbox.json` `outbounds[0].tls`, grep `clash.yaml` for `client-fingerprint`. `users.py sync` regenerates through `make_sub.py`, so a fix appears only after one of those runs.

Tell the owner the one thing it costs: whoever uses a subscription just refreshes it; whoever saved a raw link by hand needs the new link.

# Subscription

## Subscription

`make_sub.py` renders three formats; nginx picks one by User-Agent (`00-esmien-sub-map.conf`): Clash/Mihomo → `clash.yaml`, sing-box → `singbox.json`, everything else → base64 `list.txt`. The response carries `profile-update-interval: 12` and a `profile-title` that depends on the token: `apply_brand.py` scans `/var/www/esmien-sub/*/kind` and emits `00-esmien-sub-title.conf` with `map $esmien_sub_token $esmien_sub_title` (whitelist token → `Esmien VPN (LTE)`, everything else → `Esmien VPN`) plus a matching `$esmien_sub_fname` map, so downloads are named `esmien-vpn` / `esmien-vpn-lte`. A new token inherits its title from its `kind` file — never hard-code the title in the nginx template, and never let two subscriptions share a display name: the owner tells them apart by the suffix.

Rules: names are plain country names with flags (`🇪🇪 Эстония (General)`, `🇫🇷 Франция (Gemini)`, `🛠 Тест (Develop)`); the brand lives only in the group/profile title. **The main subscription ships exactly one node** — `🇪🇪 Эстония (все сервисы)` on `/general`, every scenario decided on the server. That is the product: one server, nothing to switch, and no provider traffic caused by a node he happened to tap. The whitelist entries are a **second, separate subscription** (the LTE token) and that one is a list on purpose: it is the bypass for ISP white lists, so never «clean it up» to a single node. `make_sub.py` branches on a `kind` file inside the token dir — `whitelist` → whitelist-only bundle (`make_sub.py --new-whitelist` creates one), missing/`meta` → one node, `full` → the legacy 25-entry list, opt-in only. Full shapes and the bug that shipped the big list by accident: `references/subscription-shapes.md`. Never add a third group or a node class he did not ask for.

URL shape: `https://<host>:8443/sub/<token>`. The port must be in the URL: plain 443 is blocked for the owner's ISP.

A single person can get an extra, hand-added node without changing the shared build: `<token>/extra_nodes.json` (list of `{name, link, clash, sing}`) is merged into that token only, so he can tap an owned node directly and compare it against the meta route. Shape and build behaviour: `references/scenario-routes.md`. Never hard-code such a node into `build_meta`'s default — a second tappable node for everyone is exactly the ban-risk shape the one-node subscription exists to prevent.

**A `type: select` group is inert unless a rule points at the group, not at a node.** The generated Clash profile ends with `MATCH,<some concrete node>`, so everything unmatched goes there regardless of what the user taps; no rule references the `Esmien VPN` group, which makes the switcher a decoration that only takes effect in the client's GLOBAL mode. The same trap in reverse: anything placed **after** `MATCH` is dead code (a duplicated `IP-CIDR` block after `MATCH` ships silently and never evaluates). Before promising "he can pick a node in the app", search the generated profile (`search_files`) for rules referencing the group name, and end the rule list with `MATCH,<group name>` if the switch is meant to work. The fixed `MATCH,<node>` is the deliberate no-failover posture — changing it is a routing decision for the owner, not a bug fix.

**Happ cannot express per-domain exits.** Happ asks with `Happ/<ver>/ios`, falls through the User-Agent map to `list.txt`, and so receives a bare node list — no routing at all, everything follows the selected node. Its own routing profiles (delivered as a `routing` response header or an `happ://routing/…` link built at `routing.happ.su`) only split traffic into Direct / Proxy / Block; a rule cannot name a *different* node. So a Clash rule like `DOMAIN-SUFFIX,google.com,<FR node>` has no Happ equivalent: either the rule lives only in Clash-family clients, or the decision moves to the server (see Gemini / geo). State that plainly instead of promising parity, and remember JSON-format subscriptions in Happ are limited to one provider-locked profile.

### RU traffic via the Moscow node

The recurring owner complaint is toggling the VPN on and off for Russian apps (banks, gosuslugi, VK/MAX, OZON, WB). The answer is a **client-side rule block in `make_sub.py`** that sends that traffic to the relayed Moscow node (`/p15`, «Москва - YouTube/ГосУслуги/Банки»), not to `DIRECT`: everything else keeps the foreign exit, RU apps see a Russian IP, and nothing gets switched. State plainly that the server cannot make traffic "go directly from the client" — once traffic is in the tunnel it leaves from Estonia, so the split decision is either a client rule or a different exit IP; there is no server-side shape that restores the client's home address.

Rule order inside `rules:` is what makes it work — the RU block goes **after** the Google rules (Gemini must keep winning) and **before** `MATCH`, three tiers in this order:

- `DOMAIN-SUFFIX` per host for RU services outside `.ru`: `vk.com, vk.me, vk-cdn.net, userapi.com, mycdn.me, max.ru, ozon.com, gosuslugi.ru, sberbank.ru, tbank.ru, vtb.ru, alfabank.ru, wildberries.ru, wb.ru, wbstatic.net`;
- `DOMAIN-SUFFIX,ru` and `DOMAIN-SUFFIX,su` — the long tail;
- `GEOIP,RU` — RU-hosted services behind `.com`/`.net`. It needs a real IP, so the profile keeps `dns.enable: true` (fake-ip) and must **not** carry `no-resolve` on that rule.

Mirror the same tiers in `singbox.json` (`domain_suffix` with a leading dot: `.ru`, `.su`, then `geoip: ["ru"]`), before the catch-all outbound. Generate the block from a list constant, not by hand per token, so both subscriptions stay identical.

Verify with two measurements, in this order: (1) exit — run an Xray client on the relay path (`/p15`) and read `ipinfo`; the country must be `RU` with a Moscow city; (2) purpose — the same sites from the Estonian address *without* the tunnel must fail (gosuslugi answers `000` there), otherwise the split is cosmetic and not worth shipping. Then request the real sites through the tunnel.

Say both caveats up front instead of after the owner finds them: banks often refuse datacenter IPs, and Sber serves a self-signed certificate in its chain, so `curl` answers `000` even when the route is perfect (plain HTTP answers `200`, and a browser with the Russian trusted roots is fine) — that `000` is not evidence of a broken rule.

While the entry's DNS is unreliable, ship duplicate nodes addressed by bare IP: `vless(addr=<ip>)` / `clash_proxy(addr=<ip>)` with `server`/`sni`/`Host` still carrying the hostname, so TLS and the WebSocket routing stay valid without any resolver. Pair them with an `http://<ip>/sub/<token>` vhost as an emergency fetch path — that URL exposes the token to the transit provider, so it is a fallback, never the default.

### Owner's own domain — `DIRECT` on the client

`*.esmien.ru` must never ride the tunnel. With the RU block in place, `ai` / `app` / `vpn` / `/sub/` all
fall into `DOMAIN-SUFFIX,ru` and leave through the Moscow box — 100 Mbit, +43 ms, one vCPU — which is
exactly the path the owner then describes as "the WebUI is slow / dropped". Add one rule above the RU
block, in **every** builder of `make_sub.py` (`build_whitelist`, `build_meta` and the default `build()`)
plus the sing-box mirror of each:

```yaml
  - DOMAIN-SUFFIX,esmien.ru,DIRECT      # after DOMAIN-SUFFIX,local,DIRECT (or just before MATCH,<group>)
```

```json
{"domain_suffix": [".esmien.ru"], "outbound": "direct"}   # first entry of route.rules
```

Then `python3 make_sub.py` (no args rebuilds every token) and prove it on what clients actually fetch:
`curl -A 'ClashMeta/1.18' https://<host>:8443/sub/<token> | grep -n 'esmien.ru,DIRECT'`. Clients pick it
up on their own schedule (`profile-update-interval: 12`), so say plainly that the profile has to be
refreshed by hand or it waits up to 12 h.

Two rules to state alongside it: `DIRECT` means "the device dials it itself", **not** "bypasses a CDN" —
while the record is orange the device still lands on Cloudflare and only skips the tunnel; and the rule
must sit **above** the `.ru` line, otherwise the long-tail suffix wins and nothing changes.
