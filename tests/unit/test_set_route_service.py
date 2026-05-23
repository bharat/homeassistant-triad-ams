"""Unit tests for the triad_ams.set_route global service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.triad_ams import (
    SERVICE_SET_ROUTE,
    async_setup,
)
from custom_components.triad_ams.const import DOMAIN
from custom_components.triad_ams.coordinator import TriadCoordinator
from tests.conftest import create_async_mock_method


def _extract_set_route_handler(
    hass: MagicMock,
) -> tuple[callable, vol.Schema]:
    """Return (handler, schema) registered for triad_ams.set_route."""
    for call in hass.services.async_register.call_args_list:
        args = call.args
        kwargs = call.kwargs
        domain = args[0] if len(args) > 0 else kwargs.get("domain")
        service_name = args[1] if len(args) > 1 else kwargs.get("service")
        handler = args[2] if len(args) > 2 else kwargs.get("service_func")
        schema = (
            kwargs.get("schema")
            if "schema" in kwargs
            else (args[3] if len(args) > 3 else None)
        )
        if domain == DOMAIN and service_name == SERVICE_SET_ROUTE:
            return handler, schema
    pytest.fail("set_route service was not registered")
    return None, None  # pragma: no cover - pytest.fail raises


def _make_service_call(data: dict) -> MagicMock:
    """Build a MagicMock that quacks like a ServiceCall."""
    call = MagicMock()
    call.data = data
    return call


@pytest.fixture
def hass() -> MagicMock:
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    hass.services = MagicMock()
    hass.services.async_register = MagicMock()
    return hass


@pytest.fixture
def coordinator() -> MagicMock:
    """Create a mock coordinator that passes the isinstance() runtime check."""
    coord = MagicMock(spec=TriadCoordinator)
    coord.set_output_to_input = create_async_mock_method()
    coord.disconnect_output = create_async_mock_method()
    return coord


@pytest.fixture
def config_entry(coordinator: MagicMock) -> MagicMock:
    """Create a mock config entry for an AMS8 device with the coordinator attached."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry_set_route"
    entry.data = {
        "host": "192.168.1.100",
        "port": 52000,
        "model": "AMS8",
        "input_count": 8,
        "output_count": 8,
    }
    entry.options = {}
    entry.runtime_data = coordinator
    return entry


@pytest.mark.asyncio
async def test_set_route_registered(hass: MagicMock) -> None:
    """async_setup registers the set_route service."""
    with patch(
        "custom_components.triad_ams.service.async_register_platform_entity_service"
    ):
        result = await async_setup(hass, {})

    assert result is True
    handler, schema = _extract_set_route_handler(hass)
    assert callable(handler)
    assert schema is not None


@pytest.mark.asyncio
async def test_set_route_routes_input_to_output(
    hass: MagicMock,
    config_entry: MagicMock,
    coordinator: MagicMock,
) -> None:
    """set_route(output=3, input=5) calls coordinator.set_output_to_input(3, 5)."""
    hass.config_entries.async_entries = MagicMock(return_value=[config_entry])
    with patch(
        "custom_components.triad_ams.service.async_register_platform_entity_service"
    ):
        await async_setup(hass, {})

    handler, _ = _extract_set_route_handler(hass)
    await handler(_make_service_call({"output": 3, "input": 5}))

    coordinator.set_output_to_input.assert_called_once_with(3, 5)
    coordinator.disconnect_output.assert_not_called()


@pytest.mark.asyncio
async def test_set_route_input_zero_disconnects(
    hass: MagicMock,
    config_entry: MagicMock,
    coordinator: MagicMock,
) -> None:
    """input=0 routes through coordinator.disconnect_output, not set_output_to_input."""
    hass.config_entries.async_entries = MagicMock(return_value=[config_entry])
    with patch(
        "custom_components.triad_ams.service.async_register_platform_entity_service"
    ):
        await async_setup(hass, {})

    handler, _ = _extract_set_route_handler(hass)
    await handler(_make_service_call({"output": 4, "input": 0}))

    coordinator.disconnect_output.assert_called_once_with(4)
    coordinator.set_output_to_input.assert_not_called()


