"""Unit tests for integration setup."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.triad_ams import (
    async_migrate_entry,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.triad_ams.coordinator import TriadCoordinatorConfig
from tests.conftest import create_async_mock_method


@pytest.fixture
def hass() -> MagicMock:
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = create_async_mock_method(
        return_value=True
    )
    hass.config_entries.async_unload_platforms = create_async_mock_method(
        return_value=True
    )
    return hass


@pytest.fixture
def config_entry() -> MagicMock:
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
        "active_inputs": [1, 2],
        "active_outputs": [1],
        "input_links": {},
    }
    entry.title = "Test Triad AMS"
    entry.runtime_data = None
    entry.add_update_listener = MagicMock(return_value=MagicMock())
    return entry


class TestAsyncSetup:
    """Test async_setup function."""

    @pytest.mark.asyncio
    async def test_async_setup_registers_service(self, hass: MagicMock) -> None:
        """Test that async_setup registers the service."""
        with patch(
            "custom_components.triad_ams.service.async_register_platform_entity_service"
        ) as mock_register:
            result = await async_setup(hass, {})

            assert result is True
            mock_register.assert_called_once()
            # Verify service registration
            call_args = mock_register.call_args
            assert call_args[1]["entity_domain"] == "media_player"
            assert call_args[1]["schema"] is not None


class TestAsyncSetupEntry:
    """Test async_setup_entry function."""

    @pytest.mark.asyncio
    async def test_async_setup_entry_creates_coordinator(
        self, hass: MagicMock, config_entry: MagicMock
    ) -> None:
        """Test that async_setup_entry creates coordinator."""
        with patch("custom_components.triad_ams.TriadCoordinator") as mock_coord_class:
            mock_coord = MagicMock()
            mock_coord.start = create_async_mock_method()
            mock_coord_class.return_value = mock_coord

            result = await async_setup_entry(hass, config_entry)

            assert result is True
            expected_config = TriadCoordinatorConfig(
                host="192.168.1.100", port=52000, input_count=8
            )
            mock_coord_class.assert_called_once_with(expected_config)
            assert config_entry.runtime_data == mock_coord
            mock_coord.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_setup_entry_forwards_platforms(
        self, hass: MagicMock, config_entry: MagicMock
    ) -> None:
        """Test that async_setup_entry forwards platform setup."""
        with (
            patch("custom_components.triad_ams.TriadCoordinator") as mock_coord_class,
            patch(
                "custom_components.triad_ams.repairs.async_setup_entry"
            ) as mock_repairs_setup,
        ):
            mock_coord = MagicMock()
            mock_coord.start = create_async_mock_method()
            mock_coord_class.return_value = mock_coord
            mock_repairs_setup.return_value = None

            await async_setup_entry(hass, config_entry)

            # Should be called once for media_player platform
            assert hass.config_entries.async_forward_entry_setups.call_count == 1

            # Check call (media_player platform)
            call_args = hass.config_entries.async_forward_entry_setups.call_args_list[0]
            assert call_args[0][0] == config_entry
            assert "media_player" in call_args[0][1]

            # Verify repairs.async_setup_entry was called directly
            mock_repairs_setup.assert_called_once_with(hass, config_entry)

    @pytest.mark.asyncio
    async def test_async_setup_entry_adds_update_listener(
        self, hass: MagicMock, config_entry: MagicMock
    ) -> None:
        """Test that async_setup_entry adds update listener."""
        with patch("custom_components.triad_ams.TriadCoordinator") as mock_coord_class:
            mock_coord = MagicMock()
            mock_coord.start = create_async_mock_method()
            mock_coord_class.return_value = mock_coord

            await async_setup_entry(hass, config_entry)

            config_entry.add_update_listener.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_setup_entry_handles_start_error(
        self, hass: MagicMock, config_entry: MagicMock
    ) -> None:
        """Test that async_setup_entry handles coordinator start errors."""
        with patch("custom_components.triad_ams.TriadCoordinator") as mock_coord_class:
            mock_coord = MagicMock()
            mock_coord.start = create_async_mock_method(
                side_effect=Exception("Start failed")
            )
            mock_coord_class.return_value = mock_coord

            # Should not raise
            result = await async_setup_entry(hass, config_entry)

            assert result is True


class TestAsyncUnloadEntry:
    """Test async_unload_entry function."""

    @pytest.mark.asyncio
    async def test_async_unload_entry_success(
        self, hass: MagicMock, config_entry: MagicMock
    ) -> None:
        """Test successful unload."""
        mock_coord = MagicMock()
        mock_coord.stop = create_async_mock_method()
        mock_coord.disconnect = create_async_mock_method()
        mock_coord.input_link_unsubs = [MagicMock(), MagicMock()]
        config_entry.runtime_data = mock_coord

        result = await async_unload_entry(hass, config_entry)

        assert result is True
        hass.config_entries.async_unload_platforms.assert_called_once()
        mock_coord.stop.assert_called_once()
        mock_coord.disconnect.assert_called_once()
        # Should clean up input link subscriptions
        for unsub in mock_coord.input_link_unsubs:
            unsub.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_unload_entry_no_unsubs(
        self, hass: MagicMock, config_entry: MagicMock
    ) -> None:
        """Test unload when no input link subscriptions."""
        mock_coord = MagicMock()
        mock_coord.stop = create_async_mock_method()
        mock_coord.disconnect = create_async_mock_method()
        # No _input_link_unsubs attribute
        config_entry.runtime_data = mock_coord

        result = await async_unload_entry(hass, config_entry)

        assert result is True
        # Should not raise AttributeError

    @pytest.mark.asyncio
    async def test_async_unload_entry_handles_stop_error(
        self, hass: MagicMock, config_entry: MagicMock
    ) -> None:
        """Test that unload handles stop errors."""
        mock_coord = MagicMock()
        mock_coord.stop = create_async_mock_method(side_effect=Exception("Stop failed"))
        mock_coord.disconnect = create_async_mock_method()
        config_entry.runtime_data = mock_coord

        # Should not raise
        result = await async_unload_entry(hass, config_entry)

        assert result is True
        mock_coord.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_unload_entry_unload_fails(
        self, hass: MagicMock, config_entry: MagicMock
    ) -> None:
        """Test unload when platform unload fails."""
        hass.config_entries.async_unload_platforms = create_async_mock_method(
            return_value=False
        )
        mock_coord = MagicMock()
        config_entry.runtime_data = mock_coord

        result = await async_unload_entry(hass, config_entry)

        assert result is False
        # Should not stop/disconnect if unload failed
        mock_coord.stop.assert_not_called()


class TestAsyncMigrateEntry:
    """Test async_migrate_entry function."""

    @pytest.mark.asyncio
    async def test_async_migrate_entry_no_migration_needed(
        self, hass: MagicMock, config_entry: MagicMock
    ) -> None:
        """Test migration when not needed."""
        config_entry.minor_version = 4
        config_entry.data = {
            "host": "192.168.1.100",
            "port": 52000,
            "model": "AMS8",
            "input_count": 8,
            "output_count": 8,
        }

        result = await async_migrate_entry(hass, config_entry)

        assert result is True
        hass.config_entries.async_update_entry.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_migrate_entry_adds_model(
        self, hass: MagicMock, config_entry: MagicMock
    ) -> None:
        """Test migration adds model and counts."""
        config_entry.minor_version = 0
        config_entry.data = {
            "host": "192.168.1.100",
            "port": 52000,
        }

        result = await async_migrate_entry(hass, config_entry)

        assert result is True
        hass.config_entries.async_update_entry.assert_called_once()
        call_args = hass.config_entries.async_update_entry.call_args
        new_data = call_args[1]["data"]
        assert "model" in new_data
        assert "input_count" in new_data
        assert "output_count" in new_data
        assert new_data["model"] == "AMS8"
        assert new_data["input_count"] == 8
        assert new_data["output_count"] == 8
        assert call_args[1]["minor_version"] == 4

    @pytest.mark.asyncio
    async def test_async_migrate_entry_preserves_existing(
        self, hass: MagicMock, config_entry: MagicMock
    ) -> None:
        """Test migration preserves existing data."""
        config_entry.minor_version = 0
        config_entry.data = {
            "host": "192.168.1.100",
            "port": 52000,
            "model": "AMS16",  # Already has model
        }

        result = await async_migrate_entry(hass, config_entry)

        assert result is True
        # Should not overwrite existing model
        call_args = hass.config_entries.async_update_entry.call_args
        new_data = call_args[1]["data"]
        assert new_data["model"] == "AMS16"
