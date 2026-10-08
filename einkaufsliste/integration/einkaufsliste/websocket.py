"""WebSocket-API für die Lovelace-Karte."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, UNITS
from .store import ShoppingList

_LIST_ID = vol.Required("list_id")
QUANTITY_SCHEMA = vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=0)))
UNIT_SCHEMA = vol.Any(None, vol.In(UNITS))
TEXT_SCHEMA = vol.Any(None, str)


@callback
def async_register(hass: HomeAssistant) -> None:
    for command in (
        ws_subscribe,
        ws_add,
        ws_update,
        ws_remove,
        ws_clear_checked,
        ws_move,
    ):
        websocket_api.async_register_command(hass, command)


def _get_list(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> ShoppingList | None:
    entry = hass.config_entries.async_get_entry(msg["list_id"])
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Einkaufsliste nicht gefunden"
        )
        return None
    return entry.runtime_data


async def _run(
    connection: websocket_api.ActiveConnection, msg: dict[str, Any], coro: Any
) -> None:
    """Führt eine Änderung aus und übersetzt Fehler in WebSocket-Fehler."""
    try:
        result = await coro
    except KeyError as err:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, f"Artikel nicht gefunden: {err}"
        )
        return
    except ValueError as err:
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, str(err))
        return
    if hasattr(result, "id"):
        result = asdict(result)
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/subscribe", _LIST_ID: str}
)
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Liefert die Liste und schickt bei jeder Änderung ein Update."""
    if (shopping_list := _get_list(hass, connection, msg)) is None:
        return

    @callback
    def forward() -> None:
        connection.send_message(
            websocket_api.event_message(msg["id"], shopping_list.as_dict())
        )

    connection.subscriptions[msg["id"]] = shopping_list.async_add_listener(forward)
    connection.send_result(msg["id"])
    forward()


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/add",
        _LIST_ID: str,
        vol.Required("name"): str,
        vol.Optional("quantity"): QUANTITY_SCHEMA,
        vol.Optional("unit"): UNIT_SCHEMA,
        vol.Optional("note"): TEXT_SCHEMA,
    }
)
@websocket_api.async_response
async def ws_add(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (shopping_list := _get_list(hass, connection, msg)) is None:
        return
    await _run(
        connection,
        msg,
        shopping_list.async_add(
            msg["name"],
            msg.get("quantity"),
            msg.get("unit"),
            msg.get("note"),
            parse=True,
            added_by=connection.user.name,
        ),
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/update",
        _LIST_ID: str,
        vol.Required("item_id"): str,
        vol.Optional("name"): str,
        vol.Optional("quantity"): QUANTITY_SCHEMA,
        vol.Optional("unit"): UNIT_SCHEMA,
        vol.Optional("note"): TEXT_SCHEMA,
        vol.Optional("checked"): bool,
    }
)
@websocket_api.async_response
async def ws_update(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (shopping_list := _get_list(hass, connection, msg)) is None:
        return
    changes = {
        k: v for k, v in msg.items() if k not in ("id", "type", "list_id", "item_id")
    }
    await _run(connection, msg, shopping_list.async_update(msg["item_id"], **changes))


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/remove",
        _LIST_ID: str,
        vol.Required("item_ids"): [str],
    }
)
@websocket_api.async_response
async def ws_remove(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (shopping_list := _get_list(hass, connection, msg)) is None:
        return
    await _run(connection, msg, shopping_list.async_remove(msg["item_ids"]))


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/clear_checked", _LIST_ID: str}
)
@websocket_api.async_response
async def ws_clear_checked(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (shopping_list := _get_list(hass, connection, msg)) is None:
        return
    await _run(connection, msg, shopping_list.async_clear_checked())


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/move",
        _LIST_ID: str,
        vol.Required("item_id"): str,
        vol.Optional("previous_id"): vol.Any(None, str),
    }
)
@websocket_api.async_response
async def ws_move(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (shopping_list := _get_list(hass, connection, msg)) is None:
        return
    await _run(
        connection,
        msg,
        shopping_list.async_move(msg["item_id"], msg.get("previous_id")),
    )
