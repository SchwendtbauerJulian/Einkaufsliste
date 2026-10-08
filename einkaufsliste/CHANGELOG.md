# Änderungen

## 1.2.0

- Neu: Android-App (Ordner `android-app/` im Repository). Sie überträgt Offline-Änderungen auch, wenn sie geschlossen ist
- Bei jedem Artikel steht, wer ihn auf die Liste gesetzt hat („von Anna“), in Karte, Seitenleiste und Handy-App
- Android-App: Ausweich-Adresse (z. B. Tailscale), falls die Adresse im Heimnetz nicht erreichbar ist
- Handy-App: Grundlage für die Android-App, im Browser ändert sich nichts

## 1.1.2

- Behoben: Liste in der Seitenleiste synchronisierte nicht („ausstehend“ blieb stehen), weil die App keinen Zugriff auf Home Assistant bekam
- Fehlt der Zugriff, steht oben jetzt „Kein Zugriff“ statt endlos „ausstehend“

## 1.1.1

- Behoben: Installation schlug mit „unknown error … build the image“ fehl

## 1.1.0

- Als App installierbar: Die App richtet die Integration automatisch ein
- Liste in der Seitenleiste
- Handy-App mit automatischem Abgleich, funktioniert auch ohne Empfang
- Anmeldung in der Handy-App mit dem normalen Home-Assistant-Benutzer (kein Token nötig)
- Notizfeld beim Hinzufügen
- Design in Home-Assistant-Blau

## 1.0.0

- Erste Version: Mengen und Einheiten, Abhaken, Dashboard-Karte, SQLite-Datenbank
