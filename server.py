#!/usr/bin/env python3
"""
Bike Shop Registry — shared server for the local network.

Serves index.html and keeps one shared database as a JSON file, so every
browser on the network sees the same clients, bikes and work. Standard
library only; run it with `python3 server.py`.

API
  GET  /api/version  -> {"version": n}
  GET  /api/db       -> {"version": n, "db": {...} | null}
  PUT  /api/db       <- {"baseVersion": n, "db": {...}}
                     -> 200 {"version": n+1}
                     -> 409 {"version": n, "db": {...}}  (someone saved first;
                        the client merges and tries again)

Environment
  BIKES_HOST   bind address (default 0.0.0.0 — every interface)
  BIKES_PORT   port (default 8080)
  BIKES_DATA   data directory (default ./data next to this file)
"""

import json
import os
import shutil
import sys
import threading
import time
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("BIKES_DATA", ROOT / "data")).resolve()
DB_FILE = DATA_DIR / "db.json"
BACKUP_DIR = DATA_DIR / "backups"
BACKUPS_KEPT = 60            # one per day the database changed
MAX_BODY = 64 * 1024 * 1024  # a shop's registry is far smaller; this just stops abuse

STATIC = {"/": "index.html", "/index.html": "index.html"}


class Database:
    """The whole registry as one versioned JSON document, saved atomically."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.version = 0
        self.db = None
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.version = stored.get("version", 0)
            self.db = stored.get("db")

    def snapshot(self):
        with self.lock:
            return {"version": self.version, "db": self.db}

    def put(self, base_version, db):
        """Store `db` if the writer had seen the latest version; else return the latest."""
        with self.lock:
            if base_version != self.version:
                return False, {"version": self.version, "db": self.db}
            self.version += 1
            self.db = db
            self._write()
            return True, {"version": self.version}

    def _write(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        payload = {"version": self.version, "savedAt": int(time.time() * 1000), "db": self.db}
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        self._backup()

    def _backup(self):
        # Keep the last state of each day; prune the oldest beyond BACKUPS_KEPT.
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.path, BACKUP_DIR / f"db-{date.today().isoformat()}.json")
        for old in sorted(BACKUP_DIR.glob("db-*.json"))[:-BACKUPS_KEPT]:
            old.unlink()


class Handler(BaseHTTPRequestHandler):
    server_version = "BikeShop/1"
    database: Database = None

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/version":
            return self._json(HTTPStatus.OK, {"version": self.database.snapshot()["version"]})
        if path == "/api/db":
            return self._json(HTTPStatus.OK, self.database.snapshot())
        if path in STATIC:
            return self._file(ROOT / STATIC[path], "text/html; charset=utf-8")
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_PUT(self):
        if self.path.split("?", 1)[0] != "/api/db":
            return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= MAX_BODY:
                return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "bad length"})
            body = json.loads(self.rfile.read(length))
            base, db = body["baseVersion"], body["db"]
            if not isinstance(base, int) or not isinstance(db, dict) or not isinstance(db.get("clients"), list):
                raise ValueError("not a registry database")
        except (ValueError, KeyError, TypeError) as err:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": str(err)})

        ok, result = self.database.put(base, db)
        self._json(HTTPStatus.OK if ok else HTTPStatus.CONFLICT, result)

    def _json(self, status, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path, content_type):
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")  # always pick up a new version of the app
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        # Polling makes GET /api/version very chatty; log only what matters.
        if self.command != "GET" or not self.path.startswith("/api/version"):
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def main():
    host = os.environ.get("BIKES_HOST", "0.0.0.0")
    port = int(os.environ.get("BIKES_PORT", "8080"))
    Handler.database = Database(DB_FILE)
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Bike Shop Registry on http://{host}:{port}  (data: {DB_FILE}, version {Handler.database.version})",
          flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
