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
- `/lte` — RU-entry chain for mobile/whitelist use: entry `1.fan-video.study` → `87.228.33.97` (Selectel, St Petersburg), egress `87.121.105.34` (Helsinki, PLAY2GO). ~94 Mbit/s, seller cap 2 GB/day. Google reports this egress as `ru`, so it is useless for Gemini — never point `/france` or the owner's `/ws` at it. It only helps whitelist conditions when the client dials the RU entry itself; behind this server the first hop is blocked (see Whitelist mode).

Upstreams: 10081 `/ws`, 10082 `/general`, 10083 `/france`, 10084 `/test`, 10085 `/lte` — all bound to 127.0.0.1.

Adding a route means four coordinated edits, in this order: append an inbound (`tag`, 127.0.0.1, next free port, same client id, `wsSettings.path`) to `config.json`, add the outbound and a routing rule keyed on `inboundTag` **before** the catch-all `tcp,udp → fr` rule, add `paths` + `upstreams` entries to `brand.json`, then `apply_brand.py && nginx -t && systemctl reload nginx && docker restart vpn-router`. Verify by dialling the new path through the tunnel and checking the egress with ipinfo — not by reading the config back.

Files: `/root/vpn-router/{config.json,brand.json,apply_brand.py,make_sub.py,failover.py,certbot_retry.py,provision_vpn_host.py}`, subscriptions in `/var/www/esmien-sub/<token>/`.

## Changing the public host

Never hand-edit the nginx confs — they are generated:

1. edit `host` + `cert_dir` in `/root/vpn-router/brand.json`
2. `python3 /root/vpn-router/apply_brand.py`
3. `nginx -t && systemctl reload nginx`

`apply_brand.py` also emits `vpn-compat.conf` for every entry in `legacy_hosts`, each with its own certificate. That is what makes a host switch invisible to users: old subscriptions and links keep working, no re-import needed. Keep old hosts in `legacy_hosts` while their certs auto-renew.

## Subscription

`make_sub.py` renders three formats; nginx picks one by User-Agent (`00-esmien-sub-map.conf`): Clash/Mihomo → `clash.yaml`, sing-box → `singbox.json`, everything else → base64 `list.txt`. The response carries `profile-title: Esmien VPN` and `profile-update-interval: 12`.

Rules: names are plain country names with flags (`🇪🇪 Эстония (General)`, `🇫🇷 Франция (Gemini)`, `🛠 Тест (Develop)`); the brand lives only in the group/profile title. The owner asks for "no clutter" — do not add groups or extra proxies.

URL shape: `https://<host>:8443/sub/<token>`. The port must be in the URL: plain 443 is blocked for the owner's ISP.

## Certificates

`qd.je` is treated by Let's Encrypt as **one registered domain**, so all its subdomains share the 50-certs-per-168h bucket and issuance regularly fails with `retry after <timestamp>`.

- `certbot_retry.py <host>` parses that hint, sleeps until `retry_after + 3–4s`, re-parses any newer hint, gives up only after 24 h. Log: `/var/log/certbot-retry.log`.
- `provision_vpn_host.py <host>` wraps it and on success rewrites `brand.json`, rebuilds nginx + subscriptions, reloads, verifies.
- Its final verification can print `000` if curl lands inside the reload window — re-check manually before believing the switch failed.
- Wildcard `*.esmien.qd.je` needs DNS-01. DigitalPlat (DNS host, `dns1/dns2.digitalplat.org`) has no publicly reachable API (403/404 on guessed endpoints, paths built dynamically in panel JS), so automation needs either a dashboard token plus its docs or moving the zone to a DNS provider with an open API (deSEC).

## Gemini / geo

Gemini's country is Google's own lookup of the **connection IP**, not the country of a hoster's brand, not DNS, and not the city in ipinfo. Measure it, never guess — run `scripts/gemini_geo_check.py` (packaged with this skill, deployed at `/root/vpn-router/gemini_geo_check.py`):

    python3 gemini_geo_check.py [socks5-host:port]

The Gemini web template embeds Google's verdict in `this.gbar_={CONFIG:[[[0,"www.gstatic.com","<build>","<cc>","<lang>"` — that two-letter `<cc>` is the country Google assigns to the exit. Supported codes work, `ru`/`by`/`ir`/... show the stub. Confirmed cases on this host:

- `138.124.58.x` (AEZA, Paris) → `fr` → works.
- `77.221.152.x` (AEZA, Paris) → `ru` → stub. Same city, same ASN — the /24 differs.
- Our own `141.98.166.213` (Tallinn) → `ru` → stub, even though the IP geolocates to Estonia.

Why: Google's country follows the address *registration*, not the machine's location. Our block is `netname EE-HIP-…, country EE` but its RIPE org object is `Baykov Ilya Sergeevich, country RU, Moscow` — hence `ru` despite Tallinn. `77.221.152.x` is the same story (`Aeza-Network, FR` over `AEZA GROUP LLC, RU`), while the working `138.124.58.x` is a legacy `RIPE-ERX` block with no RU org. And `87.121.105.34` shows whois is not the whole answer either (whois SE, ipinfo FI, Google `ru`) — Google blends registries with geofeeds and observed traffic. So a Paris VPS can be "Russia" for Google, and a Tallinn VPS too. Buying an exit is a per-IP lottery: rent (hourly if possible), run the checker, keep only a supported code, otherwise destroy and try another provider/subnet.

