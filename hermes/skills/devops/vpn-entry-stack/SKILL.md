---
name: vpn-entry-stack
description: Use when editing or deploying the VPN entry stack.
version: 1.0.0
author: VPS Admin
license: MIT
---

# VPN entry stack (VLESS over WebSocket + TLS)

## When to Use

Load this before touching anything that serves VPN clients: adding or removing a route, moving the public host or certificate, regenerating subscriptions, or answering a "VPN keeps dropping / no internet" report. Also load it for «нас РКН забанят?» / «что делать, если заблокируют» — `references/blocking-risk.md`. Not for the AI services on the same host — that is `ai-stack`.

The owner's home ISP (MTS, Krasnodar) drops **port 443** and kills **fake-TLS/MTProto** to this server's IP. What works is a *real* TLS handshake on a non-standard port. That single fact drives the whole design — verify it before debugging anything else.

## Reporting to the owner

He runs this stack himself and treats reports as noise unless they answer the question he asked:

- Answer in one line, then at most three or four bullets of substance. The payload — a new subscription URL, a login, a number — goes at the top, bare, without a lead-in.
- Do not replay the checks you ran, list the files you touched, or volunteer «две оговорки» nobody asked for. A long report earns «да как же ты достал», an invented label earns «не приши лишнее» — the fix is fewer words, not more explanation of the words.
- When he corrects a name or a label, use his string verbatim and change nothing else in that pass: «просто — Саша. И всё» means exactly that, not «Главный ключ (мой + Саша)».
- A destructive request stated plainly («снеси нахуй X») is a work order: do it, then say in one line what died with it and how it would come back. Do not re-ask and do not lecture about the risk first.
- He asks «почему» to get a cause, not a plan: explain the mechanism in two or three lines and stop. Offer the fix as one short question, or just make it when it is obviously what he asked for.

## Layout

```
client -> nginx TLS (8443 primary, 2087 backup) -> xray container `vpn-router` (host network)
        -> outbound "fr" (external exit) | "direct" (this server)
```

Paths (same nginx server blocks). **Only `/ws` and `/general` exist today** — the owner had every other entry
pruned («нам от подписки нужны только маршруты до Gemini и до ру-сервисов»):

- `/ws` — owner's profile, everything goes through the external FR exit.
- `/general` — Estonia (direct exit), normal traffic; every published subscription points here.
- `/france`, `/test`, `/fi` — **removed** (were unused; Gemini is reached by the `bal-google` rule from
  `/general`, not by a separate entry). Re-adding one means inbound + nginx location + rule, in that order.

There is deliberately **no** RU-entry inbound: an earlier `/lte` route (`1.fan-video.study` → Selectel SPb → Helsinki, Google saw it as `ru`) was removed once it was clear the whitelist first hop has to be dialled by the client itself, never by this server. Whitelist entries ship as direct client links only — see `references/whitelist-mode.md`.

3x-ui is **not** part of the stack: container, volume, `/panel/` route, credentials file, panel vhost, its rate-limit zone and fail2ban jail were all removed. It managed two idle inbounds and could not express "this entry -> that exit", which is the whole point of the routing, so it was one public admin surface for nothing. `references/xui-panel.md` keeps only the CSRF/login knowledge in case a UI is ever reintroduced — do not bring a panel back off your own initiative.

Upstreams: 10081 `/ws`, 10082 `/general`; 10185 is the stats API. The 22 relayed `/p<i>` inbounds and the
`in-france`/`in-test`/`in-fi` entries were **deleted** along with their passthrough outbounds — the
subscription now serves only as exits (`fr`, `fi` for Gemini; `p15`, `p17` for `.ru`). Check the real ports
with `vpn-cfg status` instead of trusting a number from a report.

Adding a route means four coordinated edits, in this order: append an inbound (`tag`, 127.0.0.1, next free port, same client id, `wsSettings.path`) to `config.json`, add the outbound and a routing rule keyed on `inboundTag` **before** the catch-all `tcp,udp → direct` rule, add `paths` + `upstreams` entries to `brand.json`, then `apply_brand.py && nginx -t && systemctl reload nginx && vpn-cfg apply` (not a bare `docker restart` — `apply` proves the routes answer and reverts a broken config). Verify by dialling the new path through the tunnel and checking the egress with ipinfo — not by reading the config back.

