"""Unit tests for TriadAmsInputMediaPlayer feature masking."""

from unittest.mock import AsyncMock, MagicMock

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


class TestTriadAmsInputMediaPlayerProxyCommands:
    """Test media playback command proxying to linked entity."""

    @pytest.mark.asyncio
    async def test_play_proxies_to_linked(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """async_media_play should call service on linked entity."""
        input_media_player.input.linked_entity_id = "media_player.linked"
        input_media_player.hass = mock_hass
        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        await input_media_player.async_media_play()

        mock_hass.services.async_call.assert_called_once_with(
            "media_player",
            "media_play",
            {"entity_id": "media_player.linked"},
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_pause_proxies_to_linked(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """async_media_pause should call service on linked entity."""
        input_media_player.input.linked_entity_id = "media_player.linked"
        input_media_player.hass = mock_hass
        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        await input_media_player.async_media_pause()

        mock_hass.services.async_call.assert_called_once_with(
            "media_player",
            "media_pause",
            {"entity_id": "media_player.linked"},
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_stop_proxies_to_linked(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """async_media_stop should call service on linked entity."""
        input_media_player.input.linked_entity_id = "media_player.linked"
        input_media_player.hass = mock_hass
        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        await input_media_player.async_media_stop()

        mock_hass.services.async_call.assert_called_once_with(
            "media_player",
            "media_stop",
            {"entity_id": "media_player.linked"},
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_next_track_proxies_to_linked(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """async_media_next_track should call service on linked entity."""
        input_media_player.input.linked_entity_id = "media_player.linked"
        input_media_player.hass = mock_hass
        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        await input_media_player.async_media_next_track()

        mock_hass.services.async_call.assert_called_once_with(
            "media_player",
            "media_next_track",
            {"entity_id": "media_player.linked"},
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_previous_track_proxies_to_linked(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """async_media_previous_track should call service on linked entity."""
        input_media_player.input.linked_entity_id = "media_player.linked"
        input_media_player.hass = mock_hass
        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        await input_media_player.async_media_previous_track()

        mock_hass.services.async_call.assert_called_once_with(
            "media_player",
            "media_previous_track",
            {"entity_id": "media_player.linked"},
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_seek_proxies_to_linked(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """async_media_seek should call service with position on linked entity."""
        input_media_player.input.linked_entity_id = "media_player.linked"
        input_media_player.hass = mock_hass
        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        await input_media_player.async_media_seek(123.45)

        mock_hass.services.async_call.assert_called_once_with(
            "media_player",
            "media_seek",
            {"entity_id": "media_player.linked", "seek_position": 123.45},
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_play_media_proxies_to_linked(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """async_play_media should call service with media info on linked entity."""
        input_media_player.input.linked_entity_id = "media_player.linked"
        input_media_player.hass = mock_hass
        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        await input_media_player.async_play_media("music", "spotify://track/123")

        mock_hass.services.async_call.assert_called_once_with(
            "media_player",
            "play_media",
            {
                "entity_id": "media_player.linked",
                "media_content_type": "music",
                "media_content_id": "spotify://track/123",
            },
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_select_source_proxies_to_linked(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """async_select_source should call service with source on linked entity."""
        input_media_player.input.linked_entity_id = "media_player.linked"
        input_media_player.hass = mock_hass
        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        await input_media_player.async_select_source("Spotify")

        mock_hass.services.async_call.assert_called_once_with(
            "media_player",
            "select_source",
            {"entity_id": "media_player.linked", "source": "Spotify"},
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_shuffle_set_proxies_to_linked(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """async_shuffle_set should call service with shuffle state on linked entity."""
        input_media_player.input.linked_entity_id = "media_player.linked"
        input_media_player.hass = mock_hass
        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        await input_media_player.async_shuffle_set(shuffle=True)

        mock_hass.services.async_call.assert_called_once_with(
            "media_player",
            "shuffle_set",
            {"entity_id": "media_player.linked", "shuffle": True},
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_repeat_set_proxies_to_linked(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """async_set_repeat should call service with repeat mode on linked entity."""
        input_media_player.input.linked_entity_id = "media_player.linked"
        input_media_player.hass = mock_hass
        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        await input_media_player.async_set_repeat("all")

        mock_hass.services.async_call.assert_called_once_with(
            "media_player",
            "repeat_set",
            {"entity_id": "media_player.linked", "repeat": "all"},
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_play_no_op_without_linked_entity(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Playback commands should be no-op when no linked entity configured."""
        input_media_player.input.linked_entity_id = None
        input_media_player.hass = mock_hass
        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        await input_media_player.async_media_play()

        mock_hass.services.async_call.assert_not_called()
