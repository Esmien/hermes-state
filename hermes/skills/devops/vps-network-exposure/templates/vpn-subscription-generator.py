# -*- coding: utf-8 -*-
"""Генератор клиентских конфигов для одного входа-туннеля и нескольких маршрутов.

Копировать, подставить HOST/PORT/BRAND/PATHS и имена узлов. Выдаёт три формата
в один каталог (его отдаёт nginx по User-Agent):
    <out>/clash.yaml    — Clash/Mihomo/FlClash (одна группа, только маршруты)
    <out>/list.txt      — base64 от списка vless:// (Happ/Hiddify/v2rayN)
    <out>/singbox.json  — sing-box

Запуск:  python3 vpn-subscription-generator.py --new     # новый токен
         python3 vpn-subscription-generator.py           # пересобрать существующие
"""
import base64
import json
import secrets
import sys
import urllib.parse
from pathlib import Path

HOST = "vpn.example.com"        # домен с валидным сертификатом
PORT = 8443                     # рабочий порт входа (не 443, если 443 режется)
BRAND = "Esmien VPN"
ROOT = Path("/var/www/esmien-sub")
UID_FILE = Path("/root/mtproto-faketls/ws-client-uuid")
ROUTES = [("🇪🇪 Эстония (General)", "/general"), ("🇫🇷 Франция (Gemini)", "/france")]
SPLIT_SUFFIXES = ["google.com", "googleapis.com", "gstatic.com", "googleusercontent.com"]


def vless(uid, path, tag):
    query = {"type": "ws", "security": "tls", "sni": HOST, "host": HOST,
             "path": path, "encryption": "none"}
    return f"vless://{uid}@{HOST}:{PORT}?" + urllib.parse.urlencode(query) + "#" + urllib.parse.quote(tag)


def clash_proxy(uid, name, path):
    return f"""  - name: "{name}"
    type: vless
    server: {HOST}
    port: {PORT}
    uuid: {uid}
    network: ws
    tls: true
    udp: true
    sni: {HOST}
    servername: {HOST}
    client-fingerprint: chrome
    alpn: [http/1.1]
    ws-opts:
      path: "{path}"
      headers:
        Host: {HOST}
"""


def build(target: Path, uid: str) -> None:
    (target / "list.txt").write_text(
        base64.b64encode(("\n".join(vless(uid, p, n) for n, p in ROUTES) + "\n").encode()).decode() + "\n")

    split = "\n".join(f"  - DOMAIN-SUFFIX,{s},{ROUTES[1][0]}" for s in SPLIT_SUFFIXES)
    proxies = "".join(clash_proxy(uid, n, p) for n, p in ROUTES)
    group = "\n".join(f'      - "{n}"' for n, _ in ROUTES)
    (target / "clash.yaml").write_text(f"""# {BRAND} — {len(ROUTES)} маршрута
mixed-port: 7890
allow-lan: false
mode: rule
log-level: info
ipv6: false

dns:
  enable: true
  ipv6: false
  enhanced-mode: fake-ip
  fake-ip-range: 198.18.0.1/16
  nameserver: [1.1.1.1, 8.8.8.8]

proxies:
{proxies}proxy-groups:
  - name: "{BRAND}"
    type: select
    proxies:
{group}

rules:
  - IP-CIDR,127.0.0.0/8,DIRECT,no-resolve
  - IP-CIDR,10.0.0.0/8,DIRECT,no-resolve
  - IP-CIDR,172.16.0.0/12,DIRECT,no-resolve
  - IP-CIDR,192.168.0.0/16,DIRECT,no-resolve
  - DOMAIN-SUFFIX,local,DIRECT
{split}
  - MATCH,{ROUTES[0][0]}
""")

    def sb(name, path):
        return {"type": "vless", "tag": name, "server": HOST, "server_port": PORT, "uuid": uid,
                "transport": {"type": "ws", "path": path, "headers": {"Host": HOST}},
                "tls": {"enabled": True, "server_name": HOST}}

    sing = {"log": {"level": "warn"},
            "inbounds": [{"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1", "listen_port": 2080}],
            "outbounds": [sb(n, p) for n, p in ROUTES] + [{"type": "direct", "tag": "direct"}],
            "route": {"rules": [{"domain_suffix": SPLIT_SUFFIXES, "outbound": ROUTES[1][0]},
                                 {"outbound": ROUTES[0][0]}]}}
    (target / "singbox.json").write_text(json.dumps(sing, indent=2, ensure_ascii=False))
    target.chmod(0o755)


def main() -> int:
    uid = UID_FILE.read_text().strip()
    existing = [p for p in ROOT.iterdir() if p.is_dir()] if ROOT.is_dir() else []
    if "--new" in sys.argv or not existing:
        token = secrets.token_urlsafe(14).replace("-", "").replace("_", "")[:18]
        target = ROOT / token
        target.mkdir(parents=True, exist_ok=True)
        build(target, uid)
        print(f"https://{HOST}:{PORT}/sub/{token}")
        return 0
    for target in sorted(existing):
        build(target, uid)
        print(f"https://{HOST}:{PORT}/sub/{target.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
