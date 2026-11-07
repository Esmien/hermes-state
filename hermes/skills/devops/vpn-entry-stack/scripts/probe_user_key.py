#!/usr/bin/env python3
"""Probe one of OUR client keys end-to-end and account the bytes.

Builds a throwaway xray client config from the subscription itself, runs it as a
local SOCKS proxy, downloads N bytes and prints the byte count plus the egress
IP. Proof that a freshly created profile works and that per-user stats are
attributed to the right key (compare the person's row before/after one tick).

    probe_user_key.py --token FZ8bjRvHt8EdKjflxv
    probe_user_key.py --token FZ8bjRvHt8EdKjflxv --bytes 5000000 --port 11170
    probe_user_key.py --legacy          # the bare main (shared) key

Exit 0 = exactly the requested bytes arrived. 1 = short read, dead key or socks
did not come up (details printed).
"""
import argparse
import base64
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.parse

XRAY = "/usr/local/bin/xray"
SUBS = "/var/www/esmien-sub"
BASE = "/root/vpn-router"


def first_link(token: str) -> str:
    raw = open(f"{SUBS}/{token}/list.txt").read().strip()
    raw += "=" * (-len(raw) % 4)
    for line in base64.b64decode(raw).decode().splitlines():
        if line.startswith("vless://"):
            return line
    raise RuntimeError(f"в подписке {token} нет vless-ссылки")


def legacy_client() -> tuple[str, int, str, str, str]:
    cfg = json.load(open(f"{BASE}/config.json"))
    brand = json.load(open(f"{BASE}/brand.json"))
    for ib in cfg["inbounds"]:
        for cl in (ib.get("settings", {}).get("clients") or []):
            if cl.get("email") == ib.get("tag"):
                return brand["host"], brand["port"], brand["host"], "/general", cl["id"]
    raise RuntimeError("в конфиге нет голого клиента (общий ключ не найден)")


def target(token: str | None) -> tuple[str, int, str, str, str]:
    if not token:
        return legacy_client()
    u = urllib.parse.urlparse(first_link(token))
    q = urllib.parse.parse_qs(u.query)
    return (u.hostname, u.port, q.get("sni", [u.hostname])[0],
            q.get("path", ["/"])[0], u.username)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", help="токен основной подписки")
    ap.add_argument("--legacy", action="store_true", help="проверить главный (общий) ключ")
    ap.add_argument("--bytes", type=int, default=3_000_000)
    ap.add_argument("--port", type=int, default=11170)
    ap.add_argument("--url", default="https://speed.cloudflare.com/__down?bytes={n}")
    a = ap.parse_args()
    if not a.token and not a.legacy:
        ap.error("нужен --token или --legacy")

    try:
        host, port, sni, path, uid = target(None if a.legacy else a.token)
    except Exception as exc:
        print(f"не собрал параметры клиента: {exc}")
        return 1

    cfg = {
        "log": {"loglevel": "warning"},
        "inbounds": [{"listen": "127.0.0.1", "port": a.port, "protocol": "socks",
                      "settings": {"udp": False}}],
        "outbounds": [{
            "protocol": "vless", "tag": "probe",
            "settings": {"vnext": [{"address": host, "port": port,
                                     "users": [{"id": uid, "encryption": "none"}]}]},
            "streamSettings": {"network": "ws", "security": "tls",
                               "tlsSettings": {"serverName": sni},
                               "wsSettings": {"path": path, "headers": {"Host": sni}}},
        }],
    }

    tmp = tempfile.mkdtemp(prefix="probe_key_")
    conf = os.path.join(tmp, "client.json")
    try:
        with open(conf, "w") as fh:
            json.dump(cfg, fh)
        os.chmod(conf, 0o600)
        proc = subprocess.Popen([XRAY, "run", "-c", conf],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
        try:
            got = subprocess.run(
                ["curl", "-sS", "-m", "90", "-o", "/dev/null", "-w", "%{size_download}",
                 "--socks5-hostname", f"127.0.0.1:{a.port}", a.url.format(n=a.bytes)],
                capture_output=True, text=True).stdout.strip()
            ip = subprocess.run(
                ["curl", "-sS", "-m", "15", "--socks5-hostname", f"127.0.0.1:{a.port}",
                 "https://ipinfo.io/ip"], capture_output=True, text=True).stdout.strip()
        finally:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    who = "главный ключ" if a.legacy else a.token
    print(f"{who}: скачано {got} байт, выход {ip or '?'}")
    if got.isdigit() and int(got) == a.bytes:
        return 0
    if got in ("0", "1"):
        print("  -> слишком большой bytes= или ключ не работает; повтори с 2000000")
    return 1


if __name__ == "__main__":
    sys.exit(main())
