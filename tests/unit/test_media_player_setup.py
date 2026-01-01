"""Unit tests for media_player setup and utility functions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.triad_ams.media_player import (
    TriadAmsMediaPlayer,
    _build_input_names,
    _cleanup_stale_entities,
    _create_input_link_handler,
    _remove_orphaned_devices,
    _setup_input_link_subscriptions,
    _update_input_name_from_state,
    async_setup_entry,
)
from custom_components.triad_ams.models import TriadAmsOutput


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
    entry.title = "Test Triad AMS"
    entry.data = {"host": "192.168.1.100", "port": 52000}
    entry.options = {
        "active_inputs": [1, 2, 3],
        "active_outputs": [1, 2],
        "input_links": {},
    }
    entry.runtime_data = None
    return entry


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Create a mock coordinator."""
    coordinator = MagicMock()
    coordinator.start = AsyncMock()
    coordinator.register_output = MagicMock()
    return coordinator


@pytest.fixture
def mock_async_add_entities() -> MagicMock:
    """Create a mock async_add_entities callback."""
    return MagicMock()


class TestBuildInputNames:
    """Test _build_input_names function."""

    def test_build_input_names_default(self, mock_hass: MagicMock) -> None:
        """Test building input names with defaults."""
        active_inputs = [1, 2, 3]
        input_links_opt = {}

        result = _build_input_names(mock_hass, active_inputs, input_links_opt)

        assert result == {1: "Input 1", 2: "Input 2", 3: "Input 3"}

    def test_build_input_names_with_linked_entity(self, mock_hass: MagicMock) -> None:
        """Test building input names with linked entity."""
        active_inputs = [1, 2]
        input_links_opt = {"1": "media_player.input1"}

        mock_state = MagicMock()
        mock_state.name = "Custom Input Name"
        mock_hass.states.get = MagicMock(return_value=mock_state)

        result = _build_input_names(mock_hass, active_inputs, input_links_opt)

        assert result[1] == "Custom Input Name"
        assert result[2] == "Input 2"

    def test_build_input_names_linked_entity_not_found(
        self, mock_hass: MagicMock
    ) -> None:
        """Test building input names when linked entity doesn't exist."""
        active_inputs = [1, 2]
        input_links_opt = {"1": "media_player.input1"}

        mock_hass.states.get = MagicMock(return_value=None)

        result = _build_input_names(mock_hass, active_inputs, input_links_opt)

        assert result[1] == "Input 1"
        assert result[2] == "Input 2"


class TestUpdateInputNameFromState:
    """Test _update_input_name_from_state function."""

    def test_update_input_name_changes_name(self, mock_hass: MagicMock) -> None:
        """Test updating input name when state changes."""
        input_names = {1: "Input 1", 2: "Input 2"}
        entities = [MagicMock(), MagicMock()]
        for entity in entities:
            entity.async_write_ha_state = MagicMock()

        mock_state = MagicMock()
        mock_state.name = "New Input Name"
        mock_hass.states.get = MagicMock(return_value=mock_state)

        _update_input_name_from_state(
            mock_hass, 1, "media_player.input1", input_names, entities
        )

        assert input_names[1] == "New Input Name"
        for entity in entities:
            entity.async_write_ha_state.assert_called_once()

    def test_update_input_name_no_change(self, mock_hass: MagicMock) -> None:
        """Test updating input name when name doesn't change."""
        input_names = {1: "Input 1"}
        entities = [MagicMock()]
        entities[0].async_write_ha_state = MagicMock()

        mock_state = MagicMock()
        mock_state.name = "Input 1"  # Same name
        mock_hass.states.get = MagicMock(return_value=mock_state)

        _update_input_name_from_state(
            mock_hass, 1, "media_player.input1", input_names, entities
        )

        # Should not call async_write_ha_state
        entities[0].async_write_ha_state.assert_not_called()

    def test_update_input_name_no_state(self, mock_hass: MagicMock) -> None:
        """Test updating input name when state is None."""
        input_names = {1: "Input 1"}
        entities = [MagicMock()]
        entities[0].async_write_ha_state = MagicMock()

        mock_hass.states.get = MagicMock(return_value=None)

        _update_input_name_from_state(
            mock_hass, 1, "media_player.input1", input_names, entities
        )

        # Should not change name or call async_write_ha_state
        assert input_names[1] == "Input 1"
        entities[0].async_write_ha_state.assert_not_called()


