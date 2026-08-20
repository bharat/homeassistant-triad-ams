"""Data models for Triad AMS integration."""

import contextlib
import logging
import time

from .const import VOLUME_STEPS
from .coordinator import TriadCoordinator
from .exceptions import TransientDeviceError

_LOGGER = logging.getLogger(__name__)
_POST_COMMAND_REFRESH_COOLDOWN_S = 3.0


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
        # Maximum volume cap (0..1); 1.0 means uncapped. Set from options by
        # the media_player platform after construction.
        self.max_volume: float = 1.0
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
        self._last_command_time: float = 0.0

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
            self._last_command_time = time.monotonic()
        except (OSError, TransientDeviceError):
            _LOGGER.exception("Failed to set source for output %d", self.number)

    @property
    def volume(self) -> float | None:
        """Return the cached volume for this output."""
        return self._volume

    async def set_volume(self, value: float) -> None:
        """Set the output volume on the device and update cache."""
        # Clamp to the configured max-volume cap. The cap only limits what
        # WE send to the device; if the volume is raised above the cap
        # externally (e.g. from a keypad), refresh() reports the actual
        # value truthfully rather than fighting it.
        value = min(float(value), self.max_volume)
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
            self._last_command_time = time.monotonic()
        except (OSError, TransientDeviceError):
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
            self._last_command_time = time.monotonic()
        except (OSError, TransientDeviceError):
            _LOGGER.exception("Failed to set mute for output %d", self.number)

    async def volume_up_step(self, *, large: bool = False) -> None:
        """Step the volume up (optionally large step), respecting max_volume."""
        cap = self.max_volume
        if cap < 1.0 and self._volume is None:
            # Cache is cold; read the current volume so the cap check below
            # can't be bypassed by stepping blind.
            with contextlib.suppress(OSError, TransientDeviceError):
                self._volume = await self.coordinator.get_output_volume(self.number)
        if cap < 1.0 and self._volume is not None and self._volume >= cap:
            # At the cap, or above it via an external control (keypad). We
            # never push the device louder, but we also do not pull an
            # externally raised volume back down: the cap limits only what
            # we send, and reported state stays truthful.
            return
        try:
            await self.coordinator.volume_step_up(self.number, large=large)
        except (OSError, TransientDeviceError):
            _LOGGER.exception("Failed to step volume up for output %d", self.number)
            return
        # A small step moves one device unit on the same 1/VOLUME_STEPS grid
        # the cap is quantized to, so it cannot overshoot from below the cap.
        # A large step can, so read back where it landed and clamp if needed.
        if cap < 1.0 and large:
            try:
                new_volume = await self.coordinator.get_output_volume(self.number)
            except (OSError, TransientDeviceError):
                _LOGGER.debug(
                    "Could not read back volume after large step for output %d",
                    self.number,
                )
                return
            self._volume = new_volume
            if new_volume > cap:
                await self.set_volume(cap)

    async def volume_down_step(self, *, large: bool = False) -> None:
        """Step the volume down (optionally large step)."""
        try:
            await self.coordinator.volume_step_down(self.number, large=large)
        except (OSError, TransientDeviceError):
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
            self._last_command_time = time.monotonic()
        except (OSError, TransientDeviceError):
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
            self._last_command_time = time.monotonic()

    async def refresh(self) -> None:
        """Refresh the state from the device (on demand only)."""
        elapsed = time.monotonic() - self._last_command_time
        if elapsed < _POST_COMMAND_REFRESH_COOLDOWN_S:
            _LOGGER.debug(
                "Output %d: command sent recently, skipping refresh",
                self.number,
            )
            return
        try:
            # Deliberately not clamped to max_volume: if the volume was
            # raised externally (e.g. keypad) we report the true device
            # state; the cap only applies to volume commands we originate.
            self._volume = await self.coordinator.get_output_volume(self.number)
        except TransientDeviceError:
            _LOGGER.debug(
                "Transient error refreshing volume for output %d; skipping",
                self.number,
            )
            return
        except OSError:
            _LOGGER.warning(
                "Failed to refresh volume for output %d",
                self.number,
                exc_info=True,
            )
            return

        # Mute is best-effort: on some AMS firmware the device returns an
        # empty response to the mute query. Suppressing OSError here avoids
        # both aborting the rest of refresh() and triggering the coordinator
        # reconnect path (since OSError propagating out of refresh would
        # cascade into _run_worker's connection-reset behavior).
        # Mute state is also tracked optimistically via set_muted().
        with contextlib.suppress(OSError, TransientDeviceError):
            self._muted = await self.coordinator.get_output_mute(self.number)

        try:
            assigned_input = await self.coordinator.get_output_source(self.number)
        except TransientDeviceError:
            _LOGGER.debug(
                "Transient error refreshing source for output %d; skipping",
                self.number,
            )
            return
        except OSError:
            _LOGGER.warning(
                "Failed to refresh source for output %d",
                self.number,
                exc_info=True,
            )
            return

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
            self._last_assigned_input = assigned_input
            self._ui_on = True
        else:
            self._assigned_input = None
            self._ui_on = False

    async def refresh_and_notify(self) -> None:
        """Refresh state and notify listeners."""
        await self.refresh()
        self._notify_listeners()
