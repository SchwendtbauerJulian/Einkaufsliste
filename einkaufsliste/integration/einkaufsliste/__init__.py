"""Einkaufsliste mit Mengen und Einheiten für Home Assistant."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from . import websocket
from .const import APP_URL, CARD_FILENAME, DB_FILENAME, DOMAIN, URL_BASE, VERSION
from .db import Database
from .http_api import (
    EinkaufslisteListsView,
    EinkaufslisteMarketsView,
    EinkaufslisteSyncView,
)
from .store import ProductCatalog, ShoppingList

PLATFORMS = [Platform.TODO]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type EinkaufslisteConfigEntry = ConfigEntry[ShoppingList]


async def _async_get_catalog(hass: HomeAssistant) -> ProductCatalog:
    """Öffnet die SQLite-Datenbank einmalig, legt die Tabellen an und lädt die Produkte."""
    if DOMAIN not in hass.data:
        db = Database(hass.config.path(DB_FILENAME))
        await hass.async_add_executor_job(db.init)
        catalog = ProductCatalog(hass, db)
        await catalog.async_load()
        hass.data[DOMAIN] = catalog
    return hass.data[DOMAIN]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Datenbank, Lovelace-Karte, Offline-App und APIs einrichten (einmalig)."""
    await _async_get_catalog(hass)
    base = Path(__file__).parent
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(URL_BASE, str(base / "www"), True),
            # Ohne Cache-Header, damit der Service Worker Updates mitbekommt
            StaticPathConfig(APP_URL, str(base / "app"), False),
        ]
    )
    add_extra_js_url(hass, f"{URL_BASE}/{CARD_FILENAME}?v={VERSION}")
    websocket.async_register(hass)
    hass.http.register_view(EinkaufslisteListsView())
    hass.http.register_view(EinkaufslisteSyncView())
    hass.http.register_view(EinkaufslisteMarketsView())
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EinkaufslisteConfigEntry) -> bool:
    catalog = await _async_get_catalog(hass)
    shopping_list = ShoppingList(hass, catalog.db, catalog, entry.entry_id)
    await shopping_list.async_load()
    entry.async_on_unload(catalog.async_add_listener(shopping_list.async_catalog_changed))
    entry.runtime_data = shopping_list
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EinkaufslisteConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: EinkaufslisteConfigEntry) -> None:
    """Artikel der Liste aus der Datenbank löschen, wenn die Liste entfernt wird."""
    catalog = await _async_get_catalog(hass)
    await hass.async_add_executor_job(catalog.db.delete_list, entry.entry_id)
