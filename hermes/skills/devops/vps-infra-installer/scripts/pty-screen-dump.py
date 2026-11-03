#!/usr/bin/env python3
"""Отрисовка терминального UI без экрана: команда → pty → pyte → текст экрана.

Зачем: прогресс-бары, панели и любой ANSI-вывод в логе выглядят как escape-байты,
по ним нельзя понять, что реально увидит человек. Скрипт запускает команду в
псевдотерминале заданного размера, кормит поток эмулятору терминала и печатает
итоговый экран (или самый заполненный кадр — он показывает панель в работе).

Примеры:
    scripts/pty-screen-dump.py --rows 34 --cols 110 --peak \
        -- python3 install.py --dry-run --only packages,users,verify
    scripts/pty-screen-dump.py -- python3 -c "print('hi')"

Зависимость pyte ставится сама в /tmp/pty-screen-venv (переопределяется PTY_DUMP_VENV).
"""

from __future__ import annotations

import argparse
import fcntl
import os
import pty
import struct
import subprocess
import sys
import termios


def ensure_pyte() -> None:
    try:
        import pyte  # noqa: F401

        return
    except ImportError:
        pass
    venv = os.environ.get("PTY_DUMP_VENV", "/tmp/pty-screen-venv")
    py = os.path.join(venv, "bin", "python")
    if not os.path.exists(py):
        subprocess.run([sys.executable, "-m", "venv", venv], check=True)
        subprocess.run([os.path.join(venv, "bin", "pip"), "install", "-q", "pyte"], check=True)
    os.execv(py, [py, os.path.abspath(__file__), *sys.argv[1:]])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=int, default=34)
    ap.add_argument("--cols", type=int, default=110)
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument("--peak", action="store_true", help="показать самый заполненный кадр вместо финального")
    ap.add_argument("cmd", nargs=argparse.REMAINDER, help="команда (после --)")
    args = ap.parse_args()
    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    if not cmd:
        ap.error("нужна команда после --")

    ensure_pyte()
    import pyte

    screen = pyte.Screen(args.cols, args.rows)
    stream = pyte.ByteStream(screen)

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", args.rows, args.cols, 0, 0))
    env = dict(
        os.environ,
        TERM="xterm-256color",
        COLUMNS=str(args.cols),
        LINES=str(args.rows),
    )
    env.pop("NO_PANE", None)

    proc = subprocess.Popen(cmd, cwd=args.cwd, stdin=slave, stdout=slave, stderr=slave, env=env)
    os.close(slave)

    best: tuple[int, list[str]] | None = None
    while True:
        try:
            chunk = os.read(master, 65536)
        except OSError:
            break
        if not chunk:
            break
        stream.feed(chunk)
        if args.peak:
            filled = sum(1 for line in screen.display if line.strip())
            if best is None or filled > best[0]:
                best = (filled, [line.rstrip() for line in screen.display])
    proc.wait()

    frame = best[1] if (args.peak and best) else [line.rstrip() for line in screen.display]
    for i, line in enumerate(frame):
        if line.strip():
            print(f"{i:02d}|{line}")
    print(f"-- exit={proc.returncode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
