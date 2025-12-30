"""Shared pytest fixtures for Triad AMS tests."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.triad_ams.coordinator import TriadCoordinator
from custom_components.triad_ams.models import TriadAmsOutput

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator


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
def mock_connection() -> AsyncMock:
    """Create a mock TriadConnection."""
    conn = AsyncMock()
    conn.host = "192.168.1.100"
    conn.port = 52000
    conn.connect = AsyncMock()
    conn.disconnect = AsyncMock()
    conn.close_nowait = MagicMock()
    conn.set_output_volume = AsyncMock()
    conn.get_output_volume = AsyncMock(return_value=0.5)
    conn.set_output_mute = AsyncMock()
    conn.get_output_mute = AsyncMock(return_value=False)
    conn.volume_step_up = AsyncMock()
    conn.volume_step_down = AsyncMock()
    conn.set_output_to_input = AsyncMock()
    conn.get_output_source = AsyncMock(return_value=1)
    conn.disconnect_output = AsyncMock()
    conn.set_trigger_zone = AsyncMock()
    return conn


@pytest.fixture
def mock_coordinator(mock_connection: AsyncMock) -> MagicMock:
    """Create a mock TriadCoordinator."""
    coordinator = MagicMock(spec=TriadCoordinator)
    coordinator._conn = mock_connection
    coordinator.input_count = 8
    coordinator.start = AsyncMock()
    coordinator.stop = AsyncMock()
    coordinator.disconnect = AsyncMock()
    coordinator.set_output_volume = AsyncMock()
    coordinator.get_output_volume = AsyncMock(return_value=0.5)
    coordinator.set_output_mute = AsyncMock()
    coordinator.get_output_mute = AsyncMock(return_value=False)
    coordinator.volume_step_up = AsyncMock()
    coordinator.volume_step_down = AsyncMock()
    coordinator.set_output_to_input = AsyncMock()
    coordinator.get_output_source = AsyncMock(return_value=1)
    coordinator.disconnect_output = AsyncMock()
    coordinator.set_trigger_zone = AsyncMock()
    coordinator.register_output = MagicMock()
    return coordinator


@pytest.fixture
def coordinator_with_mock_connection(
    mock_connection: AsyncMock,
) -> Generator[TriadCoordinator]:
    """Create a real TriadCoordinator with a mocked connection."""
    with patch(
        "custom_components.triad_ams.coordinator.TriadConnection"
    ) as mock_conn_class:
        mock_conn_class.return_value = mock_connection
        coordinator = TriadCoordinator("192.168.1.100", 52000, 8)
        yield coordinator


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
    if "integration" in str(request.node.fspath):
        # Import here to avoid circular imports
        import pytest_socket  # noqa: PLC0415

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
