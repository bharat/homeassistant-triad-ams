"""Repair platform for Triad AMS integration (Gold requirement)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .coordinator import TriadCoordinator

_LOGGER = logging.getLogger(__name__)

ISSUE_ID_UNAVAILABLE = "device_unavailable"


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """
    Set up repair platform for a config entry.

    Creates repair issues when the device becomes unavailable.
    """
    coordinator: TriadCoordinator = config_entry.runtime_data

    @callback
    def _handle_availability_change(*, is_available: bool) -> None:
        """Handle coordinator availability changes."""
        if is_available:
            # Device is available, delete the issue if it exists
            hass.async_create_task(
                issue_registry.async_delete_issue(hass, DOMAIN, ISSUE_ID_UNAVAILABLE)
            )
        else:
            # Device is unavailable, create a repair issue
            hass.async_create_task(
                issue_registry.async_create_issue(
                    hass,
                    DOMAIN,
                    ISSUE_ID_UNAVAILABLE,
                    is_fixable=False,
                    severity="error",
                    translation_key="device_unavailable",
                    translation_placeholders={
                        "entry_title": config_entry.title,
                    },
                )
            )

    # Subscribe to availability changes
    # Store the unsubscribe function to keep the callback alive
    # (WeakSet will remove it if we don't keep a reference)
    _unsub = coordinator.add_availability_listener(_handle_availability_change)

    # Store unsubscribe function on config_entry to keep callback alive
    if not hasattr(config_entry, "_triad_ams_repair_unsubs"):
        config_entry._triad_ams_repair_unsubs = []  # noqa: SLF001
    config_entry._triad_ams_repair_unsubs.append(_unsub)  # noqa: SLF001

    # Check initial state
    if not coordinator.is_available:
        await issue_registry.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_ID_UNAVAILABLE,
            is_fixable=False,
            severity="error",
            translation_key="device_unavailable",
            translation_placeholders={
                "entry_title": config_entry.title,
            },
        )

    return True
