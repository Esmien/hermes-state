#!/usr/bin/env python3
"""Снимок счётчика провайдерской подписки + наших xray-счётчиков.

    pool_probe.py sample   — снять снимок и дописать в jsonl
    pool_probe.py report   — дельты между последними двумя снимками

Секреты не печатаются: из подписки берётся только заголовок subscription-userinfo,
из конфига — только байты по outbound-тегам. UA намеренно тот же, что у sub_expiry.py
(панель уже принимает его каждый день и не считает новым устройством).
"""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path("/root/vpn-router")
OUT = Path("/root/.hermes/cache/scratch/pool_probe.jsonl")
UA = "Happ/2.11.0"


def parse_info(s: str) -> dict:
    d = {}
    for part in s.split(";"):
        k, _, v = part.strip().partition("=")
        if v.strip().isdigit():
            d[k.strip()] = int(v.strip())
    return d


def sub_headers() -> list:
    res = []
    for sub in json.loads((BASE / "subs.json").read_text()):
        rec = {"name": sub["name"]}
        try:
            req = urllib.request.Request(sub["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as r:
                rec["status"] = r.status
                rec["info"] = parse_info(r.headers.get("subscription-userinfo", ""))
        except Exception as exc:  # noqa: BLE001
            rec["error"] = type(exc).__name__
        res.append(rec)
    return res


def counters() -> dict:
    color = (BASE / "vpn-color").read_text().strip()
    port = 10185 if color == "a" else 11185
    proc = subprocess.run(
        ["/usr/local/bin/xray", "api", "statsquery",
         f"--server=127.0.0.1:{port}", "-pattern", "outbound>>>"],
        capture_output=True, text=True, timeout=40)
    tags = {}
    if proc.returncode != 0:
        return {"error": f"statsquery rc={proc.returncode}", "color": color,
                "stderr": proc.stderr.strip()[:200]}
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {"error": "bad json", "color": color, "raw": proc.stdout[:200]}
    for item in data.get("stat", []):
        parts = item.get("name", "").split(">>>")
        if len(parts) == 4 and parts[0] == "outbound":
            tags.setdefault(parts[1], {})[parts[3]] = int(item.get("value", 0) or 0)
    starts = {}
    for cname in ("vpn-router", "vpn-router-b"):
        p = subprocess.run(["docker", "inspect", cname, "--format", "{{.State.StartedAt}}"],
                           capture_output=True, text=True, timeout=20)
        starts[cname] = p.stdout.strip() or "?"
    return {"color": color, "port": port, "tags": tags, "started": starts}


def sample() -> None:
    rec = {"ts": int(time.time()), "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "subs": sub_headers(), "xray": counters()}
    with OUT.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
    for s in rec["subs"]:
        i = s.get("info", {})
        print(f'sub: {s["name"]}: up={i.get("upload")} down={i.get("download")} '
              f'total={i.get("total")} expire={i.get("expire")} err={s.get("error", "-")}')
    x = rec["xray"]
    if "error" in x:
        print("xray:", x)
        return
    tot = {"uplink": 0, "downlink": 0}
    for d in x["tags"].values():
        for k, v in d.items():
            tot[k] += v
    print(f'xray: color={x["color"]} port={x["port"]} tags={len(x["tags"])} '
          f'total_up={tot["uplink"]} total_down={tot["downlink"]} started={x["started"]}')


def report() -> None:
    rows = [json.loads(line) for line in OUT.read_text().splitlines() if line.strip()]
    if len(rows) < 2:
        print("нужно минимум два снимка")
        return
    a, b = (rows[-2], rows[-1]) if len(rows) > 2 else (rows[0], rows[-1])
    dt = b["ts"] - a["ts"]
    print(f'интервал: {dt} c ({dt / 60:.1f} мин), {a["iso"]} → {b["iso"]}')
    if a["xray"].get("started") != b["xray"].get("started"):
        print("⚠️ контейнер перезапускался между снимками — дельта xray недействительна")
    up = dn = 0
    for tag, d in b["xray"].get("tags", {}).items():
        pa = a["xray"].get("tags", {}).get(tag, {})
        if tag in ("fr", "fi") or (tag.startswith("p") and tag[1:].isdigit()):
            up += d.get("uplink", 0) - pa.get("uplink", 0)
            dn += d.get("downlink", 0) - pa.get("downlink", 0)
    print(f'фон через провайдера (без инжекта): up+down = {up + dn} B ({(up + dn) / 1e6:.1f} MB)')
    for sa, sb in zip(a["subs"], b["subs"]):
        ia, ib = sa.get("info", {}), sb.get("info", {})
        if not ia or not ib:
            print(f'{sa["name"]}: нет данных ({sa.get("error") or sb.get("error")})')
            continue
        da = (ib.get("download", 0) - ia.get("download", 0))
        if da < 0:
            print(f'{sa["name"]}: счётчик уменьшился ({da} B) — панель сбросила/пересчитала')
            continue
        print(f'{sa["name"]}: дельта download {da} B ({da / 1e6:.1f} MB)')


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "sample"
    sample() if mode == "sample" else report()
