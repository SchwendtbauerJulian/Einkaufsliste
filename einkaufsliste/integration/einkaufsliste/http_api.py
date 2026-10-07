"""HTTP-Schnittstelle für die Offline-App.

GET  /api/einkaufsliste/lists            -> verfügbare Listen
POST /api/einkaufsliste/{list_id}/sync   -> Änderungen übertragen, aktuellen Stand holen

Beide brauchen einen Zugangstoken (Authorization: Bearer ...).
"""

from __future__ import annotations

from http import HTTPStatus

from aiohttp import web
import voluptuous as vol

from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.config_entries import ConfigEntryState

from .const import DOMAIN
from .websocket import QUANTITY_SCHEMA, TEXT_SCHEMA, UNIT_SCHEMA

_OP_ID = vol.Required("op_id")

OP_SCHEMA = vol.Any(
    vol.Schema(
        {
            _OP_ID: str,
            vol.Required("op"): "add",
            vol.Required("id"): str,
            vol.Required("name"): str,
            vol.Optional("quantity"): QUANTITY_SCHEMA,
            vol.Optional("unit"): UNIT_SCHEMA,
            vol.Optional("note"): TEXT_SCHEMA,
        }
    ),
    vol.Schema(
        {
            _OP_ID: str,
            vol.Required("op"): "update",
            vol.Required("item_id"): str,
            vol.Required("changes"): {
                vol.Optional("name"): str,
                vol.Optional("quantity"): QUANTITY_SCHEMA,
                vol.Optional("unit"): UNIT_SCHEMA,
                vol.Optional("note"): TEXT_SCHEMA,
                vol.Optional("checked"): bool,
            },
        }
    ),
    vol.Schema(
        {
            _OP_ID: str,
            vol.Required("op"): "remove",
            vol.Required("item_ids"): [str],
        }
    ),
)
SYNC_SCHEMA = vol.Schema({vol.Optional("ops", default=list): [OP_SCHEMA]})


class EinkaufslisteListsView(HomeAssistantView):
    """Liefert alle geladenen Einkaufslisten."""

    url = "/api/einkaufsliste/lists"
    name = "api:einkaufsliste:lists"

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app[KEY_HASS]
        return self.json(
            [
                {"list_id": entry.entry_id, "name": entry.title}
                for entry in hass.config_entries.async_entries(DOMAIN)
                if entry.state is ConfigEntryState.LOADED
            ]
        )


class EinkaufslisteSyncView(HomeAssistantView):
    """Nimmt offline gesammelte Änderungen entgegen und liefert den aktuellen Stand."""

    url = "/api/einkaufsliste/{list_id}/sync"
    name = "api:einkaufsliste:sync"

    async def post(self, request: web.Request, list_id: str) -> web.Response:
        hass = request.app[KEY_HASS]
        entry = hass.config_entries.async_get_entry(list_id)
        if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
            return self.json_message("Einkaufsliste nicht gefunden", HTTPStatus.NOT_FOUND)
        try:
            data = SYNC_SCHEMA(await request.json())
        except ValueError:
            return self.json_message("Ungültiges JSON", HTTPStatus.BAD_REQUEST)
        except vol.Invalid as err:
            return self.json_message(f"Ungültige Daten: {err}", HTTPStatus.BAD_REQUEST)
        return self.json(await entry.runtime_data.async_sync(data["ops"]))