class TestCreateInputLinkHandler:
    """Test _create_input_link_handler function."""

    def test_handle_input_link_state_change_valid(self, mock_hass: MagicMock) -> None:
        """Test handling valid input link state change."""
        input_links_opt = {"1": "media_player.input1", "2": "media_player.input2"}
        active_inputs = [1, 2]
        input_names = {1: "Input 1", 2: "Input 2"}
        entities = [MagicMock()]
        entities[0].async_write_ha_state = MagicMock()

        handler = _create_input_link_handler(
            mock_hass, input_links_opt, active_inputs, input_names, entities
        )

        mock_event = MagicMock()
        mock_event.data = {"entity_id": "media_player.input1"}

        mock_state = MagicMock()
        mock_state.name = "Updated Name"
        mock_hass.states.get = MagicMock(return_value=mock_state)

        handler(mock_event)

        assert input_names[1] == "Updated Name"
        entities[0].async_write_ha_state.assert_called_once()

    def test_handle_input_link_state_change_no_entity_id(
        self, mock_hass: MagicMock
    ) -> None:
        """Test handling state change with no entity_id."""
        input_links_opt = {"1": "media_player.input1"}
        active_inputs = [1]
        input_names = {1: "Input 1"}
        entities = [MagicMock()]

        handler = _create_input_link_handler(
            mock_hass, input_links_opt, active_inputs, input_names, entities
        )

        mock_event = MagicMock()
        mock_event.data = {}  # No entity_id

        handler(mock_event)

        # Should not update anything
        assert input_names[1] == "Input 1"

    def test_handle_input_link_state_change_unknown_entity(
        self, mock_hass: MagicMock
    ) -> None:
        """Test handling state change for unknown entity."""
        input_links_opt = {"1": "media_player.input1"}
        active_inputs = [1]
        input_names = {1: "Input 1"}
        entities = [MagicMock()]

        handler = _create_input_link_handler(
            mock_hass, input_links_opt, active_inputs, input_names, entities
        )

        mock_event = MagicMock()
        mock_event.data = {"entity_id": "media_player.unknown"}

        handler(mock_event)

        # Should not update anything
        assert input_names[1] == "Input 1"

    def test_handle_input_link_state_change_inactive_input(
        self, mock_hass: MagicMock
    ) -> None:
        """Test handling state change for inactive input."""
        input_links_opt = {"1": "media_player.input1"}
        active_inputs = [2]  # Input 1 is not active
        input_names = {2: "Input 2"}
        entities = [MagicMock()]

        handler = _create_input_link_handler(
            mock_hass, input_links_opt, active_inputs, input_names, entities
        )

        mock_event = MagicMock()
        mock_event.data = {"entity_id": "media_player.input1"}

        handler(mock_event)

        # Should not update anything
        assert 1 not in input_names


