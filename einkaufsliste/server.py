"""Startprogramm der App.

1. Installiert bzw. aktualisiert die Integration in custom_components.
2. Stellt die Liste in der Seitenleiste bereit (Ingress): liefert die Oberfläche aus und
   leitet ihre API-Aufrufe an Home Assistant weiter. Die Anmeldung übernimmt Home Assistant.
"""

from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import sys
import urllib.error
import urllib.request

INTEGRATION_SRC = Path(os.environ.get("INTEGRATION_SRC", "/integration/einkaufsliste"))
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/homeassistant"))
OPTIONS_FILE = Path(os.environ.get("OPTIONS_FILE", "/data/options.json"))
APP_DIR = Path(os.environ.get("APP_DIR", str(INTEGRATION_SRC / "app")))
CORE_API = os.environ.get("CORE_API", "http://supervisor/core/api")
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


def log(message: str) -> None:
    print(message, flush=True)


def supervisor_token() -> str:
    """Zugangsschlüssel für die Home-Assistant-API.

    Das Basis-Image (s6-overlay) leert die Umgebungsvariablen für das Startprogramm und legt sie
    stattdessen unter /run/s6/container_environment ab.
    """
    for name in ("SUPERVISOR_TOKEN", "HASSIO_TOKEN"):
        if os.environ.get(name):
            return os.environ[name]
        file = Path("/run/s6/container_environment") / name
        if file.is_file() and (token := file.read_text().strip()):
            return token
    return ""


TOKEN = supervisor_token()


# ---------------------------------------------------------------- Integration installieren


def checksum(folder: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(folder.rglob("*")):
        if file.is_file() and "__pycache__" not in file.parts:
            digest.update(str(file.relative_to(folder)).encode())
            digest.update(file.read_bytes())
    return digest.hexdigest()


def call_service(service: str, data: dict) -> None:
    request = urllib.request.Request(
        f"{CORE_API}/services/{service}",
        data=json.dumps(data).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(request, timeout=15).close()
    except OSError as err:
        log(f"Aufruf von {service} fehlgeschlagen: {err}")


def install_integration() -> None:
    """Kopiert die mitgelieferte Integration nach custom_components, falls sie sich geändert hat."""
    if not INTEGRATION_SRC.is_dir():
        log("Keine mitgelieferte Integration gefunden – Installation übersprungen.")
        return
    dest = CONFIG_DIR / "custom_components" / "einkaufsliste"
    if dest.is_dir() and checksum(INTEGRATION_SRC) == checksum(dest):
        log("Integration ist aktuell.")
        return

    first_install = not dest.exists()
    log(f"Installiere Integration nach {dest} ...")
    shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(INTEGRATION_SRC, dest, ignore=shutil.ignore_patterns("__pycache__"))

    options = json.loads(OPTIONS_FILE.read_text()) if OPTIONS_FILE.exists() else {}
    if options.get("auto_restart"):
        log("Starte Home Assistant neu ...")
        call_service("homeassistant/restart", {})
    elif first_install:
        call_service(
            "persistent_notification/create",
            {
                "notification_id": "einkaufsliste_installiert",
                "title": "Einkaufsliste installiert",
                "message": "Bitte Home Assistant einmal neu starten (Einstellungen → System → Neu starten). "
                "Danach unter Einstellungen → Geräte & Dienste → Integration hinzufügen → "
                "„Einkaufsliste“ einrichten.",
            },
        )
    else:
        call_service(
            "persistent_notification/create",
            {
                "notification_id": "einkaufsliste_aktualisiert",
                "title": "Einkaufsliste aktualisiert",
                "message": "Bitte Home Assistant neu starten, damit die neue Version aktiv wird.",
            },
        )


# ---------------------------------------------------------------- Seitenleiste


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
    if not TOKEN:
        log("Kein Zugangsschlüssel für Home Assistant gefunden – die Liste kann nicht synchronisieren.")
    install_integration()
    log(f"Oberfläche für die Seitenleiste läuft auf Port {PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
