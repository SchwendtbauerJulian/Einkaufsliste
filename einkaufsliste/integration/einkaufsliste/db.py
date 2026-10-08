"""SQLite-Datenbank für alle Einkaufslisten.

Die Funktionen hier sind blockierend und werden über den Executor aufgerufen.
"""

from __future__ import annotations

from contextlib import closing
import sqlite3
import threading
from typing import Any

SCHEMA_VERSION = 2

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
            conn.executescript(SCHEMA)
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

    def delete_list(self, list_id: str) -> None:
        with self._lock, closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM artikel WHERE liste_id = ?", (list_id,))
            conn.execute("DELETE FROM verlauf WHERE liste_id = ?", (list_id,))