class TestSetupInputLinkSubscriptions:
    """Test _setup_input_link_subscriptions function."""

    @pytest.mark.asyncio
    async def test_setup_input_link_subscriptions_no_links(
        self, mock_hass: MagicMock, mock_coordinator: MagicMock
    ) -> None:
        """Test setting up subscriptions with no input links."""
        input_links_opt = {}
        active_inputs = [1, 2]
        input_names = {1: "Input 1", 2: "Input 2"}
        entities = []

        # Ensure coordinator doesn't have the attribute initially
        if hasattr(mock_coordinator, "_input_link_unsubs"):
            delattr(mock_coordinator, "_input_link_unsubs")

        _setup_input_link_subscriptions(
            mock_hass,
            mock_coordinator,
            input_links_opt,
            active_inputs,
            input_names,
            entities,
        )

        # Should not create any subscriptions (early return before creating attribute)
        # MagicMock will auto-create attributes, so we check it wasn't set to a list
        if hasattr(mock_coordinator, "_input_link_unsubs"):
            # If it exists, it should be empty or not a list
            unsubs = getattr(mock_coordinator, "_input_link_unsubs", None)
            # The function returns early, so this shouldn't be a list
            assert not isinstance(unsubs, list) or len(unsubs) == 0

    @pytest.mark.asyncio
    async def test_setup_input_link_subscriptions_with_links(
        self, mock_hass: MagicMock, mock_coordinator: MagicMock
    ) -> None:
        """Test setting up subscriptions with input links."""
        input_links_opt = {"1": "media_player.input1", "2": "media_player.input2"}
        active_inputs = [1, 2]
        input_names = {1: "Input 1", 2: "Input 2"}
        entities = [MagicMock()]

        # Initialize the attribute as a list
        mock_coordinator._input_link_unsubs = []

        mock_unsub = MagicMock()
        with patch(
            "custom_components.triad_ams.media_player.async_track_state_change_event",
            return_value=mock_unsub,
        ):
            _setup_input_link_subscriptions(
                mock_hass,
                mock_coordinator,
                input_links_opt,
                active_inputs,
                input_names,
                entities,
            )

            assert hasattr(mock_coordinator, "_input_link_unsubs")
            assert len(mock_coordinator._input_link_unsubs) == 1

    @pytest.mark.asyncio
    async def test_setup_input_link_subscriptions_updates_existing_names(
        self, mock_hass: MagicMock, mock_coordinator: MagicMock
    ) -> None:
        """Test that setup updates names for entities that already exist."""
        input_links_opt = {"1": "media_player.input1"}
        active_inputs = [1]
        input_names = {1: "Input 1"}  # Default name
        entities = [MagicMock()]
        entities[0].async_write_ha_state = MagicMock()

        mock_state = MagicMock()
        mock_state.name = "Custom Name"
        mock_hass.states.get = MagicMock(return_value=mock_state)

        mock_unsub = MagicMock()
        with patch(
            "custom_components.triad_ams.media_player.async_track_state_change_event",
            return_value=mock_unsub,
        ):
            _setup_input_link_subscriptions(
                mock_hass,
                mock_coordinator,
                input_links_opt,
                active_inputs,
                input_names,
                entities,
            )

            # Should update the name
            assert input_names[1] == "Custom Name"


