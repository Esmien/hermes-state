---
name: vpn-entry-stack
description: Use when editing or deploying the VPN entry stack.
---

# VPN entry stack (VLESS over WebSocket + TLS)

## When to Use

Load this before touching anything that serves VPN clients: adding or removing a route, moving the public host or certificate, regenerating subscriptions, or answering a "VPN keeps dropping / no internet" report. Not for the AI services on the same host — that is `ai-stack`.

The owner's home ISP (MTS, Krasnodar) drops **port 443** and kills **fake-TLS/MTProto** to this server's IP. What works is a *real* TLS handshake on a non-standard port. That single fact drives the whole design — verify it before debugging anything else.

## Layout

```
client -> nginx TLS (8443 primary, 2087 backup) -> xray container `vpn-router` (host network)
        -> outbound "fr" (external exit) | "direct" (this server)
```

Paths (same nginx server blocks):

- `/ws` — owner's profile, everything goes through the external FR exit.
- `/general` — Estonia (direct exit), normal traffic.
- `/france` — France (external exit), needed for Google/Gemini.
- `/test` — spare inbound for experiments, routed independently (`inboundTag in-test`).
- `/fi` — second exit that passes Gemini: `hels.sream-rutube.shop` → `193.233.136.5` (Helsinki, PLAY2GO), Google reports `fi`. Manual switch next to `/france`; no automatic failover.

There is deliberately **no** RU-entry inbound: an earlier `/lte` route (`1.fan-video.study` → Selectel SPb → Helsinki, Google saw it as `ru`) was removed once it was clear the whitelist first hop has to be dialled by the client itself, never by this server. Whitelist entries ship as direct client links only — see Whitelist mode.

3x-ui is **not** part of the stack: container, volume, `/panel/` route, credentials file, panel vhost, its rate-limit zone and fail2ban jail were all removed. It managed two idle inbounds and could not express "this entry -> that exit", which is the whole point of the routing, so it was one public admin surface for nothing. `references/xui-panel.md` keeps only the CSRF/login knowledge in case a UI is ever reintroduced — do not bring a panel back off your own initiative.

Upstreams: 10081 `/ws`, 10082 `/general`, 10083 `/france`, 10084 `/test`, 10086 `/fi`, 10100+i for the relayed `/p<i>` nodes — all bound to 127.0.0.1. Check the real ports with `vpn-cfg status` instead of trusting a number from a report.

Adding a route means four coordinated edits, in this order: append an inbound (`tag`, 127.0.0.1, next free port, same client id, `wsSettings.path`) to `config.json`, add the outbound and a routing rule keyed on `inboundTag` **before** the catch-all `tcp,udp → fr` rule, add `paths` + `upstreams` entries to `brand.json`, then `apply_brand.py && nginx -t && systemctl reload nginx && vpn-cfg apply` (not a bare `docker restart` — `apply` proves the routes answer and reverts a broken config). Verify by dialling the new path through the tunnel and checking the egress with ipinfo — not by reading the config back.

