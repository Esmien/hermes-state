# Certificates

`qd.je` is treated by Let's Encrypt as **one registered domain**, so all its subdomains share the 50-certs-per-168h bucket and issuance regularly fails with `retry after <timestamp>`.

- `certbot_retry.py <host>` parses that hint, sleeps until `retry_after + 3–4s`, re-parses any newer hint, gives up only after 24 h. Log: `/var/log/certbot-retry.log`.
- `provision_vpn_host.py <host>` wraps it and on success rewrites `brand.json`, rebuilds nginx + subscriptions, reloads, verifies.
- Its final verification can print `000` if curl lands inside the reload window — re-check manually before believing the switch failed.
- `qd.je` is a **free subdomain under someone else's registry**, and that is the deeper problem: its DNS is one provider's goodwill. Any name the entry depends on needs authoritative servers that actually answer — measure them (`dig` per NS, 5 tries each) before trusting a provider, and prefer an owned domain whose NS point at a large DNS host. Cheap registrars are fine for this (RU cards work, NS are editable); avoid giveaway TLDs that anti-spam filters already treat as hostile.
- Wildcard `*.esmien.ru` is issued with **DNS-01 through the Cloudflare API** — one certificate `esmien-wildcard` covers `*.esmien.ru` plus the apex, so a new service needs no certbot run at all, only an A record and a server block. Token lives in `/root/.secrets/cf.ini` (0600, scope `Zone:DNS:Edit`), plugin is `python3-certbot-dns-cloudflare`, renewal hook reloads nginx. Full command, verification matrix, API-side subdomain creation and the "name stopped resolving" triage: `references/domain-and-tls.md`.
