# "VPN отваливается" — triage order

A drop report is answered with measurements, not with a guess. Prove the server end to end
first; only then look at the client. Each step below produces a number you can quote.

## 1. Server liveness

```bash
docker inspect vpn-router --format '{{.State.Status}} restarts={{.RestartCount}} {{.State.StartedAt}}'
systemctl is-active nginx
```

`running` with `restarts=0` and a start time from days ago means the container never died —
a crash loop would show a fresh `StartedAt` on every check.

## 2. End-to-end dial through our own entry

This is the definitive "is the tunnel itself broken" test: a local Xray client that speaks
VLESS+WS to `127.0.0.1:8443` with the live UUID, exactly like a real phone.

```python
import json, pathlib
uuid = pathlib.Path("/root/mtproto-faketls/ws-client-uuid").read_text().strip()
cfg = {"log": {"loglevel": "warning"},
 "inbounds": [{"tag": "s", "listen": "127.0.0.1", "port": 10888, "protocol": "socks",
               "settings": {"auth": "noauth", "udp": False}}],
 "outbounds": [{"tag": "proxy", "protocol": "vless",
   "settings": {"vnext": [{"address": "127.0.0.1", "port": 8443,
                             "users": [{"id": uuid, "encryption": "none"}]}]},
   "streamSettings": {"network": "ws", "security": "tls",
     "wsSettings": {"path": "/general", "headers": {"Host": "vpn.esmien.qd.je"}},
     "tlsSettings": {"serverName": "vpn.esmien.qd.je"}}}]}
pathlib.Path("/tmp/cli.json").write_text(json.dumps(cfg))
```

Start it as a tracked background process (never `nohup`/`setsid` — the tool refuses shell-level
backgrounding and it is easier to kill a tracked child), then measure:

```bash
curl -sS -m 60 --socks5-hostname 127.0.0.1:10888 -o /dev/null \
  -w 'code=%{http_code} speed=%{speed_download} B/s time=%{time_total}\n' \
  "https://speed.cloudflare.com/__down?bytes=20000000"
curl -sS -m 20 --socks5-hostname 127.0.0.1:10888 -o /dev/null \
  -w 'generate_204=%{http_code} time=%{time_total}s\n' http://connectivitycheck.gstatic.com/generate_204
curl -sS -m 25 --socks5-hostname 127.0.0.1:10888 https://ipinfo.io/json
```

Healthy on this host: 200 at tens of MB/s, `generate_204=204` in tens of ms, exit IP equal to
the route's outbound (EE for `/general`, Paris for `/france`). Also repeat 5–6 quick requests —
a tunnel that dies mid-stream shows 000/timeouts there even when the big pull succeeded.

## 3. Kill the test client before the next measurement

```bash
pkill -f "xray run -c /tmp/cli"; sleep 1; pgrep -af "xray run" | grep -v vpn-router
```

The only surviving process should be the container's own core. If another `xray run` is alive,
the next config you start **cannot bind the socks port**, exits silently in the background, and
all following curls answer through the *previous* config — which is how a healthy `/france`
route gets reported as exiting through EE. Symptom to recognise: the measured exit IP belongs
to a different route than the path you just configured.

## 4. Count the client's reconnects

```bash
awk '$9==101 {print substr($4,14,5), $1}' /var/log/nginx/vpn-8443.log \
  | sort | uniq -c | sort -rn | head
ss -tn state established '( sport = :8443 )'
```

`101` is a completed WebSocket upgrade; field `$10` is the bytes the client got back.

| signal | reading |
|---|---|
| tens of `101`/min from one IP, zero established sockets from that IP | the device loses its network and the app retries in a loop |
| `101` with 0–200 bytes | the handshake completed, no data ever flowed |
| a few `101` per IP, long-lived established sockets, large `$10` | normal session |
| `499` on a path | client aborted; count per IP to see who is flapping |

## 5. Verdict

- Container stable, self-test fast, `generate_204 = 204` → the tunnel is healthy; the drop is the
  **client's own link**. Say it with the numbers (restarts, MB/s, reconnects per minute) and point
  at the device: "switch to mobile data on weak signal", battery optimisation on the VPN app, the
  router's band/channel. Android only declares a Wi-Fi network "no internet" when the connectivity
  probe fails, and a passing 204 rules that mechanism out.
- Self-test fails or the exit IP is wrong → our side. Check rule order first (`inboundTag` rule must
  sit before the catch-all), then that the outbound itself answers when dialled directly (build a
  second client with only that outbound — no entry, no nginx).

A phone that has already fallen back to mobile data is a different network path: MTS mobile cuts
TLS harder than the home line, so a tunnel that will not recover on LTE is a separate finding, not
proof that the server is down.
