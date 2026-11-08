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

## Health checks decide the route, so build them for the node's country

- `observatory.subjectSelector` must list **every** tag a balancer can select. A balancer over a
tag the observatory never probes gets no health data and forwards nothing: `.ru` requests hang
until the client times out, while `xray -test` and the lint stay green and the config looks
perfect. Derive the selector from the union of `PREFERENCE` values at install time instead of a
hand-written list — otherwise a newly added outbound works when dialled directly and stalls only
in production.
- Probe URLs must answer **from the node's country**. `gstatic 204` times out from a RU datacenter,
so a perfectly healthy RU exit reads DEAD. Keep a per-group pool (`ya.ru`, `mail.ru`, plus a
connectivity-check URL for RU nodes) and choose the pool by group membership, not once for all.
- Accept any `2xx`/`3xx` as alive. `ya.ru` and `mail.ru` answer `302`; an exact `{"200","204"}`
test marks every RU node dead, the watchdog then reverts the group to Estonia every minute, and
the route is broken by its own monitoring.
- Two independent health checks exist — observatory (`leastPing` + `fallbackTag`) and the watchdog
  (draft rewrite). **Live failover is the observatory's job now**: `fallbackTag` on each balancer
  (`bal-google`→`fi`, `bal-ru`→`direct`) makes xray move traffic itself in ~30–60 s when the only
  node of a group stops answering. The watchdog no longer touches live traffic at all — it writes
  `config.json` (a draft: xray reads a config only at start) and logs the verdict.
- **Never let the watchdog call `vpn-cfg apply`.** It holds `/var/lock/vpn-config.lock` for its whole
  run and `vpn-cfg` takes the same lock with `flock -w 300`, so the child waits for its own parent:
  every change died after exactly 300 s with a traceback, and nothing was ever applied. The tell in
  the journal is `применяю …` followed 300 s later by `TimeoutExpired`.
- A group that mixes an owned node with reseller relays flaps forever, because the relays are the
  unstable part. Keep the RU scenario on the owned node with `direct` as `fallbackTag`; relays go
  back in only on an explicit request.
- When relays do carry `.ru`, pick the tags by **purpose probes**, not by country label: on one pool
  `p16` (СПб) answered `tbank`/`avito`/`ozon` normally but `gosuslugi` with a steady `000`, so it was
  dropped and the selector became `p15` (Москва) + `p17` (Новосиб). Probe the sites the owner actually
  uses, then keep only the tags that pass all of them — a relay that carries half the list is worse
  than one fewer node, because the failures look intermittent.
- Measure the observatory path per pool instead of assuming it: the cloudflare `generate_204`
  **did** answer from reseller RU relays, so `leastPing` ranks them fine even though a bare RU
  datacenter was expected to time out. The watchdog's own probe targets stay RU-hosted regardless.
- Prove the flow reached the node itself, not merely that the page loaded:
`journalctl -u xray --since -1min | grep 'accepted tcp:www.gosuslugi.ru'` on the exit answers «did
this node carry it» in one line, and beats inferring it from a `200`.

## Watchdog (`scenario_fallback.py`, timer 60 s + `RandomizedDelaySec=30`)

Probes every scenario node the way a client would: TCP handshake first (that is what Happ's own
ping shows) and then one HTTP 204 **through** the node, using a throwaway Xray client with one
socks inbound per node and routing keyed on `inboundTag`. Jitter is mandatory — randomised start
delay, shuffled probe order, random target URL and user agent — a fixed rhythm hammering provider
nodes is the abuse signature their panels ban for.

Decision: keep the alive nodes of the group; `direct` when none is alive. `SINGLE` groups
(google) keep exactly one tag. **Hysteresis: a tag leaves the rotation only after 2 consecutive
failures in a row** — one bad probe is not a dead node, and the old single-failure rule is what made
`bal-ru` flap between `ru1` and `direct` every 5–11 minutes. Fail counters live in
`scenario_state.json` (`fails`). The draft is written only when a selector actually changes; it is
never applied automatically. A temporary manual swap (`{"bal-yt": ["p16","direct"]}` in
`scenario_override.json`, loaded by `scenario_routes`) is how a scenario is re-pointed for a test
without editing code.

**Probe targets (they decide whether the verdict is honest):**

- RU group → `http://www.tbank.ru/`, `http://www.avito.ru/`, `https://www.gosuslugi.ru/`. Plain HTTP
  for the first two: their HTTPS pages fail curl's trust check (Russian roots) or take >15 s, while
  the HTTP answer is a 301 in ~0.2 s. Never probe a RU exit against Google/Cloudflare — that path is
  slow from Russia on its own and produced false DEADs.
- **Alive = any HTTP answer except `000`.** A 403/429 from a bank or marketplace proves the path
  works; treating 2xx/3xx as the only success turns a live node into a dead one.
