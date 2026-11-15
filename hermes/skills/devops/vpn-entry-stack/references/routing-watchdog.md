# Routing is a moving target — a watchdog rewrites it every minute

The owner's model — and he is **strict** about it: **`fr` and `fi` carry Google/Gemini only; `p15`/`p17` carry `.ru`
and nothing else; EVERYTHING else goes to the Estonian `direct` exit.** A `catch-all → fr` rule is therefore
forbidden, including for `/ws` (an old «мой профиль целиком через Францию» leftover — the owner caught it and
called it out). Rule order that satisfies him: api → private/bittorrent blocks → Google domains → RU domains →
Google IP ranges → **catch-all `direct`**. **Keep the `protocol: bittorrent → blocked` rule**: the owner confirmed
it stays deliberately — a shared rented IP plus torrent DHT leaks mean abuse tickets and a possible null-route,
and he prefers to carry no external problems. Removing it needs his explicit word. The owned `ru1` box (`217.197.114.197`) was **dropped from the rotation by the
owner** («он объективно дерьмо»): outbound deleted, `bal-ru = [p15, p17]`, observatory `[fi, fr, p15, p17]`.
Re-adding it means rebuilding the outbound from `references/owned-ru-exit.md`, not just a selector edit. `/ws` is an entry, not an exception: its traffic walks the same rule list, so it also lands on `direct`
unless the domain matches Google or `.ru`.

`vpn-scenarios.timer` runs `scenario_fallback.py` **every 60 s** (`OnUnitActiveSec=60s`,
`RandomizedDelaySec=30`): it probes the exits, rewrites the `bal-google` / `bal-ru` selectors in
`/root/vpn-router/config.json`, then calls `vpn-cfg apply` itself. That is **not** the disabled
`vpn-failover.timer` (see «Failover — off»): both units exist, only this one is wired. Consequences:

- **Never call the routing "misconfigured" from one read of `config.json`.** The RU selector flips with
  probe results, so a value read a few minutes ago may already be gone and any note about it goes stale
  the same way. Before judging, read the moving parts: `stat -c '%y' /root/vpn-router/config.json`,
  `ls -lt /root/vpn-router/backups/config-*.json | head`, `journalctl -u vpn-scenarios -n 20`, and
  `/root/vpn-router/scenario_state.json`. A ~50/50 alternation in the backups is the signature of the
  flap, not of a hand edit. The same rule covers answering «какая у нас топология?»: build that answer from
  `scenario_state.json` plus the ws paths the subscriptions actually use
  (`grep -ho 'path: "[^"]*"' /var/www/esmien-sub/*/clash.yaml | sort | uniq -c`) — an inbound with no
  `inboundTag` rule of its own is the only thing the catch-all sees, so a `tcp,udp → fr` tail proves nothing
  about the paths clients really dial. If the owner pushes back on a routing claim you made from a single
  dump, re-read the live state before defending it: a snapshot is not a topology.
- The flips look like a defect even when nothing is broken: `PROBE_URLS_RU` mixes `ya.ru` and `mail.ru`
  with a **Google** `connectivitycheck.gstatic.com` picked at random, `http_through` counts only
  `2xx/3xx` as alive, and the TCP pre-check times out at 3 s — so a healthy RU node is declared `DEAD`,
  RU traffic drops to `direct` (Estonia) and returns minutes later. Read the report line
  (`ru1:ok(46ms)` vs `ru1:DEAD(-ms)` — the dash means the TCP pre-check failed) before blaming a rule.
  When changing probe targets, keep them RU-hosted *and* accept any HTTP answer (a `403` from a bank
  still proves the tunnel works; a `2xx`-only rule marks a live node dead).
- `config.json` is only the **A** colour's draft: xray reads its config at start, so a rewrite changes
  nothing until `vpn-cfg apply` derives `config.b.json` (ports +1000), restarts the idle container and
  flips nginx. Check which side clients really use (`cat /root/vpn-router/vpn-color`,
  `ss -tn state established | grep -oE ':1[01]0[0-9]{2}'`) — draft and live colour can disagree for
  hours, and only the live one explains what the owner sees.
- **Never leave `vpn-cfg apply` behind a 300 s subprocess timeout.** 24 inbounds to probe blow past it,
  the `TimeoutExpired` traceback kills the unit with `status=1`, and the draft is left in whatever state
  the probe produced for the next real apply. Applying is an owner decision, not a timer's.
