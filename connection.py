"""TriadConnection: manages the persistent connection to the Triad AMS device."""

import asyncio
import logging
from typing import Optional

_LOGGER = logging.getLogger(__name__)


class TriadConnection:
    def __init__(self, host: str, port: int) -> None:
        """Initialize a persistent connection to the Triad AMS device."""
        self.host = host
        self.port = port
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """Establish a connection to the Triad AMS device if not already connected."""
        if self._writer is not None:
            return
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        _LOGGER.info("Connected to Triad AMS at %s:%s", self.host, self.port)

    async def disconnect(self) -> None:
        """Close the connection to the Triad AMS device if open."""
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            self._reader = None
            self._writer = None
            _LOGGER.info("Disconnected from Triad AMS")

    async def _send_command(self, command: str) -> str:
        """Send a command to the device and return the response as a string."""
        async with self._lock:
            if self._writer is None:
                await self.connect()
            _LOGGER.debug("Sending command: %s", command)
            self._writer.write((command + "\r\n").encode())
            await self._writer.drain()
            response = await self._reader.readline()
            return response.decode().strip()

    async def set_output_volume(self, output_channel: int, percentage: float) -> None:
        """Set the volume for a specific output channel."""
        # TODO: Implement actual command
        _LOGGER.info("Set volume for output %d to %.2f", output_channel, percentage)

    async def get_output_volume(self, output_channel: int) -> float:
        """Get the volume for a specific output channel."""
        # TODO: Implement actual command
        _LOGGER.info("Get volume for output %d", output_channel)
        return 0.5

    async def set_output_to_input(
        self, output_channel: int, input_channel: int
    ) -> None:
        """Route a specific output channel to a given input channel."""
        # TODO: Implement actual command
        _LOGGER.info("Set output %d to input %d", output_channel, input_channel)

    async def get_output_source(self, output_channel: int) -> int:
        """Get the input source currently routed to a specific output channel."""
        # TODO: Implement actual command
        _LOGGER.info("Get source for output %d", output_channel)
        return 1

    async def set_trigger_zone(self, on: bool) -> None:
        """Set the trigger zone on or off."""
        # TODO: Implement actual command
        _LOGGER.info("Set trigger zone to %s", on)
