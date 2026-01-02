"""Unit tests for repair issues (Gold requirement)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.triad_ams.coordinator import (
    TriadCoordinator,
    TriadCoordinatorConfig,
)

# Import repair module directly
try:
    from custom_components.triad_ams import repair
except ImportError:
    repair = None  # type: ignore[assignment]


@pytest.fixture
def mock_config_entry_repair() -> MagicMock:
    """Create a mock config entry for repair tests."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry_123"
    entry.title = "Test Triad AMS"
    entry.data = {
        "host": "192.168.1.100",
        "port": 52000,
        "model": "AMS8",
        "input_count": 8,
        "output_count": 8,
    }
    return entry


@pytest.fixture
def mock_connection_repair() -> MagicMock:
    """Create a mock connection for repair tests."""
    connection = MagicMock()
    connection.connect = AsyncMock()
    connection.disconnect = AsyncMock()
    connection.close_nowait = MagicMock()
    return connection


@pytest.fixture
def coordinator_repair(mock_connection_repair: MagicMock) -> TriadCoordinator:
    """Create a coordinator for repair tests."""
    config = TriadCoordinatorConfig(
        host="192.168.1.100",
        port=52000,
        input_count=8,
        min_send_interval=0.01,
        poll_interval=0.1,
    )
    return TriadCoordinator(config, connection=mock_connection_repair)


class TestRepairIssues:
    """Test repair issues platform (Gold requirement)."""

    @pytest.mark.asyncio
    async def test_repair_platform_registered(
        self, mock_hass: HomeAssistant, mock_config_entry_repair: MagicMock
    ) -> None:
        """Test repair platform is registered."""
        # This test will fail until repair platform is implemented
        assert repair is not None
        assert hasattr(repair, "async_setup_entry")
        assert callable(repair.async_setup_entry)

    @pytest.mark.asyncio
    async def test_repair_issue_created_on_unavailable(
        self,
        mock_hass: HomeAssistant,
        mock_config_entry_repair: MagicMock,
        coordinator_repair: TriadCoordinator,
    ) -> None:
        """Test repair issue is created when device becomes unavailable."""
        # This test will fail until repair platform is implemented
        mock_config_entry_repair.runtime_data = coordinator_repair

        # Mock async_create_issue from issue_registry
        with patch(
            "custom_components.triad_ams.repair.issue_registry.async_create_issue"
        ) as mock_create_issue:
            mock_create_issue.return_value = None

            # Make async_create_task actually schedule the coroutine
            created_tasks = []

            def async_create_task(coro):  # noqa: ANN001, ANN202
                task = asyncio.create_task(coro)
                created_tasks.append(task)
                return task

            mock_hass.async_create_task = MagicMock(side_effect=async_create_task)

            # Setup repair platform
            assert repair is not None
            await repair.async_setup_entry(mock_hass, mock_config_entry_repair)

            # Verify listener was registered
            assert len(coordinator_repair._availability_listeners) > 0, (
                "No availability listeners registered"
            )

            # Ensure coordinator starts as available
            coordinator_repair._available = True

            # Simulate device becoming unavailable
            coordinator_repair._available = False
            coordinator_repair._notify_availability_listeners(is_available=False)

            # Wait for all created tasks to complete
            # Need to give a moment for the task to be created
            await asyncio.sleep(0.01)
            if created_tasks:
                await asyncio.gather(*created_tasks, return_exceptions=True)

            # Verify issue was created
            # This will fail until repair platform creates issues
            # Check if async_create_task was called
            assert mock_hass.async_create_task.called, (
                "async_create_task was not called"
            )
            mock_create_issue.assert_called()

    @pytest.mark.asyncio
    async def test_repair_issue_resolved_on_available(
        self,
        mock_hass: HomeAssistant,
        mock_config_entry_repair: MagicMock,
        coordinator_repair: TriadCoordinator,
    ) -> None:
        """Test repair issue is resolved when device becomes available."""
        # This test will fail until repair platform is implemented
        mock_config_entry_repair.runtime_data = coordinator_repair

        # Mock repair functions from issue_registry
        with (
            patch(
                "custom_components.triad_ams.repair.issue_registry.async_create_issue"
            ) as mock_create_issue,
            patch(
                "custom_components.triad_ams.repair.issue_registry.async_delete_issue"
            ) as mock_delete_issue,
        ):
            mock_create_issue.return_value = None
            mock_delete_issue.return_value = None

            # Make async_create_task actually schedule the coroutine
            created_tasks = []

            def async_create_task_side_effect(coro):  # noqa: ANN001, ANN202
                task = asyncio.create_task(coro)
                created_tasks.append(task)
                return task

            mock_hass.async_create_task = MagicMock(
                side_effect=async_create_task_side_effect
            )
            mock_hass.created_tasks = created_tasks

            # Setup repair platform
            assert repair is not None
            await repair.async_setup_entry(mock_hass, mock_config_entry_repair)

            # Verify listener was registered
            assert len(coordinator_repair._availability_listeners) > 0, (
                "No availability listeners registered"
            )

            # Ensure coordinator starts as available
            coordinator_repair._available = True

            # Simulate device becoming unavailable then available
            coordinator_repair._available = False
            coordinator_repair._notify_availability_listeners(is_available=False)
            # Wait for tasks
            if created_tasks:
                await asyncio.gather(*created_tasks, return_exceptions=True)
                created_tasks.clear()

            coordinator_repair._available = True
            coordinator_repair._notify_availability_listeners(is_available=True)
            # Wait for tasks
            if created_tasks:
                await asyncio.gather(*created_tasks, return_exceptions=True)

            # Verify issue was deleted when device became available
            # This will fail until repair platform deletes issues
            assert mock_hass.async_create_task.called, (
                "async_create_task was not called"
            )
            mock_delete_issue.assert_called()
