"""The Triad AMS integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .connection import TriadConnection

PLATFORMS = ["media_player"]

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Triad AMS integration (empty, config entry only)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Triad AMS from a config entry."""
    # Get connection info from entry
    host = entry.data["host"]
    port = entry.data["port"]
    connection = TriadConnection(host, port)
    entry.runtime_data = connection
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        connection: TriadConnection = entry.runtime_data
        await connection.disconnect()
    return unload_ok
