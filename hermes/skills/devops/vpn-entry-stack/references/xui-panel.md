# 3x-ui panel - removed from this stack

**Status: deleted.** Container, `xui-data` volume, `/panel/` route in `brand.json`, the
credentials file, the panel vhost, its `limit_req` zone and its fail2ban jail are all gone.
Do not go looking for the panel, and do not reintroduce one without an explicit request.

Why it went: it managed two idle inbounds that no client used, while the live routing lives in
`config.json` as entry-tag -> specific-exit chains that a panel cannot express. The only thing
it still contributed was a public admin surface. The Xray binary was extracted to
`/usr/local/bin/xray` first, because the probe scripts had been borrowing it from the container.

What replaced it: `vpn-cfg` (`references/router-ops.md`) for edits, validation, restart and
rollback, and nginx access logs for the little traffic visibility that matters.

## If a UI is ever reintroduced

Keep the two hard-won details, they cost real debugging time:

1. **CSRF.** Behind a proxy the panel answers every login with 403 unless the vhost forwards
   the original `Host` (with port), `X-Forwarded-Proto` and `X-Forwarded-For`, and the client
   echoes a matching `Origin`/`Referer`. A generic VLESS location template will not do; the
   panel needs its own location block.
2. **Login test.** `POST /login` alone always returns 403 and proves nothing. Fetch the page
   with a cookie jar, pull the `csrf-token` meta value, then post with `X-CSRF-Token` and the
   jar. Success is `{"success":true,...}` - a 200 with an empty body is not a login.

If it is ever published, put it behind a rate limit and a fail2ban jail from the start, and
remember the panel is reachable on every port that `apply_brand.py` renders.
