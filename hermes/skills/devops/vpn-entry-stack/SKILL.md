---
name: vpn-entry-stack
description: Use when editing the VPN entry, routes or subscriptions.
---

# VPN entry stack (VLESS over WebSocket + TLS)

The owner's home ISP (MTS, Novorossiysk) drops **port 443** and kills **fake-TLS/MTProto** to this server's IP. What works is a *real* TLS handshake on a non-standard port. That single fact drives the whole design — verify it before debugging anything else.

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
- `/panel/` — 3x-ui admin UI behind nginx; recipe, CSRF login check and credential rotation in `references/xui-panel.md`.

There is deliberately **no** RU-entry inbound: an earlier `/lte` route (`1.fan-video.study` → Selectel SPb → Helsinki, Google saw it as `ru`) was removed once it was clear the whitelist first hop has to be dialled by the client itself, never by this server. Whitelist entries ship as direct client links only — see Whitelist mode.

Upstreams: 10081 `/ws`, 10082 `/general`, 10083 `/france`, 10084 `/test`, 10086 `/fi`, 10100+i for the relayed `/p<i>` nodes, and 2053 for `/panel/` — all bound to 127.0.0.1.

Adding a route means four coordinated edits, in this order: append an inbound (`tag`, 127.0.0.1, next free port, same client id, `wsSettings.path`) to `config.json`, add the outbound and a routing rule keyed on `inboundTag` **before** the catch-all `tcp,udp → fr` rule, add `paths` + `upstreams` entries to `brand.json`, then `apply_brand.py && nginx -t && systemctl reload nginx && docker restart vpn-router`. Verify by dialling the new path through the tunnel and checking the egress with ipinfo — not by reading the config back.

Files: `/root/vpn-router/{config.json,brand.json,apply_brand.py,make_sub.py,failover.py,certbot_retry.py,provision_vpn_host.py,gemini_geo_check.py,probe_sub.py}`, subscriptions in `/var/www/esmien-sub/<token>/`.

## Changing the public host

Never hand-edit the nginx confs — they are generated:

1. edit `host` + `cert_dir` in `/root/vpn-router/brand.json`
2. `python3 /root/vpn-router/apply_brand.py`
3. `nginx -t && systemctl reload nginx`

`apply_brand.py` also emits `vpn-compat.conf` for every entry in `legacy_hosts`, each with its own certificate. That is what makes a host switch invisible to users: old subscriptions and links keep working, no re-import needed. Keep old hosts in `legacy_hosts` while their certs auto-renew.

## Subscription

`make_sub.py` renders three formats; nginx picks one by User-Agent (`00-esmien-sub-map.conf`): Clash/Mihomo → `clash.yaml`, sing-box → `singbox.json`, everything else → base64 `list.txt`. The response carries `profile-title: Esmien VPN` and `profile-update-interval: 12`.

Rules: names are plain country names with flags (`🇪🇪 Эстония (General)`, `🇫🇷 Франция (Gemini)`, `🛠 Тест (Develop)`); the brand lives only in the group/profile title. "No clutter" means no junk nodes and no invented groups — it does **not** cap the node list: the owner explicitly ordered every usable upstream node relayed in, so the relay pool ships as **one subscription** on its own token. The whitelist entries are a **second, separate subscription**, not a second group: the owner prefers a separate link for them. `make_sub.py` branches on a `kind` file inside the token dir — a dir whose `kind` reads `whitelist` gets a whitelist-only bundle (`make_sub.py --new-whitelist` creates one) — and the main bundle carries the relayed routes only. Never add a third group or a node class he did not ask for.

URL shape: `https://<host>:8443/sub/<token>`. The port must be in the URL: plain 443 is blocked for the owner's ISP.

## Certificates

`qd.je` is treated by Let's Encrypt as **one registered domain**, so all its subdomains share the 50-certs-per-168h bucket and issuance regularly fails with `retry after <timestamp>`.