"Smart DNS" services that unblock Gemini work by proxying the flows through their own IPs — DNS is only how they capture and redirect the domains. Changing resolvers alone cannot move the verdict, because the verdict follows the connection IP. Verified through one good exit: default resolver, Yandex DoH (`77.88.8.8`) and Google DoH (`8.8.8.8`) all returned the same `fr`; the bad exit returned `ru` under every resolver.

Route Google domains *and* Google IP ranges through the FR exit and enable `sniffing`; a partial tunnel was not enough — the whole flow must leave through the good IP. IPv6 is the one leak that does flip the verdict, because Google then reads the real address past the tunnel: this host has **no global IPv6 at all** (no address, no default route, `curl -6` → `000`), the `direct` outbound is `UseIPv4`, and generated Clash profiles carry `ipv6: false` both top-level and in `dns` — so the stack itself cannot leak. The remaining vector is a client that bypasses the tunnel for v6; diagnose on the device with `test-ipv6.com` and switch IPv6 off in that client rather than hunting the server.

## Whitelist mode (RU entry)

A whitelist is enforced on the **first hop**: the client must be able to reach the address it dials. So a chain whose first hop is this Estonian server is worthless in whitelist mode — traffic dies before it ever reaches the RU entry behind it, no matter how good that entry is. Two shapes actually work:

- the client dials the RU entry **directly** (loses the brand, the subscription and the per-tunnel control; every user then sits on the provider's single key);
- our own entry lives on a **Russian VPS** (Selectel, Timeweb, Rostelecom), and the foreign exit sits behind it — brand and control survive, at the price of one more node.

A Russian hosting IP is not automatically whitelisted either: lists cover specific service ranges, not "anything in RU". Only a real shutdown proves it; before that, say plainly that the path is unverified.

## Failover — off, deliberately

The owner removed automatic failover: `vpn-failover.timer` is `disabled`/`inactive` and the default route is pinned to `fr`. Do not re-enable it without an explicit request. Rationale: a silent flip to `direct` keeps the internet alive but leaves geo-gated services refusing in a way that looks like the tunnel works ("connected, but Gemini says no"), which is harder to diagnose than a dead tunnel. With the timer off an exit outage kills `/france`, `/ws` and everything on the default route loudly; `/general` and `/test` stay on `direct` and are unaffected.

`failover.py` and the unit files stay on disk and in the repo, unwired — re-enabling is `systemctl enable --now vpn-failover.timer`. If a probe is ever restored, keep the cadence irregular (`RandomizedDelaySec=300` on a 15-minute timer) so it does not read as a bot, and test the logic on a copy of the config, never against the live probe host.

## Borrowed exit (third-party subscription)

An exit lifted from someone's paid plan is a shared credential, not a free tunnel: provider panels count **unique IPs**, not devices, so this server shows up as one more client beside the owner's phone. The owner's plan is **unlimited** — the `720 GB / ∞` on the card is traffic *spent*, not a quota (confirmed 2026-11) — so volume is not what gets you banned; concurrency and datacenter origin are. Symptoms still worth knowing: the phone and the server knocking each other offline, or the account flagged for sharing.

A subscription bought **for the server alone** removes the duplicate-client signature (one key, one IP, exactly what the plan expects) and cuts the ban risk a lot, but not to zero: the provider still sees a datacenter origin, and transit/resale is usually forbidden in the terms. Keep a dedicated subscription off the phone and treat it as a layer under an owned VPS, not a replacement.

These sellers are typically **resellers** (arbitrage): one key, but exits on unrelated ASNs (AEZA Paris, PLAY2GO Helsinki). That explains both why they are cheap and why they cannot fix IP reputation — they rent someone else's subnets. Practical consequence: the exit behind a node can change without notice, so re-run the geo checker before blaming our side when Gemini breaks.

## Pitfalls

- `gemini_geo_check.py` lives on the host, not in the containers: `docker cp /root/vpn-router/gemini_geo_check.py 3xui:/tmp/ggc.py` before running it through a socks listener inside `3xui`, otherwise the call fails with "can't open file".
- `docker stats` reports `0B` for `vpn-router` because it runs on the host network — do not read that as "no traffic".
- `docker run -p 127.0.0.1:PORT` does not expose extra inbounds: use `--network host` (with `--user 0:0` so the 0600 config is readable).
- Keep every inbound bound to 127.0.0.1; an inbound on `0.0.0.0` publishes raw VLESS to the internet.
- Cloudflare WARP is unusable from this host: UDP 2408 and 1.1.1.1:53 get no reply (8.8.8.8 works). Do not build routing on WARP here.
- An external exit is a black box: its public hostname resolves to a front IP that may sit on a different ASN and different /24 than the subnet that actually egresses. Never infer the verdict from the resolved IP — force Google to answer from the exit: `curl --socks5-hostname <exit> 'https://dns.google/resolve?name=o-o.myaddr.l.google.com&type=TXT'` and read the `edns0-client-subnet` line. The hostname can also rotate between addresses, which silently changes the Gemini verdict.
- Everything is mirrored in `Esmien/vps-infra` under `assets/vpn/` (sanitised: no UUID, no exit password). The public repo must never receive credentials.
- After a push, `raw.githubusercontent.com` keeps serving the previous copy for minutes — a stale read is not a failed push. Confirm through the API instead: `curl -s 'https://api.github.com/repos/<owner>/<repo>/contents/<path>?ref=main'` and base64-decode `content`.
