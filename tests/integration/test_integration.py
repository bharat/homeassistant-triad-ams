"""Integration tests for Triad AMS using TCP simulator."""

import asyncio
import socket
from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.triad_ams.coordinator import TriadCoordinator
from custom_components.triad_ams.models import TriadAmsOutput
from tests.integration.simulator import TriadAmsSimulator, triad_ams_simulator


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
        "host": "127.0.0.1",
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
    return entry


@pytest.mark.integration
class TestTriadAmsIntegration:
    """End-to-end integration tests."""

    @pytest.mark.asyncio
    async def test_coordinator_setup_with_simulator(self) -> None:
        """Test coordinator setup and connection to simulator."""
        async with triad_ams_simulator() as (simulator, host, port):
            coordinator = TriadCoordinator(
                host, port, 8, min_send_interval=0.01, poll_interval=0.1
            )
            await coordinator.start()

            try:
                # Test volume get
                volume = await coordinator.get_output_volume(1)
                assert 0.0 <= volume <= 1.0

                # Test volume set
                await coordinator.set_output_volume(1, 0.75)
                await asyncio.sleep(0.1)
                assert abs(simulator.get_volume(1) - 0.75) < 0.1

            finally:
                await coordinator.stop()
                await coordinator.disconnect()

    @pytest.mark.asyncio
    async def test_output_volume_control(self) -> None:
        """Test volume control through output model."""
        async with triad_ams_simulator() as (simulator, host, port):
            coordinator = TriadCoordinator(
                host, port, 8, min_send_interval=0.01, poll_interval=0.1
            )
            await coordinator.start()

            try:
                input_names = {i: f"Input {i}" for i in range(1, 9)}
                output = TriadAmsOutput(1, "Output 1", coordinator, None, input_names)

                # Set volume
                await output.set_volume(0.6)
                await asyncio.sleep(0.1)
                assert abs(simulator.get_volume(1) - 0.6) < 0.1
                assert abs(output.volume - 0.6) < 0.1

                # Get volume
                await output.refresh()
                assert output.volume is not None
                assert 0.0 <= output.volume <= 1.0

            finally:
                await coordinator.stop()
                await coordinator.disconnect()

    @pytest.mark.asyncio
    async def test_output_mute_control(self) -> None:
        """Test mute control through output model."""
        async with triad_ams_simulator() as (simulator, host, port):
            coordinator = TriadCoordinator(
                host, port, 8, min_send_interval=0.01, poll_interval=0.1
            )
            await coordinator.start()

            try:
                input_names = {i: f"Input {i}" for i in range(1, 9)}
                output = TriadAmsOutput(1, "Output 1", coordinator, None, input_names)

                # Set mute
                await output.set_muted(muted=True)
                await asyncio.sleep(0.1)
                assert simulator.get_mute(1) is True
                assert output.muted is True

                # Unmute
                await output.set_muted(muted=False)
                await asyncio.sleep(0.1)
                assert simulator.get_mute(1) is False
                assert output.muted is False

            finally:
                await coordinator.stop()
                await coordinator.disconnect()

    @pytest.mark.asyncio
    async def test_output_source_routing(self) -> None:
        """Test source routing through output model."""
        async with triad_ams_simulator() as (simulator, host, port):
            coordinator = TriadCoordinator(
                host, port, 8, min_send_interval=0.01, poll_interval=0.1
            )
            await coordinator.start()

            try:
                input_names = {i: f"Input {i}" for i in range(1, 9)}
                output = TriadAmsOutput(1, "Output 1", coordinator, None, input_names)

                # Route to input 2
                await output.set_source(2)
                await asyncio.sleep(0.1)
                assert simulator.get_source(1) == 2
                assert output.source == 2
                assert output.source_name == "Input 2"

                # Disconnect
                await output.turn_off()
                await asyncio.sleep(0.1)
                assert simulator.get_source(1) is None
                assert output.source is None

            finally:
                await coordinator.stop()
                await coordinator.disconnect()

    @pytest.mark.asyncio
    async def test_output_volume_steps(self) -> None:
        """Test volume step operations."""
        async with triad_ams_simulator() as (simulator, host, port):
            coordinator = TriadCoordinator(
                host, port, 8, min_send_interval=0.01, poll_interval=0.1
            )
            await coordinator.start()

            try:
                input_names = {i: f"Input {i}" for i in range(1, 9)}
                output = TriadAmsOutput(1, "Output 1", coordinator, None, input_names)

                # Set initial volume
                await output.set_volume(0.5)
                await asyncio.sleep(0.1)
                initial_volume = simulator.get_volume(1)

                # Step up
                await output.volume_up_step(large=False)
                await asyncio.sleep(0.1)
                new_volume = simulator.get_volume(1)
                assert new_volume > initial_volume

                # Step down
                await output.volume_down_step(large=False)
                await asyncio.sleep(0.1)
                final_volume = simulator.get_volume(1)
                assert final_volume < new_volume

            finally:
                await coordinator.stop()
                await coordinator.disconnect()

    @pytest.mark.asyncio
    async def test_output_turn_on_restores_source(self) -> None:
        """Test that turn_on restores remembered source."""
        async with triad_ams_simulator() as (simulator, host, port):
            coordinator = TriadCoordinator(
                host, port, 8, min_send_interval=0.01, poll_interval=0.1
            )
            await coordinator.start()

            try:
                input_names = {i: f"Input {i}" for i in range(1, 9)}
                output = TriadAmsOutput(1, "Output 1", coordinator, None, input_names)

                # Set source and turn off
                await output.set_source(3)
                await asyncio.sleep(0.1)
                await output.turn_off()
                await asyncio.sleep(0.1)
                assert simulator.get_source(1) is None

                # Turn on should restore source
                await output.turn_on()
                await asyncio.sleep(0.1)
                assert simulator.get_source(1) == 3
                assert output.source == 3

            finally:
                await coordinator.stop()
                await coordinator.disconnect()

    @pytest.mark.asyncio
    async def test_zone_trigger_management(self) -> None:
        """Test zone trigger commands."""
        async with triad_ams_simulator() as (simulator, host, port):
            coordinator = TriadCoordinator(
                host, port, 8, min_send_interval=0.01, poll_interval=0.1
            )
            await coordinator.start()

            try:
                input_names = {i: f"Input {i}" for i in range(1, 9)}
                output1 = TriadAmsOutput(1, "Output 1", coordinator, None, input_names)
                output2 = TriadAmsOutput(2, "Output 2", coordinator, None, input_names)

                # Route first output (should turn on zone 1)
                await output1.set_source(1)
                await asyncio.sleep(0.1)
                assert simulator.get_zone_state(1) is True

                # Route second output (zone should stay on)
                await output2.set_source(2)
                await asyncio.sleep(0.1)
                assert simulator.get_zone_state(1) is True

                # Disconnect both (should turn off zone)
                await output1.turn_off()
                await asyncio.sleep(0.1)
                await output2.turn_off()
                await asyncio.sleep(0.1)
                assert simulator.get_zone_state(1) is False

            finally:
                await coordinator.stop()
                await coordinator.disconnect()

    @pytest.mark.asyncio
    async def test_polling_updates_state(self) -> None:
        """Test that polling updates output state."""
        async with triad_ams_simulator() as (_simulator, host, port):
            coordinator = TriadCoordinator(
                host, port, 8, min_send_interval=0.01, poll_interval=0.05
            )
            await coordinator.start()

            try:
                input_names = {i: f"Input {i}" for i in range(1, 9)}
                output = TriadAmsOutput(1, "Output 1", coordinator, None, input_names)

                # Register for polling
                coordinator.register_output(output)

                # Set state on simulator directly (simulating external change)
                # Note: We can't directly modify simulator state, but we can
                # set it via commands and verify polling picks it up
                await output.set_volume(0.8)
                await asyncio.sleep(0.2)  # Wait for poll cycle

                # Refresh should get current state
                await output.refresh()
                assert output.volume is not None
                assert abs(output.volume - 0.8) < 0.1

            finally:
                await coordinator.stop()
                await coordinator.disconnect()

    @pytest.mark.asyncio
    async def test_multiple_outputs_coordination(self) -> None:
        """Test coordination of multiple outputs."""
        async with triad_ams_simulator() as (simulator, host, port):
            coordinator = TriadCoordinator(
                host, port, 8, min_send_interval=0.01, poll_interval=0.1
            )
            await coordinator.start()

            try:
                input_names = {i: f"Input {i}" for i in range(1, 9)}
                output1 = TriadAmsOutput(1, "Output 1", coordinator, None, input_names)
                output2 = TriadAmsOutput(2, "Output 2", coordinator, None, input_names)

                # Set different volumes
                await output1.set_volume(0.5)
                await output2.set_volume(0.7)
                await asyncio.sleep(0.2)

                assert abs(simulator.get_volume(1) - 0.5) < 0.1
                assert abs(simulator.get_volume(2) - 0.7) < 0.1

                # Route to different sources
                await output1.set_source(1)
                await output2.set_source(2)
                await asyncio.sleep(0.2)

                assert simulator.get_source(1) == 1
                assert simulator.get_source(2) == 2

            finally:
                await coordinator.stop()
                await coordinator.disconnect()

    @pytest.mark.asyncio
    async def test_error_recovery(self) -> None:
        """Test error recovery and reconnection after clean disconnect."""
        # Use a fixed port so simulator can restart on the same port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            test_port = s.getsockname()[1]

        simulator = TriadAmsSimulator("127.0.0.1", test_port, 8, 8)
        try:
            host, port = await simulator.start()
            coordinator = TriadCoordinator(
                host, port, 8, min_send_interval=0.01, poll_interval=1.0
            )
            await coordinator.start()

            try:
                input_names = {i: f"Input {i}" for i in range(1, 9)}
                output = TriadAmsOutput(1, "Output 1", coordinator, None, input_names)

                # Set volume
                await output.set_volume(0.5)
                await asyncio.sleep(0.1)
                assert abs(simulator.get_volume(1) - 0.5) < 0.1

                # Explicitly disconnect coordinator (clean disconnect)
                await coordinator.disconnect()
                await asyncio.sleep(0.1)

                # Stop simulator
                await simulator.stop()
                await asyncio.sleep(0.2)

                # Restart simulator on the same port
                await simulator.start()
                # Wait for simulator to be fully ready
                await asyncio.sleep(0.3)

                # Coordinator should automatically reconnect on next command
                # The reconnect happens in the worker when the command is executed
                await output.set_volume(0.6)
                await asyncio.sleep(0.4)
                # Verify the volume was set (coordinator should have reconnected)
                volume = await coordinator.get_output_volume(1)
                assert abs(volume - 0.6) < 0.1
                assert abs(simulator.get_volume(1) - 0.6) < 0.1

            finally:
                await coordinator.stop()
                await coordinator.disconnect()
        finally:
            await simulator.stop()
