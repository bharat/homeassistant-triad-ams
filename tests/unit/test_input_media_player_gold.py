"""Unit tests for Gold-level input media player requirements."""

from unittest.mock import MagicMock

import pytest
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_registry import RegistryEntryDisabler

from custom_components.triad_ams.input_media_player import TriadAmsInputMediaPlayer
from custom_components.triad_ams.models import TriadAmsInput


@pytest.fixture
def mock_input_gold() -> MagicMock:
    """Create a mock input for gold tests."""
    input_obj = MagicMock(spec=TriadAmsInput)
    input_obj.number = 1
    input_obj.name = "Input 1"
    input_obj.linked_entity_id = None
    input_obj.coordinator = MagicMock()
    input_obj.coordinator.is_available = True
    input_obj.coordinator.add_availability_listener = MagicMock(
        return_value=MagicMock()
    )
    input_obj.add_listener = MagicMock(return_value=MagicMock())
    return input_obj


@pytest.fixture
def mock_config_entry_gold() -> MagicMock:
    """Create a mock config entry for gold tests."""
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    entry.title = "Test Triad AMS"
    entry.options = {
        "active_inputs": [1, 2],
        "active_outputs": [1],
        "input_links": {},
    }
    return entry


@pytest.fixture
def input_media_player_gold(
    mock_input_gold: MagicMock, mock_config_entry_gold: MagicMock
) -> TriadAmsInputMediaPlayer:
    """Create a TriadAmsInputMediaPlayer instance for gold tests."""
    entity = TriadAmsInputMediaPlayer(mock_input_gold, mock_config_entry_gold)
    entity.hass = MagicMock()
    return entity


class TestEntityCategory:
    """Test entity category (Gold requirement)."""

    def test_entity_has_category_attribute(
        self, input_media_player_gold: TriadAmsInputMediaPlayer
    ) -> None:
        """Test entity has _attr_entity_category attribute."""
        # This test will fail until entity category is implemented
        assert hasattr(input_media_player_gold, "_attr_entity_category")

    def test_entity_category_is_config(
        self, input_media_player_gold: TriadAmsInputMediaPlayer
    ) -> None:
        """Test entity category is set to CONFIG."""
        # This test will fail until entity category is implemented
        assert hasattr(input_media_player_gold, "_attr_entity_category")
        assert input_media_player_gold._attr_entity_category == EntityCategory.CONFIG

    def test_entity_category_property_accessible(
        self, input_media_player_gold: TriadAmsInputMediaPlayer
    ) -> None:
        """Test entity category is accessible via property."""
        # This test will fail until entity category is implemented
        assert hasattr(input_media_player_gold, "entity_category")
        assert input_media_player_gold.entity_category == EntityCategory.CONFIG


class TestEntityDisabledByDefault:
    """Test entity disabled by default (Gold requirement)."""

    def test_entity_has_disabled_by_default_attribute(
        self, input_media_player_gold: TriadAmsInputMediaPlayer
    ) -> None:
        """Test entity has _attr_entity_registry_enabled_default attribute."""
        # This test will fail until disabled by default is implemented
        assert hasattr(input_media_player_gold, "_attr_entity_registry_enabled_default")

    def test_entity_disabled_by_default_is_user(
        self, input_media_player_gold: TriadAmsInputMediaPlayer
    ) -> None:
        """Test entity disabled by default is set to USER."""
        # This test will fail until disabled by default is implemented
        assert hasattr(input_media_player_gold, "_attr_entity_registry_enabled_default")
        assert (
            input_media_player_gold._attr_entity_registry_enabled_default
            == RegistryEntryDisabler.USER
        )
