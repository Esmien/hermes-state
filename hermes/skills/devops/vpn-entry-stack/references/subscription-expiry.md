# Subscription expiry

The provider's expiry is in the `subscription-userinfo` response header of any subscription URL — `upload=…; download=…; total=…; expire=<unix>`, with `expire=0` meaning no limit. Read it from there; the biller bot and the panel page phrase it differently and go stale.

`/root/vpn-router/sub_expiry.py` reads `/root/vpn-router/subs.json` (0600, name + url pairs, never committed) and `vpn-sub-expiry.timer` runs it daily at 07:00 UTC (10:00 MSK) to message the owner at 3, 2 and 1 days before each expiry, plus once if a subscription has already lapsed. Dedup state is `sub_expiry_state.json`, keyed `<date>:<days left>`, so a second run on the same day stays silent; `--test` proves delivery, `--force` sends the report outside the schedule. A new subscription is one more line in `subs.json` — the script needs no edit.
