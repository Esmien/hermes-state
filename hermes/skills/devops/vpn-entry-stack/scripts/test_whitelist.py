#!/usr/bin/env python3
"""Test selected upstream nodes with an alternative credential.

Purpose: decide whether a node is dead or simply refuses another plan's key. Builds
an Xray client per link with the credential swapped, dials it inside the 3xui
container and prints the exit IP; silence means the key did not open the node.

Usage:
    test_whitelist.py <sub> <other-sub> <indices>            # other plan's creds
    test_whitelist.py <sub> <other-sub> <indices> --mobile   # own plan's creds

Both args are base64-or-plain subscription files. Indices are 0-based link numbers.
"""
import base64
import json
import subprocess
import sys
import urllib.parse
from pathlib import Path

CONTAINER = "3xui"
WORK = Path("/root/probe_wl")
BASE_PORT = 19500


def load(path: str) -> str:
    raw = Path(path).read_bytes().strip()
    try:
        return base64.b64decode(raw + b"=" * (-len(raw) % 4)).decode("utf-8", "ignore")
    except Exception:
        return raw.decode("utf-8", "ignore")


def cred_of(text: str, scheme: str) -> str:
    for line in text.splitlines():
        if line.startswith(scheme + "://"):
            u = urllib.parse.urlparse(line)
            if u.hostname != "0.0.0.0":  # skip placeholder nodes
                return urllib.parse.unquote(u.username or "")
    raise SystemExit(f"no {scheme} credential found")


def build(link: str, cred: str, port: int) -> dict:
    u = urllib.parse.urlparse(link)
    q = dict(urllib.parse.parse_qsl(u.query))
    net, sec = q.get("type", "tcp"), q.get("security", "none")
    sni = q.get("sni") or u.hostname
    stream = {"network": net, "security": sec}
    if sec == "tls":
        stream["tlsSettings"] = {"serverName": sni, "alpn": q.get("alpn", "h2").split(","),
                                 "fingerprint": q.get("fp", "chrome")}
    elif sec == "reality":
        stream["realitySettings"] = {"serverName": sni, "fingerprint": q.get("fp", "chrome"),
                                     "publicKey": q["pbk"], "shortId": q.get("sid", ""),
                                     "spiderX": q.get("spx", "/")}
    if net == "grpc":
        stream["grpcSettings"] = {"serviceName": q.get("serviceName", ""),
                                  "multiMode": q.get("mode") == "multi"}
    if u.scheme == "vless":
        out = {"protocol": "vless",
               "settings": {"vnext": [{"address": u.hostname, "port": u.port,
                                        "users": [{"id": cred, "encryption": "none",
                                                   "flow": q.get("flow", "")}]}]},
               "streamSettings": stream}
    else:
        out = {"protocol": "trojan",
               "settings": {"servers": [{"address": u.hostname, "port": u.port,
                                          "password": cred}]},
               "streamSettings": stream}
    return {"log": {"loglevel": "error"},
            "inbounds": [{"listen": "127.0.0.1", "port": port, "protocol": "socks",
                          "settings": {"udp": False}}],
            "outbounds": [out]}


def main() -> int:
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    sub_file, other_file, idx_arg = sys.argv[1:4]
    use_own = "--mobile" in sys.argv
    sub_text, other_text = load(sub_file), load(other_file)
    links = [l for l in sub_text.splitlines() if "://" in l]
    order = [int(x) for x in idx_arg.split(",")]

    WORK.mkdir(exist_ok=True)
    script = ["#!/bin/sh"]
    for n, i in enumerate(order):
        link = links[i]
        scheme = urllib.parse.urlparse(link).scheme
        cred = cred_of(sub_text, scheme) if use_own else cred_of(other_text, scheme)
        port = BASE_PORT + n
        (WORK / f"w{i}.json").write_text(json.dumps(build(link, cred, port)))
        name = urllib.parse.unquote(urllib.parse.urlparse(link).fragment)[:34]
        # kill by pid: pkill -f would match this shell's own command line and stop the loop
        script += [f"printf '%2d %-34s ' {i} '{name}'",
                   f"/app/bin/xray-linux-amd64 run -c /tmp/wl/w{i}.json >/dev/null 2>&1 & pid=$!",
                   "sleep 3",
                   f"out=$(curl -sS --max-time 12 --socks5-hostname 127.0.0.1:{port} https://ipinfo.io/json "
                   "2>/dev/null | python3 -c \"import sys,json;d=json.load(sys.stdin);"
                   "print(d['ip'],d['country'],d['city'])\" 2>/dev/null)",
                   'echo "${out:-NO RESPONSE}"', "kill $pid 2>/dev/null; wait $pid 2>/dev/null"]

    (WORK / "run.sh").write_text("\n".join(script) + "\n")
    subprocess.run(["docker", "cp", str(WORK) + "/.", f"{CONTAINER}:/tmp/wl"],
                   check=True, capture_output=True)
    res = subprocess.run(["docker", "exec", CONTAINER, "sh", "/tmp/wl/run.sh"],
                         capture_output=True, text=True, timeout=560)
    print(("own plan creds" if use_own else "other plan creds") + ":")
    print(res.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
