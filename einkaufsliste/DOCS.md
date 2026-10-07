# Einkaufsliste

Einkaufsliste mit **Mengen und Einheiten** (Stück, Gewicht, Volumen), Notizen, Abhaken,
Dashboard-Karte, Seitenleiste, Sprachsteuerung und einer Offline-App fürs Handy.

## Funktionen

- Artikel mit Menge und Einheit: `Stk.`, `Pkg.`, `Dose`, `Fl.`, `Bund`, `g`, `kg`, `ml`, `l`
- Freitext wird erkannt: „2 kg Mehl“, „500g Hack“, „3 Äpfel“, „Milch (1,5 l)“, „Mehl 250 g“
- Doppelte Artikel werden zusammengefasst, auch über Einheiten hinweg (1 kg + 500 g = 1,5 kg)
- Abgehakte Artikel kommen beim erneuten Hinzufügen automatisch wieder auf die Liste
- Notizen (z. B. Marke)
- Autovervollständigung: Die Liste merkt sich Artikel samt zuletzt genutzter Einheit
- Mengen per `−`/`+` anpassen, Artikel bearbeiten und löschen, „Erledigte löschen“
- Mehrere Listen möglich (z. B. „Supermarkt“, „Drogerie“)
- Jede Liste ist zugleich eine **To-do-Entität** (`todo.…`). Damit funktionieren die Standard-To-do-Karte,
  die Sprachsteuerung (Assist), Automationen und die HA-App.
- Änderungen erscheinen sofort auf allen Geräten (WebSocket-Push)
- Offline-App fürs Handy: funktioniert auch ohne Empfang im Supermarkt
- Eigener Eintrag „Einkaufsliste“ in der Seitenleiste

## Einrichtung

1. App installieren und **starten**. Die App installiert dabei die Integration in
   `custom_components/einkaufsliste`.
2. Home Assistant **neu starten** (Einstellungen → System → ⋮ → Neu starten).
   Es erscheint auch eine Benachrichtigung dazu.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen → „Einkaufsliste“** und einen
   Namen für die Liste vergeben. Danach gibt es die Entität `todo.einkaufsliste`.
4. Fertig: Die Liste ist jetzt in der **Seitenleiste** („Einkaufsliste“) und kann als Karte
   aufs Dashboard.

**Updates:** Wenn im App-Store ein Update angezeigt wird, App aktualisieren. Die App bringt die neue
Version der Integration mit und meldet sich, wenn ein Neustart von Home Assistant nötig ist.

### Option

| Option | Bedeutung |
|---|---|
| `auto_restart` | Nach Installation/Update der Integration Home Assistant automatisch neu starten, statt nur eine Benachrichtigung zu zeigen. Standard: aus. |

### Deinstallation

1. Unter Geräte & Dienste die Integration „Einkaufsliste“ löschen (das löscht auch die Artikel).
2. Die App deinstallieren.
3. Den Ordner `custom_components/einkaufsliste` löschen und Home Assistant neu starten.

## Karte

Die Karte wird von der Integration automatisch geladen. Eine Ressource musst du nicht anlegen.
Nach der Installation den Browser einmal neu laden (bzw. den App-Cache leeren).

```yaml
type: custom:einkaufsliste-card
entity: todo.einkaufsliste
title: Einkauf            # optional
show_checked: true        # optional: Bereich „Erledigt“ anzeigen
```

Bedienung:
- Oben Artikel eingeben, z. B. `2 kg Mehl`, oder Menge und Einheit separat wählen
- Checkbox oder Artikelname antippen = abhaken
- `−` / `+` ändert die Menge (Schritte: 1 Stk., 100 g, 0,5 kg, 250 ml, 0,5 l)
- Stift = bearbeiten (Name, Menge, Einheit, Notiz, löschen)

## Seitenleiste

Der Eintrag **Einkaufsliste** in der Seitenleiste zeigt die Liste in voller Größe.
Ein Token ist dort nicht nötig, die Anmeldung übernimmt Home Assistant.
Gibt es mehrere Listen, wechselst du über das Zahnrad.

## Offline-App (für den Einkauf ohne Empfang)

Die Integration bringt eine eigenständige Web-App mit. Sie läuft auch ohne Verbindung zu Home Assistant:
Abhaken, Hinzufügen und Mengen ändern werden auf dem Handy gespeichert und automatisch übertragen,
sobald wieder Verbindung besteht.

