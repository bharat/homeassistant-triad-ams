"""Integration tests for Triad AMS using TCP simulator."""

import asyncio
import socket

import pytest

from custom_components.triad_ams.coordinator import (
    TriadCoordinator,
    TriadCoordinatorConfig,
)
from custom_components.triad_ams.models import TriadAmsOutput
from tests.integration.simulator import TriadAmsSimulator


@pytest.mark.integration
class TestTriadAmsIntegration:
    """End-to-end integration tests."""

    @pytest.mark.asyncio
    async def test_coordinator_setup_with_simulator(
        self,
        simulator_fixture: tuple[TriadAmsSimulator, str, int],
        coordinator_fixture: TriadCoordinator,
    ) -> None:
        """Test coordinator setup and connection to simulator."""
        simulator, _host, _port = simulator_fixture
        coordinator = coordinator_fixture

        # Test volume get
        volume = await coordinator.get_output_volume(1)
        assert 0.0 <= volume <= 1.0

        # Test volume set
        await coordinator.set_output_volume(1, 0.75)
        assert abs(simulator.get_volume(1) - 0.75) < 0.1

    @pytest.mark.asyncio
    async def test_output_volume_control(
        self,
        simulator_fixture: tuple[TriadAmsSimulator, str, int],
        output_fixture: TriadAmsOutput,
    ) -> None:
        """Test volume control through output model."""
        simulator, _host, _port = simulator_fixture
        output = output_fixture

        # Set volume
        await output.set_volume(0.6)
        assert abs(simulator.get_volume(1) - 0.6) < 0.1
        assert abs(output.volume - 0.6) < 0.1

        # Get volume
        await output.refresh()
        assert output.volume is not None
        assert 0.0 <= output.volume <= 1.0

    @pytest.mark.asyncio
    async def test_output_mute_control(
        self,
        simulator_fixture: tuple[TriadAmsSimulator, str, int],
        output_fixture: TriadAmsOutput,
    ) -> None:
        """Test mute control through output model."""
        simulator, _host, _port = simulator_fixture
        output = output_fixture

        # Set mute
        await output.set_muted(muted=True)
        assert simulator.get_mute(1) is True
        assert output.muted is True

        # Unmute
        await output.set_muted(muted=False)
        assert simulator.get_mute(1) is False
        assert output.muted is False

    @pytest.mark.asyncio
    async def test_output_source_routing(
        self,
        simulator_fixture: tuple[TriadAmsSimulator, str, int],
        output_fixture: TriadAmsOutput,
    ) -> None:
        """Test source routing through output model."""
        simulator, _host, _port = simulator_fixture
        output = output_fixture

        # Route to input 2
        await output.set_source(2)
        assert simulator.get_source(1) == 2
        assert output.source == 2
        assert output.source_name == "Input 2"

        # Disconnect
        await output.turn_off()
        assert simulator.get_source(1) is None
        assert output.source is None

    @pytest.mark.asyncio
    async def test_output_volume_steps(
        self,
        simulator_fixture: tuple[TriadAmsSimulator, str, int],
        output_fixture: TriadAmsOutput,
    ) -> None:
        """Test volume step operations."""
        simulator, _host, _port = simulator_fixture
        output = output_fixture

        # Set initial volume
        await output.set_volume(0.5)
        initial_volume = simulator.get_volume(1)

        # Step up
        await output.volume_up_step(large=False)
        new_volume = simulator.get_volume(1)
        assert new_volume > initial_volume

        # Step down
        await output.volume_down_step(large=False)
        final_volume = simulator.get_volume(1)
        assert final_volume < new_volume

    @pytest.mark.asyncio
    async def test_output_turn_on_restores_source(
        self,
        simulator_fixture: tuple[TriadAmsSimulator, str, int],
        output_fixture: TriadAmsOutput,
    ) -> None:
        """Test that turn_on restores remembered source."""
        simulator, _host, _port = simulator_fixture
        output = output_fixture

        # Set source and turn off
        await output.set_source(3)
        await output.turn_off()
        assert simulator.get_source(1) is None

        # Turn on should restore source
        await output.turn_on()
        assert simulator.get_source(1) == 3
        assert output.source == 3

    @pytest.mark.asyncio
    async def test_zone_trigger_management(
        self,
        simulator_fixture: tuple[TriadAmsSimulator, str, int],
        coordinator_fixture: TriadCoordinator,
        input_names: dict[int, str],
    ) -> None:
        """Test zone trigger commands."""
        simulator, _host, _port = simulator_fixture
        coordinator = coordinator_fixture

        output1 = TriadAmsOutput(1, "Output 1", coordinator, None, input_names)
        output2 = TriadAmsOutput(2, "Output 2", coordinator, None, input_names)

        # Route first output (should turn on zone 1)
        await output1.set_source(1)
        assert simulator.get_zone_state(1) is True

        # Route second output (zone should stay on)
        await output2.set_source(2)
        assert simulator.get_zone_state(1) is True

        # Disconnect both (should turn off zone)
        await output1.turn_off()
        await output2.turn_off()
        assert simulator.get_zone_state(1) is False

    @pytest.mark.asyncio
    async def test_polling_updates_state(
        self,
        simulator_fixture: tuple[TriadAmsSimulator, str, int],
        coordinator_fixture: TriadCoordinator,
        output_fixture: TriadAmsOutput,
    ) -> None:
        """Test that polling updates output state."""
        _simulator, _host, _port = simulator_fixture
        coordinator = coordinator_fixture
        output = output_fixture

        # Override poll interval for this test
        coordinator._poll_interval = 0.05

        # Register for polling
        coordinator.register_output(output)

        # Set state on simulator directly (simulating external change)
        # Note: We can't directly modify simulator state, but we can
        # set it via commands and verify polling picks it up
        await output.set_volume(0.8)
        # Wait for at least one poll cycle (poll_interval=0.05)
        await asyncio.sleep(0.06)

        # Refresh should get current state
        await output.refresh()
        assert output.volume is not None
        assert abs(output.volume - 0.8) < 0.1

    @pytest.mark.asyncio
    async def test_multiple_outputs_coordination(
        self,
        simulator_fixture: tuple[TriadAmsSimulator, str, int],
        coordinator_fixture: TriadCoordinator,
        input_names: dict[int, str],
    ) -> None:
        """Test coordination of multiple outputs."""
        simulator, _host, _port = simulator_fixture
        coordinator = coordinator_fixture

        output1 = TriadAmsOutput(1, "Output 1", coordinator, None, input_names)
        output2 = TriadAmsOutput(2, "Output 2", coordinator, None, input_names)

        # Set different volumes
        await output1.set_volume(0.5)
        await output2.set_volume(0.7)

        assert abs(simulator.get_volume(1) - 0.5) < 0.1
        assert abs(simulator.get_volume(2) - 0.7) < 0.1

        # Route to different sources
        await output1.set_source(1)
        await output2.set_source(2)

        assert simulator.get_source(1) == 1
        assert simulator.get_source(2) == 2

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
            config = TriadCoordinatorConfig(
                host=host,
                port=port,
                input_count=8,
                min_send_interval=0.01,
                poll_interval=1.0,
            )
            coordinator = TriadCoordinator(config)
            await coordinator.start()

            try:
                input_names = {i: f"Input {i}" for i in range(1, 9)}
                output = TriadAmsOutput(1, "Output 1", coordinator, None, input_names)

                # Set volume
                await output.set_volume(0.5)
                assert abs(simulator.get_volume(1) - 0.5) < 0.1

                # Explicitly disconnect coordinator (clean disconnect)
                await coordinator.disconnect()

                # Stop simulator
                await simulator.stop()
                await asyncio.sleep(0.1)

                # Restart simulator on the same port
                await simulator.start()
                # Wait for simulator to be fully ready
                await asyncio.sleep(0.1)

                # Coordinator should automatically reconnect on next command
                # The reconnect happens in the worker when the command is executed
                await output.set_volume(0.6)
                # Command already awaits completion, so no sleep needed
                # Verify the volume was set (coordinator should have reconnected)
                volume = await coordinator.get_output_volume(1)
                assert abs(volume - 0.6) < 0.1
                assert abs(simulator.get_volume(1) - 0.6) < 0.1

            finally:
                await coordinator.stop()
                await coordinator.disconnect()
        finally:
            await simulator.stop()
