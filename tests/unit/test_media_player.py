"""Unit tests for TriadAmsMediaPlayer."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.media_player import MediaPlayerState
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceValidationError

from custom_components.triad_ams.media_player import TriadAmsMediaPlayer
from custom_components.triad_ams.models import TriadAmsOutput
from tests.conftest import create_async_mock_method


@pytest.fixture
def mock_output() -> MagicMock:
    """Create a mock TriadAmsOutput."""
    output = MagicMock(spec=TriadAmsOutput)
    output.number = 1
    output.name = "Output 1"
    output.source = None
    output.source_name = None
    output.source_list = ["Input 1", "Input 2"]
    output.is_on = False
    output.volume = None
    output.muted = False
    output.source_id_for_name = MagicMock(return_value=1)
    output.set_source = create_async_mock_method()
    output.set_volume = create_async_mock_method()
    output.set_muted = create_async_mock_method()
    output.volume_up_step = create_async_mock_method()
    output.volume_down_step = create_async_mock_method()
    output.turn_off = create_async_mock_method()
    output.turn_on = create_async_mock_method()
    output.refresh_and_notify = create_async_mock_method()
    output.add_listener = MagicMock(return_value=MagicMock())
    return output


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
    hass.async_create_task = MagicMock()
    return hass


@pytest.fixture
def media_player(
    mock_output: MagicMock, mock_config_entry: MagicMock
) -> TriadAmsMediaPlayer:
    """Create a TriadAmsMediaPlayer instance."""
    input_links = {1: None, 2: None}
    return TriadAmsMediaPlayer(mock_output, mock_config_entry, input_links)


class TestTriadAmsMediaPlayerInitialization:
    """Test TriadAmsMediaPlayer initialization."""

    def test_initialization(
        self, mock_output: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test basic initialization."""
        input_links = {1: None, 2: None}
        entity = TriadAmsMediaPlayer(mock_output, mock_config_entry, input_links)

        assert entity.output == mock_output
        assert entity._attr_unique_id == "test_entry_123_output_1"
        assert entity._attr_name == "Output 1"
        assert entity._attr_device_class.value == "speaker"

    def test_device_info(self, media_player: TriadAmsMediaPlayer) -> None:
        """Test device info."""
        device_info = media_player.device_info
        assert device_info["identifiers"] == {("triad_ams", "test_entry_123")}
        assert device_info["name"] == "Test Triad AMS"
        assert device_info["manufacturer"] == "Triad"
        assert device_info["model"] == "Audio Matrix"


class TestTriadAmsMediaPlayerState:
    """Test state properties."""

    def test_state_off(self, media_player: TriadAmsMediaPlayer) -> None:
        """Test state when off."""
        media_player.output.is_on = False
        assert media_player.state == MediaPlayerState.OFF

    def test_state_on(self, media_player: TriadAmsMediaPlayer) -> None:
        """Test state when on."""
        media_player.output.is_on = True
        assert media_player.state == MediaPlayerState.ON

    def test_is_on(self, media_player: TriadAmsMediaPlayer) -> None:
        """Test is_on property."""
        media_player.output.is_on = True
        assert media_player.is_on is True

    def test_source(self, media_player: TriadAmsMediaPlayer) -> None:
        """Test source property."""
        media_player.output.source_name = "Input 1"
        assert media_player.source == "Input 1"

    def test_source_none(self, media_player: TriadAmsMediaPlayer) -> None:
        """Test source when None."""
        media_player.output.source_name = None
        assert media_player.source is None

    def test_source_list(self, media_player: TriadAmsMediaPlayer) -> None:
        """Test source_list property."""
        media_player.output.source_list = ["Input 1", "Input 2"]
        assert media_player.source_list == ["Input 1", "Input 2"]

    def test_volume_level(self, media_player: TriadAmsMediaPlayer) -> None:
        """Test volume_level property."""
        media_player.output.volume = 0.75
        assert media_player.volume_level == 0.75

    def test_volume_level_none(self, media_player: TriadAmsMediaPlayer) -> None:
        """Test volume_level when None."""
        media_player.output.volume = None
        assert media_player.volume_level is None

    def test_is_volume_muted(self, media_player: TriadAmsMediaPlayer) -> None:
        """Test is_volume_muted property."""
        media_player.output.muted = True
        assert media_player.is_volume_muted is True


