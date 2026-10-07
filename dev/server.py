"""Lokaler Testserver für die Handy-App – ohne Home Assistant.

Nutzt den echten Code der Integration (store.py, db.py, parsing.py) und ersetzt nur
Home Assistant durch einen minimalen Platzhalter – inklusive einer Test-Anmeldeseite.

Start:   python dev/server.py
Öffnen:  http://127.0.0.1:8124/einkaufsliste/app/index.html

Offline testen: Server mit Strg+C beenden, in der App weiterarbeiten, Server wieder starten.
Die Daten liegen in dev/einkaufsliste-dev.db.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import html
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time
import types
from urllib.parse import parse_qs, urlencode, urlsplit

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "einkaufsliste" / "integration" / "einkaufsliste"
APP_DIR = COMPONENT / "app"
DB_PATH = Path(__file__).resolve().parent / "einkaufsliste-dev.db"
PORT = 8124
# Gültigkeit der Zugangsschlüssel in Sekunden (klein setzen, um das Erneuern zu testen)
ACCESS_TTL = int(os.environ.get("DEV_TOKEN_TTL", "1800"))
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

# ---------------------------------------------------------------- Anmeldung (wie Home Assistant)

AUTH_FILE = DB_PATH.with_name("auth-dev.json")
codes: dict[str, str] = {}  # code -> client_id
# refresh_token -> client_id; bleibt über Neustarts erhalten (wie bei Home Assistant)
refresh_tokens: dict[str, str] = json.loads(AUTH_FILE.read_text()) if AUTH_FILE.exists() else {}


def save_refresh_tokens() -> None:
    AUTH_FILE.write_text(json.dumps(refresh_tokens))
access_tokens: dict[str, float] = {}  # access_token -> läuft ab um


def issue_access() -> dict:
    token = secrets.token_hex(16)
    access_tokens[token] = time.time() + ACCESS_TTL
    return {"access_token": token, "token_type": "Bearer", "expires_in": ACCESS_TTL}


def same_origin(a: str, b: str) -> bool:
    pa, pb = urlsplit(a), urlsplit(b)
    return (pa.scheme, pa.netloc) == (pb.scheme, pb.netloc)


LOGIN_PAGE = """<!doctype html><html lang="de"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Anmelden (Test)</title>
<body style="font-family:system-ui;max-width:420px;margin:40px auto;padding:0 16px">
<h1 style="font-weight:400">Home Assistant (Test)</h1>
<p>Hier würde die normale Anmeldeseite von Home Assistant erscheinen.</p>
<a id="login" href="{href}" style="display:inline-block;background:#03a9f4;color:#fff;padding:10px 18px;
border-radius:8px;text-decoration:none">Als Testbenutzer anmelden</a>
</body></html>"""

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
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if access_tokens.get(token, 0) > time.time():
            return True
        self._json(401, {"message": "Nicht angemeldet"})
        return False

    def _read_body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length", 0)))

    def translate_path(self, path):
        # /einkaufsliste/app/<datei> -> app/<datei>
        prefix = "/einkaufsliste/app"
        path = path.split("?", 1)[0]
        return super().translate_path(path[len(prefix):] if path.startswith(prefix) else "/__nicht_vorhanden__")

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/auth/authorize":
            self._authorize(parse_qs(url.query))
            return
        if url.path == "/api/einkaufsliste/lists":
            if self._authorized():
                self._json(200, [{"list_id": LIST_ID, "name": LIST_NAME}])
            return
        if url.path in ("/", "/einkaufsliste", "/einkaufsliste/app", "/einkaufsliste/app/"):
            self.send_response(302)
            self.send_header("Location", "/einkaufsliste/app/index.html")
            self.end_headers()
            return
        super().do_GET()

    def _authorize(self, query: dict) -> None:
        client_id = query.get("client_id", [""])[0]
        redirect_uri = query.get("redirect_uri", [""])[0]
        if not same_origin(client_id, redirect_uri):
            self._json(400, {"message": "redirect_uri passt nicht zu client_id"})
            return
        code = secrets.token_hex(8)
        codes[code] = client_id
        href = f"{redirect_uri}?{urlencode({'code': code, 'state': query.get('state', [''])[0]})}"
        body = LOGIN_PAGE.format(href=html.escape(href)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _token(self) -> None:
        form = {k: v[0] for k, v in parse_qs(self._read_body().decode()).items()}
        if form.get("action") == "revoke":
            refresh_tokens.pop(form.get("token", ""), None)
            save_refresh_tokens()
            self._json(200, {})
            return
        grant = form.get("grant_type")
        client_id = form.get("client_id", "")
        if grant == "authorization_code" and codes.pop(form.get("code", ""), None) == client_id:
            refresh = secrets.token_hex(16)
            refresh_tokens[refresh] = client_id
            save_refresh_tokens()
            print("  Anmeldung erfolgreich")
            self._json(200, {**issue_access(), "refresh_token": refresh})
        elif grant == "refresh_token" and refresh_tokens.get(form.get("refresh_token", "")) == client_id:
            print("  Zugangsschlüssel erneuert")
            self._json(200, issue_access())
        else:
            self._json(400, {"error": "invalid_request"})

    def do_POST(self):
        if self.path == "/auth/token":
            self._token()
            return
        if self.path != f"/api/einkaufsliste/{LIST_ID}/sync":
            self._json(404, {"message": "Einkaufsliste nicht gefunden"})
            return
        if not self._authorized():
            return
        try:
            body = json.loads(self._read_body() or b"{}")
        except ValueError:
            self._json(400, {"message": "Ungültiges JSON"})
            return
        ops = body.get("ops", [])
        if ops:
            print(f"  Sync: {len(ops)} Änderung(en): {', '.join(op['op'] for op in ops)}")
        self._json(200, run(shopping_list.async_sync(ops)))


if __name__ == "__main__":
    print(f"Testserver läuft: http://127.0.0.1:{PORT}/einkaufsliste/app/index.html")
    print(f"Datenbank: {DB_PATH}")
    print("Beenden mit Strg+C")
    try:
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
