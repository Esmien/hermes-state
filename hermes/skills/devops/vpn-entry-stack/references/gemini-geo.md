# Gemini / geo: как Google решает, поддерживается ли страна

Gemini's country is Google's own lookup of the **connection IP** — not the country of a hoster's
brand, not DNS, and not the city in ipinfo. Measure it, never guess: `scripts/gemini_geo_check.py`
(deployed at `/root/vpn-router/gemini_geo_check.py`):

    python3 gemini_geo_check.py [socks5-host:port]

The Gemini web template embeds Google's verdict in
`this.gbar_={CONFIG:[[[0,"www.gstatic.com","<build>","<cc>","<lang>"` — that two-letter `<cc>` is
the country Google assigns to the exit. Supported codes work, `ru`/`by`/`ir`/... show the stub.
Confirmed cases on this host:

- `138.124.58.x` (AEZA, Paris) → `fr` → works.
- `77.221.152.x` (AEZA, Paris) → `ru` → stub. Same city, same ASN — the /24 differs.
- Our own `141.98.166.213` (Tallinn) → `ru` → stub, even though the IP geolocates to Estonia.

## Why

Google's country follows the address *registration*, not the machine's location. Our block is
`netname EE-HIP-…, country EE` but its RIPE org object is `Baykov Ilya Sergeevich, country RU,
Moscow` — hence `ru` despite Tallinn. `77.221.152.x` is the same story (`Aeza-Network, FR` over
`AEZA GROUP LLC, RU`), while the working `138.124.58.x` is a legacy `RIPE-ERX` block with no RU org.
And `87.121.105.34` shows whois is not the whole answer either (whois SE, ipinfo FI, Google `ru`) —
Google blends registries with geofeeds and observed traffic. So a Paris VPS can be "Russia" for
Google, and a Tallinn VPS too.

Buying an exit is a per-IP lottery: rent (hourly if possible), run the checker, keep only a
supported code, otherwise destroy and try another provider/subnet. Two purchase-side rules follow
from the whois evidence: prefer a provider whose RIPE/Aria org object is genuinely EU/US (a Russian
org marks the whole block `ru` however the netname reads), and expect the big hosters (Hetzner,
DigitalOcean, Vultr, OVH) to score badly because VPN resellers have burned their ranges for years —
small hosters score better. Hetzner and Scaleway also refuse RU cards, so check payment before
falling in love with a plan.

## "Smart DNS" is not a lever

Services that unblock Gemini work by proxying the flows through their own IPs — DNS is only how
they capture and redirect the domains. Changing resolvers alone cannot move the verdict, because
the verdict follows the connection IP. Verified through one good exit: default resolver, Yandex DoH
(`77.88.8.8`) and Google DoH (`8.8.8.8`) all returned the same `fr`; the bad exit returned `ru`
under every resolver.

## Routing and the IPv6 leak

Route Google domains *and* Google IP ranges through the FR exit and enable `sniffing`; a partial
tunnel was not enough — the whole flow must leave through the good IP. IPv6 is the one leak that
does flip the verdict, because Google then reads the real address past the tunnel: this host has
**no global IPv6 at all** (no address, no default route, `curl -6` → `000`), the `direct` outbound
is `UseIPv4`, and generated Clash profiles carry `ipv6: false` both top-level and in `dns` — so the
stack itself cannot leak. The remaining vector is a client that bypasses the tunnel for v6;
diagnose on the device with `test-ipv6.com` and switch IPv6 off in that client rather than hunting
the server.
