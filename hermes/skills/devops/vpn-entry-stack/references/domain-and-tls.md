# Domain, DNS and certificates

Host-wide, not VPN-only: the same zone and the same wildcard serve the AI services (`ai`, `llm`, `mon`, `bot`) as well as the VPN entry.

## Shape that works

- Owned domain at a registrar the owner can pay for with an RU card; NS delegated to Cloudflare.
- Every record **grey cloud** unless a service is deliberately proxied. One wildcard certificate per zone serves every vhost plus the apex.

## Issuing the wildcard

```bash
apt-get install -y python3-certbot-dns-cloudflare
# /root/.secrets/cf.ini (0600, parent dir 0700):
#   dns_cloudflare_api_token = <token>      # scope Zone:DNS:Edit on that one zone
certbot certonly --cert-name <zone>-wildcard \
  --dns-cloudflare --dns-cloudflare-credentials /root/.secrets/cf.ini \
  --dns-cloudflare-propagation-seconds 30 \
  -d '*.example.ru' -d example.ru \
  --non-interactive --agree-tos -m admin@example.ru
```

- DNS-01 needs no listening port and no ACME vhost, so it works even while the services are broken.
- Afterwards point **every** `ssl_certificate` / `ssl_certificate_key` at `/etc/letsencrypt/live/<cert-name>/fullchain.pem` and `privkey.pem` — for the VPN stack that is just `cert_dir` in `brand.json`. Reload nginx, then check each vhost separately (see matrix).
- Renewal stays with `certbot.timer`; add a deploy hook so no vhost is ever left on an expired file:

```sh
#!/bin/sh
# /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh   (0755)
nginx -t && systemctl reload nginx
```

## Proving renewal without waiting

`certbot renew --dry-run` first sleeps a randomized delay (up to ~5 minutes) and looks hung — run it in the background, or add `--no-random-sleep-on-renew`. Success reads `Congratulations, all simulated renewals succeeded`.

## Verification matrix

```bash
for h in vpn.example.ru:8443 vpn.example.ru:2087 ai.example.ru:443; do
  host=${h%:*}; port=${h#*:}
  echo -n "$h "; echo | openssl s_client -connect 127.0.0.1:$port -servername $host 2>/dev/null \
    | openssl x509 -noout -subject | cut -c1-40
done
curl -sS -o /dev/null -w '%{http_code} verify=%{ssl_verify_result}\n' https://ai.example.ru/
```

`subject=CN = *.<zone>` proves the wildcard is in place; `ssl_verify_result=0` is the only passing value. Do not accept `200` alone — a host can answer while serving a stale certificate.

## Subdomains through the API, no dashboard

A token with `Zone:DNS:Edit` is enough to create records **and** to satisfy DNS-01. It cannot touch NS, WAF, Access, Tunnel or other zones — say so instead of promising full account automation.

```bash
T=$(grep -oP '(?<=api_token = ).*' /root/.secrets/cf.ini)
zid=$(curl -sS -H "Authorization: Bearer $T" \
  'https://api.cloudflare.com/client/v4/zones?name=example.ru' | jq -r '.result[0].id')
curl -sS -X POST -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
  --data '{"type":"A","name":"new.example.ru","content":"<ip>","ttl":120,"proxied":false}' \
  "https://api.cloudflare.com/client/v4/zones/$zid/dns_records"
```

Prove it with `dig +short @1.1.1.1 new.example.ru` and `@8.8.8.8`, then delete the throwaway record. A record is not a service: without a server block the name resolves and falls through to the default vhost, so create record and vhost in the same pass — the wildcard already covers TLS.

## Limits that decide the design

- A wildcard covers exactly one label: `a.example.ru` yes, `a.b.example.ru` no.
- Orange cloud terminates TLS at the edge: HTTP-01 answers `530`, per-path WebSocket routing stops matching, and the real client IP arrives only via `CF-Connecting-IP`.
- CNAME cannot coexist with other records on the name and is not usable at the apex; the orange/edge proxy ports are limited to 80/443 and a handful of others.

## After a name change

- Grep the whole host for the old name, not just nginx: `grep -rn '<old-host>' /root/deploy /home/ai_service --include='*.env*' --include='*.yml'`. A service answers `200` on the new vhost while its webhook, OAuth redirect or public URL still points at the dead name — the music bot was deaf for days this way. Re-register and confirm the provider's own state (`getWebhookInfo` → `pending_update_count=0`, no `last_error_message`).
- Keep the old name as a legacy vhost with its own certificate until every user has moved; it costs nothing and revives stale links if that zone comes back.

## When a name stops resolving

Symptom: the browser opens the site (cache), every app reports n/a or timeout, and the server's logs show **no packets at all**.

```bash
dig +trace <host> A | tail -20               # is the delegation itself sane?
dig @<each authoritative NS> <host> A        # 5 tries each: flaky NS answer 1-2 of 5
dig @8.8.8.8 <host> A; dig @9.9.9.9 <host> A   # SERVFAIL = validators get no answer
```

Authoritatives that answer intermittently make every validating resolver return `SERVFAIL` while a large resolver still serves from cache — so "it opens in my browser but the app cannot connect" is a DNS verdict, not a tunnel failure. Fix the delegation (move the zone to a DNS host with a real API) instead of rebuilding the service, and in the meantime ship IP-addressed nodes and an IP-based subscription URL.