class TestCleanupStaleEntities:
    """Test _cleanup_stale_entities function."""

    def test_cleanup_stale_entities_removes_stale(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test removing stale entities."""
        outputs = [
            MagicMock(spec=TriadAmsOutput, number=1),
            MagicMock(spec=TriadAmsOutput, number=2),
        ]

        mock_registry = MagicMock(spec=er.EntityRegistry)
        mock_entity = MagicMock()
        mock_entity.platform = "triad_ams"
        mock_entity.config_entry_id = "test_entry_123"
        mock_entity.unique_id = "test_entry_123_output_3"  # Stale
        mock_entity.entity_id = "media_player.triad_ams_output_3"
        mock_registry.entities = {"test_entry_123_output_3": mock_entity}
        mock_registry.async_remove = MagicMock()

        def get_registry(_hass: HomeAssistant) -> er.EntityRegistry:
            return mock_registry

        _cleanup_stale_entities(
            mock_hass, mock_config_entry, outputs, entity_registry_getter=get_registry
        )

        mock_registry.async_remove.assert_called_once_with(
            "media_player.triad_ams_output_3"
        )

    def test_cleanup_stale_entities_keeps_active(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test that active entities are not removed."""
        outputs = [
            MagicMock(spec=TriadAmsOutput, number=1),
            MagicMock(spec=TriadAmsOutput, number=2),
        ]

        mock_registry = MagicMock(spec=er.EntityRegistry)
        mock_entity = MagicMock()
        mock_entity.platform = "triad_ams"
        mock_entity.config_entry_id = "test_entry_123"
        mock_entity.unique_id = "test_entry_123_output_1"  # Active
        mock_entity.entity_id = "media_player.triad_ams_output_1"
        mock_registry.entities = {"test_entry_123_output_1": mock_entity}
        mock_registry.async_remove = MagicMock()

        def get_registry(_hass: HomeAssistant) -> er.EntityRegistry:
            return mock_registry

        _cleanup_stale_entities(
            mock_hass, mock_config_entry, outputs, entity_registry_getter=get_registry
        )

        mock_registry.async_remove.assert_not_called()

    def test_cleanup_stale_entities_different_platform(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test that entities from other platforms are not removed."""
        outputs = [MagicMock(spec=TriadAmsOutput, number=1)]

        mock_registry = MagicMock(spec=er.EntityRegistry)
        mock_entity = MagicMock()
        mock_entity.platform = "other_platform"
        mock_entity.config_entry_id = "test_entry_123"
        mock_entity.unique_id = "test_entry_123_output_1"
        mock_registry.entities = {"test_entry_123_output_1": mock_entity}
        mock_registry.async_remove = MagicMock()

        def get_registry(_hass: HomeAssistant) -> er.EntityRegistry:
            return mock_registry

        _cleanup_stale_entities(
            mock_hass, mock_config_entry, outputs, entity_registry_getter=get_registry
        )

        mock_registry.async_remove.assert_not_called()


class TestRemoveOrphanedDevices:
    """Test _remove_orphaned_devices function."""

    def test_remove_orphaned_devices_removes_orphan(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test removing orphaned devices."""
        mock_entity_registry = MagicMock(spec=er.EntityRegistry)
        mock_device_registry = MagicMock(spec=dr.DeviceRegistry)

        mock_device = MagicMock()
        mock_device.id = "device_123"
        mock_device.config_entries = {"test_entry_123"}
        mock_device_registry.devices = {"device_123": mock_device}
        mock_device_registry.async_remove_device = MagicMock()

        # No entities for this device
        mock_entity_registry.async_entries_for_device = MagicMock(return_value=[])

        def get_entity_registry(_hass: HomeAssistant) -> er.EntityRegistry:
            return mock_entity_registry

        def get_device_registry(_hass: HomeAssistant) -> dr.DeviceRegistry:
            return mock_device_registry

        def get_entries_for_device(
            _registry: er.EntityRegistry,
            device_id: str,
            *,
            include_disabled_entities: bool,
        ) -> list:
            return mock_entity_registry.async_entries_for_device(
                device_id, include_disabled_entities
            )

        _remove_orphaned_devices(
            mock_hass,
            mock_config_entry,
            entity_registry_getter=get_entity_registry,
            device_registry_getter=get_device_registry,
            entries_for_device_getter=get_entries_for_device,
        )

        mock_device_registry.async_remove_device.assert_called_once_with("device_123")

    def test_remove_orphaned_devices_keeps_device_with_entities(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test that devices with entities are not removed."""
        mock_entity_registry = MagicMock(spec=er.EntityRegistry)
        mock_device_registry = MagicMock(spec=dr.DeviceRegistry)

        mock_device = MagicMock()
        mock_device.id = "device_123"
        mock_device.config_entries = {"test_entry_123"}
        mock_device_registry.devices = {"device_123": mock_device}
        mock_device_registry.async_remove_device = MagicMock()

        # Has entities
        mock_entity = MagicMock()
        mock_entity_registry.async_entries_for_device = MagicMock(
            return_value=[mock_entity]
        )

        def get_entity_registry(_hass: HomeAssistant) -> er.EntityRegistry:
            return mock_entity_registry

        def get_device_registry(_hass: HomeAssistant) -> dr.DeviceRegistry:
            return mock_device_registry

        def get_entries_for_device(
            _registry: er.EntityRegistry,
            device_id: str,
            *,
            include_disabled_entities: bool,
        ) -> list:
            return mock_entity_registry.async_entries_for_device(
                device_id, include_disabled_entities
            )

        _remove_orphaned_devices(
            mock_hass,
            mock_config_entry,
            entity_registry_getter=get_entity_registry,
            device_registry_getter=get_device_registry,
            entries_for_device_getter=get_entries_for_device,
        )

        mock_device_registry.async_remove_device.assert_not_called()

    def test_remove_orphaned_devices_different_entry(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test that devices from other entries are not removed."""
        mock_entity_registry = MagicMock(spec=er.EntityRegistry)
        mock_device_registry = MagicMock(spec=dr.DeviceRegistry)

        mock_device = MagicMock()
        mock_device.id = "device_123"
        mock_device.config_entries = {"other_entry"}  # Different entry
        mock_device_registry.devices = {"device_123": mock_device}
        mock_device_registry.async_remove_device = MagicMock()

        def get_entity_registry(_hass: HomeAssistant) -> er.EntityRegistry:
            return mock_entity_registry

        def get_device_registry(_hass: HomeAssistant) -> dr.DeviceRegistry:
            return mock_device_registry

        _remove_orphaned_devices(
            mock_hass,
            mock_config_entry,
            entity_registry_getter=get_entity_registry,
            device_registry_getter=get_device_registry,
        )

        mock_device_registry.async_remove_device.assert_not_called()


class TestAsyncSetupEntry:
    """Test async_setup_entry function."""

    @pytest.mark.asyncio
    async def test_async_setup_entry_creates_entities(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_coordinator: MagicMock,
        mock_async_add_entities: MagicMock,
    ) -> None:
        """Test that async_setup_entry creates entities."""
        mock_config_entry.runtime_data = mock_coordinator
        mock_config_entry.options = {
            "active_inputs": [1, 2],
            "active_outputs": [1, 2],
            "input_links": {},
        }

        mock_registry = MagicMock(spec=er.EntityRegistry)
        mock_registry.entities = {}
        mock_registry.async_remove = MagicMock()

        mock_device_registry = MagicMock(spec=dr.DeviceRegistry)
        mock_device_registry.devices = {}

        def get_entity_registry(_hass: HomeAssistant) -> er.EntityRegistry:
            return mock_registry

        def get_device_registry(_hass: HomeAssistant) -> dr.DeviceRegistry:
            return mock_device_registry

        def get_entries_for_device(
            _registry: er.EntityRegistry,
            _device_id: str,
            *,
            _include_disabled_entities: bool,
        ) -> list:
            return []

        with patch(
            "custom_components.triad_ams.media_player.TriadAmsOutput"
        ) as mock_output_class:
            mock_output1 = MagicMock(spec=TriadAmsOutput)
            mock_output1.number = 1
            mock_output2 = MagicMock(spec=TriadAmsOutput)
            mock_output2.number = 2
            mock_output_class.side_effect = [mock_output1, mock_output2]

            with (
                patch(
                    "custom_components.triad_ams.media_player._cleanup_stale_entities"
                ) as mock_cleanup,
                patch(
                    "custom_components.triad_ams.media_player._remove_orphaned_devices"
                ) as mock_remove,
            ):
                await async_setup_entry(
                    mock_hass, mock_config_entry, mock_async_add_entities
                )

                # Should create 2 outputs
                assert mock_output_class.call_count == 2
                # Should register outputs
                assert mock_coordinator.register_output.call_count == 2
                # Should add entities
                mock_async_add_entities.assert_called_once()
                call_args = mock_async_add_entities.call_args[0][0]
                assert len(call_args) == 2
                assert all(isinstance(e, TriadAmsMediaPlayer) for e in call_args)
                # Should call cleanup
                mock_cleanup.assert_called_once()
                mock_remove.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_setup_entry_with_input_links(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_coordinator: MagicMock,
        mock_async_add_entities: MagicMock,
    ) -> None:
        """Test async_setup_entry with input links."""
        mock_config_entry.runtime_data = mock_coordinator
        mock_config_entry.options = {
            "active_inputs": [1, 2],
            "active_outputs": [1],
            "input_links": {"1": "media_player.input1"},
        }

        mock_state = MagicMock()
        mock_state.name = "Custom Input"
        mock_hass.states.get = MagicMock(return_value=mock_state)

        mock_registry = MagicMock(spec=er.EntityRegistry)
        mock_registry.entities = {}

        mock_device_registry = MagicMock(spec=dr.DeviceRegistry)
        mock_device_registry.devices = {}

        with patch(
            "custom_components.triad_ams.media_player.TriadAmsOutput"
        ) as mock_output_class:
            mock_output = MagicMock(spec=TriadAmsOutput)
            mock_output.number = 1
            mock_output_class.return_value = mock_output

            with (
                patch(
                    "custom_components.triad_ams.media_player._setup_input_link_subscriptions"
                ) as mock_setup_links,
                patch(
                    "custom_components.triad_ams.media_player._cleanup_stale_entities"
                ),
                patch(
                    "custom_components.triad_ams.media_player._remove_orphaned_devices"
                ),
            ):
                await async_setup_entry(
                    mock_hass, mock_config_entry, mock_async_add_entities
                )

                # Should set up input link subscriptions
                mock_setup_links.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_setup_entry_handles_coordinator_start_error(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_coordinator: MagicMock,
        mock_async_add_entities: MagicMock,
    ) -> None:
        """Test that async_setup_entry handles coordinator start errors."""
        mock_config_entry.runtime_data = mock_coordinator
        mock_config_entry.options = {
            "active_inputs": [1],
            "active_outputs": [1],
            "input_links": {},
        }
        mock_coordinator.start.side_effect = Exception("Start failed")

        with patch(
            "custom_components.triad_ams.media_player.TriadAmsOutput"
        ) as mock_output_class:
            mock_output = MagicMock(spec=TriadAmsOutput)
            mock_output.number = 1
            mock_output_class.return_value = mock_output

            with (
                patch(
                    "custom_components.triad_ams.media_player._cleanup_stale_entities"
                ),
                patch(
                    "custom_components.triad_ams.media_player._remove_orphaned_devices"
                ),
            ):
                # Should not raise
                await async_setup_entry(
                    mock_hass, mock_config_entry, mock_async_add_entities
                )

                # Should still create entities
                mock_async_add_entities.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_setup_entry_calls_cleanup(
        self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_coordinator: MagicMock,
        mock_async_add_entities: MagicMock,
    ) -> None:
        """Test that async_setup_entry calls cleanup functions."""
        mock_config_entry.runtime_data = mock_coordinator
        mock_config_entry.options = {
            "active_inputs": [1],
            "active_outputs": [1],
            "input_links": {},
        }

        with patch(
            "custom_components.triad_ams.media_player.TriadAmsOutput"
        ) as mock_output_class:
            mock_output = MagicMock(spec=TriadAmsOutput)
            mock_output.number = 1
            mock_output_class.return_value = mock_output

            with (
                patch(
                    "custom_components.triad_ams.media_player._cleanup_stale_entities"
                ) as mock_cleanup,
                patch(
                    "custom_components.triad_ams.media_player._remove_orphaned_devices"
                ) as mock_remove_devices,
            ):
                await async_setup_entry(
                    mock_hass, mock_config_entry, mock_async_add_entities
                )

                # Should call cleanup functions
                mock_cleanup.assert_called_once()
                mock_remove_devices.assert_called_once()
