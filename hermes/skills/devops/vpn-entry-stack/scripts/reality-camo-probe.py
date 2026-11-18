#!/usr/bin/env python3
"""Which REALITY camo dest (and which client fingerprint) actually survives?

REALITY relays the client's ClientHello to `dest`, so a WAF in front of the camo
domain kills the handshake — and a client fingerprint the server cannot parse
(`ios`) fails authentication and falls back to the camo site, which the user sees
as «connected, no internet». Both are measured here against throwaway inbounds on
127.0.0.1; nothing touches the live entry.

Usage:
    python3 reality-camo-probe.py [camo1 camo2 ...] [--fp chrome,safari,ios]

Reading: 5/5 = usable, 4/5 = WAF eats some handshakes, 0/5 = never ship it.
Requires only the xray binary and curl; no secrets, no live config.
"""
import json
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

XRAY = "/usr/local/bin/xray"
UUID = "3b1d9c62-1f4a-4c8e-9a55-77f4a4d2b901"
SID = "0123456789abcdef"
TEST_URL = "https://api.ipify.org"
TRIES = 5

args = sys.argv[1:]
fps = ["chrome"]
if "--fp" in args:
    i = args.index("--fp")
    fps = args[i + 1].split(",")
    del args[i:i + 2]
camos = args or ["cdn.jsdelivr.net", "www.microsoft.com", "ya.ru", "2ip.ru"]
TMP = Path(tempfile.mkdtemp(prefix="camo-probe-"))


def free_port(start: int) -> int:
    port = start
    while port < start + 500:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                port += 1
    raise RuntimeError("no free port")


def keys() -> tuple[str, str]:
    out = subprocess.run([XRAY, "x25519"], capture_output=True, text=True).stdout
    return (re.search(r"Private[^:]*:\s*(\S+)", out).group(1),
            re.search(r"Public[^:]*:\s*(\S+)", out).group(1))


def run_case(camo: str, fp: str, priv: str, pub: str) -> int:
    sport, cport = free_port(20000), free_port(20500)
    server = {
        "log": {"loglevel": "error"},
        "inbounds": [{
            "tag": "rx", "listen": "127.0.0.1", "port": sport, "protocol": "vless",
            "settings": {"clients": [{"id": UUID, "flow": "xtls-rprx-vision"}], "decryption": "none"},
            "streamSettings": {"network": "tcp", "security": "reality",
                               "realitySettings": {"dest": f"{camo}:443", "serverNames": [camo],
                                                   "privateKey": priv, "shortIds": [SID]}}}]}
    client = {
        "log": {"loglevel": "error"},
        "inbounds": [{"tag": "s", "listen": "127.0.0.1", "port": cport, "protocol": "socks",
                      "settings": {"udp": False}}],
        "outbounds": [{"protocol": "vless",
                        "settings": {"vnext": [{"address": "127.0.0.1", "port": sport,
                                                  "users": [{"id": UUID, "encryption": "none",
                                                             "flow": "xtls-rprx-vision"}]}]},
                        "streamSettings": {"network": "tcp", "security": "reality",
                                           "realitySettings": {"serverName": camo, "publicKey": pub,
                                                               "shortId": SID, "fingerprint": fp}}}]}
    sp, cp = TMP / "srv.json", TMP / "cli.json"
    sp.write_text(json.dumps(server))
    cp.write_text(json.dumps(client))
    procs = [subprocess.Popen([XRAY, "-config", str(sp)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    time.sleep(1.2)
    procs.append(subprocess.Popen([XRAY, "-config", str(cp)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(1.5)
    ok = 0
    try:
        for _ in range(TRIES):
            r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-m", "12", "-w", "%{http_code}",
                                "--socks5-hostname", f"127.0.0.1:{cport}", TEST_URL],
                               capture_output=True, text=True)
            ok += 1 if r.stdout.strip() == "200" else 0
    finally:
        for p in procs:
            p.terminate()
        time.sleep(0.4)
    return ok


priv, pub = keys()
print(f"probe dir: {TMP}")
rows = []
for camo in camos:
    for fp in fps:
        ok = run_case(camo, fp, priv, pub)
        rows.append((camo, fp, ok))
        print(f"  {camo:<22} fp={fp:<8} {ok}/{TRIES}", flush=True)

print("\nranked (usable first):")
for camo, fp, ok in sorted(rows, key=lambda r: -r[2]):
    verdict = "ok" if ok == TRIES else ("WAF eats some" if ok else "never ship")
    print(f"  {camo:<22} fp={fp:<8} {ok}/{TRIES}  {verdict}")
