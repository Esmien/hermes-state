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

Upstreams: 10081 `/ws`, 10082 `/general`, 10083 `/france`, 10084 `/test` — all bound to 127.0.0.1.

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

Gemini gates on the **connection IP and account region**, not DNS — do not try to fix it with resolvers. Estonia is unsupported; a French exit works (AEZA Paris `138.124.58.80` confirmed). Route Google domains *and* Google IP ranges through the FR exit and enable `sniffing` on the inbound, otherwise IP-based requests from mobile clients bypass domain rules. A partial tunnel was not enough — traffic has to go through the FR exit fully for the stub to disappear.

## Failover

`vpn-failover.timer` (every 2 min) probes the external exit; 2 failures → default route flips to `direct`, 2 successes → back to `fr`. Internet survives an exit outage, only Gemini degrades. Test logic on a copy of the config — never point the live probe at an unreachable host.

## Pitfalls

- `docker run -p 127.0.0.1:PORT` does not expose extra inbounds: use `--network host` (with `--user 0:0` so the 0600 config is readable).
- Keep every inbound bound to 127.0.0.1; an inbound on `0.0.0.0` publishes raw VLESS to the internet.
- Cloudflare WARP is unusable from this host: UDP 2408 and 1.1.1.1:53 get no reply (8.8.8.8 works). Do not build routing on WARP here.
- Everything is mirrored in `Esmien/vps-infra` under `assets/vpn/` (sanitised: no UUID, no exit password). The public repo must never receive credentials.
