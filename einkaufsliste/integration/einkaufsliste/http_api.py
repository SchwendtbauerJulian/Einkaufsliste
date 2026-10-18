"""HTTP-Schnittstelle für die Offline-App.

GET  /api/einkaufsliste/lists            -> verfügbare Listen
POST /api/einkaufsliste/{list_id}/sync   -> Änderungen übertragen, aktuellen Stand holen
POST /api/einkaufsliste/markets          -> Märkte und Kategorien ersetzen (Admin-Modus, nur Admins)

Alle brauchen einen Zugangstoken (Authorization: Bearer ...).
"""

from __future__ import annotations

from http import HTTPStatus

from aiohttp import web
import voluptuous as vol

from homeassistant.components.http import KEY_HASS, KEY_HASS_USER, HomeAssistantView
from homeassistant.config_entries import ConfigEntryState

from .const import DOMAIN
from .store import ProductCatalog
from .websocket import (
    CATEGORY_SCHEMA,
    MARKET_SCHEMA,
    QUANTITY_SCHEMA,
    TEXT_SCHEMA,
    UNIT_SCHEMA,
)

_OP_ID = vol.Required("op_id")
# Seitenleiste: Name des Benutzers, den die App weiterreicht (URL-Parameter, weil der
# Supervisor eigene Header nicht an Home Assistant durchlässt)
USER_PARAM = "user"

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
            vol.Optional("market"): MARKET_SCHEMA,
            vol.Optional("category"): CATEGORY_SCHEMA,
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
                vol.Optional("market"): MARKET_SCHEMA,
                vol.Optional("category"): CATEGORY_SCHEMA,
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

_ENTRY = {vol.Optional("key"): vol.Any(None, str), vol.Required("name"): str}
MARKETS_SCHEMA = vol.Schema(
    {vol.Required("markets"): [{**_ENTRY, vol.Optional("categories", default=list): [_ENTRY]}]}
)


def _user_name(request: web.Request) -> str | None:
    """Name des Benutzers hinter der Anfrage.

    Die Seitenleiste ruft mit dem Zugang der App an (Systembenutzer) und schickt den Namen
    des eigentlichen Benutzers mit. Normalen Benutzern wird der Header nicht geglaubt.
    """
    user = request[KEY_HASS_USER]
    if not user.system_generated:
        return user.name
    return request.query.get(USER_PARAM, "").strip() or None


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
        return self.json(await entry.runtime_data.async_sync(data["ops"], _user_name(request)))


class EinkaufslisteMarketsView(HomeAssistantView):
    """Admin-Modus der Seitenleiste: Märkte und Kategorien ändern."""

    url = "/api/einkaufsliste/markets"
    name = "api:einkaufsliste:markets"

    async def post(self, request: web.Request) -> web.Response:
        # Seitenleiste ruft über die App mit deren Zugang (Supervisor, Admin) an; die Seitenleiste
        # selbst sehen nur Admins
        if not request[KEY_HASS_USER].is_admin:
            return self.json_message("Nur für Administratoren", HTTPStatus.FORBIDDEN)
        catalog: ProductCatalog | None = request.app[KEY_HASS].data.get(DOMAIN)
        if catalog is None:
            return self.json_message("Einkaufsliste nicht eingerichtet", HTTPStatus.NOT_FOUND)
        try:
            data = MARKETS_SCHEMA(await request.json())
        except ValueError:
            return self.json_message("Ungültiges JSON", HTTPStatus.BAD_REQUEST)
        except vol.Invalid as err:
            return self.json_message(f"Ungültige Daten: {err}", HTTPStatus.BAD_REQUEST)
        try:
            return self.json(await catalog.async_set_markets(data["markets"]))
        except ValueError as err:
            return self.json_message(str(err), HTTPStatus.BAD_REQUEST)
