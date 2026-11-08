#!/usr/bin/env python3
"""Watchdog: наш московский выход 217.197.114.197 и сайт провайдера estt.ru.

Молчит, пока состояние не изменилось (паттерн cron-watchdog: пустой stdout =
ничего не отправляется). Печатает одну строку только на переходе.
"""
import json
import socket
import time
from pathlib import Path

BOX = "217.197.114.197"
BOX_PORTS = (22, 443)
PROVIDER_HOST = "estt.ru"
STATE = Path("/root/.hermes/state/ru1-watch.json")


def tcp(host: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


def probe() -> dict:
    open_ports = [p for p in BOX_PORTS if tcp(BOX, p)]
    return {"box": bool(open_ports), "ports": open_ports,
            "provider": tcp(PROVIDER_HOST, 443)}


def main() -> int:
    cur = probe()
    prev = None
    if STATE.exists():
        try:
            prev = json.loads(STATE.read_text())
        except (ValueError, OSError):
            prev = None

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"box": cur["box"], "provider": cur["provider"],
                                 "ports": cur["ports"], "ts": int(time.time())}) + "\n")

    if prev is None:
        return 0  # первый замер — только базлайн

    lines = []
    if cur["box"] and not prev.get("box"):
        lines.append(f"🟢 Московский бокс {BOX} снова отвечает "
                     f"({','.join(map(str, cur['ports']))}). Вернуть ru-трафик на ru1?")
    elif not cur["box"] and prev.get("box"):
        lines.append(f"🔴 Московский бокс {BOX} опять не отвечает.")
    if cur["provider"] and not prev.get("provider") and not cur["box"]:
        lines.append("🟡 estt.ru снова открывается — провайдер, похоже, поднял хостинг; бокс пока нет.")

    if lines:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
