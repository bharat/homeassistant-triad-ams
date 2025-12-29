"""MediaPlayer platform for Triad AMS outputs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant, ServiceValidationError, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .models import TriadAmsOutput

_LOGGER = logging.getLogger(__name__)


def _build_input_names(
    hass: HomeAssistant,
    active_inputs: list[int],
    input_links_opt: dict[str, str],
) -> dict[int, str]:
    """Build input names dict from linked entities or defaults."""
    input_names: dict[int, str] = {}
    for i in active_inputs:
        ent_id = input_links_opt.get(str(i))
        if ent_id:
            st = hass.states.get(ent_id)
            if st:
                input_names[i] = st.name
                continue
        input_names[i] = f"Input {i}"
    return input_names


@callback
def _update_input_name_from_state(
    hass: HomeAssistant,
    input_num: int,
    entity_id: str,
    input_names: dict[int, str],
    entities: list[TriadAmsMediaPlayer],
) -> None:
    """Update input name from entity state and notify entities."""
    new_state = hass.states.get(entity_id)
    if new_state and new_state.name:
        old_name = input_names.get(input_num, f"Input {input_num}")
        new_name = new_state.name
        if old_name != new_name:
            _LOGGER.debug(
                "Updating input %d name from '%s' to '%s' (entity: %s)",
                input_num,
                old_name,
                new_name,
                entity_id,
            )
            input_names[input_num] = new_name
            for entity in entities:
                entity.async_write_ha_state()


@callback
def _create_input_link_handler(
    hass: HomeAssistant,
    input_links_opt: dict[str, str],
    active_inputs: list[int],
    input_names: dict[int, str],
    entities: list[TriadAmsMediaPlayer],
) -> Any:
    """Create callback handler for input link state changes."""

    @callback
    def _handle_input_link_state_change(event: Any) -> None:
        """Handle state changes from linked input entities."""
        entity_id = event.data.get("entity_id")
        if not entity_id:
            return

        # Find which input number this entity is linked to
        input_num = None
        for input_str, linked_ent_id in input_links_opt.items():
            if linked_ent_id == entity_id:
                try:
                    input_num = int(input_str)
                    break
                except ValueError:
                    continue

        if input_num is None or input_num not in active_inputs:
            return

        _update_input_name_from_state(hass, input_num, entity_id, input_names, entities)

    return _handle_input_link_state_change


def _setup_input_link_subscriptions(  # noqa: PLR0913
    hass: HomeAssistant,
    coordinator: Any,
    input_links_opt: dict[str, str],
    active_inputs: list[int],
    input_names: dict[int, str],
    entities: list[TriadAmsMediaPlayer],
) -> None:
    """Set up subscriptions to linked entity state changes."""
    linked_entity_ids = [ent_id for ent_id in input_links_opt.values() if ent_id]
    if not linked_entity_ids:
        return

    handler = _create_input_link_handler(
        hass, input_links_opt, active_inputs, input_names, entities
    )
    unsub = async_track_state_change_event(hass, linked_entity_ids, handler)

    # Store unsubscribe function to clean up on unload
    # Accessing private member is intentional for cleanup tracking
    if not hasattr(coordinator, "_input_link_unsubs"):
        coordinator._input_link_unsubs = []  # noqa: SLF001
    coordinator._input_link_unsubs.append(unsub)  # noqa: SLF001

    # Check immediately for any entities that might have become available
    for i in active_inputs:
        ent_id = input_links_opt.get(str(i))
        if ent_id and (
            i not in input_names or input_names.get(i, "").startswith("Input ")
        ):
            _update_input_name_from_state(hass, i, ent_id, input_names, entities)


def _cleanup_stale_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    outputs: list[TriadAmsOutput],
) -> None:
    """Remove stale entities for outputs that are no longer active."""
    allowed = {f"{entry.entry_id}_output_{o.number}" for o in outputs}
    registry = er.async_get(hass)
    for ent in list(registry.entities.values()):
        if (
            ent.platform == DOMAIN
            and ent.config_entry_id == entry.entry_id
            and ent.unique_id not in allowed
        ):
            registry.async_remove(ent.entity_id)


def _remove_orphaned_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Remove orphaned devices (those without any entities for this entry)."""
    registry = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    for device in list(dev_reg.devices.values()):
        if entry.entry_id not in device.config_entries:
            continue
        if not er.async_entries_for_device(
            registry, device.id, include_disabled_entities=True
        ):
            dev_reg.async_remove_device(device.id)


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
    # Use the coordinator attached by __init__.py in entry.runtime_data
    coordinator = entry.runtime_data

    # Use only the minimal active channel lists from options
    active_inputs: list[int] = entry.options.get("active_inputs", [])
    active_outputs: list[int] = entry.options.get("active_outputs", [])

    input_links_opt: dict[str, str] = entry.options.get("input_links", {})
    input_names = _build_input_names(hass, active_inputs, input_links_opt)
    input_links: dict[int, str | None] = {
        i: input_links_opt.get(str(i)) for i in active_inputs
    }

    outputs: list[TriadAmsOutput] = []
    for ch in sorted(active_outputs):
        name = f"Output {ch}"
        outputs.append(TriadAmsOutput(ch, name, coordinator, outputs, input_names))

    # Ensure coordinator worker is running before any refresh enqueues commands
    try:
        await coordinator.start()
    except Exception:
        _LOGGER.exception("Failed to start TriadCoordinator")

    # Register outputs for lightweight rolling polling
    for output in outputs:
        coordinator.register_output(output)

    entities = [TriadAmsMediaPlayer(output, entry, input_links) for output in outputs]
    async_add_entities(entities)
    _LOGGER.debug(
        "Entities added to Home Assistant: %s", [e.unique_id for e in entities]
    )

    _setup_input_link_subscriptions(
        hass, coordinator, input_links_opt, active_inputs, input_names, entities
    )
    _cleanup_stale_entities(hass, entry, outputs)
    _remove_orphaned_devices(hass, entry)


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
        self._output_unsub: callable | None = None
        self._options = entry.options
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

    @callback
    def _handle_output_poll_update(self) -> None:
        """Handle updates from the rolling poll (volume/mute/source changes)."""
        self._update_link_subscription()
        self.async_write_ha_state()

    def _linked_attr(self, key: str) -> Any | None:
        if not self._linked_entity_id or self.hass is None:
            return None
        st = self.hass.states.get(self._linked_entity_id)
        if not st:
            return None
        return st.attributes.get(key)

    # ---- Media info ----
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

    # ---- Core media player properties and commands ----
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

    async def async_select_source(self, source: str) -> None:
        """Select a source by friendly name."""
        input_id = self.output.source_id_for_name(source)
        if input_id is not None:
            _LOGGER.info(
                "Selecting source '%s' for output %d",
                source,
                self.output.number,
            )
            await self.output.set_source(input_id)
            # Update link subscription first so derived attributes reflect
            # the new linked source on this state write.
            self._update_link_subscription()
            self.async_write_ha_state()
        else:
            _LOGGER.error("Unknown source name: %s", source)

    async def async_added_to_hass(self) -> None:
        """Entity added to Home Assistant: seed and write initial state."""
        self._update_link_subscription()
        # Subscribe first so any async refresh updates the state when done
        self._output_unsub = self.output.add_listener(self._handle_output_poll_update)
        # Queue an initial refresh without blocking entity setup
        if self.hass is not None:
            self.hass.async_create_task(self.output.refresh_and_notify())
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Entity will be removed from Home Assistant: clean up."""
        if self._output_unsub is not None:
            self._output_unsub()
            self._output_unsub = None

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume level of the output (0..1)."""
        _LOGGER.info("Setting volume for output %d to %.2f", self.output.number, volume)
        await self.output.set_volume(volume)
        self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:  # noqa: FBT001
        """Mute or unmute the output."""
        _LOGGER.info("Setting mute for output %d to %s", self.output.number, mute)
        await self.output.set_muted(mute)
        self.async_write_ha_state()

    async def async_volume_up(self) -> None:
        """Step the volume up one unit."""
        _LOGGER.info("Volume UP (step) on output %d", self.output.number)
        await self.output.volume_up_step(large=False)
        await self.output.refresh()
        self.async_write_ha_state()

    async def async_volume_down(self) -> None:
        """Step the volume down one unit."""
        _LOGGER.info("Volume DOWN (step) on output %d", self.output.number)
        await self.output.volume_down_step(large=False)
        await self.output.refresh()
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        """Turn off the output (disconnect from any input)."""
        _LOGGER.info("Turning OFF output %d", self.output.number)
        await self.output.turn_off()
        # Unsubscribe before writing state so we don't expose linked metadata
        # while the output is off.
        self._update_link_subscription()
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Turn on the player in UI without routing a source."""
        _LOGGER.info("Turning ON output %d", self.output.number)
        await self.output.turn_on()
        self._update_link_subscription()
        self.async_write_ha_state()

    async def async_turn_on_with_source(self, input_entity_id: str) -> None:
        """Turn on this output and route the given source."""
        # Map input entity ID to input number
        input_links = self._input_links
        source = None
        for input_str, linked_entity_id in input_links.items():
            if linked_entity_id == input_entity_id:
                try:
                    source = int(input_str)
                    break
                except ValueError:
                    pass

        if source is None:
            msg = f"Input entity {input_entity_id} is not linked in integration options"
            raise ValueError(msg)

        if source not in self._options.get("active_inputs", []):
            msg = f"Input {source} is not active"
            raise ServiceValidationError(msg)

        await self.output.set_source(source)
        await self.output.turn_on()
        self._update_link_subscription()
        self.async_write_ha_state()
