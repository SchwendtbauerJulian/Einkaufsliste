"""Datenhaltung einer Einkaufsliste."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
from dataclasses import asdict, dataclass, fields
from typing import Any
from uuid import uuid4

from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import DEFAULT_UNIT, HISTORY_LIMIT
from .db import Database
from .parsing import merge_quantities, parse_item

_LOGGER = logging.getLogger(__name__)

UPDATABLE_FIELDS = {"name", "quantity", "unit", "note", "checked"}
# So viele Sync-Operationen bzw. ID-Zuordnungen werden gemerkt (gegen doppelte Übertragung)
SYNC_MEMORY = 2000


@dataclass
class ShoppingItem:
    """Ein Artikel auf der Liste."""

    id: str
    name: str
    quantity: float | None = None
    unit: str | None = None
    note: str | None = None
    checked: bool = False
    created: str = ""
    checked_at: str | None = None
    # Wer den Artikel auf die Liste gesetzt hat (Name des Benutzers, mehrere mit Komma)
    added_by: str | None = None


_ITEM_FIELDS = {f.name for f in fields(ShoppingItem)}


def _with_person(current: str | None, name: str | None) -> str | None:
    """Hängt einen weiteren Namen an ("Anna" + "Ben" -> "Anna, Ben")."""
    if not name or (current and name in current.split(", ")):
        return current
    return f"{current}, {name}" if current else name


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class ProductCatalog:
    """Märkte mit Kategorien und die Zuordnung aller bekannten Produkte (für alle Listen gemeinsam).

    Die Zuordnung wird beim ersten Anlegen eines Produkts festgelegt und lässt sich später
    ändern. Märkte und Kategorien selbst ändert der Admin-Modus der Seitenleiste.
    """

    def __init__(self, hass: HomeAssistant, db: Database) -> None:
        self.hass = hass
        self.db = db
        # [{"key", "name", "categories": [{"key", "name"}]}] in Reihenfolge
        self.markets: list[dict[str, Any]] = []
        # name.casefold() -> {"name", "market", "category"}
        self.products: dict[str, dict[str, Any]] = {}
        self._listeners: list[Callable[[Any], None]] = []

    async def async_load(self) -> None:
        self.markets = await self.hass.async_add_executor_job(self.db.load_markets)
        self.products = await self.hass.async_add_executor_job(self.db.load_products)

    def get(self, name: str) -> dict[str, Any] | None:
        return self.products.get(name.strip().casefold())

    @staticmethod
    def _find(entries: list[dict[str, Any]], value: str) -> dict[str, Any] | None:
        value = value.strip().casefold()
        return next(
            (e for e in entries if value in (e["key"].casefold(), e["name"].casefold())), None
        )

    def resolve(
        self, market: str | None, category: str | None, strict: bool = True
    ) -> tuple[str, str | None] | None:
        """Markt und Kategorie als Schlüssel; erlaubt sind Schlüssel oder Name.

        Eine Kategorie allein bestimmt ihren Markt. None = keine Zuordnung angegeben.
        Ohne `strict` wird Unbekanntes übergangen statt abgelehnt (offline gesammelte
        Änderungen, deren Markt oder Kategorie inzwischen gelöscht wurde).
        """
        found = self._find(self.markets, market) if market else None
        if market and found is None:
            if strict:
                raise ValueError(f"Unbekannter Markt: {market}")
            return None
        chosen = None
        if category:
            candidates = (
                found["categories"]
                if found
                else [c for m in self.markets for c in m["categories"]]
            )
            chosen = self._find(candidates, category)
            if chosen is None and strict:
                raise ValueError(f"Unbekannte Kategorie: {category}")
            if chosen is not None and found is None:
                found = next(m for m in self.markets if chosen in m["categories"])
        if found is None:
            return None
        return found["key"], chosen["key"] if chosen else None

    async def async_assign(
        self, name: str, market: str, category: str | None, source: Any = None
    ) -> None:
        """Ordnet ein Produkt einem Markt und ggf. einer Kategorie zu (Schlüssel aus resolve)."""
        name = name.strip()
        key = name.casefold()
        product = {"name": name, "market": market, "category": category}
        if self.products.get(key) == product:
            return
        self.products[key] = product
        await self.hass.async_add_executor_job(self.db.save_product, key, product)
        self._notify(source)

    async def async_set_markets(self, markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Admin-Modus: ersetzt alle Märkte und Kategorien (Neue ohne Schlüssel bekommen einen)."""
        keys: set[str] = set()

        def entry(raw: dict[str, Any], siblings: list[dict[str, Any]], kind: str) -> dict[str, Any]:
            name = raw["name"].strip()
            if not name:
                raise ValueError(f"{kind} ohne Namen")
            if any(e["name"].casefold() == name.casefold() for e in siblings):
                raise ValueError(f"{kind} „{name}“ gibt es doppelt")
            key = raw.get("key") or uuid4().hex[:12]
            if key in keys:
                raise ValueError(f"Schlüssel „{key}“ gibt es doppelt")
            keys.add(key)
            return {"key": key, "name": name}

        cleaned: list[dict[str, Any]] = []
        for raw in markets:
            market = entry(raw, cleaned, "Markt")
            market["categories"] = []
            for raw_category in raw.get("categories", []):
                market["categories"].append(
                    entry(raw_category, market["categories"], "Kategorie")
                )
            cleaned.append(market)

        await self.hass.async_add_executor_job(self.db.save_markets, cleaned)
        # Neu laden: Zuordnungen zu gelöschten Märkten/Kategorien hat die Datenbank entfernt
        await self.async_load()
        self._notify(None)
        return self.markets

    def _notify(self, source: Any) -> None:
        for listener in list(self._listeners):
            listener(source)

    @callback
    def async_add_listener(self, listener: Callable[[Any], None]) -> Callable[[], None]:
        """Listener bekommt die Liste, von der die Änderung kam."""
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove


