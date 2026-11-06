# Vetting a host before paying (new VPS / RU node)

## Spec sanity for our workloads

- An Xray entry or relay (24 inbounds, blue/green pair) runs in ~120 MB RAM: **1 vCPU / 1–2 GB**
is plenty; paying for more buys nothing.
- Disk: **≥20 GB**. 10 GB survives only if nothing logs and no desktop is installed.
- **ISO = server/minimal, never `*-desktop`**: the desktop image pulls GNOME, eats ~8 GB of a
  10 GB disk and ~1.5 GB RAM for a UI nobody uses on a headless box.
- **Public dedicated IPv4 must be in the price** (not an extra line, not CGNAT). Without your own
  address the box is useless as an entry point.
- **Monthly billing first.** An unproven IP cannot be validated from the order form, only from
  inside the running server — a yearly prepay bets on something unmeasured.

## Registry checks (5 minutes, before paying)

```bash
whois <domain> | grep -Ei '^(domain|registrar|created|paid-till|nserver|org)'
dig +short <domain> A; dig +short <domain> NS
whois -h whois.cymru.com " -v <ip-from-A-record>"
```

What each answer buys:

- `created` / `paid-till` — an old domain paid years ahead is a different risk class from a
  month-old one.
- `nserver` on the provider's own domain means they run their own DNS, not a reseller panel.
- The Team Cymru line prints `AS | BGP prefix | CC | registry | allocated | AS name`. Their own
  AS **and** a prefix allocated years ago = the provider owns the network; a tiny prefix resold
  through someone else's AS = you are two hops from the real owner. `CC` confirms the address
  space is actually in the country you are buying.
- Read the offer/requisites pages through `read-untrusted` (a web page, not a command): legal
  entity, INN/OGRN, claimed own datacenter. A real ИНН/ОГРН and an old domain are the cheap
  filter against one-day resellers.

## Review quality

Positive reviews on hosting catalogs (sohost, glavhost, hostings.info, tophosts, hostinghub) and
on the provider's own site are marketing and say nothing. **The absence of complaints is not
proof of anything** — say it that way instead of certifying the provider. A public DDoS incident
in their own news is a real signal: they get hit, so do not expect premium uptime and keep a
second node elsewhere for the same role.

## The caveat no provider will tell you

A datacenter address is refused by Госуслуги, banks and marketplaces **regardless of the country
the server stands in** — being in RU is necessary, not sufficient, for an RU-scenario exit. This
is provable only after the server is up: dial through it and request the actual target
(`http://www.gosuslugi.ru`, a bank, `wildberries.ru`), then decide whether to keep the plan.
State that up front when the owner is about to prepay for a year.
