"""Entity lifecycle and cleanup tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

import custom_components.triad_ams as triad_ams_module
from custom_components.triad_ams.coordinator import TriadCoordinator
from custom_components.triad_ams.media_player import (
    _cleanup_stale_entities,
    _remove_orphaned_devices,
)
from custom_components.triad_ams.models import TriadAmsOutput
from tests.integration.simulator import TriadAmsSimulator


@pytest.mark.integration
class TestEntityLifecycle:
    """Test entity lifecycle management."""

    @pytest.mark.asyncio
    async def test_entity_creation_and_registration(
        self,
        simulator_fixture: tuple[TriadAmsSimulator, str, int],
        coordinator_fixture: TriadCoordinator,
        input_names: dict[int, str],
    ) -> None:
        """Test that entities are created and registered."""
        simulator, _host, _port = simulator_fixture
        coordinator = coordinator_fixture

        outputs = []
        for i in [1, 2]:
            output = TriadAmsOutput(i, f"Output {i}", coordinator, outputs, input_names)
            outputs.append(output)
            coordinator.register_output(output)

        # Verify outputs are registered
        assert len(list(coordinator._outputs)) == 2

        # Verify outputs can be controlled
        await outputs[0].set_volume(0.5)
        assert abs(simulator.get_volume(1) - 0.5) < 0.1

    @pytest.mark.asyncio
    async def test_entity_listener_management(
        self, output_fixture: TriadAmsOutput
    ) -> None:
        """Test that entity listeners are properly managed."""
        output = output_fixture

        # Add listener
        listener_called = False

        def listener() -> None:
            nonlocal listener_called
            listener_called = True

        unsub = output.add_listener(listener)

        # Trigger notification
        await output.refresh_and_notify()
        assert listener_called

        # Remove listener
        unsub()
        listener_called = False
        await output.refresh_and_notify()
        assert not listener_called

    @pytest.mark.asyncio
    async def test_output_refresh_updates_state(
        self, output_fixture: TriadAmsOutput
    ) -> None:
        """Test that refresh updates output state from device."""
        output = output_fixture

        # Set state via commands
        await output.set_volume(0.6)
        await output.set_muted(muted=True)
        await output.set_source(2)

        # Clear local state
        output._volume = None
        output._muted = False
        output._assigned_input = None

        # Refresh should restore state
        await output.refresh()
        assert abs(output.volume - 0.6) < 0.1
        assert output.muted is True
        assert output.source == 2

    @pytest.mark.asyncio
    async def test_output_refresh_handles_audio_off(
        self, output_fixture: TriadAmsOutput
    ) -> None:
        """Test that refresh handles audio off state."""
        output = output_fixture

        # Set source then disconnect
        await output.set_source(2)
        await output.turn_off()

        # Refresh should show off state
        await output.refresh()
        assert output.source is None
        assert output.is_on is False


class TestEntityCleanup:
    """Test entity cleanup functions."""

    def test_cleanup_stale_entities(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test cleanup of stale entities."""
        # Create mock entity registry
        registry = MagicMock(spec=er.EntityRegistry)
        # Create mock entities
        entity1 = MagicMock()
        entity1.platform = "triad_ams"
        entity1.config_entry_id = "test_entry_123"
        entity1.unique_id = "test_entry_123_output_1"
        entity1.entity_id = "media_player.test_output_1"

        entity2 = MagicMock()
        entity2.platform = "triad_ams"
        entity2.config_entry_id = "test_entry_123"
        entity2.unique_id = "test_entry_123_output_99"  # Stale
        entity2.entity_id = "media_player.test_output_99"

        registry.entities = {
            "media_player.test_output_1": entity1,
            "media_player.test_output_99": entity2,
        }

        # Create outputs (only output 1 is active)
        outputs = [MagicMock()]
        outputs[0].number = 1

        # Use registry injection instead of patching
        _cleanup_stale_entities(
            mock_hass,
            mock_config_entry,
            outputs,
            entity_registry_getter=lambda _: registry,
        )

        # Should remove stale entity
        registry.async_remove.assert_called_once_with("media_player.test_output_99")

    def test_remove_orphaned_devices(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test removal of orphaned devices."""
        # Create mock registries
        entity_registry = MagicMock(spec=er.EntityRegistry)
        device_registry = MagicMock(spec=dr.DeviceRegistry)
        # Create mock device
        device = MagicMock()
        device.id = "device_123"
        device.config_entries = {"test_entry_123"}

        device_registry.devices = {"device_123": device}

        # Use registry injection instead of patching
        _remove_orphaned_devices(
            mock_hass,
            mock_config_entry,
            entity_registry_getter=lambda _: entity_registry,
            device_registry_getter=lambda _: device_registry,
            entries_for_device_getter=lambda _registry, _device_id, **_: [],
        )

        # Should remove orphaned device
        device_registry.async_remove_device.assert_called_once_with("device_123")

    def test_remove_orphaned_devices_with_entities(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test that devices with entities are not removed."""
        # Create mock registries
        entity_registry = MagicMock(spec=er.EntityRegistry)
        device_registry = MagicMock(spec=dr.DeviceRegistry)
        # Create mock device
        device = MagicMock()
        device.id = "device_123"
        device.config_entries = {"test_entry_123"}

        device_registry.devices = {"device_123": device}

        # Use registry injection instead of patching
        _remove_orphaned_devices(
            mock_hass,
            mock_config_entry,
            entity_registry_getter=lambda _: entity_registry,
            device_registry_getter=lambda _: device_registry,
            entries_for_device_getter=lambda _registry, _device_id, **_: [MagicMock()],
        )

        # Should not remove device with entities
        device_registry.async_remove_device.assert_not_called()


class TestOptionsUpdate:
    """Test options update handling."""

    @pytest.mark.asyncio
    async def test_options_update_reloads_entry(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test that options update triggers reload."""
        mock_hass.config_entries.async_reload = AsyncMock()

        # Simulate update listener
        await triad_ams_module._update_listener(mock_hass, mock_config_entry)

        mock_hass.config_entries.async_reload.assert_called_once_with("test_entry_123")
