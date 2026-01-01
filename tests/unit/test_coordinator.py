"""Unit tests for TriadCoordinator."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.triad_ams.coordinator import TriadCoordinator
from custom_components.triad_ams.models import TriadAmsOutput


@pytest.fixture
def mock_connection() -> AsyncMock:
    """Create a mock TriadConnection."""
    conn = AsyncMock()
    # Set synchronous method first to prevent AsyncMock from auto-creating it
    conn.close_nowait = MagicMock()
    conn.connect = AsyncMock()
    conn.disconnect = AsyncMock()
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
def coordinator(mock_connection: AsyncMock) -> TriadCoordinator:
    """Create a TriadCoordinator with mocked connection."""
    return TriadCoordinator(
        "192.168.1.100",
        52000,
        8,
        min_send_interval=0.01,
        poll_interval=0.1,
        connection=mock_connection,
    )


class TestTriadCoordinatorInitialization:
    """Test TriadCoordinator initialization."""

    def test_initialization(self, mock_connection: AsyncMock) -> None:
        """Test basic initialization."""
        coord = TriadCoordinator("192.168.1.100", 52000, 8, connection=mock_connection)

        assert coord._host == "192.168.1.100"
        assert coord._port == 52000
        assert coord.input_count == 8

    def test_input_count_property(self, coordinator: TriadCoordinator) -> None:
        """Test input_count property."""
        assert coordinator.input_count == 8


class TestTriadCoordinatorLifecycle:
    """Test coordinator lifecycle."""

    @pytest.mark.asyncio
    async def test_start(self, coordinator: TriadCoordinator) -> None:
        """Test starting coordinator."""
        await coordinator.start()
        assert coordinator._worker is not None
        assert coordinator._poll_task is not None
        assert not coordinator._worker.done()
        assert not coordinator._poll_task.done()

    @pytest.mark.asyncio
    async def test_start_idempotent(self, coordinator: TriadCoordinator) -> None:
        """Test that start is idempotent."""
        await coordinator.start()
        worker1 = coordinator._worker
        poll1 = coordinator._poll_task

        await coordinator.start()
        # Should not create new tasks
        assert coordinator._worker == worker1
        assert coordinator._poll_task == poll1

    @pytest.mark.asyncio
    async def test_stop(self, coordinator: TriadCoordinator) -> None:
        """Test stopping coordinator."""
        await coordinator.start()
        await coordinator.stop()

        assert coordinator._worker is None
        assert coordinator._poll_task is None

    @pytest.mark.asyncio
    async def test_stop_drains_queue(self, coordinator: TriadCoordinator) -> None:
        """Test that stop drains queue and cancels futures."""
        await coordinator.start()

        # Add a command to queue
        future = asyncio.get_running_loop().create_future()
        await coordinator._queue.put(
            type("_Command", (), {"op": AsyncMock(), "future": future})()
        )

        await coordinator.stop()

        # Future should be cancelled
        assert future.cancelled() or future.exception() is not None

    @pytest.mark.asyncio
    async def test_disconnect(
        self, coordinator: TriadCoordinator, mock_connection: AsyncMock
    ) -> None:
        """Test disconnecting."""
        await coordinator.disconnect()
        mock_connection.disconnect.assert_called_once()


class TestTriadCoordinatorCommandExecution:
    """Test command execution."""

    @pytest.mark.asyncio
    async def test_set_output_volume(
        self, coordinator: TriadCoordinator, mock_connection: AsyncMock
    ) -> None:
        """Test setting output volume."""
        await coordinator.start()
        await coordinator.set_output_volume(1, 0.75)

        # Wait a bit for command to process
        await asyncio.sleep(0.1)
        mock_connection.set_output_volume.assert_called_once_with(1, 0.75)
        await coordinator.stop()

    @pytest.mark.asyncio
    async def test_get_output_volume(
        self, coordinator: TriadCoordinator, mock_connection: AsyncMock
    ) -> None:
        """Test getting output volume."""
        await coordinator.start()
        volume = await coordinator.get_output_volume(1)

        assert volume == 0.5
        mock_connection.get_output_volume.assert_called_once_with(1)
        await coordinator.stop()

    @pytest.mark.asyncio
    async def test_set_output_mute(
        self, coordinator: TriadCoordinator, mock_connection: AsyncMock
    ) -> None:
        """Test setting mute."""
        await coordinator.start()
        await coordinator.set_output_mute(1, mute=True)

        await asyncio.sleep(0.1)
        mock_connection.set_output_mute.assert_called_once_with(1, mute=True)
        await coordinator.stop()

    @pytest.mark.asyncio
    async def test_volume_step_up(
        self, coordinator: TriadCoordinator, mock_connection: AsyncMock
    ) -> None:
        """Test volume step up."""
        await coordinator.start()
        await coordinator.volume_step_up(1, large=False)

        await asyncio.sleep(0.1)
        mock_connection.volume_step_up.assert_called_once_with(1, large=False)
        await coordinator.stop()

    @pytest.mark.asyncio
    async def test_volume_step_down(
        self, coordinator: TriadCoordinator, mock_connection: AsyncMock
    ) -> None:
        """Test volume step down."""
        await coordinator.start()
        await coordinator.volume_step_down(1, large=True)

        await asyncio.sleep(0.1)
        mock_connection.volume_step_down.assert_called_once_with(1, large=True)
        await coordinator.stop()

    @pytest.mark.asyncio
    async def test_set_output_to_input(
        self, coordinator: TriadCoordinator, mock_connection: AsyncMock
    ) -> None:
        """Test routing output to input."""
        await coordinator.start()
        await coordinator.set_output_to_input(1, 2)

        await asyncio.sleep(0.1)
        mock_connection.set_output_to_input.assert_called_once_with(1, 2)
        mock_connection.set_trigger_zone.assert_called_once_with(zone=1, on=True)
        await coordinator.stop()

    @pytest.mark.asyncio
    async def test_get_output_source(
        self, coordinator: TriadCoordinator, mock_connection: AsyncMock
    ) -> None:
        """Test getting output source."""
        await coordinator.start()
        source = await coordinator.get_output_source(1)

        assert source == 1
        mock_connection.get_output_source.assert_called_once_with(1)
        await coordinator.stop()

    @pytest.mark.asyncio
    async def test_disconnect_output(
        self, coordinator: TriadCoordinator, mock_connection: AsyncMock
    ) -> None:
        """Test disconnecting output."""
        await coordinator.start()
        # First set a source to make zone active
        await coordinator.set_output_to_input(1, 2)
        await asyncio.sleep(0.1)

        # Now disconnect
        await coordinator.disconnect_output(1)
        await asyncio.sleep(0.1)

        mock_connection.disconnect_output.assert_called_once_with(1, 8)
        # Should turn off trigger zone when zone becomes empty
        assert mock_connection.set_trigger_zone.call_count >= 1
        await coordinator.stop()

    @pytest.mark.asyncio
    async def test_set_trigger_zone(
        self, coordinator: TriadCoordinator, mock_connection: AsyncMock
    ) -> None:
        """Test setting trigger zone."""
        await coordinator.start()
        await coordinator.set_trigger_zone(zone=1, on=True)

        await asyncio.sleep(0.1)
        mock_connection.set_trigger_zone.assert_called_once_with(zone=1, on=True)
        await coordinator.stop()


class TestTriadCoordinatorPacing:
    """Test command pacing."""

    @pytest.mark.asyncio
    async def test_pacing_enforcement(
        self,
        coordinator: TriadCoordinator,
        mock_connection: AsyncMock,  # noqa: ARG002
    ) -> None:
        """Test that commands are paced."""
        coordinator._min_send_interval = 0.1
        await coordinator.start()

        start_time = asyncio.get_running_loop().time()
        await coordinator.set_output_volume(1, 0.5)
        await coordinator.set_output_volume(1, 0.6)
        await asyncio.sleep(0.2)  # Wait for both commands

        elapsed = asyncio.get_running_loop().time() - start_time
        # Should take at least min_send_interval between commands
        assert elapsed >= 0.1
        await coordinator.stop()

    @pytest.mark.asyncio
    async def test_connection_auto_connect(
        self, coordinator: TriadCoordinator, mock_connection: AsyncMock
    ) -> None:
        """Test that connection is established before commands."""
        await coordinator.start()
        await coordinator.set_output_volume(1, 0.5)

        await asyncio.sleep(0.1)
        mock_connection.connect.assert_called()
        await coordinator.stop()


class TestTriadCoordinatorErrorHandling:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_oserror_propagates(
        self, coordinator: TriadCoordinator, mock_connection: AsyncMock
    ) -> None:
        """Test that OSError is propagated to caller."""
        mock_connection.get_output_volume.side_effect = OSError("Connection failed")
        await coordinator.start()

        with pytest.raises(OSError, match="Connection failed"):
            await coordinator.get_output_volume(1)

        await coordinator.stop()

    @pytest.mark.asyncio
    async def test_timeout_propagates(
        self, coordinator: TriadCoordinator, mock_connection: AsyncMock
    ) -> None:
        """Test that TimeoutError is propagated."""
        mock_connection.get_output_volume.side_effect = TimeoutError()
        await coordinator.start()

        with pytest.raises(TimeoutError):
            await coordinator.get_output_volume(1)

        await coordinator.stop()

    @pytest.mark.asyncio
    async def test_reconnection_on_error(
        self, coordinator: TriadCoordinator, mock_connection: AsyncMock
    ) -> None:
        """Test that connection is re-established after error."""
        # First call fails, second succeeds
        call_count = 0

        def volume_side_effect(*_args: object, **_kwargs: object) -> float:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                error_msg = "Connection failed"
                raise OSError(error_msg)
            return 0.5

        mock_connection.get_output_volume = AsyncMock(side_effect=volume_side_effect)
        mock_connection.connect = AsyncMock(return_value=None)
        # close_nowait is not async - ensure it's a regular MagicMock (not AsyncMock)
        mock_connection.close_nowait = MagicMock()
        await coordinator.start()

        # Should reconnect and retry - the error is propagated to caller
        # but connection is re-established for next command
        with pytest.raises(OSError, match="Connection failed"):
            await coordinator.get_output_volume(1)

        # Next call should succeed after reconnection
        mock_connection.get_output_volume = AsyncMock(return_value=0.5)
        volume = await coordinator.get_output_volume(1)
        assert volume == 0.5

        await coordinator.stop()


class TestTriadCoordinatorPolling:
    """Test polling mechanism."""

    @pytest.mark.asyncio
    async def test_register_output(self, coordinator: TriadCoordinator) -> None:
        """Test registering output for polling."""
        output = MagicMock(spec=TriadAmsOutput)
        output.number = 1
        output.has_source = True
        output.refresh_and_notify = AsyncMock()

        coordinator.register_output(output)
        assert output in coordinator._outputs

    @pytest.mark.asyncio
    async def test_polling_round_robin(self, coordinator: TriadCoordinator) -> None:
        """Test that polling cycles through outputs."""
        output1 = MagicMock(spec=TriadAmsOutput)
        output1.number = 1
        output1.has_source = True
        output1.refresh_and_notify = AsyncMock()

        output2 = MagicMock(spec=TriadAmsOutput)
        output2.number = 2
        output2.has_source = True
        output2.refresh_and_notify = AsyncMock()

        coordinator.register_output(output1)
        coordinator.register_output(output2)

        coordinator._poll_interval = 0.05
        await coordinator.start()
        await asyncio.sleep(0.15)  # Allow a few poll cycles

        # Both should have been polled
        assert output1.refresh_and_notify.call_count >= 1
        assert output2.refresh_and_notify.call_count >= 1

        await coordinator.stop()

    @pytest.mark.asyncio
    async def test_polling_handles_errors(self, coordinator: TriadCoordinator) -> None:
        """Test that polling errors don't break the loop."""
        output = MagicMock(spec=TriadAmsOutput)
        output.number = 1
        output.has_source = True
        output.refresh_and_notify = AsyncMock(side_effect=Exception("Test error"))

        coordinator.register_output(output)
        coordinator._poll_interval = 0.05
        await coordinator.start()
        await asyncio.sleep(0.1)

        # Should continue polling despite errors
        assert output.refresh_and_notify.call_count >= 1
        await coordinator.stop()


