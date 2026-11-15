# Upstream subscriptions (relaying nodes)

Two pools, never mixed:

- **relay pool** — every usable upstream node becomes an inbound `/p<i>` (10100+i) on our host plus an outbound `p<i>`; clients reach it through us.
- **whitelist pool** — only the nodes the provider itself labels **«Глушилки»** are exported as raw upstream links (`whitelist_links.json`, 0600) into a **separate subscription of their own**, because under address allowlists our foreign entry is the first thing that gets cut. Classify by the provider's own label, never by geography: `Москва / СПб / Новосиб` nodes are ordinary RU-exit relays and belong in the relay pool, and a plan may contain no «Глушилки» at all (the PC plan has none, the mobile one has ten) — merge the pools only after the owner confirms which nodes he means.

Pitfall: Xray evaluates routing top-down. Inbound rules appended at the end land **after** the catch-all `network: tcp,udp → <default>` and are silently ignored — every relayed path then exits through the default outbound. Keep inbound-tag rules right after the block rules, before domain/ip/catch-all rules, and re-check one or two relayed paths against `ipinfo` after every import.

`import_sub.py` builds the whole relay set idempotently; `probe_sub.py` measures each node (exit IP + Google country) before it goes into the pool. Hysteria2 nodes are unusable — the Xray core does not speak it.
