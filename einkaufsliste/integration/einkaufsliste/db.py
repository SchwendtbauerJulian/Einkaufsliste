"""SQLite-Datenbank für alle Einkaufslisten.

Die Funktionen hier sind blockierend und werden über den Executor aufgerufen.
"""

from __future__ import annotations

from contextlib import closing
import sqlite3
import threading
from typing import Any

from .const import DEFAULT_MARKETS

SCHEMA_VERSION = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS artikel (
    id          TEXT    NOT NULL,
    liste_id    TEXT    NOT NULL,
    position    INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    menge       REAL,
    einheit     TEXT,
    notiz       TEXT,
    erledigt    INTEGER NOT NULL DEFAULT 0,
    erstellt    TEXT    NOT NULL,
    erledigt_am TEXT,
    hinzugefuegt_von TEXT,
    PRIMARY KEY (liste_id, id)
);
CREATE INDEX IF NOT EXISTS idx_artikel_position ON artikel (liste_id, position);

CREATE TABLE IF NOT EXISTS verlauf (
    liste_id  TEXT    NOT NULL,
    schluessel TEXT   NOT NULL,
    name      TEXT    NOT NULL,
    einheit   TEXT,
    anzahl    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (liste_id, schluessel)
);

-- Produktkatalog (für alle Listen gemeinsam): in welchem Markt es ein Produkt gibt
CREATE TABLE IF NOT EXISTS produkte (
    schluessel TEXT NOT NULL PRIMARY KEY,
    name       TEXT NOT NULL,
    markt      TEXT NOT NULL,
    kategorie  TEXT
);

