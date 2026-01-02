"""Diagnostics support for Triad AMS integration (Gold requirement)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .coordinator import TriadCoordinator


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> dict[str, Any]:
    """
    Return diagnostics for a config entry.

    Provides diagnostic information about the config entry and coordinator state
    for troubleshooting purposes.
    """
    coordinator: TriadCoordinator | None = config_entry.runtime_data

    diagnostics_data: dict[str, Any] = {
        "config_entry": {
            "title": config_entry.title,
            "entry_id": config_entry.entry_id,
            "data": {
                k: v
                for k, v in config_entry.data.items()
                if k != "host"  # Exclude host for security
            },
        },
    }

    if coordinator is not None:
        diagnostics_data["coordinator"] = {
            "host": coordinator._host,  # noqa: SLF001
            "port": coordinator._port,  # noqa: SLF001
            "input_count": coordinator.input_count,
            "available": coordinator.is_available,
        }

        # Get output states if available
        if hasattr(coordinator, "_outputs"):
            outputs_data = [
                {
                    "number": output.number,
                    "name": output.name,
                    "volume": getattr(output, "_volume", None),
                    "muted": getattr(output, "_muted", None),
                    "source": getattr(output, "_assigned_input", None),
                    "has_source": getattr(output, "has_source", False),
                }
                for output in list(coordinator._outputs)  # noqa: SLF001
                if output is not None
            ]
            diagnostics_data["outputs"] = outputs_data
        else:
            diagnostics_data["outputs"] = []

    return diagnostics_data
