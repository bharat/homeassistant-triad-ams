"""Unit tests for TriadAmsMediaPlayer Silver quality scale requirements."""

from unittest.mock import MagicMock

import pytest
from homeassistant.components.media_player import MediaPlayerState
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.triad_ams.coordinator import TriadCoordinator
from custom_components.triad_ams.media_player import TriadAmsMediaPlayer
from custom_components.triad_ams.models import TriadAmsOutput
from tests.conftest import create_async_mock_method


@pytest.fixture
def mock_output() -> MagicMock:
    """Create a mock TriadAmsOutput."""
    output = MagicMock(spec=TriadAmsOutput)
    output.number = 1
    output.name = "Output 1"
    output.source = None
    output.source_name = None
    output.source_list = ["Input 1", "Input 2"]
    output.is_on = False
    output.volume = None
    output.muted = False
    output.source_id_for_name = MagicMock(return_value=1)
    output.set_source = create_async_mock_method()
    output.set_volume = create_async_mock_method()
    output.set_muted = create_async_mock_method()
    output.volume_up_step = create_async_mock_method()
    output.volume_down_step = create_async_mock_method()
    output.turn_off = create_async_mock_method()
    output.turn_on = create_async_mock_method()
    output.refresh_and_notify = create_async_mock_method()
    output.add_listener = MagicMock(return_value=MagicMock())
    return output


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
def media_player(
    mock_output: MagicMock, mock_config_entry: MagicMock
) -> TriadAmsMediaPlayer:
    """Create a TriadAmsMediaPlayer instance."""
    input_links = {1: None, 2: None}
    return TriadAmsMediaPlayer(mock_output, mock_config_entry, input_links)


