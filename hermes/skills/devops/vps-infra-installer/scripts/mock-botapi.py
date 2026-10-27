#!/usr/bin/env python3
"""Минимальный мок Telegram Bot API для оффлайн-проверки restore/notify путей.

Зачем: живой прогон `--from-bot` тянет ~130 МБ из Telegram и пишет 9 файлов в чат
владельца, а `monitor.py backup` ещё и отправляет отчёт. Для проверки логики
(реестр file_id, split/join, sha256, guard на часть >20 МБ) сеть не нужна.

Маршруты:
  POST /bot<token>/sendDocument   multipart upload -> message_id + document.file_id
  GET  /bot<token>/getFile?file_id=ID              -> {ok, result:{file_path, file_size}}
  GET  /file/bot<token>/<path>                     -> raw bytes
  GET  /bot<token>/getUpdates?…                    -> документы, будто их переслали боту

Использование в тесте:
    import mock_botapi
    server, base = mock_botapi.start(Path("/tmp/mock-files"))
    install.TG_API = base                      # install.py читает TG_API
    monitor.urlopen = ...                      # подменить https://api.telegram.org на base

Запуск как сервер (base URL в stdout):
    python3 mock-botapi.py /tmp/mock-files
"""
from __future__ import annotations

import email.parser
import email.policy
import hashlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.files: dict[str, dict] = {}  # file_id -> {name, path, size}
        self.updates: list[dict] = []
        self.next_message_id = 1000


def make_handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            return

        def _json(self, payload: dict, code: int = 200) -> None:
            blob = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)

        def do_POST(self) -> None:  # noqa: N802
            if not urlparse(self.path).path.endswith("/sendDocument"):
                self._json({"ok": False, "description": "Not Found"}, 404)
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            ctype = self.headers.get("Content-Type", "")
            raw = f"Content-Type: {ctype}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
            msg = email.parser.BytesParser(policy=email.policy.default).parsebytes(raw)
            doc_part = None
            for part in msg.iter_parts():
                if part.get_param("name", header="content-disposition") == "document":
                    doc_part = part
            if doc_part is None:
                self._json({"ok": False, "description": "no document"}, 400)
                return
            payload = doc_part.get_payload(decode=True) or b""
            name = doc_part.get_filename() or "file"
            digest = hashlib.sha256(payload + str(store.next_message_id).encode()).hexdigest()[:32]
            file_id = f"file{store.next_message_id}_{digest}"
            target = store.root / f"{file_id}.bin"
            target.write_bytes(payload)
            store.files[file_id] = {"name": name, "path": target, "size": len(payload)}
            store.next_message_id += 1
            store.updates.append(
                {
                    "update_id": store.next_message_id,
                    "message": {
                        "message_id": store.next_message_id,
                        "document": {
                            "file_id": file_id,
                            "file_name": name,
                            "file_size": len(payload),
                        },
                    },
                }
            )
            self._json(
                {
                    "ok": True,
                    "result": {
                        "message_id": store.next_message_id,
                        "document": {
                            "file_id": file_id,
                            "file_unique_id": digest[:16],
                            "file_name": name,
                            "file_size": len(payload),
                        },
                    },
                }
            )

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path.endswith("/getFile"):
                file_id = (query.get("file_id") or [""])[0]
                item = store.files.get(file_id)
                if not item:
                    self._json({"ok": False, "description": "Bad Request: file not found"}, 400)
                    return
                self._json(
                    {
                        "ok": True,
                        "result": {
                            "file_id": file_id,
                            "file_size": item["size"],
                            "file_path": f"docs/{file_id}.bin",
                        },
                    }
                )
                return
            if parsed.path.endswith("/getUpdates"):
                self._json({"ok": True, "result": store.updates})
                return
            if "/file/bot" in parsed.path:
                name = parsed.path.rsplit("/", 1)[-1].split(".")[0]
                item = store.files.get(name)
                if not item:
                    self._json({"ok": False, "description": "Not Found"}, 404)
                    return
                blob = item["path"].read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(blob)))
                self.end_headers()
                self.wfile.write(blob)
                return
            self._json({"ok": False, "description": "Not Found"}, 404)

    return Handler


def start(store_root: Path) -> tuple[ThreadingHTTPServer, str]:
    """Поднять мок на свободном порту; вернуть (server, base_url)."""
    store = Store(store_root)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/mock-bot-files")
    srv, base = start(root)
    print(base, flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
