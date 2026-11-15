# «Нас не съели ли VPN-клиенты?» — три замера вместо догадок

"Everything on the VPN got slow" is answered by measuring three different links, in this order:

1. **Host uplink** — `curl -s -o /dev/null -w '%{speed_download}' 'https://speed.cloudflare.com/__down?bytes=50000000'`
   (measured here: ~170 MB/s ≈ 1.36 Gbit/s, and `tc -s qdisc` showed `dropped 0`, so the host throttles
   nobody — a saturated host link is the *least* likely cause). Two rules for reading that number: a single stream is
   **not** the channel (here one stream gives ~0.9–1.8 Gbit/s down but only ~330 Mbit/s up, while 4 parallel
   streams aggregate ~4.5 Gbit/s down and ~1.2 Gbit/s up — measure the aggregate when the question is «какой
   у нас канал»), and `__down?bytes=` silently caps at 100 MB: a `bytes=200000000` request came back as **1
   byte**, so keep probes at 50 MB and repeat them.
2. **Per-exit throughput** — `scripts/probe-exit-speed.py <tag>`: builds a socks client from that
   outbound, prints exit IP + MB/s, never prints credentials. Measured here: `fr` 10.4 MB/s (Paris),
   `fi` 17.3 MB/s (Helsinki) — borrowed exits are shared with the reseller's other clients, so that is
   the real ceiling for everything routed through them, not the host's gigabit.
3. **The complaining client** — `ping -c5 <his ip>` (0 % loss / 41 ms here rules out the path) plus the
   plus the request gaps in the nginx log.

   **The `.ru` ceiling is now whatever the subscription RU nodes give, not the owned box.** `ru1`
   (217.197.114.197) was a hard **100 Mbit/s** port (88–90 down / 81–95 up in one stream, 43 ms RTT to
   Tallinn) and it is **no longer in the rotation** — the owner dropped it. Today's `.ru` path is `p15`
   (Moscow) / `p17` (Novosibirsk) over shared reseller capacity, so the honest answer to «какой у нас канал»
   is: гигабиты on the Estonian host, and `.ru` depends on the reseller's load — measure it, do not inherit
   the old 100 Mbit figure. Measuring through the
   tunnel needs the outbound copied verbatim into a socks-only client (never printed); single-stream numbers
   there also hide a ~1/3 connection-failure rate, so run a burst before calling an exit healthy.

`vnstat` is installed for per-hour history — **`ens3` only**, because it otherwise auto-adds every
`veth`/`docker0`/`br-*` and the DB fills with noise:

```bash
apt-get install -y vnstat && systemctl enable --now vnstat
for i in $(vnstat --json | python3 -c "import json,sys;print(' '.join(x['name'] for x in json.load(sys.stdin)['interfaces'] if x['name']!='ens3'))"); do vnstat --remove -i "$i" --force; done
systemctl restart vnstat
```

There is **no** data before its install date — never answer a past-saturation question from it, and say
plainly that the history starts now.
