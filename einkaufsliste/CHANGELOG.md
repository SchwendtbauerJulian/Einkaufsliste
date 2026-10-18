# Änderungen

## 1.3.2

- Neu: Produkte bearbeiten (⚙ → „Produkte: Markt & Kategorie ändern“, Seitenleiste und Handy-App): alle gespeicherten Produkte durchsuchen, Markt und Kategorie ändern oder Produkt löschen, auch offline
- Abgehakt wird nur noch mit dem Kästchen, ein Tipp auf den Namen hakt nicht mehr ab (Karte, Seitenleiste, Handy-App)
- Bei „von …“ steht nur noch der Vorname
- Eingabe: Menge und Einheit stehen in der Zeile der Notiz

## 1.3.1

- Neu: Über der Liste lässt sich auswählen, welche Märkte angezeigt werden (Karte, Seitenleiste, Handy-App), auch mehrere gleichzeitig. Jeder Knopf zeigt die Anzahl offener Artikel. Die Auswahl gilt nur auf dem jeweiligen Gerät

## 1.3.0

- Neu: Märkte (Drogerie, Bauernladen, Wöss, Lebensmittel, Sonstige) und bei Lebensmitteln Kategorien (Obst, Gemüse bis Tiefkühlwaren)
- Admin-Modus in der Seitenleiste: Märkte und Kategorien umbenennen, hinzufügen, löschen und sortieren; jeder Markt kann eigene Kategorien haben
- Markt und Kategorie werden beim ersten Anlegen eines Produkts festgelegt und in der Datenbank gespeichert, danach automatisch vorbelegt
- Liste nach Markt und Kategorie gruppiert, in der Reihenfolge wie im Geschäft (Karte, Seitenleiste, Handy-App)
- Autovervollständigung schlägt alle bekannten Produkte vor und zeigt Markt und Kategorie
- Services `add_item` und `update_item`: neue Felder `market` und `category` (Name des Markts bzw. der Kategorie)

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
