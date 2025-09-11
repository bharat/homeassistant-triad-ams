"""TriadConnection: manages the persistent connection to the Triad AMS device."""

import asyncio
import logging
import re

from .const import INPUT_COUNT

_LOGGER = logging.getLogger(__name__)


class TriadConnection:
    """Manages a persistent connection to the Triad AMS device, providing methods to control and query device state."""

    # Debounce state for volume per output
    _volume_debounce_tasks: dict[int, asyncio.Task] = {}
    _volume_debounce_values: dict[int, float] = {}
    _volume_debounce_last_sent: dict[int, float] = {}

    def __init__(self, host: str, port: int) -> None:
        """Initialize a persistent connection to the Triad AMS device."""
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """Establish a connection to the Triad AMS device if not already connected."""
        if self._writer is not None:
            return
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        _LOGGER.info("Connected to Triad AMS at %s:%s", self.host, self.port)
        # Some devices need a short delay after connect before accepting commands
        await asyncio.sleep(0.2)

    async def disconnect(self) -> None:
        """Close the connection to the Triad AMS device if open."""
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            self._reader = None
            self._writer = None
            _LOGGER.info("Disconnected from Triad AMS")

    async def _send_command(self, command: bytes) -> str:
        """Send a command to the device and return the response as a string (with timeout and raw logging)."""
        async with self._lock:
            if self._writer is None:
                await self.connect()
            _LOGGER.debug("Sending raw bytes: %s", command.hex())
            self._writer.write(command)
            await self._writer.drain()
            # Add a small delay between commands for device tolerance
            await asyncio.sleep(0.2)
            try:
                response = await asyncio.wait_for(
                    self._reader.readuntil(b"\x00"), timeout=10
                )
            except TimeoutError:
                _LOGGER.error(
                    "Timeout waiting for response to command: %s", command.hex()
                )
                return ""
            except asyncio.IncompleteReadError as e:
                _LOGGER.error(
                    "Incomplete read waiting for response to command: %s, partial=%r",
                    command.hex(),
                    e.partial,
                )
                return e.partial.decode(errors="replace").strip()
            _LOGGER.debug("Raw response: %r", response)
            return response.decode(errors="replace").strip("\x00").strip()

    async def set_output_volume(self, output_channel: int, percentage: float) -> None:
        """Set the volume for a specific output channel (debounced, capped at 20%).

        Args:
            output_channel: 1-based output channel index.
            percentage: Volume as a float (0.0 = off, 1.0 = max, capped at 0.2).
        Command: FF 55 04 03 1E <output> <value>  (output sent as 0-based)
        Value: 0x00 (off) to 0xA1 (max)
        """
        capped = min(percentage, 0.2)
        now = asyncio.get_event_loop().time()
        self._volume_debounce_values[output_channel] = capped

        async def _send():
            value = self._volume_debounce_values[output_channel]
            self._volume_debounce_last_sent[output_channel] = (
                asyncio.get_event_loop().time()
            )
            val = int(value * 0xA1)
            val = max(0, min(val, 0xA1))
            cmd = bytearray.fromhex("FF5504031E") + bytes([output_channel - 1, val])
            resp = await self._send_command(cmd)
            _LOGGER.info(
                "Set volume for output %d to %.2f (capped %.2f, resp: %s)",
                output_channel,
                percentage,
                value,
                resp,
            )

        # Cancel any pending debounce task for this output
        if (
            task := self._volume_debounce_tasks.get(output_channel)
        ) and not task.done():
            task.cancel()

        # If last sent was >500ms ago, send immediately
        last_sent = self._volume_debounce_last_sent.get(output_channel, 0)
        delay = max(0, 0.5 - (now - last_sent))

        async def debounce_task():
            try:
                await asyncio.sleep(delay)
                await _send()
            except asyncio.CancelledError:
                pass

        self._volume_debounce_tasks[output_channel] = asyncio.create_task(
            debounce_task()
        )

    async def get_output_volume(self, output_channel: int) -> float:
        """Get the volume for a specific output channel.

        Args:
            output_channel: 1-based output channel index.
        Command: FF 55 04 03 1E F5 <output>
        Returns:
            float: Volume as a float (0.0 = off, 1.0 = max)
        """
        cmd = bytearray.fromhex("FF5504031EF5") + bytes([output_channel - 1])
        resp = await self._send_command(cmd)
        # Response: b'Get Out[7] Volume : -26.5\x00' or b'Get Out[7] Volume : 0xA1\x00'
        m = re.search(r"Volume : (-?\d+\.\d+|-?\d+)", resp)
        if m:
            # Device returns dB as float, convert to 0..1 scale (assume -80dB=min, 0=max)
            db = float(m.group(1))
            # Clamp and scale: -80dB (min) = 0.0, 0dB (max) = 1.0
            return max(0.0, min(1.0, (db + 80) / 80))
        m_hex = re.search(r"Volume : 0x([0-9A-Fa-f]+)", resp)
        if m_hex:
            value = int(m_hex.group(1), 16)
            return value / 0xA1
        _LOGGER.error("Could not parse output volume from response: %s", resp)
        return 0.0

    async def set_output_to_input(
        self, output_channel: int, input_channel: int
    ) -> None:
        """Route a specific output channel to a given input channel.

        Args:
            output_channel: 1-based output channel index.
            input_channel: 1-based input channel index.
        Command: FF 55 04 03 1D <output> <input>
        """
        cmd = bytearray.fromhex("FF5504031D") + bytes(
            [output_channel - 1, input_channel - 1]
        )
        resp = await self._send_command(cmd)
        # Be tolerant of varying response strings
        _LOGGER.info(
            "Set output %d to input %d (resp: %s)",
            output_channel,
            input_channel,
            resp,
        )

    async def get_output_source(self, output_channel: int) -> int | None:
        """Get the input source currently routed to a specific output channel.

        Args:
            output_channel: 1-based output channel index.
        Command: FF 55 04 03 1D F5 <output>
        Returns:
            int | None: 1-based input channel, or None if Audio Off.
        """
        cmd = bytearray.fromhex("FF5504031DF5") + bytes([output_channel - 1])
        resp = await self._send_command(cmd)
        # Response: b'Get Out[7] Input Source : input 3\x00' or b'Get Out[7] Input Source : Audio Off\x00'
        if "Audio Off" in resp:
            return None
        m = re.search(r"input (\d+)", resp)
        if m:
            return int(m.group(1))
        _LOGGER.error("Could not parse output source from response: %s", resp)
        return None

    async def set_trigger_zone(self, on: bool) -> None:
        """Set the trigger zone on or off.

        Args:
            on: True to enable, False to disable.
        Command: On: FF 55 03 05 50 00, Off: FF 55 03 05 51 00
        """
        cmd = bytearray.fromhex("FF5503055000" if on else "FF5503055100")
        resp = await self._send_command(cmd)
        _LOGGER.info("Set trigger zone to %s (resp: %s)", on, resp)

    async def disconnect_output(self, output_channel: int) -> None:
        """Disconnect the output by routing it to an invalid input channel (off).

        Args:
            output_channel: 1-based output channel index.
        Command: FF 55 04 03 1D <output> <invalid_input>
        """
        cmd = bytearray.fromhex("FF5504031D") + bytes([output_channel - 1, INPUT_COUNT])
        resp = await self._send_command(cmd)
        # Tolerate varied responses and log outcome
        if "Audio Off" in resp:
            _LOGGER.info("Disconnected output %d (resp: %s)", output_channel, resp)
        else:
            _LOGGER.info("Requested disconnect for output %d (resp: %s)", output_channel, resp)
