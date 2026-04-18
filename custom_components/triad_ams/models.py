"""Data models for Triad AMS integration."""

import contextlib
import logging

from .const import VOLUME_STEPS
from .coordinator import TriadCoordinator

_LOGGER = logging.getLogger(__name__)


class TriadAmsOutput:
    """Represents and manages a single output channel on the Triad AMS."""

    def __init__(
        self,
        number: int,
        name: str,
        coordinator: TriadCoordinator,
        outputs: list["TriadAmsOutput"] | None = None,
        input_names: dict[int, str] | None = None,
    ) -> None:
        """Initialize a Triad AMS output channel."""
        self.number = number  # 1-based output channel
        self.name = name
        self.coordinator = coordinator
        self.input_names = input_names or {
            i + 1: f"Input {i + 1}" for i in range(self._input_count)
        }
        self._volume: float | None = None
        self._muted: bool = False
        self._assigned_input: int | None = None  # None = no routed source
        # Tracks the most recent valid input assignment so we can restore it
        # when the output is turned back on.
        self._last_assigned_input: int | None = None
        self._ui_on: bool = False  # UI on/off independent of routed source
        self._input_count = self.coordinator.input_count
        self._outputs = outputs
        # Lightweight listener callbacks invoked after refreshes
        self._listeners: list[callable] = []

    # ---- Listener management for state updates ----
    def add_listener(self, cb: callable) -> callable:
        """Register a callback invoked after refresh; returns an unsubscribe."""
        self._listeners.append(cb)

        def _unsub() -> None:
            with contextlib.suppress(ValueError):
                self._listeners.remove(cb)

        return _unsub

    def _notify_listeners(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                _LOGGER.exception(
                    "Error in TriadAmsOutput listener for output %d", self.number
                )

    @property
    def source_name(self) -> str | None:
        """Return the friendly name of the current source, or None if off."""
        if self._assigned_input is None:
            return None
        return self.input_names.get(self._assigned_input)

    @property
    def source_list(self) -> list[str]:
        """Return the list of available source names."""
        return [self.input_names[i] for i in sorted(self.input_names)]

    def source_id_for_name(self, name: str) -> int | None:
        """Return the input id for a given friendly name."""
        for i, n in self.input_names.items():
            if n == name:
                return i
        return None

    @property
    def source(self) -> int | None:
        """Return the assigned input channel for this output, or None if off."""
        return self._assigned_input

    @property
    def has_source(self) -> bool:
        """Return True if routed to a source on the device."""
        return self._assigned_input is not None

    async def set_source(self, input_id: int) -> None:
        """Set the output to the given input channel (1-based)."""
        try:
            await self.coordinator.set_output_to_input(self.number, input_id)
            self._assigned_input = input_id
            # Remember this assignment so we can restore it later
            self._last_assigned_input = input_id
            # Turning on (UI) implicitly when a source is routed
            self._ui_on = True
        except OSError:
            _LOGGER.exception("Failed to set source for output %d", self.number)

    @property
    def volume(self) -> float | None:
        """Return the cached volume for this output."""
        return self._volume

    async def set_volume(self, value: float) -> None:
        """Set the output volume on the device and update cache."""
        try:
            # round() returns float; cast to int to meet device step type
            steps = round(float(value) * VOLUME_STEPS)
            steps = max(0, min(steps, VOLUME_STEPS))
            # Treat any request of 0 as the minimum audible step to avoid 'Audio Off'
            if steps == 0:
                steps = 1
            quantized = steps / VOLUME_STEPS
            await self.coordinator.set_output_volume(self.number, quantized)
            self._volume = quantized
        except OSError:
            _LOGGER.exception("Failed to set volume for output %d", self.number)

    @property
    def muted(self) -> bool:
        """Return True if muted."""
        return self._muted

    async def set_muted(self, *, muted: bool) -> None:
        """Set mute state on the device and update cache."""
        try:
            await self.coordinator.set_output_mute(self.number, mute=muted)
            self._muted = muted
        except OSError:
            _LOGGER.exception("Failed to set mute for output %d", self.number)

    async def volume_up_step(self, *, large: bool = False) -> None:
        """Step the volume up (optionally large step)."""
        try:
            await self.coordinator.volume_step_up(self.number, large=large)
        except OSError:
            _LOGGER.exception("Failed to step volume up for output %d", self.number)

    async def volume_down_step(self, *, large: bool = False) -> None:
        """Step the volume down (optionally large step)."""
        try:
            await self.coordinator.volume_step_down(self.number, large=large)
        except OSError:
            _LOGGER.exception("Failed to step volume down for output %d", self.number)

    @property
    def is_on(self) -> bool:
        """Return True if the player is on in the UI (may not be routed)."""
        return self._ui_on

    async def turn_off(self) -> None:
        """Turn off this output by disconnecting it from any input channel."""
        try:
            # Preserve current assignment so we can restore it when turning back on
            if self._assigned_input is not None:
                self._last_assigned_input = self._assigned_input
            await self.coordinator.disconnect_output(self.number)
            self._assigned_input = None
            self._ui_on = False
        except OSError:
            _LOGGER.exception("Failed to turn off output %d", self.number)

    async def turn_on(self) -> None:
        """Turn on the player and restore the previous source if known."""
        # Restore the remembered input if present (this will add the output
        # to the coordinator's zone active set via `set_output_to_input`). If no
        # remembered input exists, mark UI on only; zone triggers are managed
        # by `set_output_to_input` / `disconnect_output`.
        if self._last_assigned_input is not None:
            await self.set_source(self._last_assigned_input)
        else:
            self._ui_on = True

    async def refresh(self) -> None:
        """Refresh the state from the device (on demand only)."""
        try:
            self._volume = await self.coordinator.get_output_volume(self.number)
            self._muted = await self.coordinator.get_output_mute(self.number)
            assigned_input = await self.coordinator.get_output_source(self.number)

            _LOGGER.debug(
                "Refreshed output %d: volume=%.3f muted=%s source=%s",
                self.number,
                self._volume,
                self._muted,
                assigned_input,
            )
            # assigned_input is 1-based; validate against input_count
            if assigned_input is not None and 1 <= assigned_input <= self._input_count:
                self._assigned_input = assigned_input
                # Keep last-known assignment in sync when a valid route exists
                self._last_assigned_input = assigned_input
                self._ui_on = True
            else:
                self._assigned_input = None
                self._ui_on = False
        except OSError:
            _LOGGER.exception("Failed to refresh output %d", self.number)

    async def refresh_and_notify(self) -> None:
        """Refresh state and notify listeners."""
        await self.refresh()
        self._notify_listeners()


class TriadAmsInput:
    """
    Represents an input and proxies a linked `media_player` entity.

    Stores an optional linked entity id and provides helpers to read proxied
    media attributes from Home Assistant state. The `hass` instance must be
    supplied when reading attributes to keep the model decoupled for tests.
    """

    def __init__(
        self,
        number: int,
        name: str,
        coordinator: TriadCoordinator,
        linked_entity_id: str | None = None,
    ) -> None:
        """
        Create an input model.

        Args:
            number: 1-based input number.
            name: Friendly name.
            coordinator: Coordinator for availability tracking.
            linked_entity_id: Optional linked `media_player` entity id.

        """
        self.number = number
        self.name = name
        self.linked_entity_id = linked_entity_id
        self.coordinator = coordinator

    def set_link(self, entity_id: str | None) -> None:
        """Set or clear the linked entity id."""
        self.linked_entity_id = entity_id

    def _linked_state(self, hass: object) -> object | None:
        if not self.linked_entity_id or hass is None:
            return None
        return hass.states.get(self.linked_entity_id)

    def _linked_attr(self, hass: object, key: str) -> object | None:
        st = self._linked_state(hass)
        if not st:
            return None
        return st.attributes.get(key)

    def media_title(self, hass: object) -> str | None:
        """Return the current media title from the linked source, if any."""
        return self._linked_attr(hass, "media_title")

    def media_artist(self, hass: object) -> str | None:
        """Return the media artist from the linked source, if any."""
        return self._linked_attr(hass, "media_artist")

    def media_album_name(self, hass: object) -> str | None:
        """Return the media album from the linked source, if any."""
        return self._linked_attr(hass, "media_album_name")

    def media_duration(self, hass: object) -> int | None:
        """Return the media duration (seconds) from the linked source, if any."""
        return self._linked_attr(hass, "media_duration")

    def media_content_id(self, hass: object) -> str | None:
        """Return the media content id from the linked source, if any."""
        return self._linked_attr(hass, "media_content_id")

    def media_content_type(self, hass: object) -> str | None:
        """Return the media content type from the linked source, if any."""
        return self._linked_attr(hass, "media_content_type")

    def entity_picture(self, hass: object) -> str | None:
        """Return the artwork URL from the linked source, if any."""
        return self._linked_attr(hass, "entity_picture")