- `certbot_retry.py <host>` parses that hint, sleeps until `retry_after + 3–4s`, re-parses any newer hint, gives up only after 24 h. Log: `/var/log/certbot-retry.log`.
- `provision_vpn_host.py <host>` wraps it and on success rewrites `brand.json`, rebuilds nginx + subscriptions, reloads, verifies.
- Its final verification can print `000` if curl lands inside the reload window — re-check manually before believing the switch failed.
- Wildcard `*.esmien.qd.je` needs DNS-01. DigitalPlat (DNS host, `dns1/dns2.digitalplat.org`) has no publicly reachable API (403/404 on guessed endpoints, paths built dynamically in panel JS), so automation needs either a dashboard token plus its docs or moving the zone to a DNS provider with an open API (deSEC).

## Upstream subscriptions (relaying nodes)

Two pools, never mixed:

- **relay pool** — every usable upstream node becomes an inbound `/p<i>` (10100+i) on our host plus an outbound `p<i>`; clients reach it through us.
- **whitelist pool** — only the nodes the provider itself labels **«Глушилки»** are exported as raw upstream links (`whitelist_links.json`, 0600) into a **separate subscription of their own**, because under address allowlists our foreign entry is the first thing that gets cut. Classify by the provider's own label, never by geography: `Москва / СПб / Новосиб` nodes are ordinary RU-exit relays and belong in the relay pool, and a plan may contain no «Глушилки» at all (the PC plan has none, the mobile one has ten) — merge the pools only after the owner confirms which nodes he means.

Pitfall: Xray evaluates routing top-down. Inbound rules appended at the end land **after** the catch-all `network: tcp,udp → <default>` and are silently ignored — every relayed path then exits through the default outbound. Keep inbound-tag rules right after the block rules, before domain/ip/catch-all rules, and re-check one or two relayed paths against `ipinfo` after every import.

`import_sub.py` builds the whole relay set idempotently; `probe_sub.py` measures each node (exit IP + Google country) before it goes into the pool. Hysteria2 nodes are unusable — the Xray core does not speak it.

## Gemini / geo

Gemini's country is Google's own lookup of the **connection IP**, not the country of a hoster's brand, not DNS, and not the city in ipinfo. Measure it, never guess — run `scripts/gemini_geo_check.py` (packaged with this skill, deployed at `/root/vpn-router/gemini_geo_check.py`):

    python3 gemini_geo_check.py [socks5-host:port]

The Gemini web template embeds Google's verdict in `this.gbar_={CONFIG:[[[0,"www.gstatic.com","<build>","<cc>","<lang>"` — that two-letter `<cc>` is the country Google assigns to the exit. Supported codes work, `ru`/`by`/`ir`/... show the stub. Confirmed cases on this host:

- `138.124.58.x` (AEZA, Paris) → `fr` → works.
- `77.221.152.x` (AEZA, Paris) → `ru` → stub. Same city, same ASN — the /24 differs.
- Our own `141.98.166.213` (Tallinn) → `ru` → stub, even though the IP geolocates to Estonia.

Why: Google's country follows the address *registration*, not the machine's location. Our block is `netname EE-HIP-…, country EE` but its RIPE org object is `Baykov Ilya Sergeevich, country RU, Moscow` — hence `ru` despite Tallinn. `77.221.152.x` is the same story (`Aeza-Network, FR` over `AEZA GROUP LLC, RU`), while the working `138.124.58.x` is a legacy `RIPE-ERX` block with no RU org. And `87.121.105.34` shows whois is not the whole answer either (whois SE, ipinfo FI, Google `ru`) — Google blends registries with geofeeds and observed traffic. So a Paris VPS can be "Russia" for Google, and a Tallinn VPS too. Buying an exit is a per-IP lottery: rent (hourly if possible), run the checker, keep only a supported code, otherwise destroy and try another provider/subnet. Two purchase-side rules follow from the whois evidence: prefer a provider whose RIPE/Aria org object is genuinely EU/US (a Russian org marks the whole block `ru` however the netname reads), and expect the big hosters (Hetzner, DigitalOcean, Vultr, OVH) to score badly because VPN resellers have burned their ranges for years — small hosters score better. Hetzner and Scaleway also refuse RU cards, so check payment before falling in love with a plan.

"Smart DNS" services that unblock Gemini work by proxying the flows through their own IPs — DNS is only how they capture and redirect the domains. Changing resolvers alone cannot move the verdict, because the verdict follows the connection IP. Verified through one good exit: default resolver, Yandex DoH (`77.88.8.8`) and Google DoH (`8.8.8.8`) all returned the same `fr`; the bad exit returned `ru` under every resolver.

