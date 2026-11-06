# Scenario routing (server-side) and the one-node subscription

The owner's model: **one visible node, every scenario decided by the server**. Google goes to
France, RU sites to the RU pool, everything else — including YouTube — exits Estonia. The
subscription shows a single node — «🇪🇪 Эстония (все сервисы)» — because a second choice is not
cosmetic: whoever taps another node burns the *provider's* subscription traffic and raises the
ban risk.

## Config pieces (entry, `config.json`)

- `routing.balancers`: `bal-google`, `bal-ru`, strategy `leastPing`.
- `observatory`: `subjectSelector` = the scenario outbounds, `probeUrl` gstatic 204,
  `probeInterval: 30s`. Without it `leastPing` has nothing to rank by.
- Rules, in this order, **before** every `inboundTag` rule:
  1. google domains (`google.com`, `googleapis.com`, `gstatic.com`, `googleusercontent.com`,
     `withgoogle.com`, `google.dev`) → `bal-google`;
  2. RU (`.ru/.su/.рф` + RU-only services) → `bal-ru`;
  then the inbound rules, the google-IP block (repointed to `bal-google`) and the catch-all.
  **YouTube has no scenario**: the owner dropped it after hearing the price — every byte on a
  relay is the provider's subscription traffic, and ad-free YouTube was not worth it. YouTube
  rides the Estonian exit with everything else; do not reintroduce it without a direct request.
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
(google) keep exactly one tag. Writes `config.json` and runs `vpn-cfg apply` **only when
the selector actually changes**, so a healthy day costs zero restarts. A temporary manual swap
(`{"bal-yt": ["p16","direct"]}` in `scenario_override.json`, loaded by `scenario_routes`) is
how a scenario is re-pointed for a test without editing code — and without the watchdog
reverting it on its next pass.

Honest latency, do not oversell it: a dead node leaves rotation in ~30 s (observatory), a whole
dead group falls back to Estonia in ~1–2 min (watchdog). «5–10 секунд» is only true when the
watchdog interval itself is that tight, so do not put that number in user-facing copy without
re-measuring.

## Verification (cheap, reversible)

1. Canary rules prove both the rule and the exit: temporarily insert
   `{"domain":["domain:ipinfo.io"],"balancerTag":"bal-google"}` (and the same shape for any other
   group), `vpn-cfg apply`, then read the egress through `/general` — `82.148.254.97` (Paris) here.
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
- `announce` must be **plain UTF-8 on one line**, not base64: Happ renders a base64 value
  literally, and the user sees a wall of `8J…` characters in the profile card. A header cannot
  carry CR/LF, so flatten the text (`" ".join(text.split())`).
- Happ draws the announce in a **fixed ~3-line block (~70 chars per line) and truncates silently**
  — a 313-char text lost half its sentences mid-word. Keep it ≤ ~170 chars, one emoji per block,
  and put the important line last; the multi-line version belongs in the `clash.yaml` header and
  on `/u/<token>`. The page intro needs a real `<ul>` with spacing — `<br>`-joined sentences read
  as one run-on paragraph.
- `apply_brand.py` used to build the title/announce maps **before** running `make_sub.py`, so
  every regeneration shipped the previous text (and the previous filename) to clients while the
  files on disk were already correct. Render subscriptions first, then build the maps.
- Never promise a failover time you have not measured: the copy originally said «5–10 секунд»,
  the real numbers are ~30 s (node dropped from rotation) and 1–2 min (whole group → Estonia).
- Do **not** put Cyrillic in the `clash.yaml` header: FlClash renders YAML comments as the
  profile description and shows UTF-8 there as mojibake (a screenful of garbage on its home
  tab). The meta profile opens with a single ASCII `# Esmien VPN` line; readable copy lives in
  the `announce` header (Happ) and on `/u/<token>`.
- Migrating a live token to this kind is additive: snapshot `md5sum` of `/var/www/esmien-sub/*/*`,
  write `kind=meta`, run `make_sub.py`, prove every other token's files are byte-identical.

## Rolling it out to everybody

1. Snapshot: `md5sum` every file under `/var/www/esmien-sub/*/*` into a JSON map keyed
   `<dir>/<file>`, then write `kind=meta` into each **main** token dir (never the LTE/whitelist
   dirs — their whole point is direct provider nodes).
2. `python3 make_sub.py`, then diff the map: only main dirs may change, and every LTE file must be
   byte-identical. Print per user `узлов в list`, `proxies в clash`, `announce` present.
3. `python3 apply_brand.py && nginx -t && systemctl reload nginx` — the announce map only gains a
   token if its `announce` file exists, so check the printed token list.
4. Prove **each** per-user key still authenticates through the single node: for every token build
   a throwaway client from the first `list.txt` link (uuid, ws path, sni from the link itself)
   and `curl -x socks5h://… https://ipinfo.io/ip`. Six users must all return the Estonian exit;
   a wrong or duplicated uuid shows up as silence, not as an error message.

Old direct node links keep working after the switch (the inbounds still exist), so nobody drops
mid-refresh — say that out loud when the family is asked to update their subscription.

## Pitfalls

- The watchdog must re-read `config.json` **right before writing** and touch only selectors of
  groups that still exist: a pass that started before someone else edited the config otherwise
  writes its stale copy back and resurrects a removed balancer/rules. `vpn-cfg apply` and the
  watchdog share `/var/lock/vpn-config.lock` (`flock`), or two applies overlap.
- A removed scenario leaves its rule and outbound running on the *drained* container until the
  next flip (that is what blue/green means), so verify the cleanup with a second `apply`, not
  by counting sockets straight after the first.
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