@pytest.mark.asyncio
async def test_set_route_output_out_of_range_for_device(
    hass: MagicMock,
    config_entry: MagicMock,
    coordinator: MagicMock,
) -> None:
    """Output above the configured device's max raises HomeAssistantError."""
    # config_entry is AMS8 (output_count=8); request output=12.
    hass.config_entries.async_entries = MagicMock(return_value=[config_entry])
    with patch(
        "custom_components.triad_ams.service.async_register_platform_entity_service"
    ):
        await async_setup(hass, {})

    handler, _ = _extract_set_route_handler(hass)
    with pytest.raises(HomeAssistantError):
        await handler(_make_service_call({"output": 12, "input": 1}))

    coordinator.set_output_to_input.assert_not_called()
    coordinator.disconnect_output.assert_not_called()


@pytest.mark.asyncio
async def test_set_route_input_out_of_range_for_device(
    hass: MagicMock,
    config_entry: MagicMock,
    coordinator: MagicMock,
) -> None:
    """Input above the configured device's max raises HomeAssistantError."""
    hass.config_entries.async_entries = MagicMock(return_value=[config_entry])
    with patch(
        "custom_components.triad_ams.service.async_register_platform_entity_service"
    ):
        await async_setup(hass, {})

    handler, _ = _extract_set_route_handler(hass)
    with pytest.raises(HomeAssistantError):
        await handler(_make_service_call({"output": 1, "input": 20}))

    coordinator.set_output_to_input.assert_not_called()
    coordinator.disconnect_output.assert_not_called()


@pytest.mark.asyncio
async def test_set_route_schema_rejects_negative_input(hass: MagicMock) -> None:
    """The voluptuous schema rejects out-of-range values before the handler runs."""
    with patch(
        "custom_components.triad_ams.service.async_register_platform_entity_service"
    ):
        await async_setup(hass, {})

    _, schema = _extract_set_route_handler(hass)
    with pytest.raises(vol.Invalid):
        schema({"output": 1, "input": -1})
    with pytest.raises(vol.Invalid):
        schema({"output": 0, "input": 1})
    with pytest.raises(vol.Invalid):
        schema({"output": 25, "input": 1})
    with pytest.raises(vol.Invalid):
        schema({"output": 1, "input": 25})


@pytest.mark.asyncio
async def test_set_route_no_entries_raises(hass: MagicMock) -> None:
    """When no Triad AMS entries are configured, the service raises."""
    hass.config_entries.async_entries = MagicMock(return_value=[])
    with patch(
        "custom_components.triad_ams.service.async_register_platform_entity_service"
    ):
        await async_setup(hass, {})

    handler, _ = _extract_set_route_handler(hass)
    with pytest.raises(HomeAssistantError):
        await handler(_make_service_call({"output": 1, "input": 1}))


@pytest.mark.asyncio
async def test_set_route_multiple_entries_raises(
    hass: MagicMock,
    config_entry: MagicMock,
) -> None:
    """With more than one configured device, the service refuses to guess."""
    other = MagicMock(spec=ConfigEntry)
    other.entry_id = "second_entry"
    other.data = {
        "host": "192.168.1.101",
        "port": 52000,
        "model": "AMS16",
        "input_count": 16,
        "output_count": 16,
    }
    other.options = {}
    other.runtime_data = MagicMock(spec=TriadCoordinator)
    hass.config_entries.async_entries = MagicMock(return_value=[config_entry, other])
    with patch(
        "custom_components.triad_ams.service.async_register_platform_entity_service"
    ):
        await async_setup(hass, {})

    handler, _ = _extract_set_route_handler(hass)
    with pytest.raises(HomeAssistantError):
        await handler(_make_service_call({"output": 1, "input": 1}))
