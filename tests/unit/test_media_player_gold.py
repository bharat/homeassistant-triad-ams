"""Unit tests for Gold-level media player requirements."""

from unittest.mock import MagicMock

import pytest
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_registry import RegistryEntryDisabler

from custom_components.triad_ams.media_player import TriadAmsMediaPlayer


@pytest.fixture
def mock_output_gold() -> MagicMock:
    """Create a mock output for gold tests."""
    output = MagicMock()
    output.number = 1
    output.is_on = False
    output.source = None
    output.source_name = None
    output.source_list = []
    output.volume = 0.5
    output.muted = False
    output.coordinator = MagicMock()
    output.coordinator.is_available = True
    output.coordinator.add_availability_listener = MagicMock(return_value=MagicMock())
    return output


@pytest.fixture
def mock_config_entry_gold() -> MagicMock:
    """Create a mock config entry for gold tests."""
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    entry.title = "Test Triad AMS"
    entry.options = {"active_inputs": [1, 2], "active_outputs": [1]}
    return entry


@pytest.fixture
def media_player_gold(
    mock_output_gold: MagicMock, mock_config_entry_gold: MagicMock
) -> TriadAmsMediaPlayer:
    """Create a TriadAmsMediaPlayer instance for gold tests."""
    input_links = {1: None, 2: None}
    entity = TriadAmsMediaPlayer(mock_output_gold, mock_config_entry_gold, input_links)
    entity.hass = MagicMock()
    return entity


class TestEntityCategory:
    """Test entity category (Gold requirement)."""

    def test_entity_has_category_attribute(
        self, media_player_gold: TriadAmsMediaPlayer
    ) -> None:
        """Test entity has _attr_entity_category attribute."""
        # This test will fail until entity category is implemented
        assert hasattr(media_player_gold, "_attr_entity_category")

    def test_entity_category_is_config(
        self, media_player_gold: TriadAmsMediaPlayer
    ) -> None:
        """Test entity category is set to CONFIG."""
        # This test will fail until entity category is implemented
        assert hasattr(media_player_gold, "_attr_entity_category")
        assert media_player_gold._attr_entity_category == EntityCategory.CONFIG

    def test_entity_category_property_accessible(
        self, media_player_gold: TriadAmsMediaPlayer
    ) -> None:
        """Test entity category is accessible via property."""
        # This test will fail until entity category is implemented
        assert hasattr(media_player_gold, "entity_category")
        assert media_player_gold.entity_category == EntityCategory.CONFIG


class TestEntityDisabledByDefault:
    """Test entity disabled by default (Gold requirement)."""

    def test_entity_has_disabled_by_default_attribute(
        self, media_player_gold: TriadAmsMediaPlayer
    ) -> None:
        """Test entity has _attr_entity_registry_enabled_default attribute."""
        # This test will fail until disabled by default is implemented
        assert hasattr(media_player_gold, "_attr_entity_registry_enabled_default")

    def test_entity_disabled_by_default_is_user(
        self, media_player_gold: TriadAmsMediaPlayer
    ) -> None:
        """Test entity disabled by default is set to USER."""
        # This test will fail until disabled by default is implemented
        assert hasattr(media_player_gold, "_attr_entity_registry_enabled_default")
        assert (
            media_player_gold._attr_entity_registry_enabled_default
            == RegistryEntryDisabler.USER
        )
