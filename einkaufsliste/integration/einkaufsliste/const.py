"""Konstanten für die Einkaufsliste."""

DOMAIN = "einkaufsliste"
VERSION = "1.3.1"

DB_FILENAME = "einkaufsliste.db"

# Einheiten: Schlüssel -> Anzeigename
UNIT_LABELS: dict[str, str] = {
    # Stück
    "stk": "Stk.",
    "pkg": "Pkg.",
    "dose": "Dose",
    "flasche": "Fl.",
    "bund": "Bund",
    # Gewicht
    "g": "g",
    "kg": "kg",
    # Volumen
    "ml": "ml",
    "l": "l",
}
UNITS = list(UNIT_LABELS)
DEFAULT_UNIT = "stk"

# Umrechenbare Einheiten: Einheit -> (Basiseinheit, Faktor)
CONVERSION: dict[str, tuple[str, int]] = {
    "g": ("g", 1),
    "kg": ("g", 1000),
    "ml": ("ml", 1),
    "l": ("ml", 1000),
}

URL_BASE = "/einkaufsliste_static"
CARD_FILENAME = "einkaufsliste-card.js"
APP_URL = "/einkaufsliste/app"

HISTORY_LIMIT = 500

# Märkte beim ersten Start: (Schlüssel, Name, Kategorien). Danach im Admin-Modus der
# Seitenleiste änderbar; jeder Markt kann eigene Kategorien haben.
DEFAULT_MARKETS: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("drogerie", "Drogerie", []),
    ("bauernladen", "Bauernladen", []),
    ("woess", "Wöss", []),
    (
        "lebensmittel",
        "Lebensmittel",
        [
            ("obst_gemuese", "Obst, Gemüse"),
            ("getraenke", "Getränke"),
            ("milchprodukte", "Milchprodukte"),
            ("fleisch_wurst", "Fleisch, Wurst"),
            ("gebaeck", "Gebäck"),
            ("backwaren", "Backwaren"),
            ("cerealien", "Cerealien (Müsli, Riegel)"),
            ("suessigkeiten", "Süßigkeiten"),
            ("grundnahrungsmittel", "Grundnahrungsmittel (Nudeln, Reis, …)"),
            ("konserven", "Konserven"),
            ("haushaltswaren", "Haushaltswaren (Klopapier, …)"),
            ("knabbereien", "Knabbereien"),
            ("tiefkuehlwaren", "Tiefkühlwaren"),
        ],
    ),
    ("sonstige", "Sonstige", []),
]
