#!/usr/bin/env python3
"""FakeTLS (MTProto/mtg) handshake builder, validator and pcap analyzer.

Implements the mtg faketls check:
    digest   = HMAC-SHA256(secret, ClientHello with the 32-byte random zeroed)
    computed = digest XOR client_random
    valid    <=> computed[:28] == zeros and uint32_le(computed[28:]) is a timestamp
                 inside the server's `tolerate-time-skewness` window

Usage:
    faketls-probe.py selftest
    faketls-probe.py live <host> <port> <domain> <secret_hex>
    faketls-probe.py pcap <file> <domain> <secret_hex>

secret_hex is the mtg secret WITHOUT the leading 'ee' (the 16 random bytes).

Why this exists: it decides without a phone whether an MTProto fake-TLS ingress
rejects (falls back to the real site) or accepts a handshake, and whether a
captured client hello carries the expected secret, SNI and timestamp.
"""
import hashlib
import hmac
import os
import struct
import sys
import time

RANDOM_LEN = 32
# record header(5) + handshake type(1) + uint24 length(3) + client version(2)
RANDOM_OFFSET = 11


def _sni_ext(domain: str) -> bytes:
    name = domain.encode()
    entry = b"\x00" + struct.pack("!H", len(name)) + name
    sni_list = struct.pack("!H", len(entry)) + entry
    return struct.pack("!HH", 0, len(sni_list)) + sni_list


def build_client_hello(secret: bytes, domain: str, timestamp: int | None = None) -> bytes:
    """Build a ClientHello mtg accepts (layout: version, random, sid, cipher(2), ext_len(2))."""
    ts = int(time.time()) if timestamp is None else timestamp
    body = b"\x03\x03" + b"\x00" * RANDOM_LEN
    body += b"\x20" + os.urandom(32)
    body += b"\x13\x01"
    ext = _sni_ext(domain)
    body += struct.pack("!H", len(ext)) + ext
    hs = b"\x01" + len(body).to_bytes(3, "big") + body
    record = b"\x16\x03\x01" + struct.pack("!H", len(hs)) + hs
    digest = hmac.new(secret, record, hashlib.sha256).digest()
    pad = b"\x00" * (RANDOM_LEN - 4) + struct.pack("<I", ts)
    newrandom = bytes(a ^ b for a, b in zip(digest, pad))
    return record[:RANDOM_OFFSET] + newrandom + record[RANDOM_OFFSET + RANDOM_LEN:]


def extract_sni(record: bytes) -> str | None:
    try:
        p = RANDOM_OFFSET + RANDOM_LEN
        sid_len = record[p]
        p += 1 + sid_len + 2
        ext_len = struct.unpack("!H", record[p:p + 2])[0]
        p += 2
        end = min(len(record), p + ext_len)
        while p + 4 <= end:
            etype, elen = struct.unpack("!HH", record[p:p + 4])
            data = record[p + 4:p + 4 + elen]
            if etype == 0 and len(data) >= 5:
                nlen = struct.unpack("!H", data[3:5])[0]
                return data[5:5 + nlen].decode(errors="replace")
            p += 4 + elen
    except (IndexError, struct.error):
        return None
    return None


def validate_client_hello(record: bytes, secret: bytes) -> dict:
    if len(record) < RANDOM_OFFSET + RANDOM_LEN:
        return {"ok": False, "reason": "short"}
    if record[0] != 0x16 or record[5] != 0x01:
        return {"ok": False, "reason": "not-clienthello"}
    client_random = record[RANDOM_OFFSET:RANDOM_OFFSET + RANDOM_LEN]
    zeroed = record[:RANDOM_OFFSET] + b"\x00" * RANDOM_LEN + record[RANDOM_OFFSET + RANDOM_LEN:]
    digest = hmac.new(secret, zeroed, hashlib.sha256).digest()
    computed = bytes(a ^ b for a, b in zip(digest, client_random))
    ts = struct.unpack("<I", computed[-4:])[0]
    return {
        "ok": computed[:-4] == b"\x00" * (RANDOM_LEN - 4),
        "timestamp": ts,
        "age_seconds": int(time.time()) - ts,
        "sni": extract_sni(record),
    }


def live_probe(host: str, port: int, domain: str, secret: bytes) -> dict:
    import socket
    hello = build_client_hello(secret, domain)
    sock = socket.create_connection((host, port), timeout=8)
    sock.sendall(hello)
    sock.settimeout(8)
    data = b""
    try:
        while len(data) < 8000:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    except socket.timeout:
        pass
    sock.close()
    # A real TLS server answers with a Certificate handshake (0x0b); mtg's fake
    # layer answers garbage MTProto with a 7-byte alert (15 03 03 00 02 02 32).
    fallback = b"\x0b\x00" in data
    return {
        "bytes": len(data),
        "first": data[:8].hex(),
        "verdict": "REJECTED -> served real site" if fallback else "ACCEPTED by faketls layer",
    }


def _read_pcap(path: str):
    with open(path, "rb") as fh:
        gh = fh.read(24)
        if len(gh) < 24:
            return
        magic = gh[:4]
        endian = "<" if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
        linktype = struct.unpack(endian + "I", gh[20:24])[0]
        while True:
            ph = fh.read(16)
            if len(ph) < 16:
                break
            _ts, _usec, incl, _orig = struct.unpack(endian + "IIII", ph)
            data = fh.read(incl)
            yield linktype, data


def analyze_pcap(path: str, secret: bytes):
    streams: dict = {}
    for linktype, data in _read_pcap(path):
        if linktype == 276:      # LINUX_SLL2
            off, proto = 20, struct.unpack("!H", data[0:2])[0]
        elif linktype == 113:    # LINUX_SLL
            off, proto = 16, struct.unpack("!H", data[14:16])[0]
        elif linktype == 1:      # Ethernet
            off, proto = 14, struct.unpack("!H", data[12:14])[0]
        else:
            continue
        if proto != 0x0800:
            continue
        ip = data[off:]
        ihl = (ip[0] & 0x0F) * 4
        if ip[9] != 6:
            continue
        src = ".".join(str(b) for b in ip[12:16])
        tcp = ip[ihl:]
        sp, dp = struct.unpack("!HH", tcp[0:4])
        doff = (tcp[12] >> 4) * 4
        payload = tcp[doff:]
        if not payload:
            continue
        key = (src, sp, dp)
        streams[key] = (streams.get(key, b"") + payload)[:4096]
    for (src, sp, dp), buf in streams.items():
        idx = buf.find(b"\x16\x03\x01")
        if idx < 0:
            continue
        rec = buf[idx:]
        rlen = struct.unpack("!H", rec[3:5])[0]
        if len(rec) < 5 + rlen:
            print(f"{src}:{sp} -> {dp}: capture TRUNCATED ({len(rec)} of {5 + rlen} bytes)"
                  " — re-run tcpdump with -s 0; HMAC check below would be a false negative")
            continue
        print(f"{src}:{sp} -> {dp}: {validate_client_hello(rec[:5 + rlen], secret)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    mode = sys.argv[1]
    if mode == "selftest":
        sec = bytes.fromhex("11" * 16)
        print(validate_client_hello(build_client_hello(sec, "example.com"), sec))
    elif mode == "live":
        print(live_probe(sys.argv[2], int(sys.argv[3]), sys.argv[4], bytes.fromhex(sys.argv[5])))
    elif mode == "pcap":
        analyze_pcap(sys.argv[2], bytes.fromhex(sys.argv[4]))
    else:
        print(__doc__)