Route Google domains *and* Google IP ranges through the FR exit and enable `sniffing`; a partial tunnel was not enough — the whole flow must leave through the good IP. IPv6 is the one leak that does flip the verdict, because Google then reads the real address past the tunnel: this host has **no global IPv6 at all** (no address, no default route, `curl -6` → `000`), the `direct` outbound is `UseIPv4`, and generated Clash profiles carry `ipv6: false` both top-level and in `dns` — so the stack itself cannot leak. The remaining vector is a client that bypasses the tunnel for v6; diagnose on the device with `test-ipv6.com` and switch IPv6 off in that client rather than hunting the server.

## Whitelist mode (RU entry)

A whitelist is enforced on the **first hop**: the client must be able to reach the address it dials. So a chain whose first hop is this Estonian server is worthless in whitelist mode — traffic dies before it ever reaches the RU entry behind it, no matter how good that entry is. Two shapes actually work:

- the client dials the RU entry **directly** (loses the brand, the subscription and the per-tunnel control; every user then sits on the provider's single key);
- our own entry lives on a **Russian VPS** (Selectel, Timeweb, Rostelecom), and the foreign exit sits behind it — brand and control survive, at the price of one more node.

A Russian hosting IP is not automatically whitelisted either: lists cover specific service ranges, not "anything in RU". Only a real shutdown proves it; before that, say plainly that the path is unverified.

Whatever shape is chosen, the whitelist node must already be **installed in the client before restrictions hit**: the subscription is served from this host, so during a shutdown nobody can fetch or update it. Hand the family its own whitelist subscription (separate token, see Subscription) while the network is open, give the backup nodes plain names, and state that switching is manual — no client detects a whitelist and fails over by itself. When the family dials the provider directly, use **two separate subscriptions**: one for the server's exit, one for the family, otherwise the duplicate-IP signature the whole split was meant to remove comes straight back. Cost-wise that is ~2× the plan price and still cheaper than a second owned node.

## Failover — off, deliberately

The owner removed automatic failover: `vpn-failover.timer` is `disabled`/`inactive` and the default route is pinned to `fr`. Do not re-enable it without an explicit request. Rationale: a silent flip to `direct` keeps the internet alive but leaves geo-gated services refusing in a way that looks like the tunnel works ("connected, but Gemini says no"), which is harder to diagnose than a dead tunnel. With the timer off an exit outage kills `/france`, `/ws` and everything on the default route loudly; `/general` and `/test` stay on `direct` and are unaffected.

`failover.py` and the unit files stay on disk and in the repo, unwired — re-enabling is `systemctl enable --now vpn-failover.timer`. If a probe is ever restored, keep the cadence irregular (`RandomizedDelaySec=300` on a 15-minute timer) so it does not read as a bot, and test the logic on a copy of the config, never against the live probe host.

## Borrowed exit (third-party subscription)

An exit lifted from someone's paid plan is a shared credential, not a free tunnel: provider panels count **unique IPs**, not devices, so this server shows up as one more client beside the owner's phone. The owner's plan is **unlimited** — the `720 GB / ∞` on the card is traffic *spent*, not a quota (confirmed 2026-11) — so volume is not what gets you banned; concurrency and datacenter origin are. Symptoms still worth knowing: the phone and the server knocking each other offline, or the account flagged for sharing.

A subscription bought **for the server alone** removes the duplicate-client signature (one key, one IP, exactly what the plan expects) and cuts the ban risk a lot, but not to zero: the provider still sees a datacenter origin, and transit/resale is usually forbidden in the terms. Keep a dedicated subscription off the phone and treat it as a layer under an owned VPS, not a replacement.

These sellers are typically **resellers** (arbitrage): one key, but exits on unrelated ASNs (AEZA Paris, PLAY2GO Helsinki). That explains both why they are cheap and why they cannot fix IP reputation — they rent someone else's subnets. Practical consequence: the exit behind a node can change without notice, so re-run the geo checker before blaming our side when Gemini breaks.

### Turning a plan into a pool

Panels built on Remnawave serve a decoy to clients they do not recognise: two vless nodes named `Данное приложение не обновлено` / `или не поддерживается`, both on `0.0.0.0:1`. A browser UA, `v2rayNG/…` or `ClashMeta/…` all get that decoy. What works is a supported app UA **plus** a hardware-id header:

    curl -sS -A 'v2rayTun/4.7.0' -H 'x-hwid: <any hex>' '<sub-url>' -o sub.b64

`Happ/2.11.0` with the same header returns the profile as a JSON Xray config instead. Pad before decoding (`base64 -d` wants `len % 4 == 0`), then parse one link per line.

A second decoy means a different problem: a list of nodes named `Превышен лимит устройств` / `@VPNUI_bot` / `Сбросить лимит устройств` is the panel's device-limit page, not a parsing failure — the server's IP became one client too many. Either ask the owner to reset the limit in the provider bot, or skip the subscription entirely and have him export the node link from the phone app (cheaper — a reset gets consumed again on the next refresh).

**Credentials are per plan, not per protocol.** Inside one plan every vless node shares a single UUID and every trojan node a single password, so one key opens the whole plan. Across two plans (PC vs mobile) they differ, and a node will not answer to the other plan's key: swapping the credential and retrying is the fastest way to tell "node dead" from "wrong key". `scripts/test_whitelist.py <sub> <other-sub> <indices> [--mobile]` does exactly that — builds each node with one plan's credential, then with the other's if the first run is silent.

Handing a family subscription the *mobile* plan's keys exposes that plan: one leaked link grants every node. Say so before wiring it in.

**Labels lie — probe every node.** On one 24-node plan every node carried a country flag and a friendly name, yet only 2 gave Google a supported country: the German, Swedish, Polish, US, Albanian and Austrian exits all answered `ru`. A reseller registers its whole address space the same way, so the flag describes the sale, not the geo. Run `scripts/probe_sub.py <sub-file> [indices]` — it builds an Xray client config per link, runs it inside `3xui`, and prints exit IP + Google country — then route only the accepted nodes.

Two node kinds are unusable here: `hysteria2` links (Xray core has no such protocol) and nodes whose page yields `com` instead of a country code (Google could not place the address — not a supported verdict). Nodes that return 0 bytes are dead; treat them as absent rather than as blocked.

## Pitfalls

- The owner floats ideas in passing («выбросим эту Эстонию в помойку», «а если хостинг американский», «ничего не делаем, я образно») — that is thinking aloud, not a work order. Answer the technical question with the trade-off, then wait for an explicit «делай». Do not start a migration, buy a node or rewrite a pool off a hypothetical; he pushes back hard on unrequested initiative.
- `gemini_geo_check.py` lives on the host, not in the containers: `docker cp /root/vpn-router/gemini_geo_check.py 3xui:/tmp/ggc.py` before running it through a socks listener inside `3xui`, otherwise the call fails with "can't open file".
- `pkill -f <cfg>.json` inside `docker exec sh -c '…'` kills the shell running the loop, because the pattern matches that shell's own command line — a per-node probe stops after the first node. Launch the client with `… & pid=$!` and `kill $pid`.
- `docker stats` reports `0B` for `vpn-router` because it runs on the host network — do not read that as "no traffic".
- `docker run -p 127.0.0.1:PORT` does not expose extra inbounds: use `--network host` (with `--user 0:0` so the 0600 config is readable).
- Keep every inbound bound to 127.0.0.1; an inbound on `0.0.0.0` publishes raw VLESS to the internet.
- Cloudflare WARP is unusable from this host: UDP 2408 and 1.1.1.1:53 get no reply (8.8.8.8 works). Do not build routing on WARP here.
- An external exit is a black box: its public hostname resolves to a front IP that may sit on a different ASN and different /24 than the subnet that actually egresses. Never infer the verdict from the resolved IP — force Google to answer from the exit: `curl --socks5-hostname <exit> 'https://dns.google/resolve?name=o-o.myaddr.l.google.com&type=TXT'` and read the `edns0-client-subnet` line. The hostname can also rotate between addresses, which silently changes the Gemini verdict.
- Everything is mirrored in `Esmien/vps-infra` under `assets/vpn/` (sanitised: no UUID, no exit password). The public repo must never receive credentials.
- After a push, `raw.githubusercontent.com` keeps serving the previous copy for minutes — a stale read is not a failed push. Confirm through the API instead: `curl -s 'https://api.github.com/repos/<owner>/<repo>/contents/<path>?ref=main'` and base64-decode `content`.
