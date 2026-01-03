"""Input MediaPlayer entities for Triad AMS inputs."""

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
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN
from .models import TriadAmsInput  # noqa: TC001 - used at runtime in __init__

_LOGGER = logging.getLogger(__name__)


class InvalidGroupMemberError(HomeAssistantError):
    """Error raised when a group member is not a valid Triad AMS output."""

    translation_key = "invalid_group_member"


class TriadAmsInputMediaPlayer(MediaPlayerEntity):
    """Media player entity that proxies a linked input media_player."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    PARALLEL_UPDATES = 1

    def __init__(
        self,
        input_model: TriadAmsInput,
        entry: ConfigEntry,
        group_members: list[str] | None = None,
    ) -> None:
        """Initialize a Triad AMS input proxy media player entity."""
        self.input = input_model
        self._group_members = group_members or []
        self._attr_unique_id = f"{entry.entry_id}_input_{input_model.number}"
        self._attr_name = input_model.name
        self._attr_has_entity_name = True
        self._attr_device_class = MediaPlayerDeviceClass.RECEIVER
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "Triad",
            "model": "Audio Matrix",
        }
        self._linked_unsub: callable | None = None
        self._attr_available = True  # Track availability (Silver requirement)
        self._availability_unsub: callable | None = None

    @callback
    def _handle_linked_state_change(self, _event: object) -> None:
        """Handle state changes from the linked source entity on the event loop."""
        self.async_write_ha_state()

    @callback
    def _update_availability(self, *, is_available: bool) -> None:
        """Handle coordinator availability changes (Silver requirement)."""
        if self._attr_available == is_available:
            return
        self._attr_available = is_available
        _LOGGER.info(
            "Triad AMS input %d %s",
            self.input.number,
            "available" if is_available else "unavailable",
        )
        # Only write state if hass is set (entity is added to hass)
        if self.hass is not None:
            self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        # Check coordinator availability directly (Silver requirement)
        coordinator = getattr(self.input, "coordinator", None)
        if coordinator is not None and hasattr(coordinator, "is_available"):
            # is_available is a property, access it and ensure boolean
            avail = coordinator.is_available
            # Handle both property access and MagicMock return_value
            if callable(avail):
                return bool(avail())
            return bool(avail)
        return self._attr_available

    @property
    def state(self) -> str:
        """Proxy linked entity state (ON/OFF)."""
        if not self.input.linked_entity_id or self.hass is None:
            return MediaPlayerState.OFF
        st = self.hass.states.get(self.input.linked_entity_id)
        if not st or st.state == "unknown":
            return MediaPlayerState.OFF
        return st.state

    @property
    def supported_features(self) -> int:
        """Proxy supported features from the linked entity and add grouping support."""
        linked_features = 0
        if self.input.linked_entity_id and self.hass is not None:
            st = self.hass.states.get(self.input.linked_entity_id)
            if st:
                linked_features = int(st.attributes.get("supported_features", 0))
        volume_flags = (
            MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.VOLUME_STEP
        )
        # Inputs are proxies, so remove volume control features;
        # volume should only be adjusted on the physical outputs/speakers.
        return (linked_features & ~volume_flags) | MediaPlayerEntityFeature.GROUPING

    @property
    def group_members(self) -> list[str] | None:
        """Return combined group members from linked entity and output entities."""
        members = list(self._group_members) if self._group_members else []
        _LOGGER.debug("%s - Current group members: %s", self._attr_name, members)

        # Add linked entity's group members
        if self.input.linked_entity_id and self.hass is not None:
            st = self.hass.states.get(self.input.linked_entity_id)
            if st:
                linked_members = st.attributes.get("group_members")
                if linked_members:
                    _LOGGER.debug(
                        "%s - Adding linked group members: %s",
                        self._attr_name,
                        linked_members,
                    )
                    members.extend(linked_members)

        return members if members else None

    @group_members.setter
    def group_members(self, members: list[str]) -> None:
        """Set the list of group members."""
        self._group_members = members

    @property
    def group_leader(self) -> bool:
        """Return whether input is a group leader."""
        return len(self._group_members) > 0

    def _linked_attr(self, key: str) -> Any | None:
        if not self.input.linked_entity_id or self.hass is None:
            return None
        st = self.hass.states.get(self.input.linked_entity_id)
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

    @property
    def shuffle(self) -> bool | None:
        """Return the shuffle state from the linked source, if any."""
        return self._linked_attr("shuffle")

    @property
    def repeat(self) -> str | None:
        """Return the repeat mode from the linked source, if any."""
        return self._linked_attr("repeat")

    @property
    def sound_mode(self) -> str | None:
        """Return the current sound mode from the linked source, if any."""
        return self._linked_attr("sound_mode")

    @property
    def sound_mode_list(self) -> list[str] | None:
        """Return the list of available sound modes from the linked source, if any."""
        return self._linked_attr("sound_mode_list")

    async def async_added_to_hass(self) -> None:
        """Subscribe to linked entity state changes and coordinator availability."""
        if self.input.linked_entity_id and self.hass is not None:
            self._linked_unsub = async_track_state_change_event(
                self.hass,
                [self.input.linked_entity_id],
                self._handle_linked_state_change,
            )

        # Subscribe to coordinator availability changes (Silver requirement)
        if hasattr(self.input, "coordinator") and self.input.coordinator is not None:
            self._availability_unsub = (
                self.input.coordinator.register_availability_listener(
                    self._update_availability
                )
            )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from linked entity state changes and availability updates."""
        if self._linked_unsub is not None:
            self._linked_unsub()
            self._linked_unsub = None
        if self._availability_unsub is not None:
            self._availability_unsub()
            self._availability_unsub = None

    async def async_join_players(self, group_members: list[str]) -> None:
        """Route provided output players to this input."""
        if self.hass is None:
            return
        if not group_members:
            # Empty list means unjoin all members
            self._group_members = []
            self.async_write_ha_state()
            return

        registry = er.async_get(self.hass)

        # Group members by domain/platform
        members_by_domain: dict[str, list[str]] = {}
        for member in group_members:
            entry = registry.async_get(member)
            if entry is None:
                raise InvalidGroupMemberError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_group_member",
                    translation_placeholders={"entity_id": member},
                )

            domain = entry.platform
            if domain not in members_by_domain:
                members_by_domain[domain] = []
            members_by_domain[domain].append(member)

        # Process Triad AMS outputs - route to this input
        triad_members = members_by_domain.pop(DOMAIN, [])
        if triad_members:
            tasks = [
                self.hass.services.async_call(
                    DOMAIN,
                    "turn_on_with_source",
                    {
                        "entity_id": member,
                        "input_entity_id": self.entity_id,
                    },
                    blocking=True,
                )
                for member in triad_members
            ]
            await asyncio.gather(*tasks)

        # Process other domains - delegate to linked entity if same domain
        for domain, members in members_by_domain.items():
            # Only allow domains that match the linked entity's domain
            if not self.input.linked_entity_id:
                raise InvalidGroupMemberError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_group_member",
                    translation_placeholders={"entity_id": members[0]},
                )

            linked_entry = registry.async_get(self.input.linked_entity_id)
            if not linked_entry or linked_entry.platform != domain:
                raise InvalidGroupMemberError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_group_member",
                    translation_placeholders={"entity_id": members[0]},
                )

            # Delegate to linked entity's join service if it supports grouping
            linked_state = self.hass.states.get(self.input.linked_entity_id)
            if (
                linked_state
                and linked_state.attributes.get("supported_features", 0)
                & MediaPlayerEntityFeature.GROUPING
            ):
                await self.hass.services.async_call(
                    "media_player",
                    "join",
                    {
                        "entity_id": self.input.linked_entity_id,
                        "group_members": members,
                    },
                    blocking=True,
                )

        # Replace the group members list (don't merge)
        self._group_members = list(group_members)
        self.async_write_ha_state()

    # The unjoin operation lives on member entities (TriadAmsMediaPlayer).

    # ---- Media playback control proxying ----
    async def async_media_play(self) -> None:
        """Proxy play command to linked entity."""
        if not self.input.linked_entity_id or self.hass is None:
            return
        await self.hass.services.async_call(
            "media_player",
            "media_play",
            {"entity_id": self.input.linked_entity_id},
            blocking=False,
        )

    async def async_media_pause(self) -> None:
        """Proxy pause command to linked entity."""
        if not self.input.linked_entity_id or self.hass is None:
            return
        await self.hass.services.async_call(
            "media_player",
            "media_pause",
            {"entity_id": self.input.linked_entity_id},
            blocking=False,
        )

    async def async_media_stop(self) -> None:
        """Proxy stop command to linked entity."""
        if not self.input.linked_entity_id or self.hass is None:
            return
        await self.hass.services.async_call(
            "media_player",
            "media_stop",
            {"entity_id": self.input.linked_entity_id},
            blocking=False,
        )

    async def async_media_next_track(self) -> None:
        """Proxy next track command to linked entity."""
        if not self.input.linked_entity_id or self.hass is None:
            return
        await self.hass.services.async_call(
            "media_player",
            "media_next_track",
            {"entity_id": self.input.linked_entity_id},
            blocking=False,
        )

    async def async_media_previous_track(self) -> None:
        """Proxy previous track command to linked entity."""
        if not self.input.linked_entity_id or self.hass is None:
            return
        await self.hass.services.async_call(
            "media_player",
            "media_previous_track",
            {"entity_id": self.input.linked_entity_id},
            blocking=False,
        )

    async def async_media_seek(self, position: float) -> None:
        """Proxy seek command to linked entity."""
        if not self.input.linked_entity_id or self.hass is None:
            return
        await self.hass.services.async_call(
            "media_player",
            "media_seek",
            {"entity_id": self.input.linked_entity_id, "seek_position": position},
            blocking=False,
        )

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs: Any
    ) -> None:
        """Proxy play media command to linked entity."""
        if not self.input.linked_entity_id or self.hass is None:
            return
        await self.hass.services.async_call(
            "media_player",
            "play_media",
            {
                "entity_id": self.input.linked_entity_id,
                "media_content_type": media_type,
                "media_content_id": media_id,
                **kwargs,
            },
            blocking=False,
        )

    async def async_select_source(self, source: str) -> None:
        """Proxy source selection to linked entity."""
        if not self.input.linked_entity_id or self.hass is None:
            return
        await self.hass.services.async_call(
            "media_player",
            "select_source",
            {"entity_id": self.input.linked_entity_id, "source": source},
            blocking=False,
        )

    async def async_shuffle_set(self, *, shuffle: bool) -> None:
        """Proxy shuffle setting to linked entity."""
        if not self.input.linked_entity_id or self.hass is None:
            return
        await self.hass.services.async_call(
            "media_player",
            "shuffle_set",
            {"entity_id": self.input.linked_entity_id, "shuffle": shuffle},
            blocking=False,
        )

    async def async_set_repeat(self, repeat: str) -> None:
        """Proxy repeat mode setting to linked entity."""
        if not self.input.linked_entity_id or self.hass is None:
            return
        await self.hass.services.async_call(
            "media_player",
            "repeat_set",
            {"entity_id": self.input.linked_entity_id, "repeat": repeat},
            blocking=False,
        )