- Gemini geo (once per 10–15 min, jittered, ~170 KB gzipped): the unauthenticated `/app` shell is
  byte-identical from every country and carries **no** "not available in your country" text, so a
  body-string check cannot work. Read Google's own country from
  `this.gbar_={CONFIG:[[[0,"www.gstatic.com","<build>","<cc>","<lang>"` — EE answers `ru`
  (blocked), FR answers `co.uk` (supported). The regex must accept `co.uk`-style codes; `[a-z]{2}`
  reports the working exit as "check failed".

Honest latency, do not oversell it: a dead node leaves rotation in ~30–60 s (observatory +
`fallbackTag`), and the watchdog's draft catches up on its next passes. «5–10 секунд» is only true
when the probe interval itself is that tight — do not put that number into user-facing copy without
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
- One-off nodes for one person (typically an owned exit the owner wants to try by dialling it
  *directly*, no entry in the path): `<token>/extra_nodes.json` — a JSON list of
  `{"name", "link", "clash", "sing"}`. `build_meta` appends `link` to `list.txt`, `clash` to the
  `proxies:` block, `name` to the select group and `sing` to the sing-box `outbounds`; without the
  file the build is byte-identical to before. Verify over HTTP with both User-Agents
  (`curl` → base64 two links, `-A 'ClashMeta/1.19.33'` → two `- name:` lines) and confirm the
  other tokens still report one node. Delete the file to roll it back — no other edit needed.
- A hand-built test client must be restarted after every `apply`: an established WS session keeps
  talking to the drained colour, so a probe on the old client judges the previous config and the
  change looks "not applied". Kill the client, start a fresh one, then judge.

## Why the owner says it suddenly got faster

After the switch to one visible node the owner reports the whole web got faster — **including on
the phone, where no desktop daemon runs**. Do not credit the desktop TUN; the cause is
server-side: (1) no per-rule node switching on the client, which used to open a *new* WS session
and re-resolve names on every hop between «Франция» and «Эстония» mid-page; (2) the Google chain
now stays on one exit, so Google never sees the country change halfway through a session and
stops re-asking; (3) the old 20+-node list pinged every relay on each refresh and any of them
could be a dead reseller node. Measured throughput did not change — the number of handshakes and
country flips did.

When he compares against a third-party subscription that felt slower on «the same France»: a
reseller's «Франция» is their control server plus a rented IP (sometimes one more hop), sharing an
oversold uplink with other customers, while our France is an exit *we* dial directly. Offer to
measure it rather than argue — TCP ping and time-to-first-byte through his node versus ours turns
it into a number.

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

- `scenario_override.json` outranks the code and is easy to forget. `install()` reads it into
  `PREFERENCE`, while the balancer's selector comes from `GROUPS` — two sources feeding one script.
  A stale pin left from an earlier manual test (`{"bal-ru": ["ru1","direct"]}`) therefore keeps the
  observatory selector and the watchdog on a node you just removed, while the balancer prints the
  new tags and everything looks right. Check (and rewrite) the override file in the same pass as the
  code edit; reading it is enough, and overwriting that JSON needs no separate confirmation.
- Prove what the container actually loaded, not what is on disk: `docker cp
  vpn-router:/etc/xray/config.json /tmp/run.json` and compare with `config.json`. The file on disk
  can already carry the fix while the running pod still serves the previous generation, and every
  probe then "disproves" a change that is in fact correct.
- `ls` cheap before blaming the chain: an exit whose own `curl ipinfo.io/ip` answers with its
  public address is doing `freedom`; if the same address never shows up on the entry's timings,
  the request is not even leaving through that outbound.
- The watchdog must re-read `config.json` **right before writing** and touch only selectors of
  groups that still exist: a pass that started before someone else edited the config otherwise
  writes its stale copy back and resurrects a removed balancer/rules. `vpn-cfg apply` and the
  watchdog share `/var/lock/vpn-config.lock` (`flock`), or two applies overlap.
- A removed scenario leaves its rule and outbound running on the *drained* container until the
  next flip (that is what blue/green means), so verify the cleanup with a second `apply`, not
  by counting sockets straight after the first.
- To bring the idle colour onto the current config **without moving traffic**: `docker restart
  vpn-router-b` (or `vpn-router`, whichever is idle per `vpn-color`) and then
  `python3 vpn-bluegreen.py probe b` — 24 answers of `400` mean it is safe to flip. Do this after
  a batch of edits; otherwise the next `apply` restarts a container that is several changes
  behind, and the flip races that difference.
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
- Bound the hunt. If a routing change has not taken effect after two probe rounds, stop and report
  the three facts instead of iterating: what the running container loaded, what the selector and
  `observatory.subjectSelector` actually say, and the watchdog's verdict line. A long silent grind
  on one route reads to the owner as being stuck, and he will ask why it is taking 45 minutes.
