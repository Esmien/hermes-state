#!/usr/bin/env python3
"""Инжект известного объёма через выход провайдера (p<i>, fr, fi) + точный отчёт байт.

    inject.py <tag> <MB>

Outbound копируется из config.json verbatim во временный socks-клиент; UUID никогда
не печатается. Инжект идёт мимо vpn-router, поэтому в его outbound-счётчиках не виден —
сравнивать надо с дельтой subscription-userinfo (pool_probe.py).
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/root/vpn-router")
SCRATCH = Path("/root/.hermes/cache/scratch")
XRAY = "/usr/local/bin/xray"
SOCKS_PORT = 10999


def build_client(tag: str) -> Path:
    cfg = json.loads((BASE / "config.json").read_text())
    out = next((o for o in cfg["outbounds"] if o.get("tag") == tag), None)
    if out is None:
        raise SystemExit(f"нет outbound {tag}")
    client = {
        "log": {"loglevel": "warning"},
        "inbounds": [{"tag": "s", "listen": "127.0.0.1", "port": SOCKS_PORT,
                      "protocol": "socks", "settings": {"udp": False}}],
        "outbounds": [out],
    }
    path = SCRATCH / f"cli-{tag}.json"
    path.write_text(json.dumps(client, indent=1))
    os.chmod(path, 0o600)
    return path


def main() -> int:
    tag = sys.argv[1] if len(sys.argv) > 1 else "p1"
    mb = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    path = build_client(tag)
    proc = subprocess.Popen([XRAY, "run", "-c", str(path)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    total = 0
    try:
        chunk = 50
        for i in range(max(1, mb // chunk)):
            cmd = ["curl", "-sS", "--max-time", "60", "-o", "/dev/null",
                   "-w", "%{size_download}", "--socks5-hostname", f"127.0.0.1:{SOCKS_PORT}",
                   f"https://speed.cloudflare.com/__down?bytes={chunk}000000"]
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            got = int((p.stdout or "0").strip() or 0)
            total += got
            if got == 0 and i == 0:
                print(f"{tag}: выход не отвечает ({p.stderr.strip()[:80]})")
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        path.unlink(missing_ok=True)
    print(f"{tag}: принято {total} B ({total / 1e6:.1f} MB)")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
