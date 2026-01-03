"""Unit tests for TriadAmsInputMediaPlayer feature masking."""

from unittest.mock import MagicMock

import pytest
from homeassistant.components.media_player import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.triad_ams.media_player import TriadAmsInputMediaPlayer
from custom_components.triad_ams.models import TriadAmsInput


@pytest.fixture
def mock_input() -> MagicMock:
    """Create a mock TriadAmsInput."""
    input_obj = MagicMock(spec=TriadAmsInput)
    input_obj.number = 1
    input_obj.name = "Input 1"
    input_obj.linked_entity_id = None
    input_obj.add_listener = MagicMock(return_value=MagicMock())
    return input_obj


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Create a mock config entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry_123"
    entry.title = "Test Triad AMS"
    entry.options = {
        "active_inputs": [1, 2],
        "active_outputs": [1],
        "input_links": {},
    }
    return entry


@pytest.fixture
def mock_hass() -> MagicMock:
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    hass.data = {"integrations": {}}
    return hass


@pytest.fixture
def input_media_player(
    mock_input: MagicMock, mock_config_entry: MagicMock
) -> TriadAmsInputMediaPlayer:
    """Create a TriadAmsInputMediaPlayer instance."""
    return TriadAmsInputMediaPlayer(mock_input, mock_config_entry)


class TestTriadAmsInputMediaPlayerFeatures:
    """Test supported feature masking for input media players."""

    def test_supported_features_excludes_volume(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Ensure volume-related features are stripped from linked entity."""
        input_media_player.input.linked_entity_id = "media_player.linked_input"
        state = MagicMock()
        state.attributes = {
            "supported_features": MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.SELECT_SOURCE
        }
        mock_hass.states.get.return_value = state
        input_media_player.hass = mock_hass

        features = input_media_player.supported_features

        assert features & MediaPlayerEntityFeature.VOLUME_SET == 0
        assert features & MediaPlayerEntityFeature.VOLUME_MUTE == 0
        assert features & MediaPlayerEntityFeature.VOLUME_STEP == 0
        assert features & MediaPlayerEntityFeature.SELECT_SOURCE
        assert features & MediaPlayerEntityFeature.GROUPING


class TestTriadAmsInputMediaPlayerState:
    """Test state handling for input proxies."""

    def test_state_off_when_no_link(
        self, input_media_player: TriadAmsInputMediaPlayer
    ) -> None:
        """Input without linked entity should report OFF."""
        input_media_player.input.linked_entity_id = None

        assert input_media_player.state == MediaPlayerState.OFF

    def test_state_uses_linked_entity(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """State proxies the linked entity when available."""
        input_media_player.input.linked_entity_id = "media_player.linked"
        linked_state = MagicMock()
        linked_state.state = "on"
        mock_hass.states.get.return_value = linked_state
        input_media_player.hass = mock_hass

        assert input_media_player.state == linked_state.state

    def test_state_unknown_treated_off(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Unknown linked state should be coerced to OFF."""
        input_media_player.input.linked_entity_id = "media_player.linked"
        linked_state = MagicMock()
        linked_state.state = "unknown"
        mock_hass.states.get.return_value = linked_state
        input_media_player.hass = mock_hass

        assert input_media_player.state == MediaPlayerState.OFF


class TestTriadAmsInputMediaPlayerGroupMembers:
    """Test group membership merging for input proxies."""

    def test_group_members_merges_linked_and_local(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Group members combine local and linked lists."""
        input_media_player._group_members = ["media_player.local_1"]
        input_media_player.input.linked_entity_id = "media_player.linked"
        linked_state = MagicMock()
        linked_state.attributes = {"group_members": ["media_player.linked_1"]}
        mock_hass.states.get.return_value = linked_state
        input_media_player.hass = mock_hass

        members = input_media_player.group_members

        assert "media_player.local_1" in members
        assert "media_player.linked_1" in members

    def test_group_members_handles_missing_linked_state(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Missing linked state should not raise and returns local members."""
        input_media_player._group_members = ["media_player.local_1"]
        input_media_player.input.linked_entity_id = "media_player.linked"
        mock_hass.states.get.return_value = None
        input_media_player.hass = mock_hass

        members = input_media_player.group_members

        assert members == ["media_player.local_1"]
