#!/usr/bin/env python3
"""Convert saved HTML to readable plain text without a renderer.

Strips script/style/svg/noscript, turns tags into line breaks, unescapes
entities, drops empty lines and consecutive duplicates (nav menus repeat
every link twice). Good enough for marketing sites, docs, help centres,
legal pages and news; useless for JS-only SPAs — they need the embedded
state or a real browser.

Usage:
    python3 html_to_text.py page.html [start:end] [--grep WORD]

    html_to_text.py page.html            # whole text
    html_to_text.py page.html 0:5000     # char window, for big pages
    html_to_text.py page.html --grep тариф -C 3
"""
import argparse
import html as htmllib
import re
import sys


def html_to_text(src: str) -> str:
    s = re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", src)
    s = re.sub(r"(?s)<br\s*/?>", "\n", s)
    s = re.sub(r"(?s)</(p|div|li|tr|h[1-6]|section)>\s*", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", "\n", s)
    s = htmllib.unescape(s)
    out = []
    for line in (l.strip() for l in s.split("\n")):
        if line and (not out or out[-1] != line):
            out.append(line)
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("window", nargs="?", default=None, help="START:END char slice")
    ap.add_argument("--grep", default=None, help="print context around matches")
    ap.add_argument("-C", type=int, default=2, help="context lines for --grep")
    a = ap.parse_args()

    with open(a.path, encoding="utf-8", errors="ignore") as f:
        text = html_to_text(f.read())

    if a.grep:
        lines = text.split("\n")
        pat = re.compile(a.grep, re.I)
        for i, line in enumerate(lines):
            if pat.search(line):
                lo, hi = max(0, i - a.C), min(len(lines), i + a.C + 1)
                print("\n".join(lines[lo:hi]))
                print("-" * 40)
        return 0

    if a.window:
        start, end = (int(x) for x in a.window.split(":"))
        text = text[start:end]

    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
