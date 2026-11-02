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

Gemini's country is Google's own lookup of the **connection IP**, not the country of a hoster's brand, not DNS, and not the city in ipinfo. Measure it, never guess — run `scripts/gemini_geo_check.py` (packaged with this skill, deployed at `/root/vpn-router/gemini_geo_check.py`):

    python3 gemini_geo_check.py [socks5-host:port]

The Gemini web template embeds Google's verdict in `this.gbar_={CONFIG:[[[0,"www.gstatic.com","<build>","<cc>","<lang>"` — that two-letter `<cc>` is the country Google assigns to the exit. Supported codes work, `ru`/`by`/`ir`/... show the stub. Confirmed cases on this host:

- `138.124.58.x` (AEZA, Paris) → `fr` → works.
- `77.221.152.x` (AEZA, Paris) → `ru` → stub. Same city, same ASN — the /24 differs.
- Our own `141.98.166.213` (Tallinn) → `ru` → stub, even though the IP geolocates to Estonia.

So a Paris VPS can be "Russia" for Google, and a Tallinn VPS too. Buying an exit is a per-IP lottery: rent (hourly if possible), run the checker, keep only a supported code, otherwise destroy and try another provider/subnet.

"Smart DNS" services that unblock Gemini work by proxying the flows through their own IPs — DNS is only how they capture and redirect the domains. Changing resolvers alone cannot move the verdict, because the verdict follows the connection IP. Verified through one good exit: default resolver, Yandex DoH (`77.88.8.8`) and Google DoH (`8.8.8.8`) all returned the same `fr`; the bad exit returned `ru` under every resolver.

Route Google domains *and* Google IP ranges through the FR exit and enable `sniffing`; a partial tunnel was not enough — the whole flow must leave through the good IP. IPv6 is the one leak that does flip the verdict, because Google then reads the real address past the tunnel: this host has **no global IPv6 at all** (no address, no default route, `curl -6` → `000`), the `direct` outbound is `UseIPv4`, and generated Clash profiles carry `ipv6: false` both top-level and in `dns` — so the stack itself cannot leak. The remaining vector is a client that bypasses the tunnel for v6; diagnose on the device with `test-ipv6.com` and switch IPv6 off in that client rather than hunting the server.

## Failover

`vpn-failover.timer` probes the external exit **every 15 min with `RandomizedDelaySec=300`**, so activations land 15–20 min apart instead of on a visible 2-minute bot cadence. 2 failures → default route flips to `direct`, 2 successes → back to `fr`. Internet survives an exit outage, only Gemini degrades — but detection now takes up to ~40 min (two probes plus jitter); if that is too slow, lower `FAIL_THRESHOLD` to 1 instead of shortening the interval. Test logic on a copy of the config — never point the live probe at an unreachable host.

## Borrowed exit (third-party subscription)

An exit lifted from someone's paid plan is a shared credential, not a free tunnel: provider panels count **unique IPs**, not devices, so this server shows up as one more client beside the owner's phone, and every byte — full tunnel included — burns that plan's traffic quota. Symptoms of hitting a limit are the phone and the server knocking each other offline, or the account being flagged for datacenter-IP sharing. Keep it as a temporary layer, keep probes irregular (see Failover), and replace it with an owned VPS as soon as one passes the Gemini check.

## Pitfalls

- `docker run -p 127.0.0.1:PORT` does not expose extra inbounds: use `--network host` (with `--user 0:0` so the 0600 config is readable).
- Keep every inbound bound to 127.0.0.1; an inbound on `0.0.0.0` publishes raw VLESS to the internet.
- Cloudflare WARP is unusable from this host: UDP 2408 and 1.1.1.1:53 get no reply (8.8.8.8 works). Do not build routing on WARP here.
- An external exit is a black box: its public hostname resolves to a front IP that may sit on a different ASN and different /24 than the subnet that actually egresses. Never infer the verdict from the resolved IP — force Google to answer from the exit: `curl --socks5-hostname <exit> 'https://dns.google/resolve?name=o-o.myaddr.l.google.com&type=TXT'` and read the `edns0-client-subnet` line. The hostname can also rotate between addresses, which silently changes the Gemini verdict.
- Everything is mirrored in `Esmien/vps-infra` under `assets/vpn/` (sanitised: no UUID, no exit password). The public repo must never receive credentials.
- After a push, `raw.githubusercontent.com` keeps serving the previous copy for minutes — a stale read is not a failed push. Confirm through the API instead: `curl -s 'https://api.github.com/repos/<owner>/<repo>/contents/<path>?ref=main'` and base64-decode `content`.
