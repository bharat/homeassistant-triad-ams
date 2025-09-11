"""MediaPlayer platform for Triad AMS outputs."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaPlayerDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .connection import TriadConnection
from .const import DOMAIN, INPUT_COUNT, OUTPUT_COUNT
from .models import TriadAmsOutput

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Triad AMS media player entities from a config entry."""
    _LOGGER.debug(
        "async_setup_entry called for Triad AMS: entry_id=%s, data=%s, options=%s",
        entry.entry_id,
        entry.data,
        entry.options,
    )
    # Use the connection attached by __init__.py in entry.runtime_data
    connection: TriadConnection = entry.runtime_data
    if connection is None:
        _LOGGER.debug(
            "No runtime connection found; creating TriadConnection for host=%s, port=%s",
            entry.data["host"],
            entry.data["port"],
        )
        connection = TriadConnection(entry.data["host"], entry.data["port"])
        entry.runtime_data = connection

    # New flexible options: maps of configured channels only
    inputs_cfg: dict[str, dict] = entry.options.get("inputs_config", {})
    outputs_cfg: dict[str, dict] = entry.options.get("outputs_config", {})
    # Build input names and links by channel
    input_names: dict[int, str] = {
        int(ch): cfg.get("name", f"Input {ch}") for ch, cfg in inputs_cfg.items()
    }
    input_links: dict[int, str | None] = {
        int(ch): cfg.get("link") for ch, cfg in inputs_cfg.items()
    }
    outputs: list[TriadAmsOutput] = []
    # Only create entities for configured outputs
    for ch_str, cfg in sorted(outputs_cfg.items(), key=lambda x: int(x[0])):
        ch = int(ch_str)
        name = cfg.get("name", f"Output {ch}")
        outputs.append(TriadAmsOutput(ch, name, connection, outputs, input_names))

    await asyncio.gather(*(output.refresh() for output in outputs))
    entities = [TriadAmsMediaPlayer(output, entry.entry_id, input_links) for output in outputs]
    async_add_entities(entities)
    _LOGGER.debug(
        "Entities added to Home Assistant: %s", [e.unique_id for e in entities]
    )


class TriadAmsMediaPlayer(MediaPlayerEntity):
    """Media player entity representing a Triad AMS output."""

    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, output: TriadAmsOutput, entry_id: str, input_links: dict[int, str | None]) -> None:
        """Initialize a Triad AMS output media player entity."""
        self.output = output
        self._input_links = input_links
        self._linked_entity_id: str | None = None
        self._linked_unsub: callable | None = None
        self._attr_unique_id = f"{entry_id}_output_{output.number}"
        self._attr_name = None  # Use device name only for friendly name
        self._attr_has_entity_name = True
        self._attr_device_class = MediaPlayerDeviceClass.SPEAKER
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry_id}_output_{output.number}")},
            "name": output.name,
            "manufacturer": "Triad",
            "model": "AMS Audio Matrix Switch",
        }

    @property
    def state(self) -> str:
        """Return the state of the entity (STATE_ON or STATE_OFF)."""
        return MediaPlayerState.ON if self.is_on else MediaPlayerState.OFF

    @property
    def source(self) -> str | None:
        """Return the current source name."""
        return self.output.source_name

    @property
    def source_list(self) -> list[str]:
        """Return the list of available source names."""
        return self.output.source_list

    async def async_select_source(self, source: str) -> None:
        """Select a source by friendly name."""
        input_id = self.output.source_id_for_name(source)
        if input_id is not None:
            await self.output.set_source(input_id)
            self.async_write_ha_state()
            self._update_link_subscription()
        else:
            _LOGGER.error("Unknown source name: %s", source)

    async def async_added_to_hass(self) -> None:
        """Entity added to Home Assistant: write initial state."""
        self.async_write_ha_state()
        self._update_link_subscription()

    @property
    def is_on(self) -> bool:
        """Return True if the output is on, False if off."""
        return self.output.is_on

    @property
    def volume_level(self) -> float | None:
        """Return the volume level of the output (0..1), or None if unknown."""
        return self.output.volume if self.output.volume is not None else None

    async def async_turn_off(self) -> None:
        """Turn off the output (disconnect from any input)."""
        await self.output.turn_off()
        self.async_write_ha_state()
        self._update_link_subscription()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume level of the output (0..1)."""
        await self.output.set_volume(volume)

    async def async_turn_on(self) -> None:
        """Turn on the player in UI without routing a source."""
        await self.output.turn_on()
        self.async_write_ha_state()
        self._update_link_subscription()

    # ---- Linked upstream media attribute proxying ----
    def _current_linked_entity_id(self) -> str | None:
        src = self.output.source
        if src is None:
            return None
        return self._input_links.get(src)

    @callback
    def _update_link_subscription(self) -> None:
        desired = self._current_linked_entity_id()
        if desired == self._linked_entity_id:
            return
        # Unsubscribe previous
        if self._linked_unsub is not None:
            self._linked_unsub()
            self._linked_unsub = None
        self._linked_entity_id = desired
        if desired and self.hass is not None:
            self._linked_unsub = async_track_state_change_event(
                self.hass, [desired], lambda event: self.async_write_ha_state()
            )

    def _linked_attr(self, key: str):
        if not self._linked_entity_id or self.hass is None:
            return None
        st = self.hass.states.get(self._linked_entity_id)
        if not st:
            return None
        return st.attributes.get(key)

    @property
    def media_title(self) -> str | None:
        return self._linked_attr("media_title")

    @property
    def media_artist(self) -> str | None:
        return self._linked_attr("media_artist")

    @property
    def media_album_name(self) -> str | None:
        return self._linked_attr("media_album_name")

    @property
    def media_duration(self) -> int | None:
        return self._linked_attr("media_duration")

    @property
    def media_content_id(self) -> str | None:
        return self._linked_attr("media_content_id")

    @property
    def media_content_type(self) -> str | None:
        return self._linked_attr("media_content_type")

    @property
    def entity_picture(self) -> str | None:
        return self._linked_attr("entity_picture")
