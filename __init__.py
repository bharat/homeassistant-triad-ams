"""The Triad AMS integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

# TODO List the platforms that you want to support.
# For your initial PR, limit it to 1 platform.
_PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR]

"""Triad AMS integration for Home Assistant."""
import logging
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import entity_platform
from .const import DOMAIN
from .helper import TriadAmsClient
from .coordinator import TriadAmsCoordinator

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
# TODO Create ConfigEntry type alias with API object
# Alias name should be prefixed by integration name
type New_NameConfigEntry = ConfigEntry[MyApi]  # noqa: F821


# TODO Update entry annotation
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Triad AMS from a config entry."""

    # TODO 1. Create API instance
    # TODO 2. Validate the API connection (and authentication)
    # TODO 3. Store an API object for your platforms to access
    # entry.runtime_data = MyAPI(...)

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


# TODO Update entry annotation
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
