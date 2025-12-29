"""The Triad AMS integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import TriadCoordinator

PLATFORMS = ["media_player"]

SERVICE_TURN_ON_WITH_SOURCE = "turn_on_with_source"
ATTR_INPUT_ENTITY_ID = "input_entity_id"
# Target minor version for migration
TARGET_MINOR_VERSION = 4

_LOGGER = logging.getLogger(__name__)


async def async_setup(_hass: HomeAssistant, _config: ConfigType) -> bool:
    """Set up the Triad AMS integration (empty, config entry only)."""
    service.async_register_platform_entity_service(
        _hass,
        DOMAIN,
        SERVICE_TURN_ON_WITH_SOURCE,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={
            vol.Required(ATTR_INPUT_ENTITY_ID): cv.entity_id,
        },
        func="async_turn_on_with_source",
    )

    return True


# This integration is config-entry only; no YAML configuration
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entries to add model and counts if missing."""
    # Get current minor version, defaulting to 0 if not set
    current_minor_version = getattr(config_entry, "minor_version", 0)

    # Only migrate if minor version is less than target version
    if current_minor_version < TARGET_MINOR_VERSION:
        new_data = {**config_entry.data}

        # Add model and counts if missing
        if "model" not in config_entry.data:
            _LOGGER.info(
                "Migrating config entry %s: adding model AMS8 and input/output counts",
                config_entry.entry_id,
            )
            new_data["model"] = "AMS8"
            new_data["input_count"] = 8
            new_data["output_count"] = 8

        # Update the entry with new data and minor version
        hass.config_entries.async_update_entry(
            config_entry, data=new_data, minor_version=TARGET_MINOR_VERSION
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Triad AMS from a config entry."""
    # Get connection info from entry
    host = entry.data["host"]
    port = entry.data["port"]
    input_count = entry.data.get("input_count")
    coordinator = TriadCoordinator(host, port, input_count)
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
        # Clean up input link subscriptions
        if hasattr(coordinator, "_input_link_unsubs"):
            for unsub in coordinator._input_link_unsubs:  # noqa: SLF001
                unsub()
            coordinator._input_link_unsubs = []  # noqa: SLF001
        try:
            await coordinator.stop()
        except Exception:
            _LOGGER.exception("Error stopping coordinator")
        await coordinator.disconnect()
    return unload_ok
