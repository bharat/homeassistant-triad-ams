"""
Unit tests for state restoration after a Home Assistant restart.

Restoration is display-only: it seeds the entity's cached state from the
last saved HA state so the UI is populated before the first poll, it never
writes to the device, and the first successful poll overwrites it with
device truth unconditionally.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.components.media_player import MediaPlayerState
from homeassistant.core import HomeAssistant, State

from custom_components.triad_ams.media_player import TriadAmsMediaPlayer
from custom_components.triad_ams.models import TriadAmsOutput
from tests.conftest import create_async_mock_method

WRITE_METHODS = (
    "set_output_volume",
    "set_output_mute",
    "set_output_to_input",
    "disconnect_output",
    "volume_step_up",
    "volume_step_down",
    "set_trigger_zone",
)


@pytest.fixture
def output(mock_coordinator: MagicMock) -> TriadAmsOutput:
    """Create a real output backed by a mocked coordinator."""
    input_names = {i: f"Input {i}" for i in range(1, 9)}
    return TriadAmsOutput(1, "Output 1", mock_coordinator, None, input_names)


@pytest.fixture
def entity(output: TriadAmsOutput, mock_config_entry: MagicMock) -> TriadAmsMediaPlayer:
    """Create an entity wired to a mock hass that captures the poll task."""
    ent = TriadAmsMediaPlayer(output, mock_config_entry, {1: None, 2: None})
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    captured: list[Any] = []

    def capture_task(coro: Any) -> MagicMock:
        captured.append(coro)
        return MagicMock()

    hass.async_create_task = MagicMock(side_effect=capture_task)
    ent.hass = hass
    ent.async_write_ha_state = MagicMock()
    ent.captured_tasks = captured
    return ent


def _saved_state(state: str, attributes: dict[str, Any]) -> State:
    """Build a saved HA state as RestoreEntity would return it."""
    return State("media_player.triad_output_1", state, attributes)


async def _drain_tasks(entity: TriadAmsMediaPlayer, *, run: bool) -> None:
    """Await or discard the poll task queued by async_added_to_hass."""
    for coro in entity.captured_tasks:
        if run:
            await coro
        else:
            coro.close()
    entity.captured_tasks.clear()


class TestRestoreBeforeFirstPoll:
    """Restored snapshot populates the entity before any poll completes."""

    async def test_restores_volume_source_mute_power(
        self, entity: TriadAmsMediaPlayer, output: TriadAmsOutput
    ) -> None:
        """Volume, source, mute, and power are seeded from the saved state."""
        entity.async_get_last_state = create_async_mock_method(
            return_value=_saved_state(
                MediaPlayerState.PLAYING,
                {
                    "volume_level": 0.35,
                    "is_volume_muted": True,
                    "input_channel": 2,
                    "output_channel": 1,
                },
            )
        )
        await entity.async_added_to_hass()
        await _drain_tasks(entity, run=False)

        assert entity.volume_level == 0.35
        assert entity.is_volume_muted is True
        assert entity.source == "Input 2"
        assert entity.is_on is True
        assert entity.state == MediaPlayerState.ON
        # Remembered source survives so turn_on can restore it later
        assert output._last_assigned_input == 2

    async def test_restores_off_state(self, entity: TriadAmsMediaPlayer) -> None:
        """An output saved as off restores as off with its last volume."""
        entity.async_get_last_state = create_async_mock_method(
            return_value=_saved_state(
                MediaPlayerState.OFF,
                {"volume_level": 0.2, "is_volume_muted": False, "input_channel": None},
            )
        )
        await entity.async_added_to_hass()
        await _drain_tasks(entity, run=False)

        assert entity.is_on is False
        assert entity.state == MediaPlayerState.OFF
        assert entity.volume_level == 0.2

    async def test_no_device_writes_from_restoration(
        self, entity: TriadAmsMediaPlayer, mock_coordinator: MagicMock
    ) -> None:
        """Restoration never sends commands to the device."""
        entity.async_get_last_state = create_async_mock_method(
            return_value=_saved_state(
                MediaPlayerState.ON,
                {"volume_level": 0.35, "is_volume_muted": True, "input_channel": 2},
            )
        )
        await entity.async_added_to_hass()
        await _drain_tasks(entity, run=False)

        for method in WRITE_METHODS:
            assert not getattr(mock_coordinator, method).called

    async def test_linked_media_metadata_not_restored(
        self, entity: TriadAmsMediaPlayer
    ) -> None:
        """Media metadata from the linked source re-derives live, not restored."""
        entity.async_get_last_state = create_async_mock_method(
            return_value=_saved_state(
                MediaPlayerState.PLAYING,
                {
                    "volume_level": 0.5,
                    "input_channel": 1,
                    "media_title": "Stale Song",
                    "media_artist": "Stale Artist",
                    "media_album_name": "Stale Album",
                    "entity_picture": "http://example.com/stale.jpg",
                },
            )
        )
        await entity.async_added_to_hass()
        await _drain_tasks(entity, run=False)

        assert entity.media_title is None
        assert entity.media_artist is None
        assert entity.media_album_name is None
        assert entity.entity_picture is None

    async def test_availability_logic_unchanged(
        self,
        entity: TriadAmsMediaPlayer,
        output: TriadAmsOutput,
        mock_coordinator: MagicMock,
    ) -> None:
        """Restored snapshot is seeded even when the device is unreachable."""
        mock_coordinator.is_available = False
        entity.async_get_last_state = create_async_mock_method(
            return_value=_saved_state(
                MediaPlayerState.ON,
                {"volume_level": 0.35, "is_volume_muted": True, "input_channel": 2},
            )
        )
        await entity.async_added_to_hass()
        await _drain_tasks(entity, run=False)

        # Normal availability handling still decides availability
        assert entity.available is False
        # The snapshot is retained for when the device comes back
        assert output.volume == 0.35
        assert output.muted is True
        assert output.source == 2


class TestFirstPollWins:
    """The first successful device poll overwrites restored state."""

    async def test_conflicting_device_state_wins(
        self, entity: TriadAmsMediaPlayer, mock_coordinator: MagicMock
    ) -> None:
        """Device truth replaces a conflicting restored snapshot."""
        mock_coordinator.get_output_volume.return_value = 0.5
        mock_coordinator.get_output_mute.return_value = False
        mock_coordinator.get_output_source.return_value = 1
        entity.async_get_last_state = create_async_mock_method(
            return_value=_saved_state(
                MediaPlayerState.ON,
                {"volume_level": 0.35, "is_volume_muted": True, "input_channel": 2},
            )
        )
        await entity.async_added_to_hass()
        # Restored values visible pre-poll
        assert entity.volume_level == 0.35
        assert entity.source == "Input 2"

        await _drain_tasks(entity, run=True)

        assert entity.volume_level == 0.5
        assert entity.is_volume_muted is False
        assert entity.source == "Input 1"
        assert entity.is_on is True

    async def test_agreeing_device_state_confirmed(
        self, entity: TriadAmsMediaPlayer, mock_coordinator: MagicMock
    ) -> None:
        """When device state matches the snapshot, values are unchanged."""
        mock_coordinator.get_output_volume.return_value = 0.35
        mock_coordinator.get_output_mute.return_value = True
        mock_coordinator.get_output_source.return_value = 2
        entity.async_get_last_state = create_async_mock_method(
            return_value=_saved_state(
                MediaPlayerState.ON,
                {"volume_level": 0.35, "is_volume_muted": True, "input_channel": 2},
            )
        )
        await entity.async_added_to_hass()
        await _drain_tasks(entity, run=True)

        assert entity.volume_level == 0.35
        assert entity.is_volume_muted is True
        assert entity.source == "Input 2"
        assert entity.is_on is True

    async def test_device_off_overrides_restored_on(
        self, entity: TriadAmsMediaPlayer, mock_coordinator: MagicMock
    ) -> None:
        """A disconnected output on the device wins over a restored 'on'."""
        mock_coordinator.get_output_source.return_value = 0
        entity.async_get_last_state = create_async_mock_method(
            return_value=_saved_state(
                MediaPlayerState.ON,
                {"volume_level": 0.35, "input_channel": 2},
            )
        )
        await entity.async_added_to_hass()
        assert entity.is_on is True

        await _drain_tasks(entity, run=True)

        assert entity.is_on is False
        assert entity.source is None


class TestNoSavedState:
    """Fresh installs behave exactly as before restoration existed."""

    async def test_no_saved_state(self, entity: TriadAmsMediaPlayer) -> None:
        """With no saved state the entity starts with unknown values."""
        entity.async_get_last_state = create_async_mock_method(return_value=None)
        await entity.async_added_to_hass()
        await _drain_tasks(entity, run=False)

        assert entity.volume_level is None
        assert entity.is_volume_muted is False
        assert entity.source is None
        assert entity.is_on is False

    @pytest.mark.parametrize("saved", ["unknown", "unavailable"])
    async def test_unknown_or_unavailable_saved_state_ignored(
        self, entity: TriadAmsMediaPlayer, saved: str
    ) -> None:
        """Saved unknown/unavailable states are not used for seeding."""
        entity.async_get_last_state = create_async_mock_method(
            return_value=_saved_state(saved, {"volume_level": 0.9})
        )
        await entity.async_added_to_hass()
        await _drain_tasks(entity, run=False)

        assert entity.volume_level is None
        assert entity.is_on is False

    async def test_known_device_state_skips_restoration(
        self, entity: TriadAmsMediaPlayer, output: TriadAmsOutput
    ) -> None:
        """If device state is already known, the snapshot is not applied."""
        output._volume = 0.7
        entity.async_get_last_state = create_async_mock_method(
            return_value=_saved_state(MediaPlayerState.ON, {"volume_level": 0.2})
        )
        await entity.async_added_to_hass()
        await _drain_tasks(entity, run=False)

        assert entity.volume_level == 0.7
        assert not entity.async_get_last_state.called


class TestMalformedSavedState:
    """Malformed saved attributes are ignored without errors."""

    async def test_garbage_attributes_ignored(
        self, entity: TriadAmsMediaPlayer
    ) -> None:
        """Non-numeric or out-of-range attributes are dropped."""
        entity.async_get_last_state = create_async_mock_method(
            return_value=_saved_state(
                MediaPlayerState.ON,
                {
                    "volume_level": "loud",
                    "is_volume_muted": "yes",
                    "input_channel": "three",
                },
            )
        )
        await entity.async_added_to_hass()
        await _drain_tasks(entity, run=False)

        assert entity.volume_level is None
        assert entity.is_volume_muted is False
        assert entity.source is None
        # The valid state string still seeds power
        assert entity.is_on is True

    async def test_out_of_range_values_clamped_or_dropped(
        self, entity: TriadAmsMediaPlayer
    ) -> None:
        """Out-of-range volume clamps; out-of-range input is dropped."""
        entity.async_get_last_state = create_async_mock_method(
            return_value=_saved_state(
                MediaPlayerState.ON,
                {"volume_level": 1.5, "input_channel": 99},
            )
        )
        await entity.async_added_to_hass()
        await _drain_tasks(entity, run=False)

        assert entity.volume_level == 1.0
        assert entity.source is None