Files: `/root/vpn-router/{config.json,brand.json,apply_brand.py,make_sub.py,make_template.py,import_sub.py,users.py,probe_sub.py,test_whitelist.py,gemini_geo_check.py,sub_expiry.py,route_ru.py,subs.json,users.json,failover.py,certbot_retry.py,provision_vpn_host.py}`, subscriptions in `/var/www/esmien-sub/<token>/`. Editing, applying and rolling back: `vpn-cfg` (`references/router-ops.md`). When a client reports that the VPN "keeps dropping": `references/client-drop-triage.md` — probe the server end to end before touching anything, and start with DNS: an entry whose name no longer resolves looks exactly like a dead VPN (app can't ping any node, browser still works from cache).

## Deploy / rebuild

The entry is deliberately one container plus flat files, so a fresh server is a script run, not a rebuild from memory:

```bash
bash assets/vpn/scripts/deploy.sh <domain> [email]     # nginx+stream, cert, container, vhosts, subs
python3 /root/vpn-router/import_sub.py <sub-file> [dead indices]
```

The VPN is its **own project**, not part of the AI-stack installer: the canonical repo is the private `Esmien/vpn-service` (`router/`, `nginx/`, `scripts/`, `systemd/`). A full server rebuild is therefore two steps — `install.py` for the AI stack, then `deploy.sh` from this repo for the entry; the bootstrap one-liner does not bring the tunnel back. After any structural change, regenerate the secret-free template with `router/make_template.py`, copy the live files into the repo, and commit — it must match the live host exactly. Runtime secrets stay out of git via `.gitignore`: `config.json` (client UUID), `users.json` (per-user UUIDs), `subs.json`, `whitelist_links.json`, `*.key`, `*.pem`, `*.enc`. Full procedure and pitfalls: `references/router-ops.md`.

The owner-facing counterpart is `/root/.hermes/docs/vpn-runbook.md`: scheme with real ports and paths, every design decision with its price, a nine-step rebuild with a check after each step, six diagnostic commands with a symptom table, and the pitfalls below. It lives in the `hermes-state` snapshot, **not** in `vpn-service` (that repo takes only what actually runs on the host). After any structural change — a new port, path, scenario, timer or exit — update the runbook in the same pass; he asked for it so he can rebuild the stack by hand, and a stale runbook is worse than none.

## Changing the public host

Never hand-edit the nginx confs — they are generated:

1. edit `host` + `cert_dir` in `/root/vpn-router/brand.json`
2. `python3 /root/vpn-router/apply_brand.py`
3. `nginx -t && systemctl reload nginx`

`apply_brand.py` no longer emits a compat block: the `legacy_hosts` map and the `vpn-compat.conf` generation were deleted once the old free-domain vhosts and their certificates were removed for good. Keep it that way — a compat stub pointing at an old name keeps answering on the default server with a certificate mismatch and looks like a live site without being one. Legacy hosts are only worth keeping while their DNS still exists; a dead zone revives nothing.

Prerequisites before pointing the entry at a new name:

- The DNS record must exist and resolve from at least two public resolvers **before** certbot runs; HTTP-01 is issued through the port-80 ACME vhost, so a name that does not resolve yet wastes a validation attempt.
- Under Cloudflare the record is **A → server IP with proxy OFF (grey cloud)**. The orange proxy terminates TLS at the edge, so our own certificate and the per-path WebSocket routing stop matching; Cloudflare does support 8443 if proxying is ever wanted deliberately, but that is a different setup, not a checkbox. The concrete symptom of getting this wrong while issuing: HTTP-01 through an orange record answers `530` and certbot reports `unauthorized` — fix the colour, do not chase the webroot.
- A brand-new registered domain has its own Let's Encrypt bucket, so moving the entry to it sidesteps an exhausted bucket on the old name (see Certificates).

Verification after the switch, in one pass: `openssl s_client -servername <new host>` shows the new CN; `https://<host>:8443/` returns `200` and `/<path>` returns `400` (a WS inbound refusing a plain GET — that is the healthy answer); `/sub/<token>` returns `200` with the new host inside the links; a locally dialled Xray client gets a real egress IP; `check-host.net/check-tcp` on the entry port answers from most nodes. Verify the old name is *gone*, not stubbed: an unknown SNI falls through to the default server and answers `200` with the `*.esmien.ru` certificate, which reads like a working site in a log grep.

A name change has to reach the **applications**, not just nginx and the subscription. Grep every config on the host for the old name (`grep -rn '<old-host>' /root/deploy /home/ai_service --include='*.env*' --include='*.yml'`) — a webhook base URL, an OAuth redirect or an app's own public URL keeps answering `200` on the new vhost while quietly pointing at the dead one. Then re-register the webhook and confirm the provider's own state (`getWebhookInfo` → `pending_update_count=0`); the music bot sat deaf for days on an old `bot.<old-host>` URL that no TLS or HTTP check would ever flag.

## Scenario routing / one-node subscription

Server-side scenarios (Google→FR/FI, RU→Moscow or an owned RU box; YouTube deliberately rides the
Estonian exit) plus a subscription that exposes **one** node, and the jittered watchdog that falls
a dead scenario group back to Estonia: `references/scenario-routes.md`. Do not offer a user a
second node to tap — that is provider traffic and ban risk, not a feature.

Two rules apply to every scenario edit: a balancer tag must also be listed in
`observatory.subjectSelector` (otherwise `leastPing` has no data for it and the matching requests
hang while every config check passes), and health checks must accept `2xx`/`3xx` through a URL
that answers *from that node's country* — a RU exit probed with `gstatic` reads permanently dead.
Full symptom list and fixes: `references/scenario-routes.md`.

When the RU scenario must stop depending on reseller relays, a small owned Russian VPS with a
VLESS+Reality inbound wired in as outbound `ru1` is the shape: provisioning, firewall allowlist,
IP-reputation acceptance test and rollback in `references/owned-ru-exit.md`.

## Subscription

`make_sub.py` renders three formats; nginx picks one by User-Agent (`00-esmien-sub-map.conf`): Clash/Mihomo → `clash.yaml`, sing-box → `singbox.json`, everything else → base64 `list.txt`. The response carries `profile-update-interval: 12` and a `profile-title` that depends on the token: `apply_brand.py` scans `/var/www/esmien-sub/*/kind` and emits `00-esmien-sub-title.conf` with `map $esmien_sub_token $esmien_sub_title` (whitelist token → `Esmien VPN (LTE)`, everything else → `Esmien VPN`) plus a matching `$esmien_sub_fname` map, so downloads are named `esmien-vpn` / `esmien-vpn-lte`. A new token inherits its title from its `kind` file — never hard-code the title in the nginx template, and never let two subscriptions share a display name: the owner tells them apart by the suffix.

Rules: names are plain country names with flags (`🇪🇪 Эстония (General)`, `🇫🇷 Франция (Gemini)`, `🛠 Тест (Develop)`); the brand lives only in the group/profile title. "No clutter" means no junk nodes and no invented groups — it does **not** cap the node list: the owner explicitly ordered every usable upstream node relayed in, so the relay pool ships as **one subscription** on its own token. The whitelist entries are a **second, separate subscription**, not a second group: the owner prefers a separate link for them. `make_sub.py` branches on a `kind` file inside the token dir — a dir whose `kind` reads `whitelist` gets a whitelist-only bundle (`make_sub.py --new-whitelist` creates one) — and the main bundle carries the relayed routes only. Never add a third group or a node class he did not ask for.

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

## Per-user keys

Per-person access means each person gets their own UUID and own token; the legacy global key stays in place so already-issued links never break. `/root/vpn-router/users.py` owns it: `add <name>` injects a client into **every** vless inbound (all 24 — a user's bundle ships `/p<i>` nodes too), creates `/var/www/esmien-sub/<token>/{user,title}`, re-renders all bundles and applies. `users.json` (0600, gitignored) is the source of truth; `make_sub.py` picks a token dir's key from its `user` file, so a bundle can no longer carry a key that is not its own.

Roll it out **additively**: no credential swap, no re-import for existing clients. Snapshot `/var/www/esmien-sub/*/*` with `md5sum` first, prove the legacy bundles are byte-identical afterwards, then probe each key through each route. Full procedure, verification matrix, quota/device-limit reality: `references/per-user-keys.md`.

Rule: any script that builds inbounds (`import_sub.py`) must re-apply `users.json` before writing the config — otherwise new paths authenticate only the legacy UUID and a user's subscription lists nodes that refuse his key.

## Per-user keys (pairs: main + LTE)

`users.json` (0600, gitignored) is the source of truth: `name → {uuid, token, token_lte, title}`. `users.py add <имя>` injects that UUID as a client into **every** vless inbound (`email = "<tag>:<имя>"`), creates two token dirs — main (files `user` + `title`) and LTE (`kind=whitelist`) — then re-renders subs, rewrites the title map, reloads nginx and runs `vpn-cfg apply`. `users.py rm <имя>` drops the clients and **parks** both dirs under `/var/www/esmien-sub/.disabled/<token>.<имя>`; `users.py sync` re-applies users.json after a pool rebuild (`import_sub.py` also calls it).

Rules that make it hold:

- The legacy global UUID is registered as its owner's key (`add … --uuid <legacy> --token <existing> --lte-token <existing>`), never duplicated as a second client in the same inbound: `apply_users` skips a user whose UUID is already present. Two clients with one id in one inbound pass `xray -test` but split stats and are pointless.
- `make_sub.py` picks the UUID per token dir: a dir with a `user` file uses that person's key, without one it falls back to `/root/mtproto-faketls/ws-client-uuid`. Adding a per-user key therefore leaves every already-issued bundle byte-identical — verify with `md5sum -c` before/after rather than by eye.
- `profile-title`/filename come from the dir's `title` file and its `kind`; the `(LTE)` filename is decided by `kind`, not by the title string, or an LTE name would download as `esmien-vpn`. Titles must stay distinct **and differ early**: the LTE bundle is `Esmien VPN LTE (Имя)`, never `Esmien VPN (Имя, LTE)` — clients truncate long profile names, and with LTE at the end both profiles look identical until expanded. `users.py retitle` rewrites the existing `title` files in place when the scheme changes.
- The LTE bundle carries the provider's raw «глушилки» links, so its *content* is identical for everyone — separate tokens give separate links, not separate credentials. Say that before promising isolation.
- Rollback of a single person is `users.py rm`; a full rollback of the feature is `vpn-cfg rollback` plus deleting `user`/`title` files, since the legacy key never moved.
- The roster (who has which token, page URL, and the operations cheat-sheet) lives in `/root/vpn-router/users.md` (0600) — deliberately **outside git**: the owner does not want the people list and their tokens pushed, even to the private repo. Code goes to `Esmien/vpn-service`; `users.json`, `users.md`, `pages_index.json` and the generated subscriptions/pages stay on the host.

## Landing page per user (/u/)

Each person gets `https://<host>:8443/u/<token>` — a static, self-contained dark page (no external fonts/CDN/assets) that shows their **whole pair** as two cards and two buttons each:

- `happ://add/<sub-url>` → Happ, `incy://add/<sub-url>` → INCY. The sub URL carries no reserved characters, so it goes in **raw**; do not percent-encode (clients parse the tail as a URL).
- a copy-link chip as the fallback when the custom scheme does not open anything.

Generated by `/root/vpn-router/make_pages.py` from `users.json` into `/var/www/esmien-pages/<token>.html` (one file per token, both main and LTE, same content), plus `pages_index.json` (0600) mapping token → person. `users.py` renders the pages after every add/rm, and `apply_brand.py` runs it too, so a host move cannot leave stale links.

nginx: a second regex location in the `apply_brand.py` TEMPLATE (`^/u/(?<esmien_page_token>...)$` → `try_files /$esmien_page_token.html`) — it is generated, so never edit `/etc/nginx/conf.d/vpn-*.conf` by hand; edit the template and re-run `apply_brand.py`.

Design constraints learned the hard way: inline **SVG** icons, not emoji (a container without an emoji font renders tofu, and the look must not depend on the viewer's fonts); `flex: 1 1 0; min-width: 0` on the button row so the pair cannot overflow; keep every asset inline so the page works over a degraded link. Verify layout by measurement, not by eyeballing a screenshot: headless Chromium enforces a **500 px minimum window width**, so a `--window-size=390` screenshot is a *crop* of a 500 px render and looks falsely clipped — measure `document.documentElement.scrollWidth` against `innerWidth` inside a 390-px iframe harness instead.

## Applying changes without downtime (blue/green)

`vpn-cfg apply` never restarts the container that carries traffic. Two xray containers run side by side: `vpn-router` mounts `config.json` (the canonical file, always the **A** port block) and `vpn-router-b` mounts `config.b.json`, derived from it with every inbound port `+1000` (10081… → 11081…). `/root/vpn-router/vpn-color` holds the active color, and `apply_brand.py` adds the offset when rendering nginx upstreams — so a flip is `nginx -t` + graceful `reload`, nothing more.

`apply` sequence (`/root/vpn-router/vpn-bluegreen.py apply`): lint → `xray -test` on both variants → restart **only the idle color** → poll `http://127.0.0.1:<port><path>` on every inbound of the idle color until all answer `400` → flip → re-probe through nginx, reverting the color file automatically if anything fails. Established sockets stay on the drained container (it keeps running), so a change is invisible to connected clients; the drained one is refreshed at the next apply, when it is the idle target again. `vpn-cfg switch [a|b]` flips traffic without touching a config; `vpn-bluegreen.py status` shows both colors, ports and inbound counts.

Rules that make it safe:

- **`xray -test` does not catch a routing rule pointing at a non-existent `outboundTag`** — it validates and then silently drops that traffic. `vpn-bluegreen.py lint()` is the gate: dangling `outboundTag`/`inboundTag`/`balancerTag`, duplicate tags, duplicate or out-of-range ports, an inbound with no clients, and any `listen` that is not loopback (that last one is the "published raw VLESS" mistake caught at apply time). Keep the lint growing instead of trusting `-test`.
- A 24-inbound config means 24 direct probes per apply; poll, do not `sleep 6` and hope. A container that answers on 23 of 24 has a broken inbound and must never get the traffic.
- `docker run` for either color needs `--user 0:0`: configs are 0600 and the image runs non-root, so the container dies with `open /etc/xray/config.json: permission denied` and `restart unless-stopped` turns it into a restart loop.
- Never edit `/etc/nginx/conf.d/vpn-*.conf` after a flip — they are generated from `brand.json` plus the color file; edit the template in `apply_brand.py` and re-run it.
- Cost is one extra container of ~12 MB RAM; both are `restart unless-stopped`, so a host reboot brings both back and nginx follows `vpn-color`. This protects against *config work*, not against host death — that still needs a second machine.
- `import_sub.py` writes new inbounds with A-block ports into `config.json`; B is derived, so a pool rebuild needs no extra bookkeeping. `users.py` edits the same canonical file.

**Proving zero downtime** (the only honest test): start a big download through the tunnel with `--limit-rate` to hold it open ~30 s, run `curl` probe rounds against `/u/<token>` and `/sub/<token>` in a loop, then `vpn-cfg apply` in the middle. Expect the download to finish with the exact byte count, 0 failed probe rounds, and a color change. Measured here: 100 MB intact, 32/32 rounds, ~4 s wall clock.

## Subscription expiry

The provider's expiry is in the `subscription-userinfo` response header of any subscription URL — `upload=…; download=…; total=…; expire=<unix>`, with `expire=0` meaning no limit. Read it from there; the biller bot and the panel page phrase it differently and go stale.

`/root/vpn-router/sub_expiry.py` reads `/root/vpn-router/subs.json` (0600, name + url pairs, never committed) and `vpn-sub-expiry.timer` runs it daily at 07:00 UTC (10:00 MSK) to message the owner at 3, 2 and 1 days before each expiry, plus once if a subscription has already lapsed. Dedup state is `sub_expiry_state.json`, keyed `<date>:<days left>`, so a second run on the same day stays silent; `--test` proves delivery, `--force` sends the report outside the schedule. A new subscription is one more line in `subs.json` — the script needs no edit.

## Certificates

`qd.je` is treated by Let's Encrypt as **one registered domain**, so all its subdomains share the 50-certs-per-168h bucket and issuance regularly fails with `retry after <timestamp>`.

- `certbot_retry.py <host>` parses that hint, sleeps until `retry_after + 3–4s`, re-parses any newer hint, gives up only after 24 h. Log: `/var/log/certbot-retry.log`.
- `provision_vpn_host.py <host>` wraps it and on success rewrites `brand.json`, rebuilds nginx + subscriptions, reloads, verifies.
- Its final verification can print `000` if curl lands inside the reload window — re-check manually before believing the switch failed.
- `qd.je` is a **free subdomain under someone else's registry**, and that is the deeper problem: its DNS is one provider's goodwill. Any name the entry depends on needs authoritative servers that actually answer — measure them (`dig` per NS, 5 tries each) before trusting a provider, and prefer an owned domain whose NS point at a large DNS host. Cheap registrars are fine for this (RU cards work, NS are editable); avoid giveaway TLDs that anti-spam filters already treat as hostile.
- Wildcard `*.esmien.ru` is issued with **DNS-01 through the Cloudflare API** — one certificate `esmien-wildcard` covers `*.esmien.ru` plus the apex, so a new service needs no certbot run at all, only an A record and a server block. Token lives in `/root/.secrets/cf.ini` (0600, scope `Zone:DNS:Edit`), plugin is `python3-certbot-dns-cloudflare`, renewal hook reloads nginx. Full command, verification matrix, API-side subdomain creation and the "name stopped resolving" triage: `references/domain-and-tls.md`.

## Upstream subscriptions (relaying nodes)

Two pools, never mixed:

- **relay pool** — every usable upstream node becomes an inbound `/p<i>` (10100+i) on our host plus an outbound `p<i>`; clients reach it through us.
- **whitelist pool** — only the nodes the provider itself labels **«Глушилки»** are exported as raw upstream links (`whitelist_links.json`, 0600) into a **separate subscription of their own**, because under address allowlists our foreign entry is the first thing that gets cut. Classify by the provider's own label, never by geography: `Москва / СПб / Новосиб` nodes are ordinary RU-exit relays and belong in the relay pool, and a plan may contain no «Глушилки» at all (the PC plan has none, the mobile one has ten) — merge the pools only after the owner confirms which nodes he means.

Pitfall: Xray evaluates routing top-down. Inbound rules appended at the end land **after** the catch-all `network: tcp,udp → <default>` and are silently ignored — every relayed path then exits through the default outbound. Keep inbound-tag rules right after the block rules, before domain/ip/catch-all rules, and re-check one or two relayed paths against `ipinfo` after every import.

`import_sub.py` builds the whole relay set idempotently; `probe_sub.py` measures each node (exit IP + Google country) before it goes into the pool. Hysteria2 nodes are unusable — the Xray core does not speak it.

## RU split (banks / gosuslugi / VK / OZON / WB)

The owner's complaint is the VPN on-off toggle: he wants RU services to answer from a Russian address no matter which node is selected. Two layers, both idempotent:

- **Client** — `make_sub.py` renders, after the google rules and before `MATCH`, the `RU_DOMAINS` list then `DOMAIN-SUFFIX,ru` / `DOMAIN-SUFFIX,su` / `GEOIP,RU` → the Moscow node (name resolved by `ru_node()` from `relay_nodes.json`, it carries two U+200B after the flag). Clash/Mihomo only — Happ ignores rules from a subscription.
- **Server** — `/root/vpn-router/route_ru.py` inserts `domain: ru/su/рф + vk.com, vk.me, vk-cdn.net, userapi.com, mycdn.me, max.ru, ozon.com, wbstatic.net …` → outbound `p15` (the Moscow relay) at `index of the first fr-domain rule + 1`, i.e. **before** every `inboundTag` rule. That is what makes it hold for any selected node, the same shape as the Gemini rule. Re-run it after `import_sub.py` on a rebuild — `make_template.py` drops the rule on purpose (it points at a relay outbound that does not exist in a fresh template, and an unknown outbound makes `xray -test` fail).

Verify by behaviour, not by config: gosuslugi.ru answers `000` from the Estonian and from a foreign exit, `200` through `/general` *and* through `/ws` after the change, while `ipinfo.io/ip` on those same inbounds still returns the untouched exit (no blanket hijack). WB is the best exit proof: `www.wildberries.ru` answers `498` (its own fingerprint challenge — the same `498` comes straight from Estonia) and the body carries `data-req-ip="<node ip>"`. `card.wb.ru` returns `403` from every exit, that is WB, not routing. Sber serves a self-signed cert in the chain to curl on any exit — `http://` answers `200`, browsers with the RU trusted roots are fine.

Pitfall: `xray run -test -c config.json` on the **host** fails with `failed to open geoip.dat` — the host binary has no geo files. Validate with the image instead: `docker run --rm --user 0:0 --entrypoint /usr/local/bin/xray -v /root/vpn-router/config.json:/etc/xray/config.json:ro ghcr.io/xtls/xray-core:latest run -test -c /etc/xray/config.json` (the `--user 0:0` is required, the config is 0600 and the image runs non-root; the runtime container has no shell at all, so `docker exec … sh` is not an option).

## Gemini / geo

Gemini's country is Google's own lookup of the **connection IP** — not the hoster's brand, not DNS, not the city in ipinfo. Measure with `scripts/gemini_geo_check.py [socks5-host:port]`; `fr`/`fi`/`de` work, `ru` is the stub. Our own Tallinn IP reads `ru` because Google follows the address registration, not the machine's location; a reseller's Paris IP can read `ru` for the same reason. "Smart DNS" cannot move the verdict — the verdict follows the IP that carries the flow, so route Google domains *and* IP ranges through the good exit with `sniffing` on. IPv6 is the only leak that flips it; this host has none and the generated profiles set `ipv6: false`, so look at the client, not the server. Full evidence, whois reasoning and exit-buying rules: `references/gemini-geo.md`.

Client rules are not a guarantee — only Clash-family subscribers receive them, and Happ gets none, so a verdict that must hold in every app has to be enforced **on the server**. Xray evaluates top-down: a `domain:… → fr` rule placed *after* the `inboundTag` rules never fires, because every request from those inbounds already left through its own outbound. Put the Google rule first, right after the block rules.

**Route the whole Google *web* chain, not just `gemini.google.com`.** Google decides the country per connection, and the Gemini page is reached through `www.google.com` → `accounts.google.com` → `gstatic.com` before a single byte of the app loads. A rule that covers only `gemini.*` lets those hops out through the default exit, Google reads our Tallinn address as `ru`, and the app answers "not available in your country" even though the Gemini request itself went through France. Cover `domain:google.com` (matches every subdomain), `googleapis.com`, `gstatic.com`, `googleusercontent.com`, `google.dev`, `withgoogle.com` and keep `googlevideo.com`/`youtube.com` **out** — video stays on the selected node instead of crawling through the borrowed exit. Same trap in any "only the obvious domain" list: enumerate the sign-in and static-asset hosts too.

**Prove the server-side rule in two cheap steps, not by reading the config.** (1) Matching: temporarily repoint the rule to `blocked`, `vpn-cfg apply`, wait for the container start time to move, then dial the affected domains through the ordinary `/general` inbound — they must fail while an unrelated site still answers; restore afterwards. (2) Exit: add a throwaway `domain:<canary>` rule → the same outbound (an `ipinfo.io` canary is enough), request it through `/general` and read the egress — it must be the borrowed exit, not our address. Delete the canary, apply, and re-run one real request (`curl gemini.google.com/app` through the tunnel should return the app shell with no "not available in your country" string). Xray does **not** log which outbound a connection took, so raising `loglevel` to `debug` and grepping the container log is a dead end — the blocked/canary pair above is the only cheap evidence. A page that returns `200` proves nothing on its own: the geo refusal is in the body, and the login chain is what usually breaks.

## Whitelist mode (RU entry)

A whitelist is enforced on the **first hop**: the client must be able to reach the address it dials. So a chain whose first hop is this Estonian server is worthless in whitelist mode — traffic dies before it ever reaches the RU entry behind it, no matter how good that entry is. Two shapes actually work:

- the client dials the RU entry **directly** (loses the brand, the subscription and the per-tunnel control; every user then sits on the provider's single key);
- our own entry lives on a **Russian VPS** (Selectel, Timeweb, Rostelecom), and the foreign exit sits behind it — brand and control survive, at the price of one more node.

A Russian hosting IP is not automatically whitelisted either: lists cover specific service ranges, not "anything in RU". Only a real shutdown proves it; before that, say plainly that the path is unverified.

Whatever shape is chosen, the whitelist node must already be **installed in the client before restrictions hit**: the subscription is served from this host, so during a shutdown nobody can fetch or update it. Hand the family its own whitelist subscription (separate token, see Subscription) while the network is open, give the backup nodes plain names, and state that switching is manual — no client detects a whitelist and fails over by itself.

Before answering «does the whitelist expose us», count our own addresses in it: the exported list should contain **zero** `@<our entry host>` entries — those links point at the provider, and the only contact with us is the subscription URL. Say that as a number («0 из 9 узлов ведут на нас»), then state the real exposure: one shared provider key across every device.

**The raw «глушилки» links are the one thing not to hand out.** In whitelist mode the client dials the provider's node directly, so every phone is a separate simultaneous IP on one key — exactly the signature that gets a one-device plan flagged and killed. Normal traffic can fan out to any number of people through our entry (the provider then sees a single server IP); the provider's own links stay on the owner's device and on this server. If several people genuinely need whitelist-mode access, that is N provider subscriptions, not one shared link — say the price before wiring anything. When the family dials the provider directly, use **two separate subscriptions**: one for the server's exit, one for the family, otherwise the duplicate-IP signature the whole split was meant to remove comes straight back. Cost-wise that is ~2× the plan price and still cheaper than a second owned node.

## Client devices — always-on Linux desktop

The GNOME «Добавить VPN» dialog offers only OpenVPN / PPTP / WireGuard; our entry is VLESS over WS+TLS, so none of them apply and there is nothing to tick there. Do not answer that by adding a WireGuard/OpenVPN inbound to the server either — a new public surface with its own auth and none of the routing rules.

When the owner says he does not want to keep a client window open, the shape is a **daemon in TUN mode**, not a GUI app (Hiddify/v2rayA need the window; a local proxy on `127.0.0.1` only reaches apps that honour a system proxy). mihomo over the `clash.yaml` subscription is the cheapest base: that profile is already a complete config, so only a `tun:` block plus `dns.listen` get injected and can be re-injected on every refresh. Full recipe, systemd units, verification and pitfalls: `references/linux-always-on-client.md`.

## Failover — off, deliberately

The owner removed automatic failover: `vpn-failover.timer` is `disabled`/`inactive` and the default route is pinned to `fr`. Do not re-enable it without an explicit request. Rationale: a silent flip to `direct` keeps the internet alive but leaves geo-gated services refusing in a way that looks like the tunnel works ("connected, but Gemini says no"), which is harder to diagnose than a dead tunnel. With the timer off an exit outage kills `/france`, `/ws` and everything on the default route loudly; `/general` and `/test` stay on `direct` and are unaffected.

`failover.py` and the unit files stay on disk and in the repo, unwired — re-enabling is `systemctl enable --now vpn-failover.timer`. If a probe is ever restored, keep the cadence irregular (`RandomizedDelaySec=300` on a 15-minute timer) so it does not read as a bot, and test the logic on a copy of the config, never against the live probe host.

## Borrowed exit (third-party subscription)

An exit lifted from someone's paid plan is a shared credential, not a free tunnel: provider panels count **unique IPs**, not devices, so this server shows up as one more client beside the owner's phone. The owner's plan is **unlimited** — the `720 GB / ∞` on the card is traffic *spent*, not a quota — so volume is not what gets you banned; concurrency and datacenter origin are. Symptoms still worth knowing: the phone and the server knocking each other offline, or the account flagged for sharing.

A subscription bought **for the server alone** removes the duplicate-client signature (one key, one IP, exactly what the plan expects) and cuts the ban risk a lot, but not to zero: the provider still sees a datacenter origin, and transit/resale is usually forbidden in the terms. Keep a dedicated subscription off the phone and treat it as a layer under an owned VPS, not a replacement.

These sellers are typically **resellers** (arbitrage): one key, but exits on unrelated ASNs (AEZA Paris, PLAY2GO Helsinki). That explains both why they are cheap and why they cannot fix IP reputation — they rent someone else's subnets. Practical consequence: the exit behind a node can change without notice, so re-run the geo checker before blaming our side when Gemini breaks.

### Turning a plan into a pool

Panels built on Remnawave serve a decoy to clients they do not recognise: two vless nodes named `Данное приложение не обновлено` / `или не поддерживается`, both on `0.0.0.0:1`. A browser UA, `v2rayNG/…` or `ClashMeta/…` all get that decoy. What works is a supported app UA **plus** a hardware-id header:

    curl -sS -A 'v2rayTun/4.7.0' -H 'x-hwid: <any hex>' '<sub-url>' -o sub.b64

`Happ/2.11.0` with the same header returns the profile as a JSON Xray config instead. Pad before decoding (`base64 -d` wants `len % 4 == 0`), then parse one link per line.

A second decoy means a different problem: a list of nodes named `Превышен лимит устройств` / `@VPNUI_bot` / `Сбросить лимит устройств` is the panel's device-limit page, not a parsing failure — the server's IP became one client too many. Either ask the owner to reset the limit in the provider bot, or skip the subscription entirely and have him export the node link from the phone app (cheaper — a reset gets consumed again on the next refresh).

**Credentials are per plan, not per protocol.** Inside one plan every vless node shares a single UUID and every trojan node a single password, so one key opens the whole plan. Across two plans (PC vs mobile) they differ, and a node will not answer to the other plan's key: swapping the credential and retrying is the fastest way to tell "node dead" from "wrong key". `scripts/test_whitelist.py <sub> <other-sub> <indices> [--mobile]` does exactly that — builds each node with one plan's credential, then with the other's if the first run is silent.

Handing a family subscription the *mobile* plan's keys exposes that plan: one leaked link grants every node. Say so before wiring it in.

**Labels lie — probe every node.** On one 24-node plan every node carried a country flag and a friendly name, yet only 2 gave Google a supported country: the German, Swedish, Polish, US, Albanian and Austrian exits all answered `ru`. A reseller registers its whole address space the same way, so the flag describes the sale, not the geo. Run `scripts/probe_sub.py <sub-file> [indices]` — it builds an Xray client config per link, runs each one with the host binary (`/usr/local/bin/xray`; no container involved), and prints exit IP + Google country — then route only the accepted nodes.

Two node kinds are unusable here: `hysteria2` links (Xray core has no such protocol) and nodes whose page yields `com` instead of a country code (Google could not place the address — not a supported verdict). Nodes that return 0 bytes are dead; treat them as absent rather than as blocked.

## Desktop client, always-on (no GUI app)

When a machine must be tunnelled with nothing open and no GNOME VPN profile (that dialog only knows OpenVPN/PPTP/WireGuard), run mihomo as a systemd daemon in TUN mode. Full recipe, merge script shape and the FlClash/`add route 0: file exists` trap: `references/desktop-mihomo-tun.md`.

## Actual routing model — state it before measuring anything

The owner's model (correct him at your peril): **`fr` and `fi` exist ONLY for Gemini.** Nothing else
is meant to exit through them. Everyday/chore traffic rides the Finland entry, RU traffic rides his own
RU server. Measured in `config.json`: `bal-google` = `leastPing` over `fr`, `bal-ru` = `leastPing` over
`direct`, `direct` is plain `freedom` (our Estonian IP), and the catch-all `network: tcp,udp` rule
points at **`fr`**. Two consequences to check before answering "what goes where":

- the catch-all is what makes a `/ws` client exit via Paris for anything that is neither Google nor RU
  — if the intent is Finland, that is a routing bug, not a client problem;
- `ru1` (the owned RU VPS, `217.197.114.197`) exists as an outbound but **no rule references it**, so
  "RU goes through my RU server" is not what the live config does (`bal-ru` → `direct`). Print the rule
  table (`routing.rules`, tags only) instead of repeating either the skill or the owner's wording.

When the owner complains that "everything on the VPN got slow", the shape of the answer is: server
uplink vs exit uplink vs his local link, each measured. Uplink here is gigabit (a 50 MB pull from the
host hits ~170 MB/s), while a borrowed exit gives ~10–17 MB/s per stream and is **shared with the
reseller's other clients** — so a few people on YouTube through one exit is a plausible cause and a
saturated host link is not. `vnstat` (installed, monitoring `ens3` only) starts giving per-hour history;
there is no data for anything before its install date.

## Pitfalls

- **Never dump an outbound as JSON.** Trojan credentials live in `settings.servers[].password`, VLESS in
  `settings.vnext[].users[].id` — a "show me the outbound" print leaks the provider's shared keys and a
  client UUID straight into the chat. Print tag, protocol, address:port and stream network only, and
  mask anything whose key matches `pw|password|id|key|token`.
- The hostname is part of the entry: a flaky free DNS provider (authoritatives answering 1–2 of 5 queries) makes validating resolvers return `SERVFAIL` for every client while browsers keep working from cache — the app then shows all nodes `n/a` and nothing ever reaches the server. Diagnose with `dig` across several resolvers plus a random uncached name, mitigate with IP-address node duplicates and an HTTP-by-IP subscription, and fix the delegation — do not rebuild the tunnel.
- `check-host.net` verdicts must be read by the shape of the result, not its presence: a failed node returns `[{"error": "Connection timed out"}]`, a successful one `[{"address": …, "time": …}]`. Counting any non-null first element as reachable reports a closed port as open — require `isinstance(r[0], dict) and "time" in r[0]` before drawing conclusions about exposure.
- The owner floats ideas in passing («выбросим эту Эстонию в помойку», «а если хостинг американский», «ничего не делаем, я образно») — that is thinking aloud, not a work order. Answer the technical question with the trade-off, then wait for an explicit «делай». Do not start a migration, buy a node or rewrite a pool off a hypothetical; he pushes back hard on unrequested initiative.
- An exit probed with one request tells you nothing about its capacity: a node that accepts the first connection and refuses every following one answers a single `curl` in 0.5 s and still kills a real page load. Fire a burst of ~20 parallel requests at a real asset and compare against a known-good exit **in the same run** — measured here, `/p15` (Moscow) gave 20/20 timeouts at exactly 6 s while `fr` answered 20/20 in 0.5 s, and the same node answered 20/20 a few minutes later, so a single bad round means "degraded now", not "dead". To probe any outbound without its credentials, copy that outbound **verbatim** out of `/root/vpn-router/config.json` into a socks-only client config (never print the UUID), run `/usr/local/bin/xray run -c <cfg>`, and kill by PID. Leaked UUIDs are a real cost of this recipe: build the config in a script that reads `config.json`, never paste the outbound into a terminal command.
- A user's "the site is down" on one host is rarely the tunnel: check whether the requests reached the app at all before rebuilding anything (`references/client-drop-triage.md`, section 4d).
- Probes need no container: `/usr/local/bin/xray run -c <cfg>` in the background (`& pid=$!`) plus `gemini_geo_check.py 127.0.0.1:<socks port>` is the whole recipe. If the binary ever disappears, `docker cp vpn-router:/usr/local/bin/xray` style copy out of a running xray container beats downloading a build.
- A per-node probe must kill by PID (`… & pid=$!` … `kill $pid`). `pkill -f <cfg>.json` matches the shell that runs the loop itself and the probe stops after the first node; the same trap kills the calling shell when the pattern text appears in its own command line (`pkill -f "tcpdump -i ens3"`), so kill by the PID you started.
- Before trusting any measurement through a locally started client, confirm nothing older still holds the socks port (`pkill -f "xray run -c /tmp/cli"; pgrep -af "xray run"`). A second client that fails to bind dies silently while the first one keeps answering, so the route you just configured gets judged by the previous config — the tell is an exit IP belonging to a different route.
- After `vpn-cfg apply`, confirm the container actually restarted (`docker inspect vpn-router --format '{{.State.StartedAt}}'`) before judging a routing change. The restart is asynchronous, so a probe fired seconds later can still talk to the *previous* config: a rule temporarily switched to `blocked` answered `200` and looked unmatched, while the same test after the restart failed as it should. Same reason a "change did nothing" report is worthless until the start time moved.
- `vpn-cfg` carries its own copy of the public host (`HOST=` in `/usr/local/bin/vpn-cfg`). When the entry moves to a new name, update it in the same pass as `brand.json`: otherwise `apply` probes the dead host, TLS verification fails, the probes return `000` and the script silently rolls back to the newest backup — which can be days old and drop whatever was added since. Read the rollback line, not just "применено".
- "VPN keeps dropping" is a triage with numbers, never a guess: a container with `restarts=0`, a 20 MB pull through our own entry at full speed, and `generate_204` returning 204 prove our side is fine, and the reconnect-storm count (`101` per minute per IP vs. established sockets) then points at the device's own link. Report the measurements; do not start rebuilding the entry. Reconnect storms alone prove nothing until you read session lifetimes (`rt=$request_time` on the vhost): a few seconds per session with the same few KB transferred can be a path-MTU blackhole, worth a reversible MSS clamp on 8443/2087 — but a positive MSS result does not mean you are done, keep checking resolution and the exit separately.
- Writing nginx config through `printf`/heredoc mangles quotes and backslashes (`\"$request\"`, `\\S`), and `nginx -t` then fails on a file that looks fine on screen. Write generated snippets with Python `write_text` (staging under `/tmp` + `install -m 644` when a direct write to `/etc/nginx` is refused), test, then reload — the same trap bites fail2ban filter regexes. Same reason a python heredoc embedded in a compound `cmd1 && python3 - <<EOF` block can silently produce a truncated file (16 bytes, no error): put the generator in its own file and run it.
- Node names in `relay_nodes.json` carry **zero-width spaces** (the RU flag label has `\u200b\u200b` before `Москва`). Never hard-code such a name into a generated rule: resolve it from the pool by normalized match (`if "Москва" in n["name"].replace("\u200b", "")`) and interpolate the real string. A hardcoded variant compiles fine and ships a rule pointing at a proxy that does not exist — Clash then drops matched traffic to the group/default and the split silently does nothing.
- The host python has no `pyyaml`. Validate a generated profile in a throwaway venv (`python3 -m venv <scratch>/vy && <scratch>/vy/bin/pip -q install pyyaml`), and check that every rule target appears in `proxies`/`proxy-groups` and that the block sits before `MATCH` — parsing the file back proves the YAML, not the routing, but a dangling target is exactly the failure mode above. `IP-CIDR,…,DIRECT,no-resolve` splits into five comma fields, so do not flag it as a dangling target.
- `git push` in `/root/vpn-service` has no stored credentials; the host token is `GITHUB_KEY` in `/home/ai_service/ai-stack/ai/.env`, fed through a `GIT_ASKPASS` script that answers `x-access-token` (the same pattern `vps-infra-push.sh` uses). Without it the push dies with `could not read Username for 'https://github.com'` — wire the askpass on the first failure, in the same pass, and never surface the token to the owner: piping the value straight from `.env` into the askpass script is allowed, echoing it anywhere is not.
- `docker stats` reports `0B` for `vpn-router` because it runs on the host network — do not read that as "no traffic".
- `docker run -p 127.0.0.1:PORT` does not expose extra inbounds: use `--network host` (with `--user 0:0` so the 0600 config is readable).
- Keep every inbound bound to 127.0.0.1; an inbound on `0.0.0.0` publishes raw VLESS to the internet.
- Cloudflare WARP is unusable from this host: UDP 2408 and 1.1.1.1:53 get no reply (8.8.8.8 works). Do not build routing on WARP here.
- An external exit is a black box: its public hostname resolves to a front IP that may sit on a different ASN and different /24 than the subnet that actually egresses. Never infer the verdict from the resolved IP — force Google to answer from the exit: `curl --socks5-hostname <exit> 'https://dns.google/resolve?name=o-o.myaddr.l.google.com&type=TXT'` and read the `edns0-client-subnet` line. The hostname can also rotate between addresses, which silently changes the Gemini verdict.
- Canonical source is the private repo `Esmien/vpn-service`; `Esmien/vps-infra/assets/vpn/` is a leftover copy that is no longer updated — editing it changes nothing live. Push only credential-free files: `config.json` (UUID), `subs.json` and `whitelist_links.json` are gitignored, and no repo (public or private) should ever receive exit passwords or client UUIDs.
- After a push, `raw.githubusercontent.com` keeps serving the previous copy for minutes — a stale read is not a failed push. Confirm through the API instead: `curl -s 'https://api.github.com/repos/<owner>/<repo>/contents/<path>?ref=main'` and base64-decode `content`.
