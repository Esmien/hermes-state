# Cloudflare in front of a stack name (orange cloud)

Read before proxying `ai.esmien.ru` (or any other name) through Cloudflare, before adding CF-side
bot/WAF rules, or when `limit_req` suddenly throttles every user at once.

## Origin topology (why the order matters)

Requests arrive at the `stream` block in `/etc/nginx/nginx.conf` (`listen 443; ssl_preread on`), which
forwards raw TLS with `proxy_protocol on` to the `listen 127.0.0.1:9443 proxy_protocol ssl http2`
vhosts. `conf.d/00-proxy-realip.conf` sets `set_real_ip_from 127.0.0.1; real_ip_header proxy_protocol;`,
so `$remote_addr` is already the real client while the record is grey.

With the orange cloud on, the peer at origin is a Cloudflare edge IP, so `$remote_addr` becomes
**Cloudflare's** address. Every `limit_req zone=webui_api` / `limit_conn conn_per_ip` key is then the
same key for everybody: one shared bucket, 429s for the whole family, and fail2ban jails aimed at CF
ranges. Fix it FIRST, flip SECOND.

## Real-IP snippet (must exist before the proxy is switched on)

`/etc/nginx/snippets/cloudflare-realip.conf` — the v4+v6 ranges from
`https://www.cloudflare.com/ips-v4` and `ips-v6`, then:

```nginx
real_ip_header CF-Connecting-IP;
real_ip_recursive on;
```

Include it **inside** the `listen 127.0.0.1:9443` server block (server level overrides the http-level
`real_ip_header proxy_protocol` for that vhost only, and the proxy_protocol hop still resolves the
peer). While the record is grey the header never arrives and the directives are inert — so it is safe
to install early and the rollback to grey needs no config change.

Then `nginx -t && systemctl reload nginx` and confirm direct traffic still answers
(`curl -o /dev/null -w '%{http_code} cert=%{ssl_verify_result}' https://ai.esmien.ru/` → `200 cert=0`).

## Access: token or clicks

The agent has no Cloudflare credential by default. Either a scoped API token in
`/root/.secrets/cloudflare.token` — zone `esmien.ru`, `DNS:Edit`, `Zone Settings:Edit`, `WAF:Edit` — or
the owner does four things in the dashboard:

1. DNS → the record → Proxy status **Proxied**.
2. SSL/TLS → Overview → **Full (strict)** (origin holds the valid `esmien-wildcard` cert, so strict is safe).
3. Security → Bots → **Bot Fight Mode: On**.
4. Security → WAF → Rate limiting rule: `POST` + path `/api/v1/auths/signup` → a few requests per few
   minutes per IP → Block.

A Turnstile widget is NOT available without app support: Open WebUI 0.12.5 has no captcha code path at
all (see `references/signup-approval.md`), so a widget `auth_request` would need a patched frontend build
in `ai/webui-branding/` on top of the nginx side.

## Risks to state before flipping (free plan)

- **100 s before the first byte** → `524` on long non-streamed responses. OWUI chat streams over SSE, so
  normal answers survive; a long silent «thinking» phase can still trip it.
- **100 MB upload cap**, matching the existing `client_max_body_size 100M`.
- **TLS terminates at Cloudflare**: chat content is readable there. For a private family instance say so
  out loud instead of silently changing who can see the traffic.
- Wildcard cert is issued by DNS-01, so proxying does not affect renewals.
- Local consumers (`Hermes → 127.0.0.1:8080`) bypass the proxy entirely; nothing there changes.

## Verify after the flip

```bash
curl -o /dev/null -w 'ai=%{http_code} cert=%{ssl_verify_result}\n' https://ai.esmien.ru/
tail -n 5 /var/log/nginx/access.log          # first column must be a real client IP
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://ai.esmien.ru/api/v1/auths/signup
```

`tail` on the access log is the proof that the real-IP snippet works: an edge address (`104.16.x`,
`172.64.x`, `162.158.x`) in column 1 means nginx is still keying limits on Cloudflare.

## Rollback

One switch: back to grey cloud. The real-IP snippet stays installed and inert.
