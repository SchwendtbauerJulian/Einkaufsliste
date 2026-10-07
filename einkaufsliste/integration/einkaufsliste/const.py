"""Konstanten für die Einkaufsliste."""

DOMAIN = "einkaufsliste"
VERSION = "1.1.0"

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
