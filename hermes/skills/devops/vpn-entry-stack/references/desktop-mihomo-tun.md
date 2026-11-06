# Always-on VPN on a desktop Ubuntu (mihomo + TUN, no GUI client)

Owner wants the tunnel up without any app window open and without a GNOME VPN profile:
GNOME's «Добавить VPN» dialog speaks only OpenVPN/PPTP/WireGuard, our entry is VLESS over
WS+TLS, so the OS dialog is a dead end. Run a daemon instead.

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

## Pitfalls

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
- Trailing `\;` in a pasted multi-line block turns `curl https://ipinfo.io/ip;` into
  `https://ipinfo.io/ip\;` — ipinfo answers `404 {"title":"Wrong ip"}` and it reads like a broken
  tunnel. Send commands one per line.
- GNOME shows nothing in its VPN list — that is expected, the tunnel lives below the network applet.
  Say it up front so the owner does not go looking for a toggle.
- No killswitch by default; `strict-route: true` only prevents leaks when the uplink changes. Offer
  nftables separately instead of quietly adding it.
