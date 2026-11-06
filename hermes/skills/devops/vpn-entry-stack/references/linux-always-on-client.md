# Always-on VPN on a Linux desktop (mihomo + TUN)

For an Ubuntu machine that must be behind our entry without any client window open. Validated on mihomo 1.19.33 against the live `clash.yaml` subscription.

## Why not the native dialog, why not a GUI app

- GNOME «Добавить VPN» speaks OpenVPN / PPTP / WireGuard only. Our entry is VLESS over WebSocket+TLS — no checkbox can express it. Adding a WireGuard inbound on the server would work but creates a second public entry with its own auth, outside every routing rule we built; do not propose it as the easy path.
- Hiddify / v2rayA / NekoRay are windows: close them and the tunnel is gone. A client that only exposes SOCKS/HTTP on `127.0.0.1` covers just the apps that honour a system proxy.
- What the owner actually wants = a **daemon**: systemd service, TUN device, `auto-route`, starts at boot, nothing to keep open. It never appears in the GNOME VPN list, and should not — it sits below the network settings layer.

## Which subscription format to build on

Both formats are complete configs, not outbound lists — check before writing any merge logic:

| format | inbound | rules | final | usable as-is? |
|---|---|---|---|---|
| `clash.yaml` (Clash/Mihomo UA) | `mixed-port: 7890` | Google→FR, RU→Moscow relay, `GEOIP,RU`, ends `MATCH,<node>` | in `MATCH` | yes — only `tun:` + `dns.listen` missing |
| `singbox.json` (sing-box UA) | `mixed` on 2080 | 4 rules incl. catch-all rule | none | needs `tun` inbound **and** a `dns` block, and sniffing semantics differ between 1.11/1.12 |

Mihomo wins for desktop always-on: the format is stable across versions, the profile already carries fake-ip DNS and the full rule set, and a top-level `tun:` key can simply be appended (valid YAML) so the same patch works on every refresh.

## Install

```bash
# IPv6 off first: the profile sets ipv6: false, so v6 traffic would bypass the tunnel
sudo sysctl -w net.ipv6.conf.all.disable_ipv6=1
echo 'net.ipv6.conf.all.disable_ipv6=1' | sudo tee /etc/sysctl.d/99-no-ipv6.conf

sudo mkdir -p /opt/mihomo
VER=$(curl -fsSL https://api.github.com/repos/MetaCubeX/mihomo/releases/latest | sed -n 's/.*"tag_name": *"v\([^"]*\)".*/\1/p')
curl -fLo /tmp/m.gz "https://github.com/MetaCubeX/mihomo/releases/download/v${VER}/mihomo-linux-amd64-compatible-v${VER}.gz"
sudo gunzip -c /tmp/m.gz | sudo tee /opt/mihomo/mihomo >/dev/null
sudo chmod +x /opt/mihomo/mihomo && /opt/mihomo/mihomo -v
```

Use the `-compatible` build on amd64 (the default needs a newer GOAMD64 level); `arm64` asset for ARM laptops.

## Profile refresh script

`/usr/local/bin/vpn-sub-update.sh` — fetches, patches, validates, swaps:

```bash
#!/usr/bin/env bash
set -euo pipefail
SUB='https://<host>:8443/sub/<token>'   # same link the phone uses in Happ
DIR=/etc/mihomo; mkdir -p "$DIR"
TMP=$(mktemp); NEW="$DIR/config.yaml.new"
trap 'rm -f "$TMP" "$NEW"' EXIT
curl -fsS -m 30 -A 'ClashMeta/1.19.33' "$SUB" -o "$TMP"
python3 - "$TMP" "$NEW" <<'PY'
import sys
s = open(sys.argv[1]).read().replace(
    'dns:\n  enable: true\n', 'dns:\n  enable: true\n  listen: 0.0.0.0:1053\n', 1)
s += """
tun:
  enable: true
  stack: mixed
  device: esmien0
  mtu: 1400
  auto-route: true
  auto-detect-interface: true
  strict-route: true
  dns-hijack:
    - any:53
"""
open(sys.argv[2], 'w').write(s)
PY
/opt/mihomo/mihomo -t -d "$DIR" -f "$NEW" >/dev/null
mv "$NEW" "$DIR/config.yaml"
systemctl restart mihomo
```

The `config.yaml.new` + `mv` after `mihomo -t` is what keeps a broken provider answer from replacing a working tunnel — the test must gate the swap, not follow it.

## Units

`/etc/systemd/system/mihomo.service` — `Type=simple`, `ExecStart=/opt/mihomo/mihomo -d /etc/mihomo -f /etc/mihomo/config.yaml`, `Restart=always`, `RestartSec=3`, `LimitNOFILE=1048576`, `After=/Wants=network-online.target`, `WantedBy=multi-user.target`. Runs as root (TUN needs it); no ambient capabilities needed.

`mihomo-update.service` (`Type=oneshot`, `ExecStart=/usr/local/bin/vpn-sub-update.sh`) + `mihomo-update.timer` (`OnCalendar=*-*-* 04:00`, `RandomizedDelaySec=1800`, `Persistent=true`).

Enable: `systemctl enable --now mihomo mihomo-update.timer`. Disable: `systemctl disable --now mihomo mihomo-update.timer`.

## Verification

```bash
ip -br addr show esmien0                                    # tun device up
curl -s https://ipinfo.io/ip                                # Estonian exit, no proxy flags
curl -s -o /dev/null -w '%{http_code}\n' http://www.gosuslugi.ru   # 3xx — went to the Moscow relay
curl -s https://www.wildberries.ru | grep -o 'data-req-ip="[^"]*"' # RU node address
journalctl -u mihomo -n 30 --no-pager                       # when nothing works
```

## Pitfalls

- **Never enable `tun` while validating on the production server** — `auto-route` would hijack the host's own routing. Prove the chain with `tun.enable: false` on a spare `mixed-port` and `curl -x http://127.0.0.1:<port>`, then ship the tun block to the client only.
- `tun.dns-hijack: any:53` needs mihomo's resolver to listen: insert `listen: 0.0.0.0:1053` into the existing `dns:` block. Without it DNS dies the moment the tun comes up.
- `GEOIP,RU` needs `geoip.metadb`/MMDB; mihomo downloads it on first start automatically. A first run without network looks like a config error — check the log line `Can't find MMDB, start download` before touching the rules.
- `mihomo -t -d <dir> -f <file>` is the validation gate; it prints `test is successful`. A tun block with a typo passes `-t` only if the keys exist — keep the block byte-identical between clients instead of retyping it.
- `mtu: 1400` on the tun device; the 9000 default invites a PMTU blackhole on mobile/hotspot links.
- Kill test instances by PID (`kill <pid>`), never `pkill -f 'mihomo -d …'` — the pattern matches the shell running the command, and that shell is the caller.
- Subscription tokens are credentials: put the link in the script on the client, never echo it back in chat, and point the owner at the link he already has in Happ or at `https://<host>:8443/u/<token>` rather than printing a token.
