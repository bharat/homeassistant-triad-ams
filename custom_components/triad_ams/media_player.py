"""MediaPlayer platform for Triad AMS outputs."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .connection import TriadConnection
from .const import DOMAIN
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
            "No runtime connection found; creating TriadConnection for host=%s, "
            "port=%s",
            entry.data["host"],
            entry.data["port"],
        )
        connection = TriadConnection(entry.data["host"], entry.data["port"])
        entry.runtime_data = connection

    # Use only the minimal active channel lists from options
    active_inputs: list[int] = entry.options.get("active_inputs", [])
    active_outputs: list[int] = entry.options.get("active_outputs", [])

    input_links_opt: dict[str, str] = entry.options.get("input_links", {})
    # Use linked entity friendly names when available
    input_names: dict[int, str] = {}
    for i in active_inputs:
        ent_id = input_links_opt.get(str(i))
        if ent_id:
            st = hass.states.get(ent_id)
            if st:
                input_names[i] = st.name
                continue
        input_names[i] = f"Input {i}"
    input_links: dict[int, str | None] = {
        i: input_links_opt.get(str(i)) for i in active_inputs
    }

    outputs: list[TriadAmsOutput] = []
    for ch in sorted(active_outputs):
        name = f"Output {ch}"
        outputs.append(TriadAmsOutput(ch, name, connection, outputs, input_names))

    await asyncio.gather(*(output.refresh() for output in outputs))
    entities = [TriadAmsMediaPlayer(output, entry, input_links) for output in outputs]
    async_add_entities(entities)
    _LOGGER.debug(
        "Entities added to Home Assistant: %s", [e.unique_id for e in entities]
    )
    # Cleanup stale entities for outputs that are no longer active
    allowed = {f"{entry.entry_id}_output_{o.number}" for o in outputs}
    registry = er.async_get(hass)
    for ent in list(registry.entities.values()):
        if (
            ent.platform == DOMAIN
            and ent.config_entry_id == entry.entry_id
            and ent.unique_id not in allowed
        ):
            registry.async_remove(ent.entity_id)

    # Remove orphaned devices (those without any entities for this entry)
    dev_reg = dr.async_get(hass)
    for device in list(dev_reg.devices.values()):
        if entry.entry_id not in device.config_entries:
            continue
        if not er.async_entries_for_device(
            registry, device.id, include_disabled_entities=True
        ):
            dev_reg.async_remove_device(device.id)


class TriadAmsMediaPlayer(MediaPlayerEntity):
    """Media player entity representing a Triad AMS output."""

    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        output: TriadAmsOutput,
        entry: ConfigEntry,
        input_links: dict[int, str | None],
    ) -> None:
        """Initialize a Triad AMS output media player entity."""
        self.output = output
        self._input_links = input_links
        self._linked_entity_id: str | None = None
        self._linked_unsub: callable | None = None
        # Keep per-entry unique entity IDs stable
        self._attr_unique_id = f"{entry.entry_id}_output_{output.number}"
        # Entity name part; with has_entity_name this becomes the suffix
        self._attr_name = f"Output {output.number}"
        self._attr_has_entity_name = True
        self._attr_device_class = MediaPlayerDeviceClass.SPEAKER
        # Group all outputs under one device per config entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "Triad",
            "model": "Audio Matrix",
        }

    # ---- Optional linked upstream media attribute proxying ----
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
        if self._linked_unsub is not None:
            self._linked_unsub()
            self._linked_unsub = None
        self._linked_entity_id = desired
        if desired and self.hass is not None:
            # Register a thread-safe callback on the event loop, not in an executor
            self._linked_unsub = async_track_state_change_event(
                self.hass, [desired], self._handle_linked_state_change
            )

    @callback
    def _handle_linked_state_change(self, _event: object) -> None:
        """Handle state changes from the linked source entity on the event loop."""
        self.async_write_ha_state()

    def _linked_attr(self, key: str) -> Any | None:
        if not self._linked_entity_id or self.hass is None:
            return None
        st = self.hass.states.get(self._linked_entity_id)
        if not st:
            return None
        return st.attributes.get(key)

    @property
    def media_title(self) -> str | None:
        """Return the current media title from the linked source, if any."""
        return self._linked_attr("media_title")

    @property
    def media_artist(self) -> str | None:
        """Return the media artist from the linked source, if any."""
        return self._linked_attr("media_artist")

    @property
    def media_album_name(self) -> str | None:
        """Return the media album from the linked source, if any."""
        return self._linked_attr("media_album_name")

    @property
    def media_duration(self) -> int | None:
        """Return the media duration (seconds) from the linked source, if any."""
        return self._linked_attr("media_duration")

    @property
    def media_content_id(self) -> str | None:
        """Return the media content id from the linked source, if any."""
        return self._linked_attr("media_content_id")

    @property
    def media_content_type(self) -> str | None:
        """Return the media content type from the linked source, if any."""
        return self._linked_attr("media_content_type")

    @property
    def entity_picture(self) -> str | None:
        """Return the artwork URL from the linked source, if any."""
        return self._linked_attr("entity_picture")

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
            # Update link subscription first so derived attributes reflect
            # the new linked source on this state write.
            self._update_link_subscription()
            self.async_write_ha_state()
        else:
            _LOGGER.error("Unknown source name: %s", source)

    async def async_added_to_hass(self) -> None:
        """Entity added to Home Assistant: write initial state."""
        self._update_link_subscription()
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return True if the output is on, False if off."""
        return self.output.is_on

    @property
    def volume_level(self) -> float | None:
        """Return the volume level of the output (0..1), or None if unknown."""
        return self.output.volume if self.output.volume is not None else None

    @property
    def is_volume_muted(self) -> bool | None:
        """Return True if the output is muted."""
        return self.output.muted

    async def async_turn_off(self) -> None:
        """Turn off the output (disconnect from any input)."""
        await self.output.turn_off()
        # Unsubscribe before writing state so we don't expose linked metadata
        # while the output is off.
        self._update_link_subscription()
        self.async_write_ha_state()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume level of the output (0..1)."""
        await self.output.set_volume(volume)
        self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:  # noqa: FBT001
        """Mute or unmute the output."""
        await self.output.set_muted(mute)
        self.async_write_ha_state()

    async def async_volume_up(self) -> None:
        """Step the volume up one unit."""
        await self.output.volume_up_step(large=False)
        await self.output.refresh()
        self.async_write_ha_state()

    async def async_volume_down(self) -> None:
        """Step the volume down one unit."""
        await self.output.volume_down_step(large=False)
        await self.output.refresh()
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Turn on the player in UI without routing a source."""
        await self.output.turn_on()
        self._update_link_subscription()
        self.async_write_ha_state()

    # No media attribute proxying in simplified flow
