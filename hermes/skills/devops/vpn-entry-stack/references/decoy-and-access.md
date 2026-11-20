# Decoy page and VPN-only access

## Dashboard access limited to the tunnel

- Put `allow 85.92.158.238; allow 127.0.0.1; deny all;` in **both** stats vhosts (`:80` and the TLS block) and add `error_page 403 = @drop; location @drop { return 444; }` — an outsider then gets a dropped connection instead of a 403 that confirms the host exists.
- The VPN edge is the only address a tunnel client appears from, so the allowlist doubles as «only through our VPN». Verify both directions: direct `curl` → `000`/dropped, through a local xray client → `401`.
- **Add a routing rule `domain:stats.esmien.{com,ru} -> direct`** in `config.json`. Without it the request can leave through the NL/Gemini exit and arrive from a foreign IP, which the allowlist drops — the panel then «не открывается из туннеля» for no obvious reason.
- Trade-off to state plainly: when the VPN is down the dashboard is unreachable, including for the owner.

## Decoy instead of the nginx Welcome page

- A stock `Welcome`/stub page is the loudest «здесь ничего нет» signal. Proxy a real product login instead; the owner picked **LiteLLM `/ui/`** (title «LiteLLM Dashboard», no personal brand).
- Locations needed, in this order: `= /` → `return 302 /ui/;`, `^~ /ui/`, `^~ /litellm-asset-prefix/` (all JS/CSS chunks live there — without it the page renders blank), `= /favicon.ico`, then the real `/u/`, `/sub/` and WS paths, `location /` last.
- Add `absolute_redirect off;` in the server block: nginx otherwise emits `Location: https://host:18443/ui/` and leaks the internal listener port (docs: `server_port` is the listening port, and 18443 is the loopback vhost behind the stream front).
- `limit_except GET HEAD { deny all; }` on `/ui/` keeps the decoy read-only: a probe sees a login form, but no POST reaches the real admin API, so there is nothing to brute-force.
- **Patch the generator, not the file:** `vpn-443-in.conf` is written by `apply_brand.py` on every apply. Both the main vhost and the parallel one share the template, and `parallel_vhost` is derived from `main_vhost`, so one edit covers `.ru` and `.com`.
- The vision fallback (`127.0.0.1:8091`, what a browser sees when TLS on 443 is terminated by Xray) must show the same page; its `location /` proxies to `http://127.0.0.1:4000/ui/` so unknown paths and hysteria auth probes also get the login page.

## Hysteria masquerade

- Same surface, different protocol: without `masquerade` a stranger who speaks QUIC to the UDP port gets an empty/broken response, and pointing it at a socks proxy shows them a proxy. Point it at the nginx fallback: `masquerade: {type: proxy, proxy: {url: http://127.0.0.1:8091, rewriteHost: true}}`.
- **You cannot probe the masquerade with a plain HTTP/3 client** (aioquic, `curl --http3`): with `obfs: salamander` every non-salamander packet is dropped before TLS, so the handshake simply hangs. Test with the real hysteria client and a **wrong password**: the auth failure comes back as `authentication error, HTTP status code: <code>` and that code is the masquerade answer (404/405 = a web server that rejects the path/method).