**Voraussetzung: HTTPS.** Ohne HTTPS startet die App nicht ohne Verbindung (Regel der Browser für
Service Worker). Die App funktioniert dann zwar, aber nur, solange sie geöffnet bleibt. HTTPS bekommst du
z. B. über Nabu Casa oder ein eigenes Zertifikat (DuckDNS/Let's Encrypt, Reverse Proxy).

**Einrichten:**

1. Zugangstoken erstellen: In Home Assistant links unten auf dein Profil → Reiter *Sicherheit* →
   ganz unten *Langlebige Zugangstoken* → *Token erstellen* (Name z. B. „Einkaufsliste-App“).
   Den Token kopieren, er wird nur einmal angezeigt.
2. Auf dem Handy im Browser öffnen (Chrome auf Android, Safari auf dem iPhone):
   `https://<deine-ha-adresse>/einkaufsliste/app/index.html`
3. Token einfügen → *Listen laden* → Liste wählen → *Speichern*.
4. Zum Startbildschirm hinzufügen:
   - Android/Chrome: Menü ⋮ → *Zum Startbildschirm hinzufügen* bzw. *App installieren*
   - iPhone/Safari: Teilen-Symbol → *Zum Home-Bildschirm*
5. Einmal mit Verbindung öffnen, damit die App alles für den Offline-Betrieb speichert.

**Statusanzeige oben:** „Synchron · 12:34“ = alles übertragen, „Offline · 3 ausstehend“ = 3 Änderungen
warten auf Verbindung. Ein Tipp auf die Anzeige synchronisiert sofort.

**Wenn mehrere gleichzeitig ändern:** Die Änderungen werden in der Reihenfolge angewendet, in der sie
ankommen; bei Konflikten gilt die zuletzt übertragene. Ein Artikel, den jemand anderes inzwischen gelöscht
hat, wird übersprungen. Gleiche Artikel werden wie gewohnt zusammengefasst (offline 500 g Mehl + zu Hause
1 kg Mehl = 1,5 kg).

**Sicherheit:** Der Token gibt vollen Zugriff auf Home Assistant und liegt im Speicher des Browsers auf dem
Handy. Bei Verlust des Handys den Token in Home Assistant löschen.

## Services

| Service | Felder |
|---|---|
| `einkaufsliste.add_item` | `name`, `quantity`, `unit`, `note` |
| `einkaufsliste.update_item` | `item` (Name oder ID), `rename`, `quantity`, `unit`, `note` |
| `einkaufsliste.check_item` | `item`, `checked` (Standard: `true`) |
| `einkaufsliste.remove_item` | `item` |

Dazu kommen die Standard-Services `todo.add_item`, `todo.update_item`, `todo.remove_item`,
`todo.remove_completed_items` und `todo.get_items`.

`unit` erlaubt: `stk`, `pkg`, `dose`, `flasche`, `bund`, `g`, `kg`, `ml`, `l`

### Beispiele

```yaml
# Taster/Button: Milch auf die Liste
action: einkaufsliste.add_item
target:
  entity_id: todo.einkaufsliste
data:
  name: Milch
  quantity: 1
  unit: l
```

```yaml
# Freitext geht auch – Menge wird erkannt
action: einkaufsliste.add_item
target:
  entity_id: todo.einkaufsliste
data:
  name: "500 g Hackfleisch"
```

```yaml
# Automation: Benachrichtigung mit der offenen Liste, wenn man beim Supermarkt ist
automation:
  - alias: Einkaufsliste beim Supermarkt
    triggers:
      - trigger: zone
        entity_id: person.ich
        zone: zone.supermarkt
        event: enter
    conditions:
      - condition: numeric_state
        entity_id: todo.einkaufsliste
        above: 0
    actions:
      - action: todo.get_items
        target:
          entity_id: todo.einkaufsliste
        data:
          status: needs_action
        response_variable: liste
      - action: notify.mobile_app_mein_handy
        data:
          title: "Einkaufsliste ({{ states('todo.einkaufsliste') }})"
          message: >
            {{ liste['todo.einkaufsliste']['items'] | map(attribute='summary') | join('\n') }}
```

## Sprachsteuerung (Assist)

Über die eingebauten To-do-Sätze, z. B. *„Füge 2 kg Mehl zur Einkaufsliste hinzu“*.
Die Menge wird aus dem Text erkannt. Der Name der Liste muss dem Namen der Entität entsprechen.

## Daten

Alle Listen liegen in der SQLite-Datenbank `<config>/einkaufsliste.db`.

| Tabelle | Inhalt |
|---|---|
| `artikel` | `id`, `liste_id`, `position`, `name`, `menge`, `einheit`, `notiz`, `erledigt` (0/1), `erstellt`, `erledigt_am` |
| `verlauf` | gemerkte Artikel für die Vorschläge: `liste_id`, `schluessel`, `name`, `einheit`, `anzahl` |

`liste_id` ist die ID des Konfigurationseintrags (steht auch als Attribut `list_id` an der To-do-Entität).
Wenn du eine Liste in Home Assistant entfernst, werden ihre Zeilen gelöscht.

Beispielabfrage:

```sql
SELECT name, menge, einheit FROM artikel WHERE erledigt = 0 ORDER BY position;
```

Die Datei kannst du z. B. mit der App „SQLite Web“ ansehen. Sie wird in HA-Backups mitgesichert.
