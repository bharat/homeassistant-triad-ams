"""Unit tests for exception translations (Gold requirement)."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.triad_ams.media_player import TriadAmsMediaPlayer


@pytest.fixture
def mock_output_exception() -> MagicMock:
    """Create a mock output for exception tests."""
    output = MagicMock()
    output.number = 1
    output.is_on = False
    output.source = None
    output.source_name = None
    output.source_list = []
    output.coordinator = MagicMock()
    output.coordinator.is_available = True
    output.coordinator.add_availability_listener = MagicMock(return_value=MagicMock())
    return output


@pytest.fixture
def mock_config_entry_exception() -> MagicMock:
    """Create a mock config entry for exception tests."""
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    entry.title = "Test Triad AMS"
    entry.options = {"active_inputs": [1, 2], "active_outputs": [1]}
    return entry


@pytest.fixture
def media_player_exception(
    mock_output_exception: MagicMock, mock_config_entry_exception: MagicMock
) -> TriadAmsMediaPlayer:
    """Create a TriadAmsMediaPlayer instance for exception tests."""
    input_links = {1: "media_player.test", 2: None}
    entity = TriadAmsMediaPlayer(
        mock_output_exception, mock_config_entry_exception, input_links
    )
    entity.hass = MagicMock()
    return entity


class TestExceptionTranslations:
    """Test exception translations (Gold requirement)."""

    @pytest.mark.asyncio
    async def test_value_error_has_translation_key(
        self, media_player_exception: TriadAmsMediaPlayer
    ) -> None:
        """Test ValueError from async_turn_on_with_source has translation key."""
        # This test will fail until exceptions are replaced with translatable versions
        # Currently raises ValueError, but should raise HomeAssistantError
        # with translation_key
        with pytest.raises((HomeAssistantError, ValueError)) as exc_info:
            await media_player_exception.async_turn_on_with_source(
                "media_player.nonexistent"
            )

        # Exception should be a HomeAssistantError subclass with translation key
        # This will fail until ValueError is replaced with HomeAssistantError
        assert isinstance(exc_info.value, HomeAssistantError)
        assert hasattr(exc_info.value, "translation_key")
        assert exc_info.value.translation_key is not None

    @pytest.mark.asyncio
    async def test_service_validation_error_has_translation_key(
        self, media_player_exception: TriadAmsMediaPlayer
    ) -> None:
        """Test ServiceValidationError has translation key."""
        # This test will fail until exceptions are replaced with translatable versions
        # Set up input_links to have the entity but input not active
        media_player_exception._input_links = {3: "media_player.test"}
        media_player_exception._options = {"active_inputs": [1, 2]}

        with pytest.raises((HomeAssistantError, ServiceValidationError)) as exc_info:
            await media_player_exception.async_turn_on_with_source("media_player.test")

        # Exception should be a HomeAssistantError subclass with translation key
        # This will fail until ServiceValidationError is replaced with
        # HomeAssistantError
        assert isinstance(exc_info.value, HomeAssistantError)
        assert hasattr(exc_info.value, "translation_key")
        assert exc_info.value.translation_key is not None

    def test_translation_keys_exist_in_strings_json(self) -> None:
        """Test translation keys exist in strings.json."""
        # This test will fail until translation keys are added
        strings_path = (
            Path(__file__).parent.parent.parent
            / "custom_components"
            / "triad_ams"
            / "strings.json"
        )
        with strings_path.open() as f:
            strings = json.load(f)

        assert "exceptions" in strings
        assert "input_entity_not_linked" in strings["exceptions"]
        assert "message" in strings["exceptions"]["input_entity_not_linked"]

    def test_translation_keys_exist_in_en_json(self) -> None:
        """Test translation keys exist in translations/en.json."""
        # This test will fail until translation keys are added
        en_path = (
            Path(__file__).parent.parent.parent
            / "custom_components"
            / "triad_ams"
            / "translations"
            / "en.json"
        )
        with en_path.open() as f:
            translations = json.load(f)

        assert "exceptions" in translations
        assert "input_entity_not_linked" in translations["exceptions"]
