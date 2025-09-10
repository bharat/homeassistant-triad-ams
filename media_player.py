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
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import TriadAmsCoordinator
from .models import TriadAmsOutput

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Triad AMS media player entities from a config entry."""
    coordinator: TriadAmsCoordinator = entry.runtime_data
    entities = [
        TriadAmsMediaPlayer(coordinator, output)
        for output in coordinator.data.get("outputs", [])
    ]
    async_add_entities(entities)


class TriadAmsMediaPlayer(CoordinatorEntity[TriadAmsCoordinator], MediaPlayerEntity):
    """Media player entity representing a Triad AMS output."""

    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
    )
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: TriadAmsCoordinator, output: TriadAmsOutput
    ) -> None:
        """Initialize a Triad AMS output media player entity.

        Args:
            coordinator: The Triad AMS data update coordinator.
            output: The Triad AMS output model for this entity.
        """
        super().__init__(coordinator)
        self.output = output
        self._attr_unique_id = f"triad_ams_output_{output.number}"
        self._attr_name = output.name

    @property
    def is_on(self) -> bool:  # noqa: D102
        return self.output.is_on

    @property
    def volume_level(self) -> float | None:  # noqa: D102
        return self.output.volume

    async def async_turn_on(self) -> None:  # noqa: D102
        await self.coordinator.client.async_set_output(self.output.number, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:  # noqa: D102
        await self.coordinator.client.async_set_output(self.output.number, False)
        await self.coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float) -> None:  # noqa: D102
        await self.coordinator.client.async_set_volume(self.output.number, volume)
        await self.coordinator.async_request_refresh()
