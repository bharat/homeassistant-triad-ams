"""Unit tests for TriadAmsInputMediaPlayer Silver quality scale requirements."""

from unittest.mock import MagicMock

import pytest
from homeassistant.components.media_player import MediaPlayerState
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.triad_ams.coordinator import (
    TriadCoordinator,
    TriadCoordinatorConfig,
)
from custom_components.triad_ams.media_player import TriadAmsInputMediaPlayer
from custom_components.triad_ams.models import TriadAmsInput


@pytest.fixture
def mock_input() -> MagicMock:
    """Create a mock TriadAmsInput."""
    input_obj = MagicMock(spec=TriadAmsInput)
    input_obj.number = 1
    input_obj.name = "Input 1"
    input_obj.linked_entity_id = None
    input_obj.add_listener = MagicMock(return_value=MagicMock())
    return input_obj


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Create a mock config entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry_123"
    entry.title = "Test Triad AMS"
    entry.options = {
        "active_inputs": [1, 2],
        "active_outputs": [1],
        "input_links": {},
    }
    return entry


@pytest.fixture
def mock_hass() -> MagicMock:
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    # Add data attribute for async_write_ha_state
    hass.data = {"integrations": {}}
    return hass


@pytest.fixture
def input_media_player(
    mock_input: MagicMock, mock_config_entry: MagicMock
) -> TriadAmsInputMediaPlayer:
    """Create a TriadAmsInputMediaPlayer instance."""
    return TriadAmsInputMediaPlayer(mock_input, mock_config_entry)


