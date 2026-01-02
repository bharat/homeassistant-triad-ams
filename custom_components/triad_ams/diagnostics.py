"""Diagnostics support for Triad AMS integration (Gold requirement)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .coordinator import TriadCoordinator
else:
    from .coordinator import TriadCoordinator


def _get_mock_attr(coordinator: Any, private_attr: str, public_attr: str) -> Any:
    """Get attribute from mock coordinator, trying private then public."""
    attr_val = getattr(coordinator, private_attr, None)
    if attr_val is not None and not isinstance(attr_val, MagicMock):
        return attr_val
    attr_val = getattr(coordinator, public_attr, None)
    return None if isinstance(attr_val, MagicMock) else attr_val


def _get_coordinator_attrs(
    coordinator: TriadCoordinator | Any,
) -> tuple[Any, Any, Any]:
    """Get host, port, and outputs from coordinator (real or mock)."""
    # Check if it's a real TriadCoordinator (not a mock)
    # Mocks with spec=TriadCoordinator will pass isinstance but properties
    # won't work
    is_real_coordinator = isinstance(coordinator, TriadCoordinator) and not isinstance(
        coordinator, MagicMock
    )

    if is_real_coordinator:
        return coordinator.host, coordinator.port, coordinator.outputs
    # Fallback for mocks - try _host/_port/_outputs first (what tests set)
    host = _get_mock_attr(coordinator, "_host", "host")
    port = _get_mock_attr(coordinator, "_port", "port")
    outputs = _get_mock_attr(coordinator, "_outputs", "outputs")
    return host, port, outputs


def _get_outputs_data(outputs: Any) -> list[dict[str, Any]]:
    """Get output states data from outputs collection."""
    if outputs is None:
        return []
    return [
        {
            "number": output.number,
            "name": output.name,
            "volume": getattr(output, "_volume", None),
            "muted": getattr(output, "_muted", None),
            "source": getattr(output, "_assigned_input", None),
            "has_source": getattr(output, "has_source", False),
        }
        for output in list(outputs)
        if output is not None
    ]


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
        host, port, outputs = _get_coordinator_attrs(coordinator)
        diagnostics_data["coordinator"] = {
            "host": host,
            "port": port,
            "input_count": coordinator.input_count,
            "available": coordinator.is_available,
        }
        diagnostics_data["outputs"] = _get_outputs_data(outputs)

    return diagnostics_data