class TestTriadAmsMediaPlayerMediaAttributes:
    """Test media attributes from linked entities."""

    def test_media_title_no_link(
        self, media_player: TriadAmsMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Test media_title when no linked entity."""
        media_player.hass = mock_hass
        media_player.output.source = None
        assert media_player.media_title is None

    def test_media_title_with_link(
        self, media_player: TriadAmsMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Test media_title from linked entity."""
        # Simple state object - no MagicMock
        state = type("State", (), {"attributes": {"media_title": "Test Song"}})()

        def state_getter(_hass: HomeAssistant, _entity_id: str) -> Any:
            return state

        media_player.hass = mock_hass
        media_player._input_links = {1: "media_player.test"}
        media_player.output.source = 1
        media_player._state_getter = state_getter

        # Need to set up the link subscription
        media_player._linked_entity_id = "media_player.test"
        assert media_player.media_title == "Test Song"

    def test_media_artist(
        self, media_player: TriadAmsMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Test media_artist from linked entity."""
        # Simple state object - no MagicMock
        state = type("State", (), {"attributes": {"media_artist": "Test Artist"}})()

        def state_getter(_hass: HomeAssistant, _entity_id: str) -> Any:
            return state

        media_player.hass = mock_hass
        media_player._linked_entity_id = "media_player.test"
        media_player._state_getter = state_getter
        assert media_player.media_artist == "Test Artist"

    def test_media_album_name(
        self, media_player: TriadAmsMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Test media_album_name from linked entity."""
        # Simple state object - no MagicMock
        state = type("State", (), {"attributes": {"media_album_name": "Test Album"}})()

        def state_getter(_hass: HomeAssistant, _entity_id: str) -> Any:
            return state

        media_player.hass = mock_hass
        media_player._linked_entity_id = "media_player.test"
        media_player._state_getter = state_getter
        assert media_player.media_album_name == "Test Album"

    def test_media_duration(
        self, media_player: TriadAmsMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Test media_duration from linked entity."""
        # Simple state object - no MagicMock
        state = type("State", (), {"attributes": {"media_duration": 180}})()

        def state_getter(_hass: HomeAssistant, _entity_id: str) -> Any:
            return state

        media_player.hass = mock_hass
        media_player._linked_entity_id = "media_player.test"
        media_player._state_getter = state_getter
        assert media_player.media_duration == 180

    def test_entity_picture(
        self, media_player: TriadAmsMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Test entity_picture from linked entity."""
        # Simple state object - no MagicMock
        state = type(
            "State",
            (),
            {"attributes": {"entity_picture": "http://example.com/art.jpg"}},
        )()

        def state_getter(_hass: HomeAssistant, _entity_id: str) -> Any:
            return state

        media_player.hass = mock_hass
        media_player._linked_entity_id = "media_player.test"
        media_player._state_getter = state_getter
        assert media_player.entity_picture == "http://example.com/art.jpg"


class TestTriadAmsMediaPlayerServices:
    """Test service methods."""

    @pytest.mark.asyncio
    async def test_async_select_source(
        self, media_player: TriadAmsMediaPlayer, mock_output: MagicMock
    ) -> None:
        """Test selecting a source."""
        mock_output.source_id_for_name.return_value = 2
        media_player.async_write_ha_state = MagicMock()

        await media_player.async_select_source("Input 2")

        mock_output.set_source.assert_called_once_with(2)
        media_player.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_async_select_source_unknown(
        self, media_player: TriadAmsMediaPlayer, mock_output: MagicMock
    ) -> None:
        """Test selecting unknown source."""
        mock_output.source_id_for_name.return_value = None

        await media_player.async_select_source("Unknown Input")
        # Should not call set_source
        mock_output.set_source.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_set_volume_level(
        self, media_player: TriadAmsMediaPlayer, mock_output: MagicMock
    ) -> None:
        """Test setting volume level."""
        media_player.async_write_ha_state = MagicMock()

        await media_player.async_set_volume_level(0.75)

        mock_output.set_volume.assert_called_once_with(0.75)
        media_player.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_async_mute_volume(
        self, media_player: TriadAmsMediaPlayer, mock_output: MagicMock
    ) -> None:
        """Test muting volume."""
        media_player.async_write_ha_state = MagicMock()

        await media_player.async_mute_volume(mute=True)

        mock_output.set_muted.assert_called_once_with(muted=True)
        media_player.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_async_volume_up(
        self, media_player: TriadAmsMediaPlayer, mock_output: MagicMock
    ) -> None:
        """Test volume up."""
        media_player.async_write_ha_state = MagicMock()

        await media_player.async_volume_up()

        mock_output.volume_up_step.assert_called_once_with(large=False)
        mock_output.refresh.assert_called_once()
        media_player.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_async_volume_down(
        self, media_player: TriadAmsMediaPlayer, mock_output: MagicMock
    ) -> None:
        """Test volume down."""
        media_player.async_write_ha_state = MagicMock()

        await media_player.async_volume_down()

        mock_output.volume_down_step.assert_called_once_with(large=False)
        mock_output.refresh.assert_called_once()
        media_player.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_async_turn_off(
        self, media_player: TriadAmsMediaPlayer, mock_output: MagicMock
    ) -> None:
        """Test turning off."""
        media_player.async_write_ha_state = MagicMock()

        await media_player.async_turn_off()

        mock_output.turn_off.assert_called_once()
        media_player.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_async_turn_on(
        self, media_player: TriadAmsMediaPlayer, mock_output: MagicMock
    ) -> None:
        """Test turning on."""
        media_player.async_write_ha_state = MagicMock()

        await media_player.async_turn_on()

        mock_output.turn_on.assert_called_once()
        media_player.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_async_turn_on_with_source_valid(
        self, media_player: TriadAmsMediaPlayer, mock_output: MagicMock
    ) -> None:
        """Test turn_on_with_source with valid input."""
        media_player._input_links = {1: "media_player.input1"}
        media_player._options = {"active_inputs": [1]}
        media_player.async_write_ha_state = MagicMock()

        await media_player.async_turn_on_with_source("media_player.input1")

        mock_output.set_source.assert_called_once_with(1)
        mock_output.turn_on.assert_called_once()
        media_player.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_async_turn_on_with_source_invalid_link(
        self,
        media_player: TriadAmsMediaPlayer,
        mock_output: MagicMock,
    ) -> None:
        """Test turn_on_with_source with invalid input link."""
        media_player._input_links = {1: "media_player.input1"}

        with pytest.raises(ValueError, match="not linked"):
            await media_player.async_turn_on_with_source("media_player.unknown")

    @pytest.mark.asyncio
    async def test_async_turn_on_with_source_inactive(
        self,
        media_player: TriadAmsMediaPlayer,
        mock_output: MagicMock,
    ) -> None:
        """Test turn_on_with_source with inactive input."""
        media_player._input_links = {1: "media_player.input1"}
        media_player._options = {"active_inputs": [2]}  # Input 1 not active

        with pytest.raises(ServiceValidationError, match="not active"):
            await media_player.async_turn_on_with_source("media_player.input1")


class TestTriadAmsMediaPlayerLifecycle:
    """Test entity lifecycle."""

    @pytest.mark.asyncio
    async def test_async_added_to_hass(
        self,
        media_player: TriadAmsMediaPlayer,
        mock_hass: MagicMock,
        mock_output: MagicMock,
    ) -> None:
        """Test entity added to hass."""
        media_player.hass = mock_hass
        media_player.async_write_ha_state = MagicMock()

        await media_player.async_added_to_hass()

        mock_output.add_listener.assert_called_once()
        mock_hass.async_create_task.assert_called_once()
        media_player.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_async_will_remove_from_hass(
        self,
        media_player: TriadAmsMediaPlayer,
        mock_output: MagicMock,
    ) -> None:
        """Test entity removed from hass."""
        mock_unsub = MagicMock()
        media_player._output_unsub = mock_unsub

        await media_player.async_will_remove_from_hass()

        mock_unsub.assert_called_once()
        assert media_player._output_unsub is None


class TestTriadAmsMediaPlayerLinkSubscription:
    """Test input link subscriptions."""

    @pytest.mark.asyncio
    async def test_link_subscription_update(
        self, media_player: TriadAmsMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Test updating link subscription."""
        # Return a regular callable, not an AsyncMock
        unsub_func = MagicMock()
        with patch(
            "custom_components.triad_ams.media_player.async_track_state_change_event",
            return_value=unsub_func,
        ):
            media_player.hass = mock_hass
            media_player._input_links = {1: "media_player.input1"}
            media_player.output.source = 1

            media_player._update_link_subscription()

            # Should subscribe to linked entity
            assert media_player._linked_entity_id == "media_player.input1"

    @pytest.mark.asyncio
    async def test_link_subscription_removal(
        self,
        media_player: TriadAmsMediaPlayer,
        mock_hass: MagicMock,
    ) -> None:
        """Test removing link subscription."""
        # Patch async_track_state_change_event - it's a regular function that
        # returns a synchronous unsubscribe callable. Use new_callable=MagicMock
        # to prevent patch from auto-detecting it as async based on the name.
        unsub_func = MagicMock()
        with patch(
            "custom_components.triad_ams.media_player.async_track_state_change_event",
            new_callable=MagicMock,
            return_value=unsub_func,
        ):
            media_player.hass = mock_hass

            # Use a regular callable, not a mock, to avoid AsyncMock issues
            unsub_called = False

            def mock_unsub() -> None:
                nonlocal unsub_called
                unsub_called = True

            media_player._linked_unsub = mock_unsub
            media_player._linked_entity_id = "media_player.input1"
            media_player.output.source = None

            media_player._update_link_subscription()

            # Should unsubscribe
            assert unsub_called
            assert media_player._linked_entity_id is None

    @pytest.mark.asyncio
    async def test_handle_linked_state_change(
        self, media_player: TriadAmsMediaPlayer
    ) -> None:
        """Test handling linked entity state change."""
        media_player.async_write_ha_state = MagicMock()

        media_player._handle_linked_state_change(MagicMock())

        media_player.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_output_poll_update(
        self, media_player: TriadAmsMediaPlayer
    ) -> None:
        """Test handling output poll update."""
        media_player.async_write_ha_state = MagicMock()
        media_player._update_link_subscription = MagicMock()

        media_player._handle_output_poll_update()

        media_player._update_link_subscription.assert_called_once()
        media_player.async_write_ha_state.assert_called_once()

    def test_current_linked_entity_id_with_source(
        self, media_player: TriadAmsMediaPlayer
    ) -> None:
        """Test _current_linked_entity_id when source is set."""
        media_player._input_links = {1: "media_player.input1"}
        media_player.output.source = 1

        result = media_player._current_linked_entity_id()

        assert result == "media_player.input1"

    def test_current_linked_entity_id_no_source(
        self, media_player: TriadAmsMediaPlayer
    ) -> None:
        """Test _current_linked_entity_id when source is None."""
        media_player.output.source = None

        result = media_player._current_linked_entity_id()

        assert result is None

    def test_linked_attr_no_linked_entity(
        self, media_player: TriadAmsMediaPlayer
    ) -> None:
        """Test _linked_attr when no linked entity."""
        media_player._linked_entity_id = None

        result = media_player._linked_attr("media_title")

        assert result is None

    def test_linked_attr_no_hass(self, media_player: TriadAmsMediaPlayer) -> None:
        """Test _linked_attr when hass is None."""
        media_player._linked_entity_id = "media_player.test"
        media_player.hass = None

        result = media_player._linked_attr("media_title")

        assert result is None

    def test_linked_attr_state_not_found(
        self, media_player: TriadAmsMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Test _linked_attr when state is not found."""

        def state_getter(_hass: HomeAssistant, _entity_id: str) -> None:
            return None

        media_player.hass = mock_hass
        media_player._linked_entity_id = "media_player.test"
        media_player._state_getter = state_getter

        result = media_player._linked_attr("media_title")

        assert result is None

    def test_media_content_id(
        self, media_player: TriadAmsMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Test media_content_id from linked entity."""
        # Simple state object - no MagicMock
        state = type("State", (), {"attributes": {"media_content_id": "track_123"}})()

        def state_getter(_hass: HomeAssistant, _entity_id: str) -> Any:
            return state

        media_player.hass = mock_hass
        media_player._linked_entity_id = "media_player.test"
        media_player._state_getter = state_getter
        assert media_player.media_content_id == "track_123"

    def test_media_content_type(
        self, media_player: TriadAmsMediaPlayer, mock_hass: MagicMock
    ) -> None:
        """Test media_content_type from linked entity."""
        # Simple state object - no MagicMock
        state = type("State", (), {"attributes": {"media_content_type": "music"}})()

        def state_getter(_hass: HomeAssistant, _entity_id: str) -> Any:
            return state

        media_player.hass = mock_hass
        media_player._linked_entity_id = "media_player.test"
        media_player._state_getter = state_getter
        assert media_player.media_content_type == "music"
