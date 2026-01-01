"""Shared pytest fixtures for Triad AMS tests."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.triad_ams.coordinator import TriadCoordinator
from custom_components.triad_ams.models import TriadAmsOutput

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

# Import pytest_socket at module level to avoid PLC0415
try:
    import pytest_socket
except ImportError:
    pytest_socket = None  # Optional dependency


def create_async_mock_method(
    return_value: Any = None, side_effect: Any = None
) -> MagicMock:
    """
    Create a MagicMock with an async function.

    This avoids AsyncMock's issue of creating coroutines on attribute access.
    Coroutines are only created when the method is actually called.
    """
    # Store values in a mutable dict that can be updated
    state: dict[str, Any] = {"return_value": return_value, "side_effect": side_effect}

    async def async_method(*args: Any, **kwargs: Any) -> Any:
        # Check for side_effect first
        if state["side_effect"] is not None:
            se = state["side_effect"]
            if callable(se) and not isinstance(se, type):
                return se(*args, **kwargs)
            if not callable(se):
                raise se
        # Return the return_value
        return state["return_value"]

    mock = MagicMock(side_effect=async_method)
    # Store state on the mock so we can update it
    mock._async_mock_state = state

    # Override return_value and side_effect properties
    def _get_return_value(mock_self: MagicMock) -> Any:
        return mock_self._async_mock_state["return_value"]

    def _set_return_value(mock_self: MagicMock, value: Any) -> None:
        mock_self._async_mock_state["return_value"] = value

    def _get_side_effect(_mock_self: MagicMock) -> Any:
        # Always return the async_method wrapper to avoid creating coroutines
        return async_method

    def _set_side_effect(mock_self: MagicMock, value: Any) -> None:
        mock_self._async_mock_state["side_effect"] = value
        # Keep the async wrapper
        MagicMock.side_effect.fset(mock_self, async_method)

    # Use property descriptor
    type(mock).return_value = property(_get_return_value, _set_return_value)
    type(mock).side_effect = property(_get_side_effect, _set_side_effect)

    return mock


@pytest.fixture
def mock_hass() -> MagicMock:
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    hass.async_create_task = MagicMock()
    return hass


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Create a mock config entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry_123"
    entry.data = {
        "host": "192.168.1.100",
        "port": 52000,
        "model": "AMS8",
        "input_count": 8,
        "output_count": 8,
    }
    entry.options = {
        "active_inputs": [1, 2, 3, 4],
        "active_outputs": [1, 2],
        "input_links": {},
    }
    entry.title = "Test Triad AMS"
    entry.runtime_data = None
    return entry


@pytest.fixture
def mock_connection() -> MagicMock:
    """Create a mock TriadConnection."""
    conn = MagicMock()
    # Set synchronous attributes
    conn.host = "192.168.1.100"
    conn.port = 52000
    conn.close_nowait = MagicMock()

    # Set async methods using explicit coroutines
    conn.connect = create_async_mock_method()
    conn.disconnect = create_async_mock_method()
    conn.set_output_volume = create_async_mock_method()
    conn.get_output_volume = create_async_mock_method(return_value=0.5)
    conn.set_output_mute = create_async_mock_method()
    conn.get_output_mute = create_async_mock_method(return_value=False)
    conn.volume_step_up = create_async_mock_method()
    conn.volume_step_down = create_async_mock_method()
    conn.set_output_to_input = create_async_mock_method()
    conn.get_output_source = create_async_mock_method(return_value=1)
    conn.disconnect_output = create_async_mock_method()
    conn.set_trigger_zone = create_async_mock_method()

    return conn


@pytest.fixture
def mock_coordinator(mock_connection: MagicMock) -> MagicMock:
    """Create a mock TriadCoordinator."""
    coordinator = MagicMock(spec=TriadCoordinator)
    coordinator._conn = mock_connection
    coordinator.input_count = 8
    coordinator.start = create_async_mock_method()
    coordinator.stop = create_async_mock_method()
    coordinator.disconnect = create_async_mock_method()
    coordinator.set_output_volume = create_async_mock_method()
    coordinator.get_output_volume = create_async_mock_method(return_value=0.5)
    coordinator.set_output_mute = create_async_mock_method()
    coordinator.get_output_mute = create_async_mock_method(return_value=False)
    coordinator.volume_step_up = create_async_mock_method()
    coordinator.volume_step_down = create_async_mock_method()
    coordinator.set_output_to_input = create_async_mock_method()
    coordinator.get_output_source = create_async_mock_method(return_value=1)
    coordinator.disconnect_output = create_async_mock_method()
    coordinator.set_trigger_zone = create_async_mock_method()
    coordinator.register_output = MagicMock()
    return coordinator


@pytest.fixture
def coordinator_with_mock_connection(
    mock_connection: MagicMock,
) -> Generator[TriadCoordinator]:
    """Create a real TriadCoordinator with a mocked connection."""
    return TriadCoordinator("192.168.1.100", 52000, 8, connection=mock_connection)


@pytest.fixture
def triad_ams_output(
    coordinator_with_mock_connection: TriadCoordinator,
) -> TriadAmsOutput:
    """Create a TriadAmsOutput instance for testing."""
    input_names = {i: f"Input {i}" for i in range(1, 9)}
    return TriadAmsOutput(
        1, "Output 1", coordinator_with_mock_connection, None, input_names
    )


@pytest.fixture
def input_names() -> dict[int, str]:
    """Return default input names for testing."""
    return {i: f"Input {i}" for i in range(1, 9)}


@pytest.fixture
def event_loop() -> Generator[asyncio.AbstractEventLoop]:
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def enable_sockets_for_integration_tests(request: pytest.FixtureRequest) -> None:
    """Enable socket usage for integration tests."""
    # Check if this is an integration test by looking at the test path
    if "integration" in str(request.node.fspath) and pytest_socket is not None:
        pytest_socket.enable_socket()


@pytest.fixture
async def hass_fixture() -> AsyncGenerator[HomeAssistant]:
    """Create a Home Assistant instance for testing."""
    # This will be provided by pytest-homeassistant-custom-component
    # For now, we'll use a mock
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    hass.async_create_task = MagicMock()
    return hass


@pytest.fixture
def mock_state() -> MagicMock:
    """Create a mock state object."""
    state = MagicMock()
    state.name = "Test Entity"
    state.state = "playing"
    state.attributes = {
        "media_title": "Test Song",
        "media_artist": "Test Artist",
        "media_album_name": "Test Album",
        "media_duration": 180,
        "media_content_id": "test://content",
        "media_content_type": "music",
        "entity_picture": "http://example.com/art.jpg",
    }
    return state
