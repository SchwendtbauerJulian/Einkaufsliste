# Einkaufsliste – Android-App

Die Handy-App aus `einkaufsliste/integration/einkaufsliste/app/` als echte Android-App (Capacitor).
Oberfläche und Logik sind dieselben Dateien, `copy-web.js` kopiert sie beim Bauen nach `www/`.

Dazu kommen:

- **Anmeldung** mit Adresse, Benutzer und Passwort, direkt über die Anmelde-Schnittstelle von Home Assistant
  (`/auth/login_flow`). Die Anmeldeseite muss sich dafür nicht im Browser öffnen.
- **Anfragen über die native HTTP-Schicht.** Damit gibt es kein CORS-Problem, und `http://` im Heimnetz
  funktioniert auch.
- **Zwei Adressen:** Heimnetz und Ausweich (z. B. Tailscale). Probiert wird zuerst die, die zuletzt
  erreichbar war. Nicht erreichbare Adressen werden nach 5 Sekunden aufgegeben.
- **Abgleich im Hintergrund** (`SyncWorker.java`, WorkManager). Geht die App in den Hintergrund und es gibt
  noch nicht übertragene Änderungen, plant sie einen Auftrag „übertragen, sobald Netz da ist“. Android führt
  ihn auch aus, wenn die App geschlossen ist oder das Handy neu gestartet wurde. Ist Home Assistant noch nicht
  erreichbar, versucht Android es nach und nach erneut (1 min, 2 min, 3 min, …).

```
copy-web.js                     Web-App nach www/ kopieren (+ capacitor.js, ohne Service Worker)
capacitor.config.json           App-ID, Name
android/                        Android-Projekt
└── app/src/main/java/io/github/schwendtbauerjulian/einkaufsliste/
    ├── MainActivity.java       registriert das Plugin
    ├── BackgroundSyncPlugin.java  Brücke zur Web-App (Zustand speichern/laden, Abgleich planen)
    ├── SyncStore.java          gemeinsamer Speicher von Web-App und Hintergrund-Abgleich
    └── SyncWorker.java         Abgleich im Hintergrund (wie sync() in app.js)
```

## Einmalig einrichten

Am PC:

- **Node.js** und **Android Studio** (bringt Android SDK, Java 21 und `adb` mit)
- In diesem Ordner: `npm install`
- Falls Gradle das SDK nicht findet, `android/local.properties` mit
  `sdk.dir=C:/Users/<name>/AppData/Local/Android/Sdk` anlegen.

Am Handy:

1. *Einstellungen → Über das Telefon* öffnen und 7× auf *Build-Nummer* tippen. Damit schaltest du die
   Entwickleroptionen frei.
2. *Einstellungen → System → Entwickleroptionen → USB-Debugging* einschalten.
3. Das Handy per USB anschließen und *USB-Debugging zulassen* bestätigen.

## Aufs Handy spielen

```
npm run run
```

Kopiert die Web-App, baut das Projekt und fragt, auf welches Gerät die App soll (Handy oder Emulator).
Alternativ `npx cap open android` und in Android Studio auf ▶ klicken.

**Ohne Kabel:** `npm run apk` baut `android/app/build/outputs/apk/debug/app-debug.apk`. Diese Datei aufs
Handy schicken und dort installieren (Installation aus unbekannten Quellen einmal erlauben).

Nach Änderungen an der Web-App reicht ein erneutes `npm run run`. Die Daten auf dem Handy bleiben erhalten.

## Ausprobieren ohne Home Assistant

1. `python dev/server.py` (im Hauptordner starten)
2. App im Emulator starten und als Adresse `http://10.0.2.2:8124` eintragen. Zum Testen der
   Ausweich-Adresse als erste Adresse eine nicht erreichbare eintragen (z. B. `192.168.250.250:8123`) und
   `10.0.2.2:8124` als Ausweich-Adresse. Als Benutzername geht
   jeder, das Passwort ist `test`. Mit dem Benutzernamen `mfa` wird zusätzlich der Code `123456` abgefragt.
3. Hintergrund-Abgleich testen: Im Emulator WLAN und mobile Daten ausschalten, etwas eintragen, die App mit
   der Home-Taste verlassen und das Netz wieder einschalten. Im Testserver erscheint `Sync: …`, ohne dass die
   App geöffnet wird. Im Log (`adb logcat -s Einkaufsliste`) steht „… im Hintergrund übertragen“.

## Hinweise

- Die App ist mit dem Debug-Schlüssel signiert. Das reicht zum Installieren. Für den Play Store bräuchte
  sie einen eigenen Schlüssel und ein Release-Build.
- Versionsnummer der App: `versionCode`/`versionName` in `android/app/build.gradle`. Damit sich die App
  über eine bestehende Installation drüber installieren lässt, muss `versionCode` steigen. Beim
  Debug-Build ist das egal.
