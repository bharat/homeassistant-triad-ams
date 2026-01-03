"""Unit tests for TriadAmsInputMediaPlayer feature masking."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.media_player import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.triad_ams.const import DOMAIN
from custom_components.triad_ams.input_media_player import (
    InvalidGroupMemberError,
    TriadAmsInputMediaPlayer,
)
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


class TestTriadAmsInputMediaPlayerGrouping:
    """Test async_join_players grouping behavior."""

    @pytest.mark.asyncio
    async def test_join_players_with_empty_list_unjoins_all(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Empty group_members list should clear all members."""
        input_media_player._group_members = [
            "media_player.output_1",
            "media_player.output_2",
        ]
        input_media_player.hass = mock_hass
        input_media_player.async_write_ha_state = MagicMock()

        await input_media_player.async_join_players([])

        assert input_media_player._group_members == []
        input_media_player.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_join_players_with_triad_outputs(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Joining Triad AMS outputs should call turn_on_with_source service."""
        input_media_player.hass = mock_hass
        input_media_player.entity_id = "media_player.input_1"
        input_media_player.async_write_ha_state = MagicMock()

        mock_registry = MagicMock()
        mock_hass.data[er.DATA_REGISTRY] = mock_registry

        # Mock registry entries for Triad AMS outputs
        output1_entry = MagicMock()
        output1_entry.platform = DOMAIN
        output2_entry = MagicMock()
        output2_entry.platform = DOMAIN

        mock_registry.async_get = MagicMock(
            side_effect=lambda entity_id: {
                "media_player.output_1": output1_entry,
                "media_player.output_2": output2_entry,
            }.get(entity_id)
        )

        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        await input_media_player.async_join_players(
            ["media_player.output_1", "media_player.output_2"]
        )

        assert mock_hass.services.async_call.call_count == 2
        # Verify turn_on_with_source was called for each output
        calls = mock_hass.services.async_call.call_args_list
        for call in calls:
            # Check positional args (domain, service, service_data)
            assert len(call.args) == 3
            assert call.args[0] == DOMAIN
            assert call.args[1] == "turn_on_with_source"
            assert "entity_id" in call.args[2]
            assert "input_entity_id" in call.args[2]
        assert input_media_player._group_members == [
            "media_player.output_1",
            "media_player.output_2",
        ]

    @pytest.mark.asyncio
    async def test_join_players_with_mixed_domains_raises_error(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Mixing Triad outputs with non-linked domain raises error."""
        input_media_player.hass = mock_hass
        input_media_player.input.linked_entity_id = None  # No linked entity
        input_media_player.async_write_ha_state = MagicMock()

        mock_registry = MagicMock()
        mock_hass.data[er.DATA_REGISTRY] = mock_registry

        # Mock registry: one Triad output, one Sonos entity
        output_entry = MagicMock()
        output_entry.platform = DOMAIN
        sonos_entry = MagicMock()
        sonos_entry.platform = "sonos"

        mock_registry.async_get = MagicMock(
            side_effect=lambda entity_id: {
                "media_player.triad_output": output_entry,
                "media_player.sonos_speaker": sonos_entry,
            }.get(entity_id)
        )

        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        # Should raise because sonos entity has no linked entity to delegate to
        with pytest.raises(InvalidGroupMemberError):
            await input_media_player.async_join_players(
                ["media_player.triad_output", "media_player.sonos_speaker"]
            )

    @pytest.mark.asyncio
    async def test_join_players_delegates_to_linked_entity_with_grouping(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Delegate to linked entity if it supports grouping."""
        input_media_player.hass = mock_hass
        input_media_player.input.linked_entity_id = "media_player.sonos_main"
        input_media_player.async_write_ha_state = MagicMock()

        mock_registry = MagicMock()
        mock_hass.data[er.DATA_REGISTRY] = mock_registry

        # Mock registry: Triad output and Sonos speakers
        output_entry = MagicMock()
        output_entry.platform = DOMAIN
        sonos_main_entry = MagicMock()
        sonos_main_entry.platform = "sonos"
        sonos_speaker_entry = MagicMock()
        sonos_speaker_entry.platform = "sonos"

        mock_registry.async_get = MagicMock(
            side_effect=lambda entity_id: {
                "media_player.triad_output": output_entry,
                "media_player.sonos_main": sonos_main_entry,
                "media_player.sonos_speaker": sonos_speaker_entry,
            }.get(entity_id)
        )

        # Mock linked entity state with grouping support
        linked_state = MagicMock()
        linked_state.attributes = {
            "supported_features": MediaPlayerEntityFeature.GROUPING
        }
        mock_hass.states.get = MagicMock(
            side_effect=lambda entity_id: linked_state
            if entity_id == "media_player.sonos_main"
            else None
        )

        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        await input_media_player.async_join_players(
            ["media_player.triad_output", "media_player.sonos_speaker"]
        )

        # Should call both turn_on_with_source for Triad and join for Sonos
        assert mock_hass.services.async_call.call_count == 2
        calls = mock_hass.services.async_call.call_args_list

        # Verify Triad output routing
        triad_call = next(
            c for c in calls if len(c.args) > 1 and c.args[1] == "turn_on_with_source"
        )
        assert len(triad_call.args) == 3
        assert triad_call.args[0] == DOMAIN
        assert triad_call.args[1] == "turn_on_with_source"

        # Verify Sonos grouping delegation
        sonos_call = next(c for c in calls if len(c.args) > 1 and c.args[1] == "join")
        assert len(sonos_call.args) == 3
        assert sonos_call.args[0] == "media_player"
        assert sonos_call.args[1] == "join"
        assert sonos_call.args[2]["entity_id"] == "media_player.sonos_main"
        assert sonos_call.args[2]["group_members"] == ["media_player.sonos_speaker"]

    @pytest.mark.asyncio
    async def test_join_players_raises_when_linked_entity_lacks_grouping(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Should skip delegation when linked entity doesn't support grouping."""
        input_media_player.hass = mock_hass
        input_media_player.input.linked_entity_id = "media_player.chromecast_main"
        input_media_player.async_write_ha_state = MagicMock()

        mock_registry = MagicMock()
        mock_hass.data[er.DATA_REGISTRY] = mock_registry

        # Mock registry
        output_entry = MagicMock()
        output_entry.platform = DOMAIN
        chromecast_main_entry = MagicMock()
        chromecast_main_entry.platform = "cast"
        chromecast_speaker_entry = MagicMock()
        chromecast_speaker_entry.platform = "cast"

        mock_registry.async_get = MagicMock(
            side_effect=lambda entity_id: {
                "media_player.triad_output": output_entry,
                "media_player.chromecast_main": chromecast_main_entry,
                "media_player.chromecast_speaker": chromecast_speaker_entry,
            }.get(entity_id)
        )

        # Mock linked entity WITHOUT grouping support
        linked_state = MagicMock()
        linked_state.attributes = {"supported_features": 0}  # No GROUPING feature
        mock_hass.states.get = MagicMock(
            side_effect=lambda entity_id: linked_state
            if entity_id == "media_player.chromecast_main"
            else None
        )

        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        # Should succeed for Triad output but not attempt delegation
        await input_media_player.async_join_players(
            ["media_player.triad_output", "media_player.chromecast_speaker"]
        )

        # Only Triad output should be routed (no join call for unsupported grouping)
        assert mock_hass.services.async_call.call_count == 1
        call = mock_hass.services.async_call.call_args_list[0]
        assert len(call.args) == 3
        assert call.args[0] == DOMAIN
        assert call.args[1] == "turn_on_with_source"

    @pytest.mark.asyncio
    async def test_join_players_replaces_members_not_merges(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Group members should be replaced, not merged with existing."""
        input_media_player.hass = mock_hass
        input_media_player.entity_id = "media_player.input_1"
        input_media_player._group_members = [
            "media_player.old_output_1",
            "media_player.old_output_2",
        ]
        input_media_player.async_write_ha_state = MagicMock()

        mock_registry = MagicMock()
        mock_hass.data[er.DATA_REGISTRY] = mock_registry

        output_entry = MagicMock()
        output_entry.platform = DOMAIN
        mock_registry.async_get = MagicMock(return_value=output_entry)

        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        await input_media_player.async_join_players(["media_player.new_output"])

        # Should completely replace, not merge
        assert input_media_player._group_members == ["media_player.new_output"]
        assert "media_player.old_output_1" not in input_media_player._group_members
        assert "media_player.old_output_2" not in input_media_player._group_members

    @pytest.mark.asyncio
    async def test_join_players_with_unregistered_entity_raises_error(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Should raise InvalidGroupMemberError for unregistered entities."""
        input_media_player.hass = mock_hass
        input_media_player.async_write_ha_state = MagicMock()

        mock_registry = MagicMock()
        mock_hass.data[er.DATA_REGISTRY] = mock_registry
        mock_registry.async_get = MagicMock(return_value=None)  # Entity not found

        with pytest.raises(InvalidGroupMemberError) as exc_info:
            await input_media_player.async_join_players(
                ["media_player.nonexistent_entity"]
            )

        assert exc_info.value.translation_key == "invalid_group_member"
        assert (
            exc_info.value.translation_placeholders["entity_id"]
            == "media_player.nonexistent_entity"
        )

    @pytest.mark.asyncio
    async def test_join_players_with_wrong_domain_raises_error(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Raise error when non-Triad entity doesn't match linked domain."""
        input_media_player.hass = mock_hass
        input_media_player.input.linked_entity_id = "media_player.sonos_main"
        input_media_player.async_write_ha_state = MagicMock()

        mock_registry = MagicMock()
        mock_hass.data[er.DATA_REGISTRY] = mock_registry

        # Mock registry: Triad output, Sonos linked entity, but trying to join cast
        output_entry = MagicMock()
        output_entry.platform = DOMAIN
        sonos_main_entry = MagicMock()
        sonos_main_entry.platform = "sonos"
        cast_entry = MagicMock()
        cast_entry.platform = "cast"  # Wrong domain

        mock_registry.async_get = MagicMock(
            side_effect=lambda entity_id: {
                "media_player.triad_output": output_entry,
                "media_player.sonos_main": sonos_main_entry,
                "media_player.cast_speaker": cast_entry,
            }.get(entity_id)
        )

        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        # Should raise because cast domain doesn't match sonos linked entity
        with pytest.raises(InvalidGroupMemberError) as exc_info:
            await input_media_player.async_join_players(
                ["media_player.triad_output", "media_player.cast_speaker"]
            )

        assert exc_info.value.translation_key == "invalid_group_member"
        assert (
            exc_info.value.translation_placeholders["entity_id"]
            == "media_player.cast_speaker"
        )


class TestTriadAmsInputMediaPlayerGetJoinableGroupMembers:
    """Test async_get_joinable_group_members service method."""

    @pytest.mark.asyncio
    async def test_get_joinable_returns_empty_without_entity_id(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Should return empty list if entity_id is not set."""
        input_media_player.hass = mock_hass
        input_media_player.entity_id = None

        result = await input_media_player.async_get_joinable_group_members()

        assert result == {"joinable_members": []}

    @pytest.mark.asyncio
    async def test_get_joinable_returns_empty_without_hass(
        self, input_media_player: TriadAmsInputMediaPlayer
    ) -> None:
        """Should return empty list if hass is not set."""
        input_media_player.entity_id = "media_player.input_1"
        input_media_player.hass = None

        result = await input_media_player.async_get_joinable_group_members()

        assert result == {"joinable_members": []}

    @pytest.mark.asyncio
    async def test_get_joinable_includes_unlinked_speaker_outputs(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Should include all unlinked Triad outputs with speaker device_class."""
        input_media_player.hass = mock_hass
        input_media_player.entity_id = "media_player.input_1"
        input_media_player.input.linked_entity_id = None

        # Mock registry
        mock_registry = MagicMock()
        output1_entry = MagicMock()
        output1_entry.entity_id = "media_player.output_1"
        output1_entry.platform = DOMAIN
        output1_entry.domain = "media_player"

        output2_entry = MagicMock()
        output2_entry.entity_id = "media_player.output_2"
        output2_entry.platform = DOMAIN
        output2_entry.domain = "media_player"

        mock_registry.entities = {
            "abc": output1_entry,
            "def": output2_entry,
        }
        mock_hass.data[er.DATA_REGISTRY] = mock_registry

        # Mock states with speaker device_class
        output1_state = MagicMock()
        output1_state.attributes = {
            "device_class": "speaker",
            "linked_input_entity_id": None,
        }
        output2_state = MagicMock()
        output2_state.attributes = {
            "device_class": "speaker",
            "linked_input_entity_id": None,
        }

        mock_hass.states.get = MagicMock(
            side_effect=lambda entity_id: {
                "media_player.output_1": output1_state,
                "media_player.output_2": output2_state,
            }.get(entity_id)
        )

        result = await input_media_player.async_get_joinable_group_members()

        assert "media_player.output_1" in result["joinable_members"]
        assert "media_player.output_2" in result["joinable_members"]
        assert "media_player.input_1" not in result["joinable_members"]  # Exclude self

    @pytest.mark.asyncio
    async def test_get_joinable_excludes_non_speaker_outputs(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Should exclude Triad outputs that are not speakers."""
        input_media_player.hass = mock_hass
        input_media_player.entity_id = "media_player.input_1"
        input_media_player.input.linked_entity_id = None

        # Mock registry
        mock_registry = MagicMock()
        output1_entry = MagicMock()
        output1_entry.entity_id = "media_player.output_1"
        output1_entry.platform = DOMAIN
        output1_entry.domain = "media_player"

        receiver_entry = MagicMock()
        receiver_entry.entity_id = "media_player.receiver"
        receiver_entry.platform = DOMAIN
        receiver_entry.domain = "media_player"

        mock_registry.entities = {
            "abc": output1_entry,
            "def": receiver_entry,
        }
        mock_hass.data[er.DATA_REGISTRY] = mock_registry

        # Mock states - one speaker, one receiver
        output1_state = MagicMock()
        output1_state.attributes = {
            "device_class": "speaker",
            "linked_input_entity_id": None,
        }
        receiver_state = MagicMock()
        receiver_state.attributes = {
            "device_class": "receiver",
            "linked_input_entity_id": None,
        }

        mock_hass.states.get = MagicMock(
            side_effect=lambda entity_id: {
                "media_player.output_1": output1_state,
                "media_player.receiver": receiver_state,
            }.get(entity_id)
        )

        result = await input_media_player.async_get_joinable_group_members()

        assert "media_player.output_1" in result["joinable_members"]
        assert "media_player.receiver" not in result["joinable_members"]

    @pytest.mark.asyncio
    async def test_get_joinable_includes_linked_to_current_input(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Should include outputs linked to the current input entity."""
        input_media_player.hass = mock_hass
        input_media_player.entity_id = "media_player.input_1"
        input_media_player.input.linked_entity_id = None

        # Mock registry
        mock_registry = MagicMock()
        output1_entry = MagicMock()
        output1_entry.entity_id = "media_player.output_1"
        output1_entry.platform = DOMAIN
        output1_entry.domain = "media_player"

        output2_entry = MagicMock()
        output2_entry.entity_id = "media_player.output_2"
        output2_entry.platform = DOMAIN
        output2_entry.domain = "media_player"

        mock_registry.entities = {
            "abc": output1_entry,
            "def": output2_entry,
        }
        mock_hass.data[er.DATA_REGISTRY] = mock_registry

        # output_1 is unlinked, output_2 is linked to input_1
        output1_state = MagicMock()
        output1_state.attributes = {
            "device_class": "speaker",
            "linked_input_entity_id": None,
        }
        output2_state = MagicMock()
        output2_state.attributes = {
            "device_class": "speaker",
            "linked_input_entity_id": "media_player.input_1",
        }

        mock_hass.states.get = MagicMock(
            side_effect=lambda entity_id: {
                "media_player.output_1": output1_state,
                "media_player.output_2": output2_state,
            }.get(entity_id)
        )

        result = await input_media_player.async_get_joinable_group_members()

        assert "media_player.output_1" in result["joinable_members"]
        assert "media_player.output_2" in result["joinable_members"]

    @pytest.mark.asyncio
    async def test_get_joinable_excludes_linked_to_other_inputs(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Should exclude outputs linked to other input entities."""
        input_media_player.hass = mock_hass
        input_media_player.entity_id = "media_player.input_1"
        input_media_player.input.linked_entity_id = None

        # Mock registry
        mock_registry = MagicMock()
        output1_entry = MagicMock()
        output1_entry.entity_id = "media_player.output_1"
        output1_entry.platform = DOMAIN
        output1_entry.domain = "media_player"

        output2_entry = MagicMock()
        output2_entry.entity_id = "media_player.output_2"
        output2_entry.platform = DOMAIN
        output2_entry.domain = "media_player"

        mock_registry.entities = {
            "abc": output1_entry,
            "def": output2_entry,
        }
        mock_hass.data[er.DATA_REGISTRY] = mock_registry

        # output_1 is unlinked, output_2 is linked to input_2
        output1_state = MagicMock()
        output1_state.attributes = {
            "device_class": "speaker",
            "linked_input_entity_id": None,
        }
        output2_state = MagicMock()
        output2_state.attributes = {
            "device_class": "speaker",
            "linked_input_entity_id": "media_player.input_2",
        }

        mock_hass.states.get = MagicMock(
            side_effect=lambda entity_id: {
                "media_player.output_1": output1_state,
                "media_player.output_2": output2_state,
            }.get(entity_id)
        )

        result = await input_media_player.async_get_joinable_group_members()

        assert "media_player.output_1" in result["joinable_members"]
        assert "media_player.output_2" not in result["joinable_members"]

    @pytest.mark.asyncio
    async def test_get_joinable_returns_triad_only_when_linked_lacks_grouping(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Should return only Triad outputs when linked entity lacks GROUPING."""
        input_media_player.hass = mock_hass
        input_media_player.entity_id = "media_player.input_1"
        input_media_player.input.linked_entity_id = "media_player.no_grouping"

        # Mock registry
        mock_registry = MagicMock()
        output1_entry = MagicMock()
        output1_entry.entity_id = "media_player.output_1"
        output1_entry.platform = DOMAIN
        output1_entry.domain = "media_player"

        mock_registry.entities = {"abc": output1_entry}
        mock_hass.data[er.DATA_REGISTRY] = mock_registry

        # Mock linked state WITHOUT GROUPING feature
        linked_state = MagicMock()
        linked_state.attributes = {
            "device_class": "speaker",
            "supported_features": 0,  # No GROUPING feature
        }

        output1_state = MagicMock()
        output1_state.attributes = {
            "device_class": "speaker",
            "linked_input_entity_id": None,
        }

        mock_hass.states.get = MagicMock(
            side_effect=lambda entity_id: {
                "media_player.no_grouping": linked_state,
                "media_player.output_1": output1_state,
            }.get(entity_id)
        )

        result = await input_media_player.async_get_joinable_group_members()

        # Should only include Triad output, no platform entities
        assert "media_player.output_1" in result["joinable_members"]
        assert len(result["joinable_members"]) == 1

    @pytest.mark.asyncio
    async def test_get_joinable_includes_platform_entities_from_linked_player(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Should include speaker entities from linked player platform."""
        input_media_player.hass = mock_hass
        input_media_player.entity_id = "media_player.input_1"
        input_media_player.input.linked_entity_id = "media_player.sonos_main"

        # Mock registry
        mock_registry = MagicMock()
        sonos_main_entry = MagicMock()
        sonos_main_entry.entity_id = "media_player.sonos_main"
        sonos_main_entry.platform = "sonos"
        sonos_main_entry.domain = "media_player"

        sonos_speaker1_entry = MagicMock()
        sonos_speaker1_entry.entity_id = "media_player.sonos_speaker_1"
        sonos_speaker1_entry.platform = "sonos"
        sonos_speaker1_entry.domain = "media_player"

        sonos_speaker2_entry = MagicMock()
        sonos_speaker2_entry.entity_id = "media_player.sonos_speaker_2"
        sonos_speaker2_entry.platform = "sonos"
        sonos_speaker2_entry.domain = "media_player"

        mock_registry.entities = {
            "sonos_main": sonos_main_entry,
            "sonos_1": sonos_speaker1_entry,
            "sonos_2": sonos_speaker2_entry,
        }

        def async_get_side_effect(entity_id: str) -> MagicMock | None:
            return {
                "media_player.sonos_main": sonos_main_entry,
            }.get(entity_id)

        mock_registry.async_get = MagicMock(side_effect=async_get_side_effect)
        mock_hass.data[er.DATA_REGISTRY] = mock_registry

        # Mock states
        sonos_main_state = MagicMock()
        sonos_main_state.attributes = {
            "device_class": "speaker",
            "supported_features": MediaPlayerEntityFeature.GROUPING,
        }

        sonos_speaker1_state = MagicMock()
        sonos_speaker1_state.attributes = {"device_class": "speaker"}

        sonos_speaker2_state = MagicMock()
        sonos_speaker2_state.attributes = {"device_class": "speaker"}

        mock_hass.states.get = MagicMock(
            side_effect=lambda entity_id: {
                "media_player.sonos_main": sonos_main_state,
                "media_player.sonos_speaker_1": sonos_speaker1_state,
                "media_player.sonos_speaker_2": sonos_speaker2_state,
            }.get(entity_id)
        )

        result = await input_media_player.async_get_joinable_group_members()

        assert "media_player.sonos_speaker_1" in result["joinable_members"]
        assert "media_player.sonos_speaker_2" in result["joinable_members"]
        assert (
            "media_player.sonos_main" not in result["joinable_members"]
        )  # Exclude linked entity

    @pytest.mark.asyncio
    async def test_get_joinable_filters_platform_entities_by_speaker_class(
        self, input_media_player: TriadAmsInputMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Should only include speaker platform entities, not other device classes."""
        input_media_player.hass = mock_hass
        input_media_player.entity_id = "media_player.input_1"
        input_media_player.input.linked_entity_id = "media_player.sonos_main"

        # Mock registry
        mock_registry = MagicMock()
        sonos_main_entry = MagicMock()
        sonos_main_entry.entity_id = "media_player.sonos_main"
        sonos_main_entry.platform = "sonos"
        sonos_main_entry.domain = "media_player"

        sonos_speaker_entry = MagicMock()
        sonos_speaker_entry.entity_id = "media_player.sonos_speaker"
        sonos_speaker_entry.platform = "sonos"
        sonos_speaker_entry.domain = "media_player"

        sonos_receiver_entry = MagicMock()
        sonos_receiver_entry.entity_id = "media_player.sonos_receiver"
        sonos_receiver_entry.platform = "sonos"
        sonos_receiver_entry.domain = "media_player"

        mock_registry.entities = {
            "sonos_main": sonos_main_entry,
            "sonos_speaker": sonos_speaker_entry,
            "sonos_receiver": sonos_receiver_entry,
        }

        def async_get_side_effect(entity_id: str) -> MagicMock | None:
            return {
                "media_player.sonos_main": sonos_main_entry,
            }.get(entity_id)

        mock_registry.async_get = MagicMock(side_effect=async_get_side_effect)
        mock_hass.data[er.DATA_REGISTRY] = mock_registry

        # Mock states - speaker and receiver
        sonos_main_state = MagicMock()
        sonos_main_state.attributes = {
            "device_class": "speaker",
            "supported_features": MediaPlayerEntityFeature.GROUPING,
        }

        sonos_speaker_state = MagicMock()
        sonos_speaker_state.attributes = {"device_class": "speaker"}

        sonos_receiver_state = MagicMock()
        sonos_receiver_state.attributes = {"device_class": "receiver"}

        mock_hass.states.get = MagicMock(
            side_effect=lambda entity_id: {
                "media_player.sonos_main": sonos_main_state,
                "media_player.sonos_speaker": sonos_speaker_state,
                "media_player.sonos_receiver": sonos_receiver_state,
            }.get(entity_id)
        )

        result = await input_media_player.async_get_joinable_group_members()

        assert "media_player.sonos_speaker" in result["joinable_members"]
        assert "media_player.sonos_receiver" not in result["joinable_members"]
