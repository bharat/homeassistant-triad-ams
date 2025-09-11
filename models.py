"""Data models for Triad AMS integration."""

import logging

from .connection import TriadConnection
from .const import INPUT_COUNT, OUTPUT_COUNT

_LOGGER = logging.getLogger(__name__)


class TriadAmsOutput:
    """Represents and manages a single output channel on the Triad AMS."""

    def __init__(self, number: int, name: str, connection: TriadConnection) -> None:
        """Initialize a Triad AMS output channel."""
        self.number = number  # 1-based output channel
        self.name = name
        self.connection = connection
        self._volume: float | None = None
        self._assigned_input: int | None = None  # None means off
        # For now, just use 1-based input channels with generic names

        self.input_names = {i + 1: f"Input {i + 1}" for i in range(INPUT_COUNT)}

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

    async def set_source(self, input_id: int) -> None:
        """Set the output to the given input channel (1-based)."""
        try:
            await self.connection.set_output_to_input(self.number - 1, input_id - 1)
            self._assigned_input = input_id
        except OSError as err:
            _LOGGER.error("Failed to set source for output %d: %s", self.number, err)

    @property
    def volume(self) -> float | None:
        """Return the cached volume for this output."""
        return self._volume

    async def set_volume(self, value: float) -> None:
        """Set the output volume on the device and update cache."""
        try:
            await self.connection.set_output_volume(self.number, value)
            self._volume = value
        except OSError as err:
            _LOGGER.error("Failed to set volume for output %d: %s", self.number, err)

    @property
    def is_on(self) -> bool:
        """Return True if the output is assigned to an input channel."""
        return self._assigned_input is not None

    async def turn_off(self) -> None:
        """Turn off this output by disconnecting it from any input channel."""
        try:
            await self.connection.disconnect_output(self.number)
            self._assigned_input = None
        except OSError as err:
            _LOGGER.error("Failed to turn off output %d: %s", self.number, err)

    async def refresh(self) -> None:
        """Refresh the state from the device (on demand only)."""
        try:
            self._volume = await self.connection.get_output_volume(self.number)
            assigned_input = await self.connection.get_output_source(self.number)
            if assigned_input is not None and assigned_input < OUTPUT_COUNT:
                self._assigned_input = assigned_input
            else:
                self._assigned_input = None
        except OSError as err:
            _LOGGER.error("Failed to refresh output %d: %s", self.number, err)