class ShoppingList:
    """Eine Einkaufsliste mit Speicherung und Änderungs-Benachrichtigung."""

    def __init__(
        self, hass: HomeAssistant, db: Database, catalog: ProductCatalog, list_id: str
    ) -> None:
        self.hass = hass
        self.list_id = list_id
        self._db = db
        self.catalog = catalog
        self._save_lock = asyncio.Lock()
        self.items: list[ShoppingItem] = []
        # Bekannte Artikel für Autovervollständigung: name.casefold() -> Infos
        self.history: dict[str, dict[str, Any]] = {}
        self._listeners: list[Callable[[], None]] = []
        # Offline-App: bereits verarbeitete Operationen und App-ID -> echte Artikel-ID
        self._seen_ops: dict[str, None] = {}
        self._id_map: dict[str, str] = {}
        self._batching = False

    # ------------------------------------------------------------------ Laden/Speichern

    async def async_load(self) -> None:
        items, self.history = await self.hass.async_add_executor_job(
            self._db.load, self.list_id
        )
        self.items = [
            ShoppingItem(**{k: v for k, v in raw.items() if k in _ITEM_FIELDS})
            for raw in items
        ]

    async def _async_changed(self) -> None:
        if self._batching:
            return
        async with self._save_lock:
            # Stand erst innerhalb der Sperre kopieren, damit immer der neueste gespeichert wird
            items = [asdict(i) for i in self.items]
            history = {k: dict(v) for k, v in self.history.items()}
            await self.hass.async_add_executor_job(
                self._db.save, self.list_id, items, history
            )
        self._notify()

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def async_catalog_changed(self, source: Any) -> None:
        """Eine andere Liste hat Markt oder Kategorie eines Produkts geändert."""
        if source is not self:
            self._notify()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def as_dict(self) -> dict[str, Any]:
        history = sorted(
            self.history.values(), key=lambda h: h.get("count", 0), reverse=True
        )
        return {
            "items": [asdict(i) for i in self.items],
            "history": history,
            "products": list(self.catalog.products.values()),
            "markets": self.catalog.markets,
        }

    # ------------------------------------------------------------------ Suchen

    def get(self, item_id: str) -> ShoppingItem:
        for item in self.items:
            if item.id == item_id:
                return item
        raise KeyError(item_id)

    def find(self, id_or_name: str) -> ShoppingItem | None:
        """Sucht per ID oder Name (offene Artikel haben Vorrang)."""
        key = id_or_name.strip().casefold()
        matches = [
            i for i in self.items if i.id == id_or_name or i.name.casefold() == key
        ]
        matches.sort(key=lambda i: i.checked)
        return matches[0] if matches else None

    # ------------------------------------------------------------------ Ändern

    def _remember(self, item: ShoppingItem, count: bool = False) -> None:
        key = item.name.casefold()
        entry = self.history.setdefault(key, {"name": item.name, "count": 0})
        entry["name"] = item.name
        if item.unit:
            entry["unit"] = item.unit
        if count:
            entry["count"] = entry.get("count", 0) + 1
        if len(self.history) > HISTORY_LIMIT:
            rarest = min(self.history, key=lambda k: self.history[k].get("count", 0))
            self.history.pop(rarest)

    async def async_add(
        self,
        name: str,
        quantity: float | None = None,
        unit: str | None = None,
        note: str | None = None,
        *,
        parse: bool = False,
        merge: bool = True,
        item_id: str | None = None,
        added_by: str | None = None,
        market: str | None = None,
        category: str | None = None,
    ) -> ShoppingItem:
        """Fügt einen Artikel hinzu oder erhöht die Menge eines vorhandenen.

        Mit `market` und/oder `category` (Schlüssel oder Name) wird das Produkt im Katalog
        zugeordnet.
        """
        assignment = self.catalog.resolve(market, category)
        name = name.strip()
        if parse and quantity is None:
            name, quantity, parsed_unit = parse_item(name)
            unit = unit or parsed_unit
        if not name:
            raise ValueError("Der Artikelname darf nicht leer sein")
        if assignment is not None:
            await self.catalog.async_assign(name, *assignment, source=self)

        known = self.history.get(name.casefold(), {})
        if quantity is not None and unit is None:
            unit = known.get("unit", DEFAULT_UNIT)
        if quantity is None:
            unit = None
        note = _empty_to_none(note)

        existing = self.find(name) if merge else None
        if existing is not None:
            if existing.checked:
                # Bereits gekaufter Artikel kommt wieder auf die Liste
                existing.checked = False
                existing.checked_at = None
                existing.quantity, existing.unit = quantity, unit
                existing.note = note
                existing.added_by = added_by
                self._remember(existing, count=True)
                await self._async_changed()
                return existing
            merged = merge_quantities(existing.quantity, existing.unit, quantity, unit)
            if merged is not None:
                existing.quantity, existing.unit = merged
                existing.note = note or existing.note
                existing.added_by = _with_person(existing.added_by, added_by)
                self._remember(existing, count=True)
                await self._async_changed()
                return existing

        item = ShoppingItem(
            id=item_id or uuid4().hex,
            name=name,
            quantity=quantity,
            unit=unit,
            note=note,
            created=dt_util.utcnow().isoformat(),
            added_by=added_by,
        )
        self.items.append(item)
        self._remember(item, count=True)
        await self._async_changed()
        return item

    async def async_update(self, item_id: str, **changes: Any) -> ShoppingItem:
        item = self.get(item_id)
        # Vor allen Änderungen prüfen, damit ein falscher Markt nichts halb ändert
        assignment = self.catalog.resolve(
            changes.pop("market", None), changes.pop("category", None)
        )
        for key, value in changes.items():
            if key not in UPDATABLE_FIELDS:
                continue
            if key == "name":
                value = value.strip()
                if not value:
                    raise ValueError("Der Artikelname darf nicht leer sein")
            elif key == "note":
                value = _empty_to_none(value)
            elif key == "checked":
                value = bool(value)
                if value != item.checked:
                    item.checked_at = dt_util.utcnow().isoformat() if value else None
            setattr(item, key, value)

        if item.quantity is None:
            item.unit = None
        elif item.unit is None:
            item.unit = DEFAULT_UNIT
        if assignment is not None:
            await self.catalog.async_assign(item.name, *assignment, source=self)
        self._remember(item)
        await self._async_changed()
        return item

    async def async_remove(self, item_ids: list[str]) -> None:
        ids = set(item_ids)
        missing = ids - {i.id for i in self.items}
        if missing:
            raise KeyError(", ".join(missing))
        self.items = [i for i in self.items if i.id not in ids]
        await self._async_changed()

    async def async_clear_checked(self) -> int:
        before = len(self.items)
        self.items = [i for i in self.items if not i.checked]
        removed = before - len(self.items)
        if removed:
            await self._async_changed()
        return removed

    async def async_move(self, item_id: str, previous_id: str | None) -> None:
        """Verschiebt einen Artikel hinter `previous_id` (None = an den Anfang)."""
        item = self.get(item_id)
        previous = self.get(previous_id) if previous_id is not None else None
        self.items.remove(item)
        index = self.items.index(previous) + 1 if previous is not None else 0
        self.items.insert(index, item)
        await self._async_changed()

    # ------------------------------------------------------------------ Offline-App

    async def async_sync(
        self, ops: list[dict[str, Any]], user: str | None = None
    ) -> dict[str, Any]:
        """Wendet offline gesammelte Änderungen von `user` an und liefert den aktuellen Stand.

        Operationen, die schon verarbeitet wurden (erneute Übertragung) oder sich auf
        inzwischen gelöschte Artikel beziehen, werden übersprungen.
        """
        changed = False
        self._batching = True
        try:
            for op in ops:
                if op["op_id"] in self._seen_ops:
                    continue
                try:
                    await self._apply_op(op, user)
                except (KeyError, ValueError) as err:
                    _LOGGER.debug("Sync-Operation übersprungen: %s (%s)", op, err)
                self._remember_op(op["op_id"])
                changed = True
        finally:
            self._batching = False
        if changed:
            await self._async_changed()
        return self.as_dict()

    def _remember_op(self, op_id: str) -> None:
        self._seen_ops[op_id] = None
        while len(self._seen_ops) > SYNC_MEMORY:
            self._seen_ops.pop(next(iter(self._seen_ops)))
        while len(self._id_map) > SYNC_MEMORY:
            self._id_map.pop(next(iter(self._id_map)))

    def _resolve(self, item_id: str) -> str:
        return self._id_map.get(item_id, item_id)

    def _lenient_market(self, data: dict[str, Any]) -> dict[str, Any]:
        """Markt/Kategorie, die es inzwischen nicht mehr gibt, weglassen statt die Änderung zu verlieren."""
        assignment = self.catalog.resolve(
            data.get("market"), data.get("category"), strict=False
        )
        market, category = assignment or (None, None)
        return {**data, "market": market, "category": category}

    async def _apply_op(self, op: dict[str, Any], user: str | None) -> None:
        kind = op["op"]
        if kind == "add":
            if any(i.id == op["id"] for i in self.items):
                return
            op = self._lenient_market(op)
            item = await self.async_add(
                op["name"],
                op.get("quantity"),
                op.get("unit"),
                op.get("note"),
                parse=True,
                item_id=op["id"],
                added_by=user,
                market=op.get("market"),
                category=op.get("category"),
            )
            # Wurde der Artikel mit einem vorhandenen zusammengefasst, hat er dessen ID
            if item.id != op["id"]:
                self._id_map[op["id"]] = item.id
        elif kind == "update":
            changes = self._lenient_market(op["changes"])
            await self.async_update(self._resolve(op["item_id"]), **changes)
        elif kind == "remove":
            existing = {i.id for i in self.items}
            ids = [i for i in map(self._resolve, op["item_ids"]) if i in existing]
            if ids:
                await self.async_remove(ids)
