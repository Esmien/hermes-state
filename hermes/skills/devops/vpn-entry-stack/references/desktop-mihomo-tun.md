# Always-on VPN on a desktop Ubuntu (mihomo + TUN, no GUI client)

Owner wants the tunnel up without any app window open and without a GNOME VPN profile:
GNOME's «Добавить VPN» dialog speaks only OpenVPN/PPTP/WireGuard, our entry is VLESS over
WS+TLS, so the OS dialog is a dead end. Run a daemon instead.

## Toggle: `sudo vpn on|off|status` (`/usr/local/bin/vpn`)

The owner asked for exactly this shape — `on` (Estonia up) and `off` (tunnel down, FlClash free to
run again), nothing in between. `on` stops FlClash first, refreshes the profile, starts the unit,
waits for `esmien0`, then prints the exit IP; `off` stops the unit and reports leftovers.

- **No killswitch.** It was offered and refused in plain words («я не защищаюсь, я просто хочу
  пользоваться заблокированными сервисами»): if the tunnel dies, traffic going out directly is
  acceptable. Never reintroduce nftables blocking unasked; `strict-route: true` already handles the
  one leak that matters (uplink change), and anything more is offered as a separate opt-in.
- The nightly `vpn-sub-update.sh` timer must restart the unit **only when it is active**, otherwise
  `vpn off` is silently undone at 04:00: `systemctl is-active --quiet mihomo && systemctl restart mihomo`.
- `vpn status` is the one-command health check: service state, `esmien0`, whether FlClash runs, exit IP.
- The desktop profile can be the one-node `meta` subscription: client-side RU/Google rules must not be
  re-added there, the entry decides those (see `scenario-routes.md`).

## Recipe (validated on the owner's laptop, 2026-11)

Binary: `mihomo-linux-amd64-compatible-*.gz` from `MetaCubeX/mihomo` releases (the
`-compatible` build avoids GOAMD64 v2/v3 SIGILL on older CPUs), unpacked to
`/opt/mihomo/mihomo`.

Profile: fetch `https://<host>:8443/sub/<token>` with `-A 'ClashMeta/1.19.33'` — the nginx
UA map then serves `clash.yaml` (a `curl` UA gets the base64 `list.txt`, which mihomo cannot
read). Merge in, at the top level of the YAML:

- inside `dns:` → `listen: 0.0.0.0:1053` (needed for `dns-hijack` to have a server);
- appended block `tun: {enable, stack: mixed, device: esmien0, mtu: 1400, auto-route,
  auto-detect-interface, strict-route, dns-hijack: [any:53]}`.

Fetch/merge/validate/replace in one script (`/usr/local/bin/vpn-sub-update.sh`): write to
`config.yaml.new`, `mihomo -t -d <dir> -f <new>`, only then `mv` over `config.yaml` and
`systemctl restart mihomo`. A daily `mihomo-update.timer` runs it, so node changes arrive
without touching the machine.

Unit: plain `Type=simple`, `ExecStart=/opt/mihomo/mihomo -d /etc/mihomo -f /etc/mihomo/config.yaml`,
`Restart=always`. Root is required for TUN; no AmbientCapabilities needed.

Also disable IPv6 (`net.ipv6.conf.all.disable_ipv6=1`): the profile ships `ipv6: false`, so v6
traffic would leave outside the tunnel and flip the Gemini/geo verdict.

Verify by behaviour: `ip -br addr show esmien0` (expect `198.18.0.1/30`), `curl -s https://ipinfo.io/ip`
→ Estonian exit, `curl -s -o /dev/null -w '%{http_code}' http://www.gosuslugi.ru` → 3xx (Moscow relay).

## Subscription token: rotatable, never hardcoded

The token lives in `/etc/mihomo/sub.url` (root, 0600), not in the scripts — rotation is
`sudo vpn edit <url|token>` (`/usr/local/bin/vpn-sub-edit`): it strips whitespace/quotes,
extracts the tail of a pasted URL (or builds one from a bare token), fetches it with the
`ClashMeta` UA to prove 200 + `^proxies:` before writing, prints only the last 4 chars, then
re-runs the updater if the tunnel is active and **rolls the URL back** if that fails. `vpn`
itself stays untouched except for a 4-line guard right after `set -uo pipefail`:
`if [ "$1" = edit ] → shift; exec vpn-sub-edit "$@"` — patch it with python3(find + insert), never
by rewriting the file, so local edits made during the install survive.

Updater reads the URL from that file, so a new token is one command, no editing of scripts.

## Pitfalls

- **Pasted heredocs carry a stray backslash before `;`.** The owner's terminal turned
  `curl … api.ipify.org; echo` into `api.ipify.org\; echo` *inside* a `tee <<'EOF'` body, so the
  script silently requested a URL ending in `;`. Build any script you send him **without a single
  `;`** — multi-line `then`/`fi`, `if [ $? -ne 0 ]` instead of `|| { … ; … }`, no `case … ;;` — then
  verify with `grep -c ';' /usr/local/bin/<script>` (expect 0) and `bash -n`. This removes the whole
  class of failure instead of asking him to hunt backslashes.

- **A second Clash-family client owns everything.** FlClash/Hiddify sitting in the tray grabs
  `127.0.0.1:7890`, the `FlClashX` interface, `198.18.0.0/30` and routing table 2022. mihomo then
  fails with `Start Mixed(http+socks) server error: bind: address already in use` and
  `Start TUN listening error: configure tun interface: add route 0: file exists`, while traffic
  already flows through the other app and looks like a success. Diagnose with
  `ip rule show` + `ip route show table all | grep 198.18`: a `FlClashX`/`198.18.0.0/30` line is the
  tell. Quit that app (tray → Quit, plus `~/.config/autostart/*clash*.desktop`) before blaming mihomo.
- `add route 0: file exists` is *never* a kernel quirk — something already owns that route/table.
- Script edited with a placeholder token (`.../sub/ТОКЕН`) plus `set -e` and `curl -f` exits with no
  output at all — reads as «терминал просто закрылся». Keep `set -uo pipefail` (no `-e`) and print an
  explicit message per failure step; give the owner `bash -x` as the debug path.
- The owner's zsh turns a pasted `;` into `\;` **inside a heredoc body too**, so a script created with
  `sudo tee … <<'EOF'` can silently contain `https://api.ipify.org\; echo` — curl then requests a URL
  ending in `;` and an extra `echo` argument, and `-s` hides the failure as an empty line. After any
  heredoc-created script, grep it for backslashes (`grep -n '\\' /usr/local/bin/<script>`) before debugging
  behaviour. Trailing `\;` on a pasted command line has the same effect: `curl https://ipinfo.io/ip;`
  becomes `https://ipinfo.io/ip\;` and ipinfo answers `404 {"title":"Wrong ip"}`. Send one command per
  line, never a block joined by `;`.
- GNOME shows nothing in its VPN list — that is expected, the tunnel lives below the network applet.
  Say it up front so the owner does not go looking for a toggle.
