"""The Triad AMS integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import homeassistant.helpers.config_validation as cv

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import TriadCoordinator

PLATFORMS = ["media_player"]

_LOGGER = logging.getLogger(__name__)


async def async_setup(_hass: HomeAssistant, _config: ConfigType) -> bool:
    """Set up the Triad AMS integration (empty, config entry only)."""
    return True


# This integration is config-entry only; no YAML configuration
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Triad AMS from a config entry."""
    # Get connection info from entry
    host = entry.data["host"]
    port = entry.data["port"]
    coordinator = TriadCoordinator(host, port)
    entry.runtime_data = coordinator
    # Start the coordinator worker so entities can execute commands immediately
    try:
        await coordinator.start()
    except Exception:
        _LOGGER.exception("Failed to start TriadCoordinator")
    # Reload entities automatically when options change
    entry.async_on_unload(entry.add_update_listener(_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options updates by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: TriadCoordinator = entry.runtime_data
        try:
            await coordinator.stop()
        except Exception:
            _LOGGER.exception("Error stopping coordinator")
        await coordinator.disconnect()
    return unload_ok