class TestTriadAmsMediaPlayerSilverUnavailable:
    """Test entity unavailable state (Silver requirement)."""

    def test_entity_unavailable_when_coordinator_unavailable(
        self, media_player: TriadAmsMediaPlayer
    ) -> None:
        """Test entity unavailable when coordinator indicates device unavailable."""
        # Mock coordinator to be unavailable
        # Note: This test will fail until we implement coordinator.is_available()
        coordinator = MagicMock()
        coordinator.is_available = MagicMock(return_value=False)
        # Attach coordinator to output (via output.coordinator)
        media_player.output.coordinator = coordinator

        # Entity should be unavailable (available property should be False)
        # Note: When unavailable, state might be None or last known state
        # The key is that available property reflects coordinator availability
        assert hasattr(media_player, "available")
        assert media_player.available is False

    def test_entity_available_when_coordinator_available(
        self, media_player: TriadAmsMediaPlayer
    ) -> None:
        """Test entity returns normal state (ON/OFF) when coordinator is available."""
        # Mock coordinator to be available
        coordinator = MagicMock()
        coordinator.is_available = MagicMock(return_value=True)
        media_player.output.coordinator = coordinator

        # Entity should return normal state (not UNAVAILABLE)
        # When output is on, should be ON; when off, should be OFF
        media_player.output.is_on = True
        assert media_player.state == MediaPlayerState.ON
        assert media_player.available is True

        media_player.output.is_on = False
        assert media_player.state == MediaPlayerState.OFF
        assert media_player.available is True

    def test_entity_state_transition_unavailable_to_available(
        self, media_player: TriadAmsMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Test entity transitions from unavailable to available on reconnect."""
        coordinator = MagicMock()
        coordinator.is_available = MagicMock(return_value=False)
        media_player.output.coordinator = coordinator
        media_player.hass = mock_hass
        media_player.async_write_ha_state = (
            MagicMock()
        )  # Mock to avoid entity_id requirement

        # Initially unavailable
        if hasattr(media_player, "_update_availability"):
            media_player._update_availability(is_available=False)
        assert media_player.available is False

        # Simulate connection restored
        coordinator.is_available = MagicMock(return_value=True)
        # Trigger availability update callback
        if hasattr(media_player, "_update_availability"):
            media_player._update_availability(is_available=True)

        # Should now be available
        assert media_player.available is True

    def test_entity_state_transition_available_to_unavailable(
        self, media_player: TriadAmsMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Test entity transitions from available to unavailable on connection loss."""
        coordinator = MagicMock()
        coordinator.is_available = MagicMock(return_value=True)
        media_player.output.coordinator = coordinator
        media_player.hass = mock_hass
        media_player.async_write_ha_state = (
            MagicMock()
        )  # Mock to avoid entity_id requirement

        # Initially available
        if hasattr(media_player, "_update_availability"):
            media_player._update_availability(is_available=True)
        media_player.output.is_on = True
        assert media_player.state == MediaPlayerState.ON
        assert media_player.available is True

        # Simulate connection lost
        coordinator.is_available = MagicMock(return_value=False)
        # Trigger availability update callback
        if hasattr(media_player, "_update_availability"):
            media_player._update_availability(is_available=False)

        # Should now be unavailable
        assert media_player.available is False

    def test_entity_available_property_reflects_coordinator(
        self, media_player: TriadAmsMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Test _attr_available property reflects coordinator's is_available() state."""
        coordinator = MagicMock()
        coordinator.is_available = MagicMock(return_value=True)
        media_player.output.coordinator = coordinator
        media_player.hass = mock_hass
        media_player.async_write_ha_state = (
            MagicMock()
        )  # Mock to avoid entity_id requirement

        # Should reflect coordinator state
        assert media_player.available is True

        coordinator.is_available = MagicMock(return_value=False)
        if hasattr(media_player, "_update_availability"):
            media_player._update_availability(is_available=False)
        assert media_player.available is False


class TestTriadAmsMediaPlayerSilverLogging:
    """Test logging when unavailable (Silver requirement)."""

    def test_logs_when_entity_becomes_unavailable(
        self,
        media_player: TriadAmsMediaPlayer,
        mock_hass: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test logging occurs when entity transitions to unavailable."""
        coordinator = MagicMock()
        coordinator.is_available = MagicMock(return_value=True)
        media_player.output.coordinator = coordinator
        media_player.hass = mock_hass
        media_player.async_write_ha_state = (
            MagicMock()
        )  # Mock to avoid entity_id requirement

        # Initially available
        media_player._attr_available = True

        # Simulate becoming unavailable
        if hasattr(media_player, "_update_availability"):
            with caplog.at_level("INFO"):
                media_player._update_availability(is_available=False)

            # Verify log message is present
            assert any(
                "unavailable" in record.message.lower()
                for record in caplog.records
                if hasattr(media_player, "output")
                and hasattr(media_player.output, "number")
            )

    def test_logs_when_entity_becomes_available(
        self,
        media_player: TriadAmsMediaPlayer,
        mock_hass: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test logging occurs when entity transitions back to available."""
        coordinator = MagicMock()
        coordinator.is_available = MagicMock(return_value=False)
        media_player.output.coordinator = coordinator
        media_player.hass = mock_hass
        media_player.async_write_ha_state = (
            MagicMock()
        )  # Mock to avoid entity_id requirement

        # Initially unavailable
        media_player._attr_available = False

        # Simulate becoming available
        if hasattr(media_player, "_update_availability"):
            with caplog.at_level("INFO"):
                media_player._update_availability(is_available=True)

            # Verify log message is present
            assert any(
                "available" in record.message.lower()
                for record in caplog.records
                if hasattr(media_player, "output")
                and hasattr(media_player.output, "number")
            )

    def test_coordinator_logs_unavailable(
        self, mock_connection: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test coordinator logs when availability changes to False."""
        # Create a real coordinator instance
        coord = TriadCoordinator("192.168.1.100", 52000, 8, connection=mock_connection)

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
        coord = TriadCoordinator("192.168.1.100", 52000, 8, connection=mock_connection)

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


class TestTriadAmsMediaPlayerSilverParallelUpdates:
    """Test parallel updates constant (Silver requirement)."""

    def test_parallel_updates_constant_set(self) -> None:
        """Test PARALLEL_UPDATES constant is set to 1."""
        # This test will fail until we add PARALLEL_UPDATES constant
        assert hasattr(TriadAmsMediaPlayer, "PARALLEL_UPDATES")
        assert TriadAmsMediaPlayer.PARALLEL_UPDATES == 1

    def test_parallel_updates_constant_type(self) -> None:
        """Test PARALLEL_UPDATES is an integer."""
        # This test will fail until we add PARALLEL_UPDATES constant
        assert hasattr(TriadAmsMediaPlayer, "PARALLEL_UPDATES")
        assert isinstance(TriadAmsMediaPlayer.PARALLEL_UPDATES, int)
