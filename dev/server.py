"""Lokaler Testserver für die Offline-App – ohne Home Assistant.

Nutzt den echten Code der Integration (store.py, db.py, parsing.py) und ersetzt nur
Home Assistant durch einen minimalen Platzhalter.

Start:   python dev/server.py
Öffnen:  http://localhost:8124/einkaufsliste/app/index.html
Token:   dev

Offline testen: Server mit Strg+C beenden, in der App weiterarbeiten, Server wieder starten.
Die Daten liegen in dev/einkaufsliste-dev.db.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import types

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "einkaufsliste" / "integration" / "einkaufsliste"
APP_DIR = COMPONENT / "app"
DB_PATH = Path(__file__).resolve().parent / "einkaufsliste-dev.db"
PORT = 8124
TOKEN = "dev"
LIST_ID = "dev-liste"
LIST_NAME = "Einkaufsliste (Test)"

# ---------------------------------------------------------------- Home-Assistant-Platzhalter

for name in ("homeassistant", "homeassistant.util"):
    sys.modules[name] = types.ModuleType(name)
core = types.ModuleType("homeassistant.core")
core.HomeAssistant = object
core.callback = lambda func: func
sys.modules["homeassistant.core"] = core
dt = types.ModuleType("homeassistant.util.dt")
dt.utcnow = lambda: datetime.now(UTC)
sys.modules["homeassistant.util.dt"] = dt
sys.modules["homeassistant.util"].dt = dt

# Integration als Paket laden, ohne __init__.py (das braucht echtes Home Assistant)
package = types.ModuleType("einkaufsliste")
package.__path__ = [str(COMPONENT)]
sys.modules["einkaufsliste"] = package

from einkaufsliste.db import Database  # noqa: E402
from einkaufsliste.store import ShoppingList  # noqa: E402


class FakeHass:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def async_add_executor_job(self, func, *args):
        return self.loop.run_in_executor(None, func, *args)


loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, daemon=True).start()


def run(coro):
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


db = Database(str(DB_PATH))
db.init()
shopping_list = ShoppingList(FakeHass(loop), db, LIST_ID)
run(shopping_list.async_load())

# ---------------------------------------------------------------- HTTP


class Handler(SimpleHTTPRequestHandler):
    # Windows liefert .js sonst evtl. als text/plain – dann verweigert der Browser den Service Worker
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".json": "application/json",
        ".css": "text/css",
        ".png": "image/png",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP_DIR), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"  {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}\n")

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _json(self, status: int, data) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if self.headers.get("Authorization") == f"Bearer {TOKEN}":
            return True
        self._json(401, {"message": "Nicht angemeldet"})
        return False

    def translate_path(self, path):
        # /einkaufsliste/app/<datei> -> app/<datei>
        prefix = "/einkaufsliste/app"
        path = path.split("?", 1)[0]
        return super().translate_path(path[len(prefix):] if path.startswith(prefix) else "/__nicht_vorhanden__")

    def do_GET(self):
        if self.path == "/api/einkaufsliste/lists":
            if self._authorized():
                self._json(200, [{"list_id": LIST_ID, "name": LIST_NAME}])
            return
        if self.path in ("/", "/einkaufsliste", "/einkaufsliste/app", "/einkaufsliste/app/"):
            self.send_response(302)
            self.send_header("Location", "/einkaufsliste/app/index.html")
            self.end_headers()
            return
        super().do_GET()

    def do_POST(self):
        if self.path != f"/api/einkaufsliste/{LIST_ID}/sync":
            self._json(404, {"message": "Einkaufsliste nicht gefunden"})
            return
        if not self._authorized():
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError:
            self._json(400, {"message": "Ungültiges JSON"})
            return
        ops = body.get("ops", [])
        if ops:
            print(f"  Sync: {len(ops)} Änderung(en): {', '.join(op['op'] for op in ops)}")
        self._json(200, run(shopping_list.async_sync(ops)))


if __name__ == "__main__":
    print(f"Testserver läuft: http://localhost:{PORT}/einkaufsliste/app/index.html")
    print(f"Token: {TOKEN}   Datenbank: {DB_PATH}")
    print("Beenden mit Strg+C")
    try:
        ThreadingHTTPServer(("localhost", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
