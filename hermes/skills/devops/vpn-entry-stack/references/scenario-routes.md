# Scenario routing (server-side) and the one-node subscription

The owner's model: **one visible node, every scenario decided by the server**. Google goes to
France, RU sites to Moscow, YouTube to Albania, everything else exits Estonia. The subscription
shows a single node — «🇪🇪 Эстония (все сервисы)» — because a second choice is not cosmetic:
whoever taps another node burns the *provider's* subscription traffic and raises the ban risk.

## Config pieces (entry, `config.json`)

- `routing.balancers`: `bal-google`, `bal-ru`, `bal-yt`, strategy `leastPing`.
- `observatory`: `subjectSelector` = the scenario outbounds, `probeUrl` gstatic 204,
  `probeInterval: 30s`. Without it `leastPing` has nothing to rank by.
- Rules, in this order, **before** every `inboundTag` rule:
  1. google domains (`google.com`, `googleapis.com`, `gstatic.com`, `googleusercontent.com`,
     `withgoogle.com`, `google.dev`) → `bal-google`;
  2. youtube (`youtube.com`, `googlevideo.com`, `ytimg.com`, `youtu.be`,
     `youtube-nocookie.com`, `ggpht.com`, `yt.be`) → `bal-yt`;
  3. RU (`.ru/.su/.рф` + RU-only services) → `bal-ru`;
  then the inbound rules, the google-IP block (repointed to `bal-google`) and the catch-all.
- `scenario_routes.py install` builds all of that idempotently; `set-selector <group> <tags…>`
  rewrites one selector (the watchdog's only write).

## `leastPing` is not ordered

A `bal-google` over `["fr","fi"]` picked **Finland** over France in practice — leastPing ranks by
probe latency, not by preference. When a scenario has a primary and a reserve, keep **one** tag in
the selector and let the watchdog promote the reserve; the balancer is then just a named slot.
RU keeps all three relays (all equivalent) so leastPing genuinely spreads.

## Watchdog (`scenario_fallback.py`, timer 60 s + `RandomizedDelaySec=30`)

Probes every scenario node the way a client would: TCP handshake first (that is what Happ's own
ping shows) and then one HTTP 204 **through** the node, using a throwaway Xray client with one
socks inbound per node and routing keyed on `inboundTag`. Jitter is mandatory — randomised start
delay, shuffled probe order, random target URL and user agent — a fixed rhythm hammering provider
nodes is the abuse signature their panels ban for.

Decision: keep the alive nodes of the group; `direct` when none is alive. `SINGLE` groups
(google, youtube) keep exactly one tag. Writes `config.json` and runs `vpn-cfg apply` **only when
the selector actually changes**, so a healthy day costs zero restarts.

Honest latency, do not oversell it: a dead node leaves rotation in ~30 s (observatory), a whole
dead group falls back to Estonia in ~1–2 min (watchdog). «5–10 секунд» is only true when the
watchdog interval itself is that tight, so do not put that number in user-facing copy without
re-measuring.

## Verification (cheap, reversible)

1. Canary rules prove both the rule and the exit: temporarily insert
   `{"domain":["domain:ipinfo.io"],"balancerTag":"bal-google"}` and
   `{"domain":["domain:ipify.org"],"balancerTag":"bal-yt"}`, `vpn-cfg apply`, then read the
   egress through `/general` — `82.148.254.97` (Paris) and `157.22.240.212` (Albania) here.
   Re-running `scenario_routes.py install` drops the canaries; apply again.
2. Real requests through `/general`: plain host → Estonian IP; `gemini.google.com/app` → `200` and
   no "not available in your country"; `wildberries.ru` → `data-req-ip` carries the RU node.
3. `gemini_geo_check.py` can report `no geo marker in response` on a page that actually loaded —
   the marker is markup-dependent; trust the two checks above instead of that one tool alone.
4. Watchdog dry run: `scenario_fallback.py --dry-run` prints per-node `ok(123ms)`/`DEAD(-)` and the
   verdict per group.

## Subscription side

- `make_sub.py` has a `meta` kind (`<token>/kind` = `meta`): one proxy, one `select` group with
  that single entry, `MATCH,Esmien VPN`; sing-box gets one outbound; `list.txt` gets one link.
  No client rules at all — the server enforces the scenario anyway.
- The full text goes into the `clash.yaml` header as `# ` comments (engines ignore comments, the
  file stays readable for whoever opens the profile) and as an `announce` header for Happ.
- `announce` is base64 of UTF-8 plain text; `apply_brand.py` maps it per token from
  `<token>/announce`, and an empty value makes nginx drop the header for every other token.
  Happ shows it as an in-app notice; ~5 lines is the safe size, the long version belongs on the
  `/u/<token>` landing page.
- Migrating a live token to this kind is additive: snapshot `md5sum` of `/var/www/esmien-sub/*/*`,
  write `kind=meta`, run `make_sub.py`, prove every other token's files are byte-identical.

## Pitfalls

- `make_template.py` copied `routing.balancers` and `observatory` verbatim, so the secret-free
  template referenced provider relays a fresh deploy does not have and would not start. Filter
  selectors against the kept outbounds and drop balancers/observatory left empty.
- A canary rule inserted by index shifts the rules around it; restore by re-running the builder,
  not by deleting a line by hand.
- The provider relay list can change under us; after `import_sub.py` on a rebuild re-run
  `scenario_routes.py install`, or the balancers point at tags that no longer exist and only the
  lint (never `xray -test`) catches it.
- A `meta` subscription kills the client-side rules that used to carry the scenarios: if the
  desktop mihomo profile is rebuilt from that token, do not re-add RU/Google rules there — the
  entry does it now, and two layers drift apart silently.
