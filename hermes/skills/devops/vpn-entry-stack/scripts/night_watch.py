#!/usr/bin/env python3
"""Ночной сторож плана: сэмпл subscription-userinfo каждые N минут + итог в Telegram.

    night_watch.py <samples> <interval_s>

Запускать transient-юнитом, чтобы не оставлять файлов в /etc:

    systemd-run --unit=pool-watch --collect \
        /usr/bin/python3 <этот файл> 96 300

Пишет /root/.hermes/cache/scratch/pool_watch.jsonl. В отчёте рядом с подозрительным планом
всегда идёт контрольный: всплеск на обоих сразу — это наш собственный стек, только на
подозрительном — кто-то ещё. Креды и токены не печатаются, только МБ и время (МСК).
"""
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path("/root/vpn-router")
OUT = Path("/root/.hermes/cache/scratch/pool_watch.jsonl")
ENV = Path("/home/ai_service/notifications/.env")
UA = "Happ/2.11.0"  # тот же UA, что у sub_expiry.py: панель не считает это новым устройством
MSK = timezone(timedelta(hours=3))
BURST_MB = 50


def parse_info(s: str) -> dict:
    d = {}
    for part in s.split(";"):
        k, _, v = part.strip().partition("=")
        if v.strip().isdigit():
            d[k.strip()] = int(v.strip())
    return d


def snapshot() -> list:
    res = []
    for sub in json.loads((BASE / "subs.json").read_text()):
        rec = {"name": sub["name"]}
        try:
            req = urllib.request.Request(sub["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as r:
                rec["info"] = parse_info(r.headers.get("subscription-userinfo", ""))
        except Exception as exc:  # noqa: BLE001
            rec["error"] = type(exc).__name__
        res.append(rec)
    return res


def send(text: str) -> None:
    found = {}
    for line in ENV.read_text().splitlines():
        k, _, v = line.partition("=")
        if k.strip() in ("BOT_TOKEN", "BOT_OWNER"):
            found[k.strip()] = v.strip().strip('"').strip("'")
    token, chat = found.get("BOT_TOKEN"), found.get("BOT_OWNER")
    if not token or not chat:
        print("no BOT_TOKEN/BOT_OWNER")
        return
    payload = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML",
                          "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                 data=payload, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=25)


def main() -> int:
    samples = int(sys.argv[1]) if len(sys.argv) > 1 else 96
    interval = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    watch = (sys.argv[3] if len(sys.argv) > 3 else "мобильная")

    for i in range(samples):
        rec = {"ts": int(time.time()),
               "iso": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "subs": snapshot()}
        with OUT.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        if i < samples - 1:
            time.sleep(interval)

    rows = [json.loads(line) for line in OUT.read_text().splitlines() if line.strip()]
    intervals, bursts, control_bursts = [], [], []
    for a, b in zip(rows, rows[1:]):
        dt = b["ts"] - a["ts"]
        if dt <= 0:
            continue
        got = {}
        for sa, sb in zip(a["subs"], b["subs"]):
            ia, ib = sa.get("info", {}), sb.get("info", {})
            if ia and ib:
                got[sa["name"]] = ib.get("download", 0) - ia.get("download", 0)
        w = next((v for k, v in got.items() if watch in k), 0)
        c = next((v for k, v in got.items() if watch not in k), 0)
        t = datetime.fromtimestamp(b["ts"], MSK).strftime("%H:%M")
        intervals.append((t, w, c))
        if w / 1e6 > BURST_MB:
            bursts.append((t, w, c))
        if c / 1e6 > BURST_MB:
            control_bursts.append((t, c))

    total_w = sum(w for _, w, _ in intervals) / 1e9
    total_c = sum(c for _, _, c in intervals) / 1e9
    lines = [f"🌙 {watch} план за ночь: {len(intervals)} интервалов",
             f"подозрительный {total_w:.1f} ГБ, контрольный {total_c:.1f} ГБ"]
    if bursts:
        lines.append(f"всплесков >{BURST_MB} МБ: {len(bursts)}")
        for t, w, c in bursts[:8]:
            lines.append(f"• {t} МСК — {w / 1e6:.0f} МБ (контрольный за тот же интервал {c / 1e6:.0f} МБ)")
    else:
        lines.append("всплесков нет — план всю ночь тихий")
    if control_bursts:
        lines.append(f"всплесков на контрольном: {len(control_bursts)} — значит это был наш стек")
    text = "\n".join(lines)
    print(text)
    try:
        send(text)
    except Exception as exc:  # noqa: BLE001
        print(f"telegram: {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
