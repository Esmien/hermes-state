#!/usr/bin/env python3
"""Внешний аудит пачки хостов: полный диапазон TCP + что за портом.

    python3 fleet-portscan.py 1.2.3.4 5.6.7.8 [--common] [--json out.json]

--common — только типовой список портов (быстро, ~15 с на хост);
без флага — весь диапазон 1..65535 connect-сканом (медленно, ~1.5–2 мин на хост).

Печатает по хосту: открытые порты, баннер и набор методов SSH, TLS subject/issuer
для портов с рукопожатием, HTTP-заголовок/титул там, где это HTTP. Ничего не меняет
на удалённой стороне — только TCP-коннекты и один TLS/HTTP-запрос на порт.

Зачем: nmap на хосте может отсутствовать, а connect-скан на asyncio хватает тех же
ответов и не требует прав. Результаты трактуй по правилам скилла: чужой серт
(Apple/Google) на хостинговом IP = фронтинг; одинаковый серт на N хостах = одно имя
на весь флот; `publickey,password` = парольный SSH открыт; 3389 = RDP наружу.
"""
import argparse, asyncio, json, re, socket, ssl, subprocess, sys

COMMON = sorted({22, 80, 443, 8443, 8080, 8443, 2096, 2087, 2083, 2222, 3389, 10605,
                 14308, 7001, 8000, 8880, 9000, 10000, 2053, 2086, 2095, 54321})


async def probe(ip, port, sem, timeout):
    async with sem:
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
            w.close()
            return port
        except Exception:
            return None


async def scan(ip, ports, timeout=2.0, conc=1200):
    sem = asyncio.Semaphore(conc)
    open_ports = []
    step = 3000
    for start in range(1, max(ports) + 1, step):
        chunk = [p for p in ports if start <= p < start + step]
        for got in await asyncio.gather(*[probe(ip, p, sem, timeout) for p in chunk]):
            if got:
                open_ports.append(got)
    return sorted(set(open_ports))


def ssh_banner(ip, port):
    try:
        s = socket.create_connection((ip, port), timeout=6)
        banner = s.recv(80).decode(errors="ignore").strip()
        s.close()
        return banner
    except Exception as exc:
        return "ERR %s" % type(exc).__name__


def ssh_methods(ip, port):
    """Набор методов виден без логина: 'publickey,password' = пароль открыт."""
    try:
        out = subprocess.run(
            ["ssh", "-p", str(port), "-o", "PreferredAuthentications=none",
             "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
             "-o", "ConnectTimeout=6", "nobody@" + ip],
            capture_output=True, text=True, timeout=15)
        m = re.search(r"Permission denied \(([^)]*)\)", out.stderr)
        return m.group(1) if m else "?"
    except Exception:
        return "?"


def tls_info(ip, port):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((ip, port), timeout=8) as raw:
            with ctx.wrap_socket(raw, server_hostname=ip) as tls:
                cert = tls.getpeercert() or {}
        subject = {k: v for part in cert.get("subject", ()) for k, v in part}
        issuer = {k: v for part in cert.get("issuer", ()) for k, v in part}
        return "CN=%s / %s" % (subject.get("commonName", "?"), issuer.get("organizationName", "?"))
    except Exception:
        return ""


def http_probe(ip, port, tls=False):
    scheme = "https" if tls else "http"
    try:
        out = subprocess.run(["curl", "-sk", "--max-time", "8", "-D-",
                              "%s://%s:%d/" % (scheme, ip, port)],
                             capture_output=True, text=True, timeout=12).stdout
    except Exception:
        return ""
    head, _, body = out.partition("\r\n\r\n")
    status = re.search(r"HTTP/[\d.]+ (\d{3})", head)
    server = re.search(r"(?im)^server:\s*(.+)$", head)
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", body)
    if not status:
        return ""
    bits = [status.group(1)]
    if server:
        bits.append("srv=" + server.group(1).strip()[:30])
    if title:
        bits.append("title=" + re.sub(r"\s+", " ", title.group(1)).strip()[:50])
    return " ".join(bits)


async def audit(ip, ports, full):
    open_ports = await scan(ip, ports) if full else await scan(ip, ports)
    info = {"open": open_ports, "ssh": {}, "tls": {}, "http": {}}
    for p in open_ports:
        if p in (22, 2222):
            info["ssh"][str(p)] = {"banner": ssh_banner(ip, p), "methods": ssh_methods(ip, p)}
        if p == 3389:
            info["rdp"] = True
        t = tls_info(ip, p)
        if t:
            info["tls"][str(p)] = t
            h = http_probe(ip, p, tls=True)
        else:
            h = http_probe(ip, p, tls=False)
        if h:
            info["http"][str(p)] = h
    return info


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hosts", nargs="+")
    ap.add_argument("--common", action="store_true")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    ports = COMMON if args.common else list(range(1, 65536))
    result = {}
    for ip in args.hosts:
        result[ip] = await audit(ip, ports, not args.common)
        d = result[ip]
        print("\n%s  ports=%s" % (ip, d["open"]))
        for p, v in d["ssh"].items():
            print("  ssh/%s: %s | methods=%s" % (p, v["banner"], v["methods"]))
        if d.get("rdp"):
            print("  3389: RDP наружу — проверять в первую очередь")
        for p, v in d["tls"].items():
            print("  tls/%s: %s" % (p, v))
        for p, v in d["http"].items():
            print("  http/%s: %s" % (p, v))
        sys.stdout.flush()
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=1)
        print("\njson -> " + args.json)


if __name__ == "__main__":
    asyncio.run(main())
