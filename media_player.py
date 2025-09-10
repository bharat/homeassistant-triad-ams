"""MediaPlayer platform for Triad AMS outputs."""
from __future__ import annotations
import logging
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .coordinator import TriadAmsCoordinator
from .models import TriadAmsOutput

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: TriadAmsCoordinator = entry.runtime_data
    entities = [
        TriadAmsOutputMediaPlayer(coordinator, output)
        for output in coordinator.data.get("outputs", [])
    ]
    async_add_entities(entities)

class TriadAmsOutputMediaPlayer(CoordinatorEntity[TriadAmsCoordinator], MediaPlayerEntity):
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON |
        MediaPlayerEntityFeature.TURN_OFF |
        MediaPlayerEntityFeature.VOLUME_SET
    )
    _attr_has_entity_name = True

    def __init__(self, coordinator: TriadAmsCoordinator, output: TriadAmsOutput) -> None:
        super().__init__(coordinator)
        self.output = output
        self._attr_unique_id = f"triad_ams_output_{output.number}"
        self._attr_name = output.name

    @property
    def is_on(self) -> bool:
        return self.output.is_on

    @property
    def volume_level(self) -> float | None:
        return self.output.volume

    async def async_turn_on(self) -> None:
        await self.coordinator.client.async_set_output(self.output.number, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        await self.coordinator.client.async_set_output(self.output.number, False)
        await self.coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float) -> None:
        await self.coordinator.client.async_set_volume(self.output.number, volume)
        await self.coordinator.async_request_refresh()
