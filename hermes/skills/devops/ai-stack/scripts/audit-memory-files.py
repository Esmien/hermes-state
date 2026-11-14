#!/usr/bin/env python3
"""Аудит файлов файловой памяти Open WebUI по всем песочницам (только чтение).

Проверяет то, что не видно из `--dry-run` provisioner и из счётчиков БД:
  * ровно один управляемый блок `<!-- managed:begin/end -->` в AGENTS.md;
  * канонических строк шаблона вне блока нет (старый текст не висит рядом);
  * размер и число записей MEMORY.md / PROFILE.md;
  * владелец и права файлов.

Запуск:  python3 audit-memory-files.py [--base /home/ai_service/sandbox/users]
Код возврата 1, если найдены дефекты — годится для таймера/CI.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

MANAGED_BEGIN = "<!-- managed:begin -->"
MANAGED_END = "<!-- managed:end -->"
TEMPLATE_LINES = (
    "# Память",
    "# Memory",
)

def records(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]

def audit_file(path: Path) -> dict:
    info: dict = {"exists": path.exists()}
    if not path.exists():
        return info
    st = path.stat()
    text = path.read_text(encoding="utf-8", errors="replace")
    info.update(
        chars=len(text),
        records=len(records(text)),
        uid=st.st_uid,
        gid=st.st_gid,
        mode=oct(st.st_mode & 0o777),
    )
    return info

def audit_agents(path: Path) -> dict:
    info = audit_file(path)
    if not info.get("exists"):
        return info
    text = path.read_text(encoding="utf-8", errors="replace")
    info["managed_blocks"] = text.count(MANAGED_BEGIN)
    if MANAGED_BEGIN in text and MANAGED_END in text:
        head, rest = text.split(MANAGED_BEGIN, 1)
        body, tail = rest.split(MANAGED_END, 1)
        outside = head + tail
        info["template_lines_outside"] = sum(
            1 for ln in records(outside) if ln in TEMPLATE_LINES
        )
    else:
        info["template_lines_outside"] = None
    info["defects"] = []
    if info["managed_blocks"] != 1:
        info["defects"].append(f"managed blocks: {info['managed_blocks']}")
    if info.get("template_lines_outside"):
        info["defects"].append("template text outside block")
    return info

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="/home/ai_service/sandbox/users")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    base = Path(args.base)
    if not base.is_dir():
        print(f"base not found: {base}", file=sys.stderr)
        return 2

    report: dict[str, dict] = {}
    for user_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        agents = user_dir / ".agents"
        if not agents.is_dir():
            continue
        report[user_dir.name] = {
            "AGENTS.md": audit_agents(agents / "AGENTS.md"),
            "MEMORY.md": audit_file(agents / "MEMORY.md"),
            "PROFILE.md": audit_file(agents / "PROFILE.md"),
        }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for slug, files in report.items():
            a, m, p = files["AGENTS.md"], files["MEMORY.md"], files["PROFILE.md"]
            print(
                f"{slug:20s} blocks={a.get('managed_blocks')} "
                f"outside={a.get('template_lines_outside')} "
                f"MEMORY={m.get('chars')}c/{m.get('records')}r "
                f"PROFILE={p.get('chars')}c/{p.get('records')}r "
                f"owner={m.get('uid')}:{m.get('gid')} mode={m.get('mode')}"
            )
            for d in a.get("defects", []):
                print(f"  !! {d}")

    bad = [s for s, f in report.items() if f["AGENTS.md"].get("defects")]
    print(f"\nusers={len(report)} with_defects={len(bad)}")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
