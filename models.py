"""Data models for Triad AMS integration."""

import logging

from .connection import TriadConnection

_LOGGER = logging.getLogger(__name__)


class TriadAmsOutput:
    """Represents and manages a single output channel on the Triad AMS."""

    def __init__(self, number: int, name: str, connection: TriadConnection) -> None:
        """Initialize a Triad AMS output channel."""
        self.number = number
        self.name = name
        self.connection = connection
        self._volume: float | None = None
        self._is_on: bool = False
        self._source: int | None = None

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
        """Return True if the output is on."""
        return self._is_on

    async def set_is_on(self, value: bool) -> None:
        """Set the output on/off state on the device and update cache."""
        try:
            # For now, treat 'on' as routed to any input (stub)
            await self.connection.set_output_to_input(self.number, 1 if value else 0)
            self._is_on = value
        except OSError as err:
            _LOGGER.error("Failed to set on/off for output %d: %s", self.number, err)

    @property
    def source(self) -> int | None:
        """Return the cached source for this output."""
        return self._source

    async def set_source(self, value: int) -> None:
        """Set the output source on the device and update cache."""
        try:
            await self.connection.set_output_to_input(self.number, value)
            self._source = value
        except OSError as err:
            _LOGGER.error("Failed to set source for output %d: %s", self.number, err)

    async def refresh(self) -> None:
        """Refresh the state from the device (on demand only)."""
        try:
            self._volume = await self.connection.get_output_volume(self.number)
            self._source = await self.connection.get_output_source(self.number)
            # For now, treat 'on' as source != 0
            self._is_on = self._source != 0
        except OSError as err:
            _LOGGER.error("Failed to refresh output %d: %s", self.number, err)
