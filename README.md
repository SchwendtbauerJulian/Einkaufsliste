# Einkaufsliste für Home Assistant

App-Repository für Home Assistant: eine Einkaufsliste mit **Mengen und Einheiten**
(Stück, Gewicht, Volumen), Notizen, Abhaken, Dashboard-Karte, Seitenleiste, Sprachsteuerung
und einer **Handy-App**, die auch ohne Empfang funktioniert. Die Daten liegen in einer SQLite-Datenbank.

## Installation

1. In Home Assistant: **Einstellungen → Apps → App-Store** (früher „Add-ons“).
2. Oben rechts **⋮ → Repositories**, die Adresse dieses Repositories einfügen und auf **Hinzufügen** tippen.
3. Die Seite neu laden. Unten erscheint **Einkaufsliste**. Öffnen, **Installieren** und dann **Starten**.
4. Home Assistant **neu starten**.
5. **Einstellungen → Geräte & Dienste → Integration hinzufügen → „Einkaufsliste“**.

Die ausführliche Anleitung (Karte, Handy-App, Services, Sprachsteuerung) steht in
[einkaufsliste/DOCS.md](einkaufsliste/DOCS.md). In Home Assistant findest du sie im Reiter
„Dokumentation“ der App.

## Aufbau

Die App ist ein kleiner Container. Beim Start kopiert sie die mitgelieferte Integration nach
`/config/custom_components/einkaufsliste` und stellt die Liste in der Seitenleiste bereit.
Die eigentliche Logik steckt in der Integration.

```
repository.yaml                      Beschreibung des Repositories für den App-Store
einkaufsliste/                       die App
├── config.yaml                      App-Definition (Seitenleiste, Rechte, Optionen)
├── Dockerfile, run.sh               Container: installiert die Integration, startet server.py
├── server.py                        Oberfläche in der Seitenleiste (leitet API-Aufrufe weiter)
├── DOCS.md, CHANGELOG.md, icon.png, logo.png, translations/
└── integration/einkaufsliste/       die Home-Assistant-Integration
    ├── __init__.py                  Setup, Karte und Handy-App ausliefern
    ├── config_flow.py               Einrichtung über die UI
    ├── db.py                        SQLite-Datenbank
    ├── store.py                     Datenmodell, Zusammenfassen von Mengen, Offline-Sync
    ├── parsing.py                   „2 kg Mehl“ → Name/Menge/Einheit
    ├── todo.py                      To-do-Entität und Services
    ├── websocket.py                 API für die Karte (inkl. Live-Updates)
    ├── http_api.py                  API für die Handy-App
    ├── www/einkaufsliste-card.js    Dashboard-Karte
    └── app/                         Handy-App (index.html, app.js, sw.js, Icons)
dev/
├── vorschau.html                    Vorschau der Karte im Browser
└── server.py                        Testserver für die Handy-App (inkl. Test-Anmeldung)
```

## Neue Version veröffentlichen

1. Änderungen machen.
2. Versionsnummer an allen vier Stellen erhöhen: `einkaufsliste/config.yaml`,
   `integration/einkaufsliste/manifest.json`, `integration/einkaufsliste/const.py` (`VERSION`) und
   `CARD_VERSION` in der Karte. Bei Änderungen an der Handy-App außerdem `CACHE` in `app/sw.js`.
3. Einen Eintrag in `einkaufsliste/CHANGELOG.md` schreiben.
4. Committen und pushen. Home Assistant zeigt das Update nach einiger Zeit im App-Store an
   (sofort: App-Store → ⋮ → Nach Updates suchen).

## Lokal ausprobieren (ohne Home Assistant)

- **Karte:** `dev/vorschau.html` im Browser öffnen.
- **Handy-App:** `python dev/server.py`, dann <http://127.0.0.1:8124/einkaufsliste/app/index.html>.
  Der Testserver bildet die Anmeldeseite von Home Assistant nach („Als Testbenutzer anmelden“).
  Zum Offline-Testen den Server mit Strg+C beenden, in der App weiterarbeiten und den Server
  wieder starten.
