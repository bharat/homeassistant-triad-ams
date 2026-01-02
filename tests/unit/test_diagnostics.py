"""Unit tests for diagnostics functionality (Gold requirement)."""

from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.triad_ams.coordinator import TriadCoordinator

# Import will fail until diagnostics.py is created - this is expected
try:
    from custom_components.triad_ams import diagnostics
except ImportError:
    diagnostics = None  # type: ignore[assignment]


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Create a mock config entry."""
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
    entry.runtime_data = None
    return entry


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Create a mock coordinator."""
    coordinator = MagicMock(spec=TriadCoordinator)
    coordinator._host = "192.168.1.100"
    coordinator._port = 52000
    coordinator.input_count = 8
    coordinator.is_available = True
    return coordinator


class TestDiagnostics:
    """Test diagnostics functionality (Gold requirement)."""

    @pytest.mark.asyncio
    async def test_diagnostics_function_exists(
        self, mock_hass: HomeAssistant, mock_config_entry: MagicMock
    ) -> None:
        """Test that async_get_config_entry_diagnostics function exists."""
        # This test will fail until diagnostics.py is created
        assert diagnostics is not None
        assert hasattr(diagnostics, "async_get_config_entry_diagnostics")
        assert callable(diagnostics.async_get_config_entry_diagnostics)

    @pytest.mark.asyncio
    async def test_diagnostics_returns_config_entry_data(
        self,
        mock_hass: HomeAssistant,
        mock_config_entry: MagicMock,
        mock_coordinator: MagicMock,
    ) -> None:
        """Test diagnostics returns config entry data."""
        mock_config_entry.runtime_data = mock_coordinator
        # This test will fail until diagnostics.py is implemented
        assert diagnostics is not None
        result = await diagnostics.async_get_config_entry_diagnostics(
            mock_hass, mock_config_entry
        )

        assert "config_entry" in result
        assert result["config_entry"]["title"] == "Test Triad AMS"
        # Host should be excluded from data for security
        assert "host" not in result["config_entry"].get("data", {})

    @pytest.mark.asyncio
    async def test_diagnostics_returns_coordinator_state(
        self,
        mock_hass: HomeAssistant,
        mock_config_entry: MagicMock,
        mock_coordinator: MagicMock,
    ) -> None:
        """Test diagnostics returns coordinator state."""
        mock_config_entry.runtime_data = mock_coordinator
        # This test will fail until diagnostics.py is implemented
        assert diagnostics is not None
        result = await diagnostics.async_get_config_entry_diagnostics(
            mock_hass, mock_config_entry
        )

        assert "coordinator" in result
        assert result["coordinator"]["host"] == "192.168.1.100"
        assert result["coordinator"]["port"] == 52000
        assert result["coordinator"]["input_count"] == 8
        assert result["coordinator"]["available"] is True

    @pytest.mark.asyncio
    async def test_diagnostics_handles_missing_coordinator(
        self, mock_hass: HomeAssistant, mock_config_entry: MagicMock
    ) -> None:
        """Test diagnostics handles missing coordinator gracefully."""
        mock_config_entry.runtime_data = None
        # This test will fail until diagnostics.py is implemented
        assert diagnostics is not None
        result = await diagnostics.async_get_config_entry_diagnostics(
            mock_hass, mock_config_entry
        )

        # Should still return config_entry data even if coordinator is missing
        assert "config_entry" in result
