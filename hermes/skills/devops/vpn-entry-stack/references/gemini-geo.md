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

# Gemini / geo

## Gemini / geo

Gemini's country is Google's own lookup of the **connection IP** — not the hoster's brand, not DNS, not the city in ipinfo. Measure with `scripts/gemini_geo_check.py [socks5-host:port]`; `fr`/`fi`/`de` work, `ru` is the stub. Our own Tallinn IP reads `ru` because Google follows the address registration, not the machine's location; a reseller's Paris IP can read `ru` for the same reason. "Smart DNS" cannot move the verdict — the verdict follows the IP that carries the flow, so route Google domains *and* IP ranges through the good exit with `sniffing` on. IPv6 is the only leak that flips it; this host has none and the generated profiles set `ipv6: false`, so look at the client, not the server. Full evidence, whois reasoning and exit-buying rules: `references/gemini-geo.md`.

Client rules are not a guarantee — only Clash-family subscribers receive them, and Happ gets none, so a verdict that must hold in every app has to be enforced **on the server**. Xray evaluates top-down: a `domain:… → fr` rule placed *after* the `inboundTag` rules never fires, because every request from those inbounds already left through its own outbound. Put the Google rule first, right after the block rules.

**Route the whole Google *web* chain, not just `gemini.google.com`.** Google decides the country per connection, and the Gemini page is reached through `www.google.com` → `accounts.google.com` → `gstatic.com` before a single byte of the app loads. A rule that covers only `gemini.*` lets those hops out through the default exit, Google reads our Tallinn address as `ru`, and the app answers "not available in your country" even though the Gemini request itself went through France. Cover `domain:google.com` (matches every subdomain), `googleapis.com`, `gstatic.com`, `googleusercontent.com`, `google.dev`, `withgoogle.com` and keep `googlevideo.com`/`youtube.com` **out** — video stays on the selected node instead of crawling through the borrowed exit. Same trap in any "only the obvious domain" list: enumerate the sign-in and static-asset hosts too.

**Prove the server-side rule in two cheap steps, not by reading the config.** (1) Matching: temporarily repoint the rule to `blocked`, `vpn-cfg apply`, wait for the container start time to move, then dial the affected domains through the ordinary `/general` inbound — they must fail while an unrelated site still answers; restore afterwards. (2) Exit: add a throwaway `domain:<canary>` rule → the same outbound (an `ipinfo.io` canary is enough), request it through `/general` and read the egress — it must be the borrowed exit, not our address. Delete the canary, apply, and re-run one real request (`curl gemini.google.com/app` through the tunnel should return the app shell with no "not available in your country" string). Xray does **not** log which outbound a connection took, so raising `loglevel` to `debug` and grepping the container log is a dead end — the blocked/canary pair above is the only cheap evidence. A page that returns `200` proves nothing on its own: the geo refusal is in the body, and the login chain is what usually breaks.

**A `blocked` fallback fakes a country refusal.** When a single-node balancer loses its node the
observatory answers with `fallbackTag`, and if that tag is `blocked` every connection is blackholed:
`gemini.google.com:443 [in-general -> blocked]` in bursts, page half-loads, and the app reports a
send error while both the exit and the account are fine. Count the per-host route tags before
blaming geo: `grep 'accepted tcp:gemini' access.log | sed 's/.*-> //;s/]//' | sort | uniq -c`. Any
`blocked` in that histogram is a config bug, not Google — the scenario fallback must be a real exit.
The reverse is just as wrong: a geo verdict read from a page that came through `blocked`/dead exit
says nothing about the exit you meant to test, so probe the exit directly before drawing conclusions.
