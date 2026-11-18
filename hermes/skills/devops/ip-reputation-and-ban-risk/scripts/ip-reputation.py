#!/usr/bin/env python3
"""Read-only IP reputation / ban-risk audit.

    ip-reputation.py 1.2.3.4 [5.6.7.8 ...]     # passive sources only
    ip-reputation.py -a 1.2.3.4                # + port / SSH / TLS probes

Prints one JSON document to stdout. No auth attempts, no writes, no cron.
Requires: dig, whois, openssl, ssh (openssl/ssh only for -a).
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DNSBL = [
    ("spamhaus-zen", "zen.spamhaus.org"),
    ("barracuda", "b.barracudacentral.org"),
    ("spamcop", "bl.spamcop.net"),
    ("uceprotect-l2", "dnsbl-2.uceprotect.net"),
    ("uceprotect-l3", "dnsbl-3.uceprotect.net"),
    ("blocklist.de", "bl.blocklist.de"),
    ("dronebl", "dnsbl.dronebl.org"),
    ("psbl", "psbl.surriel.com"),
    ("s5h", "all.s5h.net"),
    ("manitu", "ix.dnsbl.manitu.net"),
    ("spameatingmonkey", "bl.spameatingmonkey.net"),
]

PORTS = [21, 22, 23, 25, 80, 110, 143, 443, 993, 2087, 2222, 3306,
         4443, 5432, 6379, 8080, 8443, 9000, 9200]

UA_JSON = {"User-Agent": "curl/8.5", "Accept": "application/json"}
UA_HTML = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}


def dig(name, rtype="A"):
    try:
        out = subprocess.run(["dig", "+short", "+time=2", "+tries=1", rtype, name],
                             capture_output=True, text=True, timeout=8).stdout
    except Exception as exc:  # noqa: BLE001
        return ["ERR:%s" % exc]
    return [line.strip() for line in out.splitlines()
            if line.strip() and not line.startswith(";")]


def http(url, headers, raw=False, timeout=15):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
    return body if raw else json.loads(body)


def rev(ip):
    return ".".join(reversed(ip.split(".")))


def whois_info(ip):
    try:
        text = subprocess.run(["whois", ip], capture_output=True, text=True,
                              timeout=20).stdout
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:120]}

    def grab(*keys):
        for key in keys:
            hit = re.search(rf"^{key}\s*:\s*(.+)$", text, re.M | re.I)
            if hit:
                return hit.group(1).strip()
        return None

    return {
        "netname": grab("netname"),
        "org": grab("org-name", "orgname"),
        "country": grab("country"),
        "abuse": grab("OrgAbuseEmail", "abuse-mailbox"),
        "created": grab("created", "regdate"),
    }


def ptr_info(ip):
    names = [n.rstrip(".") for n in dig(f"{rev(ip)}.in-addr.arpa", "PTR")]
    forward = {}
    for name in names:
        forward[name] = dig(name)
    confirmed = any(ip in addrs for addrs in forward.values())
    return {"ptr": names, "forward": forward, "forward_confirmed": confirmed}


def spamhaus_usable():
    return any(a.startswith("127.") for a in dig("2.0.0.127.zen.spamhaus.org"))


def dnsbl_info(ip):
    zone_results = {}
    for label, zone in DNSBL:
        codes = [a for a in dig(f"{rev(ip)}.{zone}") if a.startswith("127.")]
        zone_results[label] = codes or None
    if not spamhaus_usable():
        zone_results["spamhaus-zen"] = "unverifiable: resolver blocked by Spamhaus"
    return zone_results


def dronebl_page(ip):
    """CIDR listing + type + comment live only on the HTML lookup page."""
    try:
        text = http(f"https://www.dronebl.org/lookup?ip={ip}", UA_HTML, raw=True)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:120]}
    if "not listed in DroneBL" in text:
        return {"listed": False}
    hit = re.search(r"part of a CIDR listing on (\S+) as type (\d+) \(([^)]+)\)\s*"
                    r"with comment (.+?)\n", text)
    if hit:
        return {"listed": True, "cidr": hit.group(1), "type": int(hit.group(2)),
                "type_name": hit.group(3), "comment": hit.group(4).strip()[:200]}
    hit = re.search(r"as type (\d+) \(([^)]+)\)", text)
    if hit:
        return {"listed": True, "type": int(hit.group(1)), "type_name": hit.group(2)}
    return {"listed": None, "note": "page parsed empty — open it in the browser"}


def shodan(ip):
    try:
        return http(f"https://internetdb.shodan.io/{ip}", UA_JSON)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:120]}


def classifiers(ip):
    try:
        return http("http://ip-api.com/json/%s?fields=country,isp,as,reverse,proxy,"
                    "hosting,mobile" % ip, UA_JSON, timeout=12)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:120]}


def threat_intel(ip):
    out = {}
    try:
        otx = http(f"https://otx.alienvault.com/api/v1/indicators/IPv4/{ip}/general", UA_JSON)
        out["otx_pulses"] = otx.get("pulse_info", {}).get("count")
    except Exception as exc:  # noqa: BLE001
        out["otx_pulses"] = "ERR:%s" % str(exc)[:60]
    try:
        sfs = http(f"https://api.stopforumspam.com/api?ip={ip}&json", UA_JSON)
        out["sfs"] = {k: sfs.get("ip", {}).get(k) for k in ("appears", "frequency")}
    except Exception as exc:  # noqa: BLE001
        out["sfs"] = "ERR:%s" % str(exc)[:60]
    return out


def open_ports(ip, ports=PORTS, timeout=2):
    def probe(port):
        sock = socket.socket()
        sock.settimeout(timeout)
        try:
            return port if sock.connect_ex((ip, port)) == 0 else None
        finally:
            sock.close()
    with ThreadPoolExecutor(max_workers=16) as pool:
        return [p for p in pool.map(probe, ports) if p]


def ssh_fingerprint(ip):
    out = {}
    try:
        sock = socket.create_connection((ip, 22), 4)
        sock.settimeout(4)
        out["banner"] = sock.recv(120).decode("utf-8", "replace").strip()
        sock.close()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:80]}
    try:
        res = subprocess.run(
            ["ssh", "-o", "PreferredAuthentications=none", "-o", "BatchMode=yes",
             "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
             "-o", "ConnectTimeout=5", "nobody@" + ip],
            capture_output=True, text=True, timeout=15)
        hit = re.search(r"Permission denied \(([^)]*)\)", res.stderr)
        out["auth_methods"] = hit.group(1).split(",") if hit else res.stderr.strip()[:120]
    except Exception as exc:  # noqa: BLE001
        out["auth_methods"] = "ERR:%s" % str(exc)[:60]
    return out


def tls_probe(ip, port, sni="www.apple.com"):
    """Subject + SNI invariance: unchanged subject for a bogus SNI = TLS passthrough."""
    def subject(name):
        res = subprocess.run(
            ["openssl", "s_client", "-connect", f"{ip}:{port}",
             "-servername", name], input="", capture_output=True, text=True, timeout=12)
        if "BEGIN CERTIFICATE" not in res.stdout:
            return None
        cert = subprocess.run(["openssl", "x509", "-noout", "-subject"],
                              input=res.stdout, capture_output=True, text=True,
                              timeout=10).stdout.strip()
        return cert.replace("subject=", "")

    first = subject(sni)
    if not first:
        return {"port": port, "error": "no certificate"}
    second = subject("example.org")
    return {"port": port, "cert_subject": first[:120],
            "sni_invariant": bool(second and second == first)}


def audit(ip, active=False):
    row = {"ip": ip, "asn": whois_info(ip), "ptr": ptr_info(ip),
           "dnsbl": dnsbl_info(ip), "dronebl": dronebl_page(ip),
           "shodan": shodan(ip), "classifier": classifiers(ip),
           "intel": threat_intel(ip)}
    if active:
        row["ports_open"] = open_ports(ip)
        if 22 in row["ports_open"]:
            row["ssh"] = ssh_fingerprint(ip)
        tls = [tls_probe(ip, p) for p in row["ports_open"] if p in (443, 4443, 8443)]
        if tls:
            row["tls"] = tls
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ips", nargs="+")
    parser.add_argument("-a", "--active", action="store_true",
                        help="also probe ports, SSH methods and TLS certificates")
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=min(5, len(args.ips))) as pool:
        rows = list(pool.map(lambda ip: audit(ip, args.active), args.ips))
    json.dump(rows, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
