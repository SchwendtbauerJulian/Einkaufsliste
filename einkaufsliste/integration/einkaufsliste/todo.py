"""Einkaufsliste als To-do-Entität (für Standard-Karte, Assist und Automationen)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EinkaufslisteConfigEntry
from .const import UNITS
from .parsing import format_summary, parse_item
from .store import ShoppingItem, ShoppingList

_QUANTITY = vol.All(vol.Coerce(float), vol.Range(min=0))
_ITEM_FIELDS = {
    vol.Optional("quantity"): _QUANTITY,
    vol.Optional("unit"): vol.In(UNITS),
    vol.Optional("note"): cv.string,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EinkaufslisteConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([EinkaufslisteTodoEntity(entry.entry_id, entry.title, entry.runtime_data)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "add_item",
        {vol.Required("name"): cv.string, **_ITEM_FIELDS},
        "async_service_add_item",
    )
    platform.async_register_entity_service(
        "update_item",
        {
            vol.Required("item"): cv.string,
            vol.Optional("rename"): cv.string,
            **_ITEM_FIELDS,
        },
        "async_service_update_item",
    )
    platform.async_register_entity_service(
        "check_item",
        {vol.Required("item"): cv.string, vol.Optional("checked", default=True): cv.boolean},
        "async_service_check_item",
    )
    platform.async_register_entity_service(
        "remove_item",
        {vol.Required("item"): cv.string},
        "async_service_remove_item",
    )


def _summary(item: ShoppingItem) -> str:
    return format_summary(item.name, item.quantity, item.unit)


class EinkaufslisteTodoEntity(TodoListEntity):
    """To-do-Entität für eine Einkaufsliste."""

    _attr_should_poll = False
    _attr_icon = "mdi:cart"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.MOVE_TODO_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, entry_id: str, title: str, shopping_list: ShoppingList) -> None:
        self._list = shopping_list
        self._attr_unique_id = entry_id
        self._attr_name = title
        self._attr_extra_state_attributes = {"list_id": entry_id}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._list.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def todo_items(self) -> list[TodoItem]:
        return [
            TodoItem(
                uid=item.id,
                summary=_summary(item),
                status=TodoItemStatus.COMPLETED if item.checked else TodoItemStatus.NEEDS_ACTION,
                description=item.note,
            )
            for item in self._list.items
        ]

    # ------------------------------------------------------------------ To-do-API

    async def async_create_todo_item(self, item: TodoItem) -> None:
        name, quantity, unit = parse_item(item.summary or "")
        new = await self._list.async_add(name, quantity, unit, note=item.description)
        if item.status == TodoItemStatus.COMPLETED:
            await self._list.async_update(new.id, checked=True)

    async def async_update_todo_item(self, item: TodoItem) -> None:
        try:
            current = self._list.get(item.uid or "")
        except KeyError as err:
            raise ServiceValidationError(f"Artikel nicht gefunden: {item.uid}") from err
        changes: dict[str, Any] = {"note": item.description}
        # Nur neu parsen, wenn der Text wirklich geändert wurde
        if item.summary and item.summary != _summary(current):
            name, quantity, unit = parse_item(item.summary)
            changes.update(name=name, quantity=quantity, unit=unit)
        if item.status is not None:
            changes["checked"] = item.status == TodoItemStatus.COMPLETED
        await self._list.async_update(current.id, **changes)

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        await self._list.async_remove(uids)

    async def async_move_todo_item(self, uid: str, previous_uid: str | None = None) -> None:
        await self._list.async_move(uid, previous_uid)

    # ------------------------------------------------------------------ Eigene Services

    def _find(self, item: str) -> ShoppingItem:
        if (found := self._list.find(item)) is None:
            raise ServiceValidationError(f"Artikel '{item}' ist nicht auf der Liste")
        return found

    async def async_service_add_item(self, name: str, **fields: Any) -> None:
        await self._list.async_add(
            name,
            fields.get("quantity"),
            fields.get("unit"),
            fields.get("note"),
            parse="quantity" not in fields,
        )

    async def async_service_update_item(self, item: str, **fields: Any) -> None:
        found = self._find(item)
        if "rename" in fields:
            fields["name"] = fields.pop("rename")
        await self._list.async_update(found.id, **fields)

    async def async_service_check_item(self, item: str, checked: bool = True) -> None:
        await self._list.async_update(self._find(item).id, checked=checked)

    async def async_service_remove_item(self, item: str) -> None:
        await self._list.async_remove([self._find(item).id])
