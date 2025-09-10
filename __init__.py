"""The Triad AMS integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .coordinator import TriadAmsCoordinator
from .helper import TriadAmsClient

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
    client = TriadAmsClient(host, port)
    coordinator = TriadAmsCoordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: TriadAmsCoordinator = entry.runtime_data
        await coordinator.client.async_disconnect()
    return unload_ok
