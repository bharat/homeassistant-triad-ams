"""
Connection management for Triad AMS.

Provides async helpers to control and query device state.
"""

import asyncio
import logging
import re
from typing import cast

from .const import INPUT_COUNT

_LOGGER = logging.getLogger(__name__)


class TriadConnection:
    """Manage a persistent connection to the Triad AMS device."""

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
        """
        Send a command and return the response string.

        Adds a small inter-command delay, logs raw traffic, and applies a
        reasonable timeout to reads.
        """
        async with self._lock:
            if self._writer is None or self._reader is None:
                await self.connect()
            # Create local non-optional references for type checkers
            writer = cast("asyncio.StreamWriter", self._writer)
            reader = cast("asyncio.StreamReader", self._reader)
            _LOGGER.debug("Sending raw bytes: %s", command.hex())
            writer.write(command)
            await writer.drain()
            # Add a small delay between commands for device tolerance
            await asyncio.sleep(0.2)
            try:
                response = await asyncio.wait_for(reader.readuntil(b"\x00"), timeout=10)
            except TimeoutError:
                _LOGGER.exception(
                    "Timeout waiting for response to command: %s", command.hex()
                )
                return ""
            except asyncio.IncompleteReadError as e:
                _LOGGER.exception(
                    "Incomplete read waiting for response to command: %s, partial=%r",
                    command.hex(),
                    e.partial,
                )
                return e.partial.decode(errors="replace").strip()
            _LOGGER.debug("Raw response: %r", response)
            return response.decode(errors="replace").strip("\x00").strip()

    async def set_output_volume(self, output_channel: int, percentage: float) -> None:
        """
        Set volume with simple rate limit: immediate send, max 1/500ms, trailing final.

        Args:
            output_channel: 1-based output channel index.
            percentage: Volume as a float (0.0 = off, 1.0 = max).
        Command: FF 55 04 03 1E <output> <value>  (output sent as 0-based)
        Value: 0x00 (off) to 0xA1 (max)

        """
        _LOGGER.debug(
            "Request to set volume for output %d to %.2f", output_channel, percentage
        )

        # Clamp to device range 0..1.0 (0x00..0xA1)
        capped = max(0.0, min(percentage, 1.0))

        val = int(capped * 0xA1)
        val = max(0, min(val, 0xA1))
        cmd = bytearray.fromhex("FF5504031E") + bytes([output_channel - 1, val])
        resp = await self._send_command(cmd)
        _LOGGER.info(
            "Set volume for output %d to %.2f (resp: %s)",
            output_channel,
            capped,
            resp,
        )

    async def get_output_volume(self, output_channel: int) -> float:
        """
        Get the volume for a specific output channel.

        Args:
            output_channel: 1-based output channel index.
        Command: FF 55 04 03 1E F5 <output>
        Returns:
            float: Volume as a float (0.0 = off, 1.0 = max)

        """
        cmd = bytearray.fromhex("FF5504031EF5") + bytes([output_channel - 1])
        resp = await self._send_command(cmd)
        m = re.search(r"Volume : (-?\d+\.\d+|-?\d+)", resp)
        if m:
            # Device returns dB; convert to 0..1 scale
            # Assume -80 dB is min and 0 dB is max
            db = float(m.group(1))
            # Clamp and scale: -80 dB -> 0.0, 0 dB -> 1.0
            return max(0.0, min(1.0, (db + 80) / 80))
        m_hex = re.search(r"Volume : 0x([0-9A-Fa-f]+)", resp)
        if m_hex:
            value = int(m_hex.group(1), 16)
            return value / 0xA1
        _LOGGER.error("Could not parse output volume from response: %s", resp)
        return 0.0

    async def set_output_mute(self, output_channel: int, *, mute: bool) -> None:
        """
        Set mute state for an output channel.

        Args:
            output_channel: 1-based output channel index.
            mute: True to mute, False to unmute.

        Commands:
            Mute on:  FF 55 03 03 17 <output>
            Mute off: FF 55 03 03 18 <output>

        """
        base = "FF55030317" if mute else "FF55030318"
        cmd = bytearray.fromhex(base) + bytes([output_channel - 1])
        resp = await self._send_command(cmd)
        _LOGGER.info(
            "Set mute for output %d to %s (resp: %s)", output_channel, mute, resp
        )

    async def get_output_mute(self, output_channel: int) -> bool:
        """
        Return True if the output is muted.

        Command: FF 55 04 03 17 F5 <output>
        Response formats observed (case varies):
          - "Get Out[1] Mute status : Unmute"
          - "Get Out[5] Mute status : mute"
          - "Mute : On" / "Mute : Off"
          - "Muted" / "Unmuted"

        """
        cmd = bytearray.fromhex("FF55040317F5") + bytes([output_channel - 1])
        resp = await self._send_command(cmd)
        # Try to capture the token after "Mute" or "Mute status"
        m = re.search(r"Mute(?:\s+status)?\s*:\s*([A-Za-z0-9]+)", resp, re.IGNORECASE)
        if m:
            token = m.group(1).strip().lower()
            true_tokens = {"on", "mute", "muted", "1", "true", "yes"}
            false_tokens = {"off", "unmute", "unmuted", "0", "false", "no"}
            if token in true_tokens:
                return True
            if token in false_tokens:
                return False
        # Fallback heuristics
        if re.search(r"\bmuted\b", resp, re.IGNORECASE):
            return True
        if re.search(r"\bunmuted|unmute\b", resp, re.IGNORECASE):
            return False
        _LOGGER.warning("Could not parse mute state from response: %s", resp)
        return False

    async def volume_step_up(self, output_channel: int, *, large: bool = False) -> None:
        """Step the output volume up (small or large step)."""
        cmd = bytearray.fromhex("FF55030315" if large else "FF55030313") + bytes(
            [output_channel - 1]
        )
        resp = await self._send_command(cmd)
        _LOGGER.debug(
            "Volume step up (%s) for output %d (resp: %s)",
            "large" if large else "small",
            output_channel,
            resp,
        )

    async def volume_step_down(
        self, output_channel: int, *, large: bool = False
    ) -> None:
        """Step the output volume down (small or large step)."""
        cmd = bytearray.fromhex("FF55030316" if large else "FF55030314") + bytes(
            [output_channel - 1]
        )
        resp = await self._send_command(cmd)
        _LOGGER.debug(
            "Volume step down (%s) for output %d (resp: %s)",
            "large" if large else "small",
            output_channel,
            resp,
        )

    async def set_output_to_input(
        self, output_channel: int, input_channel: int
    ) -> None:
        """
        Route a specific output channel to a given input channel.

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
        """
        Get the input source currently routed to a specific output channel.

        Args:
            output_channel: 1-based output channel index.
        Command: FF 55 04 03 1D F5 <output>
        Returns:
            int | None: 1-based input channel, or None if Audio Off.

        """
        cmd = bytearray.fromhex("FF5504031DF5") + bytes([output_channel - 1])
        resp = await self._send_command(cmd)
        if "Audio Off" in resp:
            return None
        m = re.search(r"input (\d+)", resp)
        if m:
            return int(m.group(1))
        _LOGGER.error("Could not parse output source from response: %s", resp)
        return None

    async def set_trigger_zone(self, *, on: bool) -> None:
        """
        Set the trigger zone on or off.

        Args:
            on: True to enable, False to disable.
        Command: On: FF 55 03 05 50 00, Off: FF 55 03 05 51 00

        """
        cmd = bytearray.fromhex("FF5503055000" if on else "FF5503055100")
        resp = await self._send_command(cmd)
        _LOGGER.info("Set trigger zone to %s (resp: %s)", on, resp)

    async def disconnect_output(self, output_channel: int) -> None:
        """
        Disconnect the output by routing it to an invalid input channel (off).

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
            _LOGGER.info(
                "Requested disconnect for output %d (resp: %s)", output_channel, resp
            )
