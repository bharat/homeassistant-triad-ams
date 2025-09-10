"""MediaPlayer platform for Triad AMS outputs."""

from __future__ import annotations

import logging

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from .models import TriadAmsOutput
from .connection import TriadConnection

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Triad AMS media player entities from a config entry."""
    # For now, create outputs from config entry options
    connection = hass.data.setdefault("triad_ams_connection", None)
    if connection is None:
        connection = TriadConnection(entry.data["host"], entry.data["port"])
        hass.data["triad_ams_connection"] = connection
    output_names = entry.options.get("outputs", [f"Output {i + 1}" for i in range(8)])
    outputs = [
        TriadAmsOutput(i + 1, output_names[i], connection)
        for i in range(len(output_names))
    ]
    entities = [TriadAmsMediaPlayer(output) for output in outputs]
    async_add_entities(entities)


class TriadAmsMediaPlayer(MediaPlayerEntity):
    """Media player entity representing a Triad AMS output."""

    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
    )
    _attr_has_entity_name = True

    def __init__(self, output: TriadAmsOutput) -> None:
        """Initialize a Triad AMS output media player entity."""
        self.output = output
        self._attr_unique_id = f"triad_ams_output_{output.number}"
        self._attr_name = output.name

    @property
    def is_on(self) -> bool:
        """Return True if the output is on."""
        return self.output.is_on

    @property
    def volume_level(self) -> float | None:
        """Return the volume level of the output."""
        return self.output.volume

    async def async_turn_on(self) -> None:
        """Turn on the output."""
        await self.output.set_is_on(True)

    async def async_turn_off(self) -> None:
        """Turn off the output."""
        await self.output.set_is_on(False)

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume level of the output."""
        await self.output.set_volume(volume)