Files: `/root/vpn-router/{config.json,brand.json,apply_brand.py,make_sub.py,make_template.py,import_sub.py,users.py,probe_sub.py,test_whitelist.py,gemini_geo_check.py,sub_expiry.py,route_ru.py,subs.json,users.json,failover.py,certbot_retry.py,provision_vpn_host.py}`, subscriptions in `/var/www/esmien-sub/<token>/`. Editing, applying and rolling back: `vpn-cfg` (`references/router-ops.md`). Per-user/route traffic counters and «кто пользуется подписками»: `references/usage-stats.md`. When a client reports that the VPN "keeps dropping": `references/client-drop-triage.md` — probe the server end to end before touching anything, and start with DNS: an entry whose name no longer resolves looks exactly like a dead VPN (app can't ping any node, browser still works from cache).

## Deploy / rebuild

The entry is deliberately one container plus flat files, so a fresh server is a script run, not a rebuild from memory:

```bash
bash assets/vpn/scripts/deploy.sh <domain> [email]     # nginx+stream, cert, container, vhosts, subs
python3 /root/vpn-router/import_sub.py <sub-file> [dead indices]
```

The VPN is its **own project**, not part of the AI-stack installer: the canonical repo is the private `Esmien/vpn-service` (`router/`, `nginx/`, `scripts/`, `systemd/`). A full server rebuild is therefore two steps — `install.py` for the AI stack, then `deploy.sh` from this repo for the entry; the bootstrap one-liner does not bring the tunnel back. After any structural change, regenerate the secret-free template with `router/make_template.py`, copy the live files into the repo, and commit — it must match the live host exactly. Runtime secrets stay out of git via `.gitignore`: `config.json` (client UUID), `users.json` (per-user UUIDs), `subs.json`, `whitelist_links.json`, `*.key`, `*.pem`, `*.enc`. Full procedure and pitfalls: `references/router-ops.md`.

The owner-facing counterpart is `/root/.hermes/docs/vpn-runbook.md`: scheme with real ports and paths, every design decision with its price, a nine-step rebuild with a check after each step, six diagnostic commands with a symptom table, and the pitfalls in `references/pitfalls.md`. It lives in the `hermes-state` snapshot, **not** in `vpn-service` (that repo takes only what actually runs on the host). After any structural change — a new port, path, scenario, timer or exit — update the runbook in the same pass; he asked for it so he can rebuild the stack by hand, and a stale runbook is worse than none.

## Changing the public host

Move host, port, cert and subscriptions in one pass: nginx server blocks, `brand.json` paths, regenerated subs, `vpn-cfg`'s own `HOST=` copy, then `apply_brand.py && nginx -t && reload && vpn-cfg apply` — a stale copy in `vpn-cfg` makes `apply` probe the old name and revert a good config.

Full text → [references/changing-public-host.md](references/changing-public-host.md)

## Scenario routing / one-node subscription

Server-side scenarios (Google→FR/FI, RU→Moscow or an owned RU box; YouTube deliberately rides the
Estonian exit) plus a subscription that exposes **one** node, and the jittered watchdog that falls
a dead scenario group back to Estonia: `references/scenario-routes.md`. Do not offer a user a
second node to tap — that is provider traffic and ban risk, not a feature.

Two rules apply to every scenario edit: a balancer tag must also be listed in
`observatory.subjectSelector` (otherwise `leastPing` has no data for it and the matching requests
hang while every config check passes), and health checks must accept `2xx`/`3xx` through a URL
that answers *from that node's country* — a RU exit probed with `gstatic` reads permanently dead.
Full symptom list and fixes: `references/scenario-routes.md`.

When the RU scenario must stop depending on reseller relays, a small owned Russian VPS with a
VLESS+Reality inbound wired in as outbound `ru1` is the shape: provisioning, firewall allowlist,
IP-reputation acceptance test and rollback in `references/owned-ru-exit.md`; what to check on the
box before wiring it, and the exit-node pitfalls — `references/ru-exit-node.md`.

## Subscription

`make_sub.py` renders three formats and nginx picks one by User-Agent (`00-esmien-sub-map.conf`): Clash/Mihomo → `clash.yaml`, sing-box → `singbox.json`, everything else → base64 `list.txt`. URL shape: `https://<host>:8443/sub/<token>` — the port must be in the URL, plain 443 is blocked for the owner's ISP. The layout comes from the `kind` file in the token dir (`meta` = one node, `whitelist` = provider list, `full` = legacy 25-node list).

Full text → [references/subscription-shapes.md](references/subscription-shapes.md)

## Deep dives (references)

- **Change the public host** — nginx, cert, `brand.json`, subscriptions and `vpn-cfg` host copy in one pass → `references/changing-public-host.md`
- **Per-user keys** — every person gets their own UUID and sub URL, so revocation touches nobody else → `references/per-user-keys.md`
- **Landing page per user (`/u/`)** — the page each user opens for their links → `references/landing-pages.md`
- **Usage stats** — per-user counters from the xray `StatsService`, «кто реально пользуется» → `references/usage-stats.md`
- **Blue/green** — applying a config change with no downtime → `references/blue-green.md`
- **Subscription expiry** — read it from the provider's `subscription-userinfo` header, not the panel; daily 07:00 UTC timer warns at 3/2/1 days → `references/subscription-expiry.md`
- **Upstream subscriptions** — relaying third-party nodes as exits → `references/upstream-subscriptions.md`
- **RU split** — banks / gosuslugi / VK / OZON / WB direct or via the RU exit → `references/ru-split.md`
- **Gemini / geo** — the country is Google's own lookup of the connection IP; measure with `scripts/gemini_geo_check.py` → `references/gemini-geo.md`
- **Whitelist mode** — the LTE whitelist list goes to the client as links, never through this server → `references/whitelist-mode.md`
- **Borrowed exit** — a third-party subscription used as an exit → `references/borrowed-exit.md`
- **Routing watchdog** — a timer rewrites routing every minute; edits must survive it → `references/routing-watchdog.md`
- **«Нас не съели ли VPN-клиенты?»** — three measurements instead of guesses → `references/client-share-measurements.md`
- **Блокировка РКН** — четыре реальные ручки (IP/SNI/диапазон/whitelist), триаж, переезд на новый IP, цена домена и общий IP с AI-стеком → `references/blocking-risk.md`
- **Pitfalls** — the full list of expensive mistakes → `references/pitfalls.md`

## Certificates

Full text → [references/certificates.md](references/certificates.md)

## Client devices — always-on Linux desktop

The GNOME «Добавить VPN» dialog offers only OpenVPN / PPTP / WireGuard; our entry is VLESS over WS+TLS, so none of them apply and there is nothing to tick there. Do not answer that by adding a WireGuard/OpenVPN inbound to the server either — a new public surface with its own auth and none of the routing rules.

When the owner says he does not want to keep a client window open, the shape is a **daemon in TUN mode**, not a GUI app (Hiddify/v2rayA need the window; a local proxy on `127.0.0.1` only reaches apps that honour a system proxy). mihomo over the `clash.yaml` subscription is the cheapest base: that profile is already a complete config, so only a `tun:` block plus `dns.listen` get injected and can be re-injected on every refresh. Full recipe, systemd units, verification and pitfalls: `references/linux-always-on-client.md`; the GUI-free desktop variant (merge script, unit files, FlClash/`add route 0: file exists` trap) — `references/desktop-mihomo-tun.md`.

## Failover — off, deliberately

The owner removed automatic failover: `vpn-failover.timer` is `disabled`/`inactive` and the default route is pinned to `direct`. Do not re-enable it without an explicit request. Rationale: a silent flip to `direct` keeps the internet alive but leaves geo-gated services refusing in a way that looks like the tunnel works ("connected, but Gemini says no"), which is harder to diagnose than a dead tunnel. With the timer off an exit outage now costs only the scenario it carries — Google/Gemini falls from `fr` to the
`fi` fallback and then fails loudly, while everything on `direct` is untouched.

`failover.py` and the unit files stay on disk and in the repo, unwired — re-enabling is `systemctl enable --now vpn-failover.timer`. If a probe is ever restored, keep the cadence irregular (`RandomizedDelaySec=300` on a 15-minute timer) so it does not read as a bot, and test the logic on a copy of the config, never against the live probe host.

## Traps worth memorising

The three that cost the most, verbatim from `references/pitfalls.md`:

- **Never dump an outbound as JSON.** Trojan credentials live in `settings.servers[].password`, VLESS in
  `settings.vnext[].users[].id` — a "show me the outbound" print leaks the provider's shared keys and a
  client UUID straight into the chat. Print tag, protocol, address:port and stream network only, and
  mask anything whose key matches `pw|password|id|key|token`.
- A user's "the site is down" on one host is rarely the tunnel: check whether the requests reached the app at all before rebuilding anything (`references/client-drop-triage.md`, section 4d). Also check that the name **exists**: under a fake-ip client a nonexistent host is handed a `198.18.x.x` and simply hangs, so the browser reports `ERR_TIMED_OUT` instead of "server not found" and the tunnel takes the blame for a bad URL — `dig +short @1.1.1.1 <host>` plus the zone's record list settles it in one step.
- Writing nginx config through `printf`/heredoc mangles quotes and backslashes (`\"$request\"`, `\\S`), and `nginx -t` then fails on a file that looks fine on screen. Write generated snippets with Python `write_text` (staging under `/tmp` + `install -m 644` when a direct write to `/etc/nginx` is refused), test, then reload — the same trap bites fail2ban filter regexes. Same reason a python heredoc embedded in a compound `cmd1 && python3 - <<EOF` block can silently produce a truncated file (16 bytes, no error): put the generator in its own file and run it.
