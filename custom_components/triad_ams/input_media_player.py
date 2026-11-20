"""
Input MediaPlayer entities for Triad AMS inputs.

Input entities are proxy media players that represent audio sources connected
to the Triad AMS matrix. They are only created when an input is configured
with a linked external media player entity.

Purpose and Features:
--------------------
1. Playback Control Proxy:
   - Forward play/pause/next/previous commands to the linked media player
   - Display state and metadata from the linked player
   - Strip volume controls (volume is managed by output entities)

2. Group Coordinator:
   - Support the media_player.join service to route outputs to this input
   - Track which outputs (group_members) are playing this input's audio
   - Enable multi-room audio by grouping outputs together

3. Cross-Platform Grouping:
   - Can group Triad outputs with non-Triad speakers (e.g., Sonos)
   - Delegates grouping to linked entity if it supports GROUPING feature
   - Routes Triad outputs through hardware matrix, others through linked player

Creation Logic:
--------------
Input entities are ONLY created when ALL conditions are met:
- Input number is in the active_inputs list (config option)
- Input has a linked_entity_id configured (in input_links option)
- The linked entity exists in Home Assistant

If any condition is false, no entity is created but the input remains
available as a selectable source for output entities.

Grouping Model:
--------------
When media_player.join is called on an input entity with a list of outputs:

1. Triad Outputs:
   - Call turn_on_with_source service to route hardware audio
   - Outputs play the analog/digital signal from the input

2. Non-Triad Outputs (same domain as linked entity):
   - Delegate to linked entity's join service if supported
   - Enables grouping Sonos speakers, Chromecasts, etc.
   - Linked entity manages the software grouping

3. Mixed Groups:
   - Both hardware and software grouping happen simultaneously
   - Triad zones play hardware audio, non-Triad zones join via software

4. Invalid Members:
   - Unregistered entities raise InvalidGroupMemberError
   - Non-Triad entities without matching linked domain raise error
   - Ensures only compatible devices are grouped
"""

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
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
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
    """
    Media player entity that proxies a linked input media_player.

    This entity represents an audio source (input) on the Triad AMS matrix
    that is linked to an external media player (e.g., Sonos, Chromecast).

    Key Responsibilities:
    --------------------
    1. Proxy Playback Controls:
       - Forwards play/pause/next/etc. to the linked media player
       - Displays linked player's state, metadata, and artwork
       - Excludes volume controls (volume managed by output entities)

    2. Group Coordination:
       - Implements async_join_players to route outputs to this input
       - Maintains group_members list of outputs playing this input
       - Supports cross-platform grouping with compatible devices

    3. State Synchronization:
       - Tracks linked entity state changes via event subscription
       - Updates display when linked player changes
       - Monitors coordinator availability

    Entity Creation:
    ---------------
    Only created when the input has a linked_entity_id configured.
    Without a linked entity, the input is still available as a source
    for outputs but doesn't get its own entity.

    Grouping Behavior:
    -----------------
    When media_player.join is called with group_members:
    - Triad outputs: Routed via hardware to play this input's audio
    - Non-Triad outputs: Delegated to linked entity if supported
    - Empty list: Ungroups all members
    - Invalid members: Raises InvalidGroupMemberError
    """

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
        # Gold requirement: entity category
        self._attr_entity_category = EntityCategory.CONFIG
        # Gold requirement: entity disabled by default
        self._attr_entity_registry_enabled_default = RegistryEntryDisabler.USER
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "Triad",
            "model": "Audio Matrix",
        }
        self._linked_unsub: callable | None = None
        self._attr_available = True  # Track availability (Silver requirement)
        self._availability_unsub: callable | None = None
        self._registry_unsub: callable | None = None

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
        seen = set(members)

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
                    for member in linked_members:
                        if member in seen:
                            continue
                        seen.add(member)
                        members.append(member)

        return members or None

    @group_members.setter
    def group_members(self, members: list[str]) -> None:
        """Set the list of group members."""
        self._group_members = members

    def add_group_member(self, entity_id: str) -> None:
        """Add a Triad output entity to the group member list if missing."""
        if entity_id in self._group_members:
            return
        self._group_members.append(entity_id)
        self.async_write_ha_state()

    def remove_group_member(self, entity_id: str) -> None:
        """Remove a Triad output entity from the group member list if present."""
        if entity_id not in self._group_members:
            return
        self._group_members.remove(entity_id)
        self.async_write_ha_state()

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
            self._availability_unsub = self.input.coordinator.add_availability_listener(
                self._update_availability
            )

        # Track entity registry updates to handle renamed group members
        if self.hass is not None:
            self._registry_unsub = self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._handle_entity_registry_updated
            )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from linked entity state changes and availability updates."""
        if self._linked_unsub is not None:
            self._linked_unsub()
            self._linked_unsub = None
        if self._availability_unsub is not None:
            self._availability_unsub()
            self._availability_unsub = None
        if self._registry_unsub is not None:
            self._registry_unsub()
            self._registry_unsub = None

    @callback
    def _handle_entity_registry_updated(self, event: Any) -> None:
        """Update cached group members if an entity is renamed."""
        data = event.data
        if data.get("action") != "update":
            return
        old_entity_id = data.get("old_entity_id")
        new_entity_id = data.get("entity_id")
        if not old_entity_id or not new_entity_id:
            return
        if old_entity_id not in self._group_members:
            return

        seen: set[str] = set()
        updated: list[str] = []
        for member in self._group_members:
            updated_member = new_entity_id if member == old_entity_id else member
            if updated_member in seen:
                continue
            seen.add(updated_member)
            updated.append(updated_member)
        self._group_members = updated
        self.async_write_ha_state()

    async def async_get_groupable_players(self) -> dict[str, Any]:
        """
        Return all output entities that can group with this input.

        Joinable members include:
        1. All Triad AMS output entities that are:
           - Not linked to any input, OR
           - Linked to the current input entity
        2. Platform entities from the linked player entity (if supported)

        If the linked entity supports GROUPING and implements
        async_get_groupable_players (or legacy async_get_joinable_group_members),
        its response is used directly.
        Otherwise, platform entities are discovered by filtering the
        entity registry for matching domain and speaker device_class.

        This enables callers to determine which outputs can be routed
        to play this input's audio, either through hardware routing
        (Triad outputs) or software grouping (linked platform outputs).

        Returns:
            Dict with 'result' key containing list of entity IDs that can
            join this input. Returns empty list if entity_id is not set.

        Example:
            Input linked to Sonos speaker at
            media_player.sonos_living_room:

            - Returns all unlinked Triad outputs
            - Returns all Triad outputs linked to this input
            - Returns Sonos speakers from linked entity's grouping response
              (or manual discovery if linked entity lacks the method)

        """
        if not self.entity_id or self.hass is None:
            return {"result": []}

        joinable = []
        registry = er.async_get(self.hass)
        linked_state = None
        linked_input_name = None

        if self.input.linked_entity_id:
            linked_state = self.hass.states.get(self.input.linked_entity_id)
            if linked_state:
                linked_input_name = linked_state.name

        # Get all Triad AMS output entities
        triad_outputs = [
            entry.entity_id
            for entry in registry.entities.values()
            if entry.platform == DOMAIN
            and entry.domain == "media_player"
            and entry.entity_id != self.entity_id  # Exclude self
        ]

        # Filter outputs: not linked or linked to this input
        for output_id in triad_outputs:
            state = self.hass.states.get(output_id)
            if not state:
                continue

            # Only include outputs with speaker device_class
            if state.attributes.get("device_class") != MediaPlayerDeviceClass.SPEAKER:
                continue

            # Check if output is playing a different input via source attribute
            # Source contains the friendly name of the input being played
            current_source = state.attributes.get("source")

            # Include output if:
            # 1. It has no source (not playing anything), OR
            # 2. Its source matches this input's name (already playing this input), OR
            # 3. Its source matches the current linked entity name (if it changed)
            if (
                current_source is None
                or current_source == self._attr_name
                or (linked_input_name and current_source == linked_input_name)
            ):
                joinable.append(output_id)

        # Add platform entities from linked player if available
        if self.input.linked_entity_id and linked_state:
            # Only proceed if linked entity supports GROUPING feature
            supported_features = linked_state.attributes.get("supported_features", 0)
            if not (supported_features & MediaPlayerEntityFeature.GROUPING):
                return {"result": joinable}

            # Discover platform entities from same platform as linked entity
            joinable.extend(await self._discover_platform_entities(registry))

        return {"result": joinable}

    async def _discover_platform_entities(
        self, registry: er.EntityRegistry
    ) -> list[str]:
        """
        Discover platform entities by filtering entity registry.

        Get all media_player entities from the same platform as the
        linked entity, filtering for speaker device_class only.

        Args:
            registry: Entity registry instance.

        Returns:
            List of entity_ids matching platform and device_class.

        """
        platform_entities = []

        if not self.input.linked_entity_id or self.hass is None:
            return platform_entities

        # Get platform of linked entity
        linked_entry = registry.async_get(self.input.linked_entity_id)
        if not linked_entry:
            return platform_entities

        linked_domain = linked_entry.platform

        # Find all media_player entities from same platform
        candidates = [
            entry.entity_id
            for entry in registry.entities.values()
            if entry.platform == linked_domain
            and entry.domain == "media_player"
            and entry.entity_id != self.input.linked_entity_id
        ]

        # Filter for speaker device_class
        for entity_id in candidates:
            entity_state = self.hass.states.get(entity_id)
            if (
                entity_state
                and entity_state.attributes.get("device_class")
                == MediaPlayerDeviceClass.SPEAKER
            ):
                platform_entities.append(entity_id)

        return platform_entities

    async def async_join_players(self, group_members: list[str]) -> None:
        """
        Route provided output players to this input.

        This implements the media_player.join service to enable grouping
        outputs with this input entity. It handles both Triad outputs
        (hardware routing) and non-Triad outputs (software grouping).

        Grouping Logic:
        --------------
        1. Empty list: Ungroups all members
        2. Triad outputs: Routes hardware audio to play this input
        3. Non-Triad outputs: Delegates to linked entity's join service
        4. Mixed groups: Both hardware and software grouping simultaneously

        Validation:
        ----------
        - All entities must be registered in entity registry
        - Non-Triad entities must match linked entity's platform
        - Linked entity must support GROUPING feature for delegation
        - Raises InvalidGroupMemberError for invalid members

        Platform Examples:
        -----------------
        Join 2 Triad zones + 2 Sonos speakers to a Sonos input:
        - Triad zones: Hardware routed to play input's analog audio
        - Sonos speakers: Joined to linked Sonos via its group service
        - Result: All 4 zones playing synchronized audio

        Args:
            group_members: List of entity IDs to group with this input.
                          Empty list ungroups all members.

        Raises:
            InvalidGroupMemberError: If entity is not registered, wrong
                                    platform, or doesn't support grouping

        """
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