-- Märkte und ihre Kategorien, Reihenfolge wie im Geschäft (im Admin-Modus änderbar)
CREATE TABLE IF NOT EXISTS maerkte (
    schluessel TEXT    NOT NULL PRIMARY KEY,
    name       TEXT    NOT NULL,
    position   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS kategorien (
    schluessel TEXT    NOT NULL PRIMARY KEY,
    markt      TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    position   INTEGER NOT NULL
);
"""

# Spalte in der Datenbank -> Feld im Datenmodell
_ITEM_COLUMNS = {
    "id": "id",
    "name": "name",
    "menge": "quantity",
    "einheit": "unit",
    "notiz": "note",
    "erledigt": "checked",
    "erstellt": "created",
    "erledigt_am": "checked_at",
    "hinzugefuegt_von": "added_by",
}


class Database:
    """Zugriff auf die SQLite-Datei (eine Datei für alle Listen)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        """Legt die Tabellen an (falls noch nicht vorhanden)."""
        with self._lock, closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            conn.executescript(SCHEMA)
            if version < 4:
                # Version 3 -> 4: Märkte und Kategorien mit den Vorgaben füllen
                self._write_markets(
                    conn,
                    [
                        {
                            "key": key,
                            "name": name,
                            "categories": [{"key": k, "name": n} for k, n in categories],
                        }
                        for key, name, categories in DEFAULT_MARKETS
                    ],
                )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(artikel)")}
            if "hinzugefuegt_von" not in columns:
                # Version 1 -> 2: wer den Artikel auf die Liste gesetzt hat
                conn.execute("ALTER TABLE artikel ADD COLUMN hinzugefuegt_von TEXT")
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()

    def load(self, list_id: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        """Liest Artikel (sortiert) und Verlauf einer Liste."""
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM artikel WHERE liste_id = ? ORDER BY position", (list_id,)
            ).fetchall()
            items = [
                {field: row[column] for column, field in _ITEM_COLUMNS.items()}
                for row in rows
            ]
            for item in items:
                item["checked"] = bool(item["checked"])

            history = {
                row["schluessel"]: {
                    "name": row["name"],
                    "unit": row["einheit"],
                    "count": row["anzahl"],
                }
                for row in conn.execute(
                    "SELECT * FROM verlauf WHERE liste_id = ?", (list_id,)
                )
            }
        return items, history

    def save(
        self,
        list_id: str,
        items: list[dict[str, Any]],
        history: dict[str, dict[str, Any]],
    ) -> None:
        """Schreibt den kompletten Stand einer Liste in einer Transaktion."""
        with self._lock, closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM artikel WHERE liste_id = ?", (list_id,))
            conn.executemany(
                """INSERT INTO artikel
                   (id, liste_id, position, name, menge, einheit, notiz,
                    erledigt, erstellt, erledigt_am, hinzugefuegt_von)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        item["id"],
                        list_id,
                        position,
                        item["name"],
                        item["quantity"],
                        item["unit"],
                        item["note"],
                        int(item["checked"]),
                        item["created"],
                        item["checked_at"],
                        item.get("added_by"),
                    )
                    for position, item in enumerate(items)
                ],
            )
            conn.execute("DELETE FROM verlauf WHERE liste_id = ?", (list_id,))
            conn.executemany(
                """INSERT INTO verlauf (liste_id, schluessel, name, einheit, anzahl)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (
                        list_id,
                        key,
                        entry["name"],
                        entry.get("unit"),
                        entry.get("count", 0),
                    )
                    for key, entry in history.items()
                ],
            )

    def load_products(self) -> dict[str, dict[str, Any]]:
        """Liest den Produktkatalog: name.casefold() -> Produkt."""
        with self._lock, closing(self._connect()) as conn:
            return {
                row["schluessel"]: {
                    "name": row["name"],
                    "market": row["markt"],
                    "category": row["kategorie"],
                }
                for row in conn.execute("SELECT * FROM produkte")
            }

    def save_product(self, key: str, product: dict[str, Any]) -> None:
        with self._lock, closing(self._connect()) as conn, conn:
            conn.execute(
                """INSERT OR REPLACE INTO produkte (schluessel, name, markt, kategorie)
                   VALUES (?, ?, ?, ?)""",
                (key, product["name"], product["market"], product["category"]),
            )

    def load_markets(self) -> list[dict[str, Any]]:
        """Märkte samt Kategorien, jeweils in ihrer Reihenfolge."""
        with self._lock, closing(self._connect()) as conn:
            markets = [
                {"key": row["schluessel"], "name": row["name"], "categories": []}
                for row in conn.execute("SELECT * FROM maerkte ORDER BY position")
            ]
            by_key = {m["key"]: m for m in markets}
            for row in conn.execute("SELECT * FROM kategorien ORDER BY position"):
                if (market := by_key.get(row["markt"])) is not None:
                    market["categories"].append({"key": row["schluessel"], "name": row["name"]})
        return markets

    def save_markets(self, markets: list[dict[str, Any]]) -> None:
        """Ersetzt alle Märkte und Kategorien.

        Produkte eines gelöschten Markts sind danach nicht mehr zugeordnet, Produkte einer
        gelöschten Kategorie behalten ihren Markt.
        """
        with self._lock, closing(self._connect()) as conn, conn:
            self._write_markets(conn, markets)
            conn.execute("DELETE FROM produkte WHERE markt NOT IN (SELECT schluessel FROM maerkte)")
            conn.execute(
                """UPDATE produkte SET kategorie = NULL
                   WHERE kategorie IS NOT NULL AND kategorie NOT IN
                     (SELECT schluessel FROM kategorien WHERE markt = produkte.markt)"""
            )

    @staticmethod
    def _write_markets(conn: sqlite3.Connection, markets: list[dict[str, Any]]) -> None:
        conn.execute("DELETE FROM maerkte")
        conn.execute("DELETE FROM kategorien")
        conn.executemany(
            "INSERT INTO maerkte (schluessel, name, position) VALUES (?, ?, ?)",
            [(m["key"], m["name"], i) for i, m in enumerate(markets)],
        )
        conn.executemany(
            "INSERT INTO kategorien (schluessel, markt, name, position) VALUES (?, ?, ?, ?)",
            [
                (c["key"], m["key"], c["name"], i)
                for m in markets
                for i, c in enumerate(m["categories"])
            ],
        )

    def delete_list(self, list_id: str) -> None:
        with self._lock, closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM artikel WHERE liste_id = ?", (list_id,))
            conn.execute("DELETE FROM verlauf WHERE liste_id = ?", (list_id,))
