#!/usr/bin/env python3
"""Аудит хоста снаружи: открытые TCP-порты, что на них отвечает, TLS-личность, режимы входа SSH.

Зачем: nmap на хосте может не стоять, а ответ «что торчит наружу» нужен целиком — включая
случайные высокие порты, на которых живут входы VPN. Стучится только рукопожатием / GET.

    port-audit.py 1.2.3.4 5.6.7.8            # типовые порты (~30 с/хост)
    port-audit.py --full 1.2.3.4            # весь диапазон 1-65535 (~2 мин/хост)
    port-audit.py --hosts-file fleet.txt --full --json /tmp/audit.json

Что печатает по каждому адресу:
  * открытые порты;
  * TLS-личность (subject/issuer/SAN) — чужой бренд в серте на случайном IP = фронтинг;
  * HTTP(S): код, Server, <title> — и признак панели (x-ui / 3x-ui / marzban / hiddify / remnawave);
  * SSH: `Permission denied (publickey,password)` = парольный вход включён.

Границы: UDP не проверяется (hysteria/QUIC так не видна), скан идёт с одного адреса —
хосты с фильтром по источнику могут ответить пусто.
"""

import argparse
import asyncio
import json
import re
import socket
import ssl
import subprocess
import sys

COMMON = sorted(set("""
21 22 23 25 53 80 81 110 143 443 465 587 993 995 1080 1081 1087 1088 1090 2000
2052 2053 2054 2080 2082 2083 2086 2087 2095 2096 2222 3000 3128 3306 3389 4433
4443 5000 5432 6379 7000 7001 8000 8006 8008 8080 8081 8082 8088 8090 8443 8444
8880 8888 9000 9090 9443 10000 10443 18080 54321
""".split()), key=int)

HTTP_PORTS = {80, 81, 8000, 8006, 8008, 8080, 8081, 8082, 8088, 8090, 8880, 8888, 9000, 3000}
PANEL_MARKS = ("x-ui", "3x-ui", "marzban", "hiddify", "remnawave", "v2ray", "sing-box", "panel")
BRANDS = ("apple.com", "google.com", "microsoft.com", "cloudflare.com", "amazon.com")


def scan_ports(ip, ports, timeout=1.5, concurrency=800):
    async def probe(port, sem):
        async with sem:
            try:
                _, w = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
                w.close()
                return port
            except Exception:
                return None

    async def run():
        sem = asyncio.Semaphore(concurrency)
        return [p for p in await asyncio.gather(*[probe(p, sem) for p in ports]) if p]

    return asyncio.run(run())


def scan_full(ip):
    found, step = [], 4000
    for start in range(1, 65536, step):
        found += scan_ports(ip, range(start, min(start + step, 65536)), timeout=1.2, concurrency=1200)
    return sorted(set(found))


def tls_identity(ip, port, timeout=4):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=ip) as tls:
                der = tls.getpeercert(binary_form=True)
    except Exception:
        return None
    info = subprocess.run(
        ["openssl", "x509", "-inform", "DER", "-noout", "-subject", "-issuer", "-ext", "subjectAltName"],
        input=der, capture_output=True,
    ).stdout.decode(errors="ignore")
    return " ".join(info.split())[:220]


def http_identity(ip, port, tls):
    scheme = "https" if tls else "http"
    out = subprocess.run(
        ["curl", "-sk" if tls else "-s", "--max-time", "8", "-D-", f"{scheme}://{ip}:{port}/"],
        capture_output=True, text=True,
    ).stdout
    head, _, body = out.partition("\r\n\r\n")
    status = re.search(r"HTTP/[\d.]+ (\d{3})", head)
    server = re.search(r"(?im)^server:\s*(.+)$", head)
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", body)
    return {
        "status": status.group(1) if status else "",
        "server": server.group(1).strip()[:32] if server else "",
        "title": re.sub(r"\s+", " ", title.group(1)).strip()[:60] if title else "",
        "body": body[:60].strip(),
    }


def ssh_modes(ip, port=22):
    res = subprocess.run(
        ["ssh", "-p", str(port), "-o", "PreferredAuthentications=none",
         "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
         "-o", "ConnectTimeout=6", f"root@{ip}"],
        capture_output=True, text=True,
    )
    m = re.search(r"Permission denied \(([^)]*)\)", res.stderr)
    if m:
        return m.group(1)
    tail = (res.stderr.strip().splitlines() or [""])[-1]
    return tail[:80]


def audit(ip, full=False):
    ports = scan_full(ip) if full else scan_ports(ip, COMMON)
    report = {"ip": ip, "open": ports, "services": {}, "ssh": ""}
    for port in ports:
        entry, tls = {}, tls_identity(ip, port)
        if tls:
            entry["tls"] = tls
            entry["fronting"] = [b for b in BRANDS if b in tls]
        if tls or port in HTTP_PORTS:
            entry["http"] = http_identity(ip, port, bool(tls))
            hay = (entry["http"].get("title", "") + " " + entry["http"].get("body", "")).lower()
            if any(mark in hay for mark in PANEL_MARKS):
                entry["panel"] = True
            if "404 page not found" in hay:
                entry["note"] = "xray/Go-фолбэк, не панель"
        if entry:
            report["services"][port] = entry
    if 22 in ports:
        report["ssh"] = ssh_modes(ip)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ips", nargs="*")
    ap.add_argument("--hosts-file")
    ap.add_argument("--full", action="store_true", help="сканировать 1-65535")
    ap.add_argument("--json", help="сохранить результат в файл")
    args = ap.parse_args()

    ips = list(args.ips)
    if args.hosts_file:
        ips += [l.split()[0] for l in open(args.hosts_file) if l.strip() and not l.startswith("#")]
    if not ips:
        ap.error("нужен хотя бы один адрес или --hosts-file")

    results = []
    for ip in ips:
        print(f"\n=== {ip}", flush=True)
        try:
            rep = audit(ip, args.full)
        except KeyboardInterrupt:
            break
        results.append(rep)
        print(f"  open: {rep['open'] or '— (ничего)'}")
        for port, data in rep["services"].items():
            bits = []
            if data.get("tls"):
                bits.append(data["tls"])
            if data.get("fronting"):
                bits.append("⚠ ЧУЖОЙ БРЕНД: " + ",".join(data["fronting"]))
            if data.get("http"):
                h = data["http"]
                bits.append(f"http={h['status'] or '?'} srv={h['server']!r} title={h['title']!r}")
            if data.get("panel"):
                bits.append("⚠ ПАНЕЛЬ")
            if data.get("note"):
                bits.append(data["note"])
            print(f"  {port}: " + " | ".join(bits))
        if rep["ssh"]:
            mark = "⚠ пароль разрешён" if "password" in rep["ssh"] else "только ключ"
            print(f"  22: ssh modes={rep['ssh']} — {mark}")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=1)
        print(f"\njson: {args.json}")


if __name__ == "__main__":
    sys.exit(main())