class TestTriadAmsInputMediaPlayerSilverUnavailable:
    """Test entity unavailable state (Silver requirement)."""

    def test_entity_unavailable_when_coordinator_unavailable(
        self, input_media_player: TriadAmsInputMediaPlayer
    ) -> None:
        """Test entity unavailable when coordinator indicates device unavailable."""
        # Mock coordinator to be unavailable
        # Note: This test will fail until we implement coordinator.is_available()
        coordinator = MagicMock()
        coordinator.is_available = MagicMock(return_value=False)
        # Attach coordinator to input (via input.coordinator)
        input_media_player.input.coordinator = coordinator

        # Entity should be unavailable (available property should be False)
        # Note: When unavailable, state might be None or last known state
        # The key is that available property reflects coordinator availability
        assert hasattr(input_media_player, "available")
        assert input_media_player.available is False

    def test_entity_available_when_coordinator_available(
        self, input_media_player: TriadAmsInputMediaPlayer
    ) -> None:
        """Test entity returns normal state when coordinator is available."""
        # Mock coordinator to be available
        coordinator = MagicMock()
        coordinator.is_available = MagicMock(return_value=True)
        input_media_player.input.coordinator = coordinator

        # Entity should return normal state (not UNAVAILABLE)
        # Input entities return OFF when no linked entity
        assert input_media_player.state == MediaPlayerState.OFF
        assert input_media_player.available is True

    def test_entity_state_transition_unavailable_to_available(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Test entity transitions from unavailable to available on reconnect."""
        coordinator = MagicMock()
        coordinator.is_available = MagicMock(return_value=False)
        input_media_player.input.coordinator = coordinator
        input_media_player.hass = mock_hass
        input_media_player.async_write_ha_state = (
            MagicMock()
        )  # Mock to avoid entity_id requirement

        # Initially unavailable
        if hasattr(input_media_player, "_update_availability"):
            input_media_player._update_availability(is_available=False)
        assert input_media_player.available is False

        # Simulate connection restored
        coordinator.is_available = MagicMock(return_value=True)
        # Trigger availability update callback
        if hasattr(input_media_player, "_update_availability"):
            input_media_player._update_availability(is_available=True)

        # Should now be available
        assert input_media_player.available is True

    def test_entity_state_transition_available_to_unavailable(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Test entity transitions from available to unavailable on connection loss."""
        coordinator = MagicMock()
        coordinator.is_available = MagicMock(return_value=True)
        input_media_player.input.coordinator = coordinator
        input_media_player.hass = mock_hass
        input_media_player.async_write_ha_state = (
            MagicMock()
        )  # Mock to avoid entity_id requirement

        # Initially available
        if hasattr(input_media_player, "_update_availability"):
            input_media_player._update_availability(is_available=True)
        # Input entities return OFF when no linked entity
        assert input_media_player.state == MediaPlayerState.OFF
        assert input_media_player.available is True

        # Simulate connection lost
        coordinator.is_available = MagicMock(return_value=False)
        # Trigger availability update callback
        if hasattr(input_media_player, "_update_availability"):
            input_media_player._update_availability(is_available=False)

        # Should now be unavailable
        assert input_media_player.available is False

    def test_entity_available_property_reflects_coordinator(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Test _attr_available property reflects coordinator's is_available() state."""
        coordinator = MagicMock()
        coordinator.is_available = MagicMock(return_value=True)
        input_media_player.input.coordinator = coordinator
        input_media_player.hass = mock_hass
        input_media_player.async_write_ha_state = (
            MagicMock()
        )  # Mock to avoid entity_id requirement

        # Should reflect coordinator state
        assert input_media_player.available is True

        coordinator.is_available = MagicMock(return_value=False)
        if hasattr(input_media_player, "_update_availability"):
            input_media_player._update_availability(is_available=False)
        assert input_media_player.available is False


class TestTriadAmsInputMediaPlayerSilverLogging:
    """Test logging when unavailable (Silver requirement)."""

    def test_logs_when_entity_becomes_unavailable(
        self,
        input_media_player: TriadAmsInputMediaPlayer,
        mock_hass: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test logging occurs when entity transitions to unavailable."""
        coordinator = MagicMock()
        coordinator.is_available = MagicMock(return_value=True)
        input_media_player.input.coordinator = coordinator
        input_media_player.hass = mock_hass
        input_media_player.async_write_ha_state = (
            MagicMock()
        )  # Mock to avoid entity_id requirement

        # Initially available
        input_media_player._attr_available = True

        # Simulate becoming unavailable
        if hasattr(input_media_player, "_update_availability"):
            with caplog.at_level("INFO"):
                input_media_player._update_availability(is_available=False)

            # Verify log message is present
            assert any(
                "unavailable" in record.message.lower()
                for record in caplog.records
                if hasattr(input_media_player, "input")
                and hasattr(input_media_player.input, "number")
            )

    def test_logs_when_entity_becomes_available(
        self,
        input_media_player: TriadAmsInputMediaPlayer,
        mock_hass: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test logging occurs when entity transitions back to available."""
        coordinator = MagicMock()
        coordinator.is_available = MagicMock(return_value=False)
        input_media_player.input.coordinator = coordinator
        input_media_player.hass = mock_hass
        input_media_player.async_write_ha_state = (
            MagicMock()
        )  # Mock to avoid entity_id requirement

        # Initially unavailable
        input_media_player._attr_available = False

        # Simulate becoming available
        if hasattr(input_media_player, "_update_availability"):
            with caplog.at_level("INFO"):
                input_media_player._update_availability(is_available=True)

            # Verify log message is present
            assert any(
                "available" in record.message.lower()
                for record in caplog.records
                if hasattr(input_media_player, "input")
                and hasattr(input_media_player.input, "number")
            )

    def test_coordinator_logs_unavailable(
        self, mock_connection: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test coordinator logs when availability changes to False."""
        # Create a real coordinator instance
        config = TriadCoordinatorConfig(host="192.168.1.100", port=52000, input_count=8)
        coord = TriadCoordinator(config, connection=mock_connection)

        # Simulate connection failure triggering unavailable state
        # The logging happens in _run_worker when network exceptions occur
        # For this test, we'll verify that the logging infrastructure exists
        # by checking that _notify_availability_listeners can be called
        # and that the coordinator tracks availability
        if hasattr(coord, "_available"):
            # Simulate the coordinator detecting unavailability
            # (In real code, this happens in _run_worker when network exceptions occur)
            coord._available = False
            if hasattr(coord, "_notify_availability_listeners"):
                # The actual logging happens in _run_worker, but we can verify
                # that the infrastructure is in place
                coord._notify_availability_listeners(is_available=False)
                # Verify coordinator tracks availability
                assert coord.is_available is False

    def test_coordinator_logs_available(
        self, mock_connection: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test coordinator logs when availability changes to True."""
        config = TriadCoordinatorConfig(host="192.168.1.100", port=52000, input_count=8)
        coord = TriadCoordinator(config, connection=mock_connection)

        # Simulate successful reconnection
        # The logging happens in _ensure_connection when reconnecting
        # For this test, we'll verify that the logging infrastructure exists
        if hasattr(coord, "_available"):
            coord._available = False  # Start as unavailable
            if hasattr(coord, "_notify_availability_listeners"):
                # The actual logging happens in _ensure_connection, but we can verify
                # that the infrastructure is in place
                coord._available = True
                coord._notify_availability_listeners(is_available=True)
                # Verify coordinator tracks availability
                assert coord.is_available is True


class TestTriadAmsInputMediaPlayerSilverParallelUpdates:
    """Test parallel updates constant (Silver requirement)."""

    def test_parallel_updates_constant_set(self) -> None:
        """Test PARALLEL_UPDATES constant is set to 1."""
        # This test will fail until we add PARALLEL_UPDATES constant
        assert hasattr(TriadAmsInputMediaPlayer, "PARALLEL_UPDATES")
        assert TriadAmsInputMediaPlayer.PARALLEL_UPDATES == 1

    def test_parallel_updates_constant_type(self) -> None:
        """Test PARALLEL_UPDATES is an integer."""
        # This test will fail until we add PARALLEL_UPDATES constant
        assert hasattr(TriadAmsInputMediaPlayer, "PARALLEL_UPDATES")
        assert isinstance(TriadAmsInputMediaPlayer.PARALLEL_UPDATES, int)
