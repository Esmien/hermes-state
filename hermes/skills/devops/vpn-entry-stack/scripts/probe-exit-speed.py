#!/usr/bin/env python3
"""Real throughput + exit IP of one xray outbound, without leaking its credentials.

Usage: probe-exit-speed.py <outbound-tag> [bytes]

Builds a throwaway socks-only client from /root/vpn-router/config.json, so the outbound's UUID /
trojan password is never printed or pasted into a command line. Prints exit country/org and MB/s.
Compare against a direct pull from the host to separate "host uplink" from "borrowed exit".
"""

import json
import os
import signal
import subprocess
import sys
import time

SRC = "/root/vpn-router/config.json"
XRAY = "/usr/local/bin/xray"


def main() -> int:
    tag = sys.argv[1] if len(sys.argv) > 1 else "fr"
    nbytes = int(sys.argv[2]) if len(sys.argv) > 2 else 20_000_000
    cfg = json.load(open(SRC))
    try:
        ob = next(o for o in cfg["outbounds"] if o.get("tag") == tag)
    except StopIteration:
        print(f"no outbound tagged {tag}")
        return 2

    port = 12080
    client = {
        "log": {"loglevel": "error"},
        "inbounds": [{"tag": "s", "port": port, "listen": "127.0.0.1",
                      "protocol": "socks", "settings": {"udp": False}}],
        "outbounds": [ob],
    }
    path = f"/tmp/xray-probe-{tag}.json"
    with open(path, "w") as fh:
        json.dump(client, fh)
    os.chmod(path, 0o600)

    proc = subprocess.Popen([XRAY, "run", "-c", path],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(2)
        r = subprocess.run(["curl", "-s", "--max-time", "20", "--socks5-hostname",
                            f"127.0.0.1:{port}", "https://ipinfo.io/json"],
                           capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)
            print(f"[{tag}] exit={d.get('ip')} {d.get('country')} {d.get('city')} {d.get('org', '')[:40]}")
        except Exception:
            print(f"[{tag}] exit probe failed: {r.stdout[:120]!r}")
        r = subprocess.run(["curl", "-s", "-o", "/dev/null", "--max-time", "60",
                            "--socks5-hostname", f"127.0.0.1:{port}",
                            "-w", "%{speed_download} %{time_total} %{size_download}",
                            f"https://speed.cloudflare.com/__down?bytes={nbytes}"],
                           capture_output=True, text=True)
        spd, tot, got = r.stdout.split()[:3]
        print(f"[{tag}] {int(float(got)) / 1048576:.1f} MB at "
              f"{float(spd) / 1048576:.1f} MB/s in {float(tot):.2f}s")
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        os.remove(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
