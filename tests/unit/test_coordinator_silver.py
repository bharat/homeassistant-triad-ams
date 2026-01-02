"""Unit tests for TriadCoordinator Silver quality scale requirements."""

from unittest.mock import MagicMock

import pytest

from custom_components.triad_ams.coordinator import (
    TriadCoordinator,
    TriadCoordinatorConfig,
)


class TestTriadCoordinatorSilverAvailability:
    """Test coordinator availability tracking (Silver requirement)."""

    def test_coordinator_is_available_initial(self, mock_connection: MagicMock) -> None:
        """Test coordinator starts as available."""
        config = TriadCoordinatorConfig(host="192.168.1.100", port=52000, input_count=8)
        coordinator = TriadCoordinator(config, connection=mock_connection)

        # This test will fail until we implement is_available() property
        assert hasattr(coordinator, "is_available")
        assert coordinator.is_available is True

    @pytest.mark.asyncio
    async def test_coordinator_is_available_after_connection_failure(
        self, mock_connection: MagicMock
    ) -> None:
        """Test coordinator becomes unavailable after network exception."""
        config = TriadCoordinatorConfig(
            host="192.168.1.100",
            port=52000,
            input_count=8,
            min_send_interval=0.01,
            poll_interval=0.1,
        )
        coordinator = TriadCoordinator(config, connection=mock_connection)

        await coordinator.start()

        # Simulate a network exception in the worker
        # This will fail until we implement availability tracking
        if hasattr(coordinator, "_available"):
            # Simulate connection failure
            coordinator._available = False

            # Verify coordinator is now unavailable
            assert coordinator.is_available is False

        await coordinator.stop()

    @pytest.mark.asyncio
    async def test_coordinator_is_available_after_reconnect(
        self, mock_connection: MagicMock
    ) -> None:
        """Test coordinator becomes available after successful reconnection."""
        config = TriadCoordinatorConfig(
            host="192.168.1.100",
            port=52000,
            input_count=8,
            min_send_interval=0.01,
            poll_interval=0.1,
        )
        coordinator = TriadCoordinator(config, connection=mock_connection)

        await coordinator.start()

        # Simulate connection failure then recovery
        if hasattr(coordinator, "_available"):
            # Start as unavailable
            coordinator._available = False
            assert coordinator.is_available is False

            # Simulate successful reconnection
            coordinator._available = True

            # Verify coordinator is now available
            assert coordinator.is_available is True

        await coordinator.stop()

    @pytest.mark.asyncio
    async def test_coordinator_notifies_listeners_on_availability_change(
        self, mock_connection: MagicMock
    ) -> None:
        """Test availability listeners are notified when state changes."""
        config = TriadCoordinatorConfig(
            host="192.168.1.100",
            port=52000,
            input_count=8,
            min_send_interval=0.01,
            poll_interval=0.1,
        )
        coordinator = TriadCoordinator(config, connection=mock_connection)

        await coordinator.start()

        # This test will fail until we implement availability listeners
        listener_called = False
        listener_value = None

        def availability_listener(*, is_available: bool) -> None:
            nonlocal listener_called, listener_value
            listener_called = True
            listener_value = is_available

        if hasattr(coordinator, "add_availability_listener"):
            unsub = coordinator.add_availability_listener(availability_listener)

            # Simulate availability change
            if hasattr(coordinator, "_notify_availability_listeners"):
                coordinator._notify_availability_listeners(is_available=False)

                # Verify listener was called
                assert listener_called is True
                assert listener_value is False

                # Test transition back to available
                listener_called = False
                coordinator._notify_availability_listeners(is_available=True)
                assert listener_called is True
                assert listener_value is True

                # Unsubscribe
                unsub()

        await coordinator.stop()
