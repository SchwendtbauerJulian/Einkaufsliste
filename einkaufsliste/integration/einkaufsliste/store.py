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


_ITEM_FIELDS = {f.name for f in fields(ShoppingItem)}


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class ShoppingList:
    """Eine Einkaufsliste mit Speicherung und Änderungs-Benachrichtigung."""

    def __init__(self, hass: HomeAssistant, db: Database, list_id: str) -> None:
        self.hass = hass
        self.list_id = list_id
        self._db = db
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
        for listener in list(self._listeners):
            listener()

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
        return {"items": [asdict(i) for i in self.items], "history": history}

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
    ) -> ShoppingItem:
        """Fügt einen Artikel hinzu oder erhöht die Menge eines vorhandenen."""
        name = name.strip()
        if parse and quantity is None:
            name, quantity, parsed_unit = parse_item(name)
            unit = unit or parsed_unit
        if not name:
            raise ValueError("Der Artikelname darf nicht leer sein")

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
                self._remember(existing, count=True)
                await self._async_changed()
                return existing
            merged = merge_quantities(existing.quantity, existing.unit, quantity, unit)
            if merged is not None:
                existing.quantity, existing.unit = merged
                existing.note = note or existing.note
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
        )
        self.items.append(item)
        self._remember(item, count=True)
        await self._async_changed()
        return item

    async def async_update(self, item_id: str, **changes: Any) -> ShoppingItem:
        item = self.get(item_id)
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

    async def async_sync(self, ops: list[dict[str, Any]]) -> dict[str, Any]:
        """Wendet offline gesammelte Änderungen an und liefert den aktuellen Stand.

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
                    await self._apply_op(op)
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

    async def _apply_op(self, op: dict[str, Any]) -> None:
        kind = op["op"]
        if kind == "add":
            if any(i.id == op["id"] for i in self.items):
                return
            item = await self.async_add(
                op["name"],
                op.get("quantity"),
                op.get("unit"),
                op.get("note"),
                parse=True,
                item_id=op["id"],
            )
            # Wurde der Artikel mit einem vorhandenen zusammengefasst, hat er dessen ID
            if item.id != op["id"]:
                self._id_map[op["id"]] = item.id
        elif kind == "update":
            await self.async_update(self._resolve(op["item_id"]), **op["changes"])
        elif kind == "remove":
            existing = {i.id for i in self.items}
            ids = [i for i in map(self._resolve, op["item_ids"]) if i in existing]
            if ids:
                await self.async_remove(ids)
