"""Entity lifecycle and cleanup tests."""

import asyncio
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

import custom_components.triad_ams as triad_ams_module
from custom_components.triad_ams.coordinator import TriadCoordinator
from custom_components.triad_ams.media_player import (
    _cleanup_stale_entities,
    _remove_orphaned_devices,
)
from custom_components.triad_ams.models import TriadAmsOutput
from tests.integration.simulator import triad_ams_simulator


@pytest.fixture
def mock_hass() -> MagicMock:
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    hass.async_create_task = MagicMock()
    # Add helpers attribute for entity/device registry access
    hass.helpers = MagicMock()
    # Add data attribute for registry singleton storage
    hass.data = {}
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
    entry.runtime_data = None
    entry.add_update_listener = MagicMock(return_value=MagicMock())
    return entry


@pytest.mark.integration
class TestEntityLifecycle:
    """Test entity lifecycle management."""

    @pytest.mark.asyncio
    async def test_entity_creation_and_registration(self) -> None:
        """Test that entities are created and registered."""
        async with triad_ams_simulator() as (simulator, host, port):
            coordinator = TriadCoordinator(
                host, port, 8, min_send_interval=0.01, poll_interval=1.0
            )
            await coordinator.start()

            try:
                input_names = {i: f"Input {i}" for i in range(1, 9)}
                outputs = []
                for i in [1, 2]:
                    output = TriadAmsOutput(
                        i, f"Output {i}", coordinator, outputs, input_names
                    )
                    outputs.append(output)
                    coordinator.register_output(output)

                # Verify outputs are registered
                assert len(list(coordinator._outputs)) == 2

                # Verify outputs can be controlled
                await outputs[0].set_volume(0.5)
                await asyncio.sleep(0.1)
                assert abs(simulator.get_volume(1) - 0.5) < 0.1

            finally:
                await coordinator.stop()
                await coordinator.disconnect()

    @pytest.mark.asyncio
    async def test_entity_listener_management(self) -> None:
        """Test that entity listeners are properly managed."""
        async with triad_ams_simulator() as (_simulator, host, port):
            coordinator = TriadCoordinator(
                host, port, 8, min_send_interval=0.01, poll_interval=1.0
            )
            await coordinator.start()

            try:
                input_names = {i: f"Input {i}" for i in range(1, 9)}
                output = TriadAmsOutput(1, "Output 1", coordinator, None, input_names)

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

            finally:
                await coordinator.stop()
                await coordinator.disconnect()

    @pytest.mark.asyncio
    async def test_output_refresh_updates_state(self) -> None:
        """Test that refresh updates output state from device."""
        async with triad_ams_simulator() as (_simulator, host, port):
            coordinator = TriadCoordinator(
                host, port, 8, min_send_interval=0.01, poll_interval=1.0
            )
            await coordinator.start()

            try:
                input_names = {i: f"Input {i}" for i in range(1, 9)}
                output = TriadAmsOutput(1, "Output 1", coordinator, None, input_names)

                # Set state via commands
                await output.set_volume(0.6)
                await output.set_muted(muted=True)
                await output.set_source(2)
                await asyncio.sleep(0.1)

                # Clear local state
                output._volume = None
                output._muted = False
                output._assigned_input = None

                # Refresh should restore state
                await output.refresh()
                assert abs(output.volume - 0.6) < 0.1
                assert output.muted is True
                assert output.source == 2

            finally:
                await coordinator.stop()
                await coordinator.disconnect()

    @pytest.mark.asyncio
    async def test_output_refresh_handles_audio_off(self) -> None:
        """Test that refresh handles audio off state."""
        async with triad_ams_simulator() as (_simulator, host, port):
            coordinator = TriadCoordinator(
                host, port, 8, min_send_interval=0.01, poll_interval=1.0
            )
            await coordinator.start()

            try:
                input_names = {i: f"Input {i}" for i in range(1, 9)}
                output = TriadAmsOutput(1, "Output 1", coordinator, None, input_names)

                # Set source then disconnect
                await output.set_source(2)
                await asyncio.sleep(0.1)
                await output.turn_off()
                await asyncio.sleep(0.1)

                # Refresh should show off state
                await output.refresh()
                assert output.source is None
                assert output.is_on is False

            finally:
                await coordinator.stop()
                await coordinator.disconnect()


class TestEntityCleanup:
    """Test entity cleanup functions."""

    def test_cleanup_stale_entities(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test cleanup of stale entities."""
        # Create mock entity registry
        registry = MagicMock(spec=er.EntityRegistry)
        # Patch er.async_get to return our mock registry
        with mock.patch(
            "custom_components.triad_ams.media_player.er.async_get",
            return_value=registry,
        ):
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

            _cleanup_stale_entities(mock_hass, mock_config_entry, outputs)

            # Should remove stale entity
            registry.async_remove.assert_called_once_with("media_player.test_output_99")

    def test_remove_orphaned_devices(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test removal of orphaned devices."""
        # Create mock registries
        entity_registry = MagicMock(spec=er.EntityRegistry)
        device_registry = MagicMock(spec=dr.DeviceRegistry)
        # Patch registry getters to return our mocks
        with (
            mock.patch(
                "custom_components.triad_ams.media_player.er.async_get",
                return_value=entity_registry,
            ),
            mock.patch(
                "custom_components.triad_ams.media_player.dr.async_get",
                return_value=device_registry,
            ),
            mock.patch(
                "custom_components.triad_ams.media_player.er.async_entries_for_device",
                return_value=[],
            ),
        ):
            # Create mock device
            device = MagicMock()
            device.id = "device_123"
            device.config_entries = {"test_entry_123"}

            device_registry.devices = {"device_123": device}

            _remove_orphaned_devices(mock_hass, mock_config_entry)

            # Should remove orphaned device
            device_registry.async_remove_device.assert_called_once_with("device_123")

    def test_remove_orphaned_devices_with_entities(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test that devices with entities are not removed."""
        # Create mock registries
        entity_registry = MagicMock(spec=er.EntityRegistry)
        device_registry = MagicMock(spec=dr.DeviceRegistry)
        # Patch registry getters to return our mocks
        with (
            mock.patch(
                "custom_components.triad_ams.media_player.er.async_get",
                return_value=entity_registry,
            ),
            mock.patch(
                "custom_components.triad_ams.media_player.dr.async_get",
                return_value=device_registry,
            ),
            mock.patch(
                "custom_components.triad_ams.media_player.er.async_entries_for_device",
                return_value=[MagicMock()],
            ),
        ):
            # Create mock device
            device = MagicMock()
            device.id = "device_123"
            device.config_entries = {"test_entry_123"}

            device_registry.devices = {"device_123": device}

            _remove_orphaned_devices(mock_hass, mock_config_entry)

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