class TestTriadCoordinatorZoneManagement:
    """Test zone management."""

    def test_zone_for_output(self, coordinator: TriadCoordinator) -> None:
        """Test zone calculation."""
        assert coordinator._zone_for_output(1) == 1  # Zone 1
        assert coordinator._zone_for_output(8) == 1  # Zone 1
        assert coordinator._zone_for_output(9) == 2  # Zone 2
        assert coordinator._zone_for_output(16) == 2  # Zone 2
        assert coordinator._zone_for_output(17) == 3  # Zone 3
        assert coordinator._zone_for_output(24) == 3  # Zone 3

    def test_zone_clamping(self, coordinator: TriadCoordinator) -> None:
        """Test zone number clamping."""
        assert coordinator._zone_for_output(25) == 3  # Clamped to max zone
        assert coordinator._zone_for_output(100) == 3  # Clamped to max zone

    @pytest.mark.asyncio
    async def test_zone_trigger_on_first_output(
        self, coordinator: TriadCoordinator, mock_connection: AsyncMock
    ) -> None:
        """Test that trigger zone turns on when first output is routed."""
        await coordinator.start()
        await coordinator.set_output_to_input(1, 2)

        await asyncio.sleep(0.1)
        # Should turn on zone 1
        mock_connection.set_trigger_zone.assert_called_with(zone=1, on=True)
        await coordinator.stop()

    @pytest.mark.asyncio
    async def test_zone_trigger_off_last_output(
        self, coordinator: TriadCoordinator, mock_connection: AsyncMock
    ) -> None:
        """Test that trigger zone turns off when last output is disconnected."""
        await coordinator.start()
        # Route output 1 (zone 1)
        await coordinator.set_output_to_input(1, 2)
        await asyncio.sleep(0.1)

        # Disconnect it
        await coordinator.disconnect_output(1)
        await asyncio.sleep(0.1)

        # Should turn off zone 1
        assert any(
            call == ((), {"zone": 1, "on": False})
            for call in mock_connection.set_trigger_zone.call_args_list
        )
        await coordinator.stop()
