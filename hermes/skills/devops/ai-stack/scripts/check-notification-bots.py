#!/usr/bin/env python3
"""Read-only health check of the Telegram notification path.

Answers the question "why didn't I get a message" without touching secrets:
  * validates every bot token with getMe (prints usernames only),
  * checks the file_id registry the restore path depends on (parts, sizes, age).

Exit codes: 0 = all good, 1 = at least one bot/registry problem.
Run as root (needs to read 0640 root:ai_service and 0600 root env files).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

NOTIF_ENV = Path("/home/ai_service/notifications/.env")
HERMES_ENV = Path("/root/.hermes/.env")
REGISTRY = Path("/home/ai_service/ai-stack/backups/postgres/.tg-registry.json")
TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")
DOWNLOAD_LIMIT = 20 * 1024 * 1024


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def check_token(label: str, token: str) -> bool:
    if not token:
        print(f"  ✗ {label}: не задан")
        return False
    if not TOKEN_RE.match(token):
        print(f"  ✗ {label}: не токен Telegram ({len(token)} символов, нет префикса 'id:hash') — заглушка или мусор")
        return False
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=15) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        print(f"  ✗ {label}: HTTP {exc.code} (токен отозван?)")
        return False
    except OSError as exc:
        print(f"  ✗ {label}: сеть недоступна ({exc.__class__.__name__})")
        return False
    print(f"  ✓ {label}: @{data['result']['username']}")
    return True


def check_registry() -> bool:
    if not REGISTRY.is_file():
        print(f"  ✗ реестр file_id отсутствует: {REGISTRY}")
        return False
    try:
        data = json.loads(REGISTRY.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  ✗ реестр не читается: {exc}")
        return False
    sets = data.get("sets") or []
    if not sets:
        print("  ✗ реестр пуст — ни один дамп не дошёл до бота")
        return False
    ok = True
    for entry in sets:
        parts = entry.get("parts") or []
        sizes = [int(p.get("size") or 0) for p in parts]
        biggest = max(sizes) if sizes else 0
        stamp = entry.get("created_at") or "?"
        age = "?"
        try:
            created = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            age = f"{(datetime.now(timezone.utc) - created).total_seconds() / 3600:.1f} ч"
        except ValueError:
            pass
        too_big = biggest > DOWNLOAD_LIMIT
        ok = ok and not too_big
        print(
            f"  {'✓' if not too_big else '✗'} {entry.get('db')}: {entry.get('dump')} — "
            f"{len(parts)} частей, макс {biggest / 2**20:.1f} MiB, {age} назад"
            + (" — часть больше лимита getFile 20 MiB, скачать нельзя" if too_big else "")
        )
    return ok


def main() -> int:
    notif = read_env(NOTIF_ENV)
    hermes = read_env(HERMES_ENV)
    print("Боты:")
    ok = check_token("monitor.py BOT_TOKEN", notif.get("BOT_TOKEN", ""))
    ok = check_token("monitor.py FILE_BOT_TOKEN", notif.get("FILE_BOT_TOKEN", "")) and ok
    ok = check_token("Hermes TELEGRAM_BOT_TOKEN", hermes.get("TELEGRAM_BOT_TOKEN", "")) and ok
    print("Реестр восстановления:")
    ok = check_registry() and ok
    print("OK" if ok else "ЕСТЬ ПРОБЛЕМЫ")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
