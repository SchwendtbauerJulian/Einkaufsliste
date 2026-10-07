"""Oberfläche der Einkaufsliste in der Seitenleiste (Ingress).

Liefert die App aus der Integration aus und leitet ihre API-Aufrufe an Home Assistant
weiter. Die Anmeldung übernimmt Home Assistant (Ingress), ein Token ist nicht nötig.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

APP_DIR = Path(os.environ.get("APP_DIR", "/integration/einkaufsliste/app"))
CORE_API = os.environ.get("CORE_API", "http://supervisor/core/api")
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
PORT = int(os.environ.get("PORT", "8099"))
# Nur der Ingress-Proxy von Home Assistant darf zugreifen
ALLOWED_CLIENTS = set(os.environ.get("ALLOWED_CLIENTS", "172.30.32.2").split(","))

FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/manifest.json": ("manifest.json", "application/json"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
}
PROXY = re.compile(r"^/proxy/(lists|[A-Za-z0-9_-]+/sync)$")
INGRESS_FLAG = b"<script>window.EINKAUFSLISTE_INGRESS = true;</script>\n  "


class Handler(BaseHTTPRequestHandler):
    server_version = "Einkaufsliste"

    def log_message(self, fmt, *args):
        if os.environ.get("DEBUG"):
            sys.stderr.write(f"{self.command} {self.path} {args}\n")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _allowed(self) -> bool:
        if self.client_address[0] in ALLOWED_CLIENTS:
            return True
        self._send(403, b"Forbidden", "text/plain")
        return False

    def do_GET(self):
        if not self._allowed():
            return
        path = self.path.split("?", 1)[0]
        if path in FILES:
            name, content_type = FILES[path]
            body = (APP_DIR / name).read_bytes()
            if name == "index.html":
                # Kennzeichnet für app.js, dass sie in der Seitenleiste läuft
                body = body.replace(b'<script src="app.js">', INGRESS_FLAG + b'<script src="app.js">')
            self._send(200, body, content_type)
        elif PROXY.match(path):
            self._proxy(path, None)
        else:
            self._send(404, b"Not found", "text/plain")

    def do_POST(self):
        if not self._allowed():
            return
        path = self.path.split("?", 1)[0]
        if not PROXY.match(path):
            self._send(404, b"Not found", "text/plain")
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self._proxy(path, body)

    def _proxy(self, path: str, body: bytes | None) -> None:
        url = f"{CORE_API}/einkaufsliste/{path.removeprefix('/proxy/')}"
        request = urllib.request.Request(
            url,
            data=body,
            method="POST" if body is not None else "GET",
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                self._send(response.status, response.read(), "application/json")
        except urllib.error.HTTPError as err:
            self._send(err.code, err.read(), "application/json")
        except OSError as err:
            message = json.dumps({"message": f"Home Assistant nicht erreichbar: {err}"})
            self._send(502, message.encode(), "application/json")


if __name__ == "__main__":
    print(f"Einkaufsliste-Oberfläche läuft auf Port {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
