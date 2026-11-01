# VPN, proxies and shared HTTPS ingress

## VPN and proxies

- After approval, complete deployment through real connection and recovery checks; distinguish owner-side client tests from checks already performed.
- Bind the admin panel to loopback and verify a real login with the new credentials. Verify the backend itself listens, not merely Docker's published port.
- Exercise a real tunnel with a client and an HTTPS request through its SOCKS proxy. This proves protocol and egress, not reachability from the owner's network or account access.
- 3x-ui `setting -getApiToken` can prepend explanatory lines: extract the line beginning `apiToken:`. Repeated calls rotate the token; retain one in memory across API requests. Inbound API fields may already be JSON objects. Never print tokens, client URLs or secret configuration.
- For Docker connection diagnosis check established sockets inside the container network namespace as well (`docker exec <container> netstat -tn` or `ss -tn`): host `ss` on the published port can show zero with DNAT. Compare authenticated client counters with a user request; established TCP alone proves neither tunnel operation nor page loading.

## Shared HTTPS port and client IP

- Before sharing occupied port 443, inspect all IPv4/IPv6 listeners, vhosts, Nginx modules and actual HTTP responses and prepare rollback. First configure and test the loopback backend; after approval modify ingress, run `nginx -t` and reload, not restart.
- When routing via `stream`/`ssl_preread` to a local HTTPS backend, preserve the real client IP: otherwise backend limits, logs and ACLs see loopback. Configure PROXY protocol on both sides and trust it only on loopback; check all vhosts and applications. Test first on a separate listener, then with two independent external IPs, including rate limiting and spoofing. HTTP 200 does not prove client IP preservation.
- Distinguish external TCP, TLS/fallback and actual application connectivity from the user's network. For MTProto the link uses the published host port, not the container port. Never output secrets or links in chat or diagnostic logs.
- For region-restricted services, check egress IP geolocation, service HTTP availability and authenticated access from the device through the established VPN separately. HTTP 200 and IP country do not prove account or subscription access.
- After ingress changes, transfer configuration and recovery procedure to the recovery repository without secrets; verify restoration and autostart. Report outstanding recovery or client tests rather than claiming completion.
- Inspect current ingress configuration and sockets instead of relying on historical notes: external IPs in the access log only prove individual requests, not rate limits, ACLs or spoofing protection. Independently verify application connectivity from the user's network and recovery-repository synchronization.
