"""
Connection management for Triad AMS.

Provides async helpers to control and query device state.
"""

import asyncio
import contextlib
import logging
import re
from typing import cast

from .const import VOLUME_STEPS
from .volume_lut import step_for_db

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
            _LOGGER.debug("connect(): already connected; skipping")
            return
        _LOGGER.debug("connect(): begin to %s:%s", self.host, self.port)
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        _LOGGER.info("Connected to Triad AMS at %s:%s", self.host, self.port)
        # Some devices need a short delay after connect before accepting commands
        await asyncio.sleep(0.2)
        _LOGGER.debug("connect(): ready (post-sleep)")

    async def disconnect(self) -> None:
        """Close the connection to the Triad AMS device if open."""
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            self._reader = None
            self._writer = None
            _LOGGER.info("Disconnected from Triad AMS")

    def close_nowait(self) -> None:
        """Close the transport without awaiting shutdown (non-blocking)."""
        _LOGGER.debug(
            "close_nowait(): writer is %s", "present" if self._writer else "None"
        )
        if self._writer is not None:
            with contextlib.suppress(Exception):
                self._writer.close()
        self._reader = None
        self._writer = None
        _LOGGER.debug("close_nowait(): cleared reader/writer")

    async def _send_command(self, command: bytes, *, expect: str | None = None) -> str:
        """
        Send a command and return the response string.

        Adds a small inter-command delay, logs raw traffic, and applies a
        reasonable timeout to reads.
        """
        _LOGGER.debug("_send_command(): waiting for lock")
        async with self._lock:
            _LOGGER.debug("_send_command(): acquired lock")
            if self._writer is None or self._reader is None:
                _LOGGER.debug("_send_command(): transport missing; calling connect()")
                await self.connect()
            # Create local non-optional references for type checkers
            writer = cast("asyncio.StreamWriter", self._writer)
            reader = cast("asyncio.StreamReader", self._reader)
            _LOGGER.debug("Sending raw bytes: %s", command.hex())
            _LOGGER.debug("_send_command(): writing %d bytes", len(command))
            writer.write(command)
            _LOGGER.debug("_send_command(): before drain()")
            await writer.drain()
            _LOGGER.debug("_send_command(): after drain()")
            # Add a very small delay for device tolerance
            await asyncio.sleep(0.1)
            _LOGGER.debug("_send_command(): awaiting response")
            response = await asyncio.wait_for(reader.readuntil(b"\x00"), timeout=5)
            _LOGGER.debug("_send_command(): received %d bytes", len(response))
            _LOGGER.debug("Raw response: %r", response)
            text = response.decode(errors="replace").strip("\x00").strip()
            # Evaluate the first (and only) frame. If it doesn't match the
            # expected pattern, allow exactly one skip for an unsolicited
            # AudioSense event, then re-evaluate the next frame.
            if (
                expect is not None
                and text
                and not re.search(expect, text, re.IGNORECASE)
            ):
                if re.search(
                    r"^AudioSense:Input\[\d+\]\s*:\s*(0|1)\s*$",
                    text,
                    re.IGNORECASE,
                ):
                    _LOGGER.debug("Skipping unsolicited AudioSense event: %s", text)
                    response = await asyncio.wait_for(
                        reader.readuntil(b"\x00"), timeout=5
                    )
                    _LOGGER.debug("Raw response (post-AudioSense): %r", response)
                    text = response.decode(errors="replace").strip("\x00").strip()
                # After optional skip, if still not matching -> error
                if text and not re.search(expect, text, re.IGNORECASE):
                    _LOGGER.warning("Unexpected response: %s", text)
                    self.close_nowait()
                    err_msg = "Unexpected response from device"
                    raise OSError(err_msg)
            # Detect device-side command error or protocol desync (nulls)
            if text == "" or re.search(r"^command\s+error$", text, re.IGNORECASE):
                _LOGGER.warning(
                    "Device returned error/empty response for command: %s; "
                    "resetting connection",
                    command.hex(),
                )
                # Proactively drop the connection without blocking
                _LOGGER.debug("_send_command(): before close_nowait() on error")
                self.close_nowait()
                _LOGGER.debug("_send_command(): after close_nowait() on error")
                msg = "Triad command error or empty response"
                raise OSError(msg)
            return text

    async def send_raw(self, command: bytes) -> str:
        """
        Send a raw command and return the decoded response string.

        Intended for diagnostic/debug usage. Uses the same transport, lock,
        and parsing behavior as all other commands.
        """
        return await self._send_command(command)

    async def set_output_volume(self, output_channel: int, percentage: float) -> None:
        """
        Set volume immediately without debouncing.

        Args:
            output_channel: 1-based output channel index.
            percentage: Volume as a float (0.0 = off, 1.0 = max).
        Command: FF 55 04 03 1E <output> <value>  (output sent as 0-based)
        Value: 0x00 (off) to 0x64 (max)

        """
        # Clamp to device range 0..1.0 (0x00..0x64)
        capped = max(0.0, min(percentage, 1.0))

        # Quantize to nearest device step for consistency (0..VOLUME_STEPS)
        val = round(capped * VOLUME_STEPS)
        val = max(0, min(val, VOLUME_STEPS))
        cmd = bytearray.fromhex("FF5504031E") + bytes([output_channel - 1, val])
        resp = await self._send_command(cmd, expect=r"Output\s+Volume|Volume\s*:")
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
        resp = await self._send_command(cmd, expect=r"Volume\s*:")
        # Prefer raw hex value if present (exact mapping to slider scale)
        m_hex = re.search(r"Volume\s*:\s*0x([0-9A-Fa-f]+)", resp)
        if m_hex:
            value = int(m_hex.group(1), 16)
            return max(0.0, min(1.0, value / VOLUME_STEPS))
        # Otherwise parse dB and map to nearest step using measured LUT
        m = re.search(r"Volume\s*:\s*(-?\d+(?:\.\d+)?)", resp)
        if m:
            db = float(m.group(1))
            step = step_for_db(db)
            return step / VOLUME_STEPS
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
        resp = await self._send_command(cmd, expect=r"Mute")
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
        resp = await self._send_command(cmd, expect=r"(Input\s+Source|Audio\s+Off)")
        if large:
            _LOGGER.info("Volume step up (large) for output %d", output_channel)
            _LOGGER.debug(
                "Volume step up (large) for output %d (resp: %s)", output_channel, resp
            )
        else:
            _LOGGER.debug(
                "Volume step up (small) for output %d (resp: %s)", output_channel, resp
            )

    async def volume_step_down(
        self, output_channel: int, *, large: bool = False
    ) -> None:
        """Step the output volume down (small or large step)."""
        cmd = bytearray.fromhex("FF55030316" if large else "FF55030314") + bytes(
            [output_channel - 1]
        )
        resp = await self._send_command(cmd, expect=r"(Input\s+Source|Audio\s+Off)")
        if large:
            _LOGGER.info("Volume step down (large) for output %d", output_channel)
            _LOGGER.debug(
                "Volume step down (large) for output %d (resp: %s)",
                output_channel,
                resp,
            )
        else:
            _LOGGER.debug(
                "Volume step down (small) for output %d (resp: %s)",
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
        resp = await self._send_command(cmd, expect=r"Trigger|Set\s+.*")
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
        # Accept "Audio Off", "Input Source : input N" or device 'Set ...' echoes
        resp = await self._send_command(
            cmd, expect=r"(Audio\s+Off|Input\s+Source|Set\s+.*)"
        )
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
        resp = await self._send_command(cmd, expect=r"Max\s+Volume|0x|dB|Set\s+.*")
        _LOGGER.info("Set trigger zone to %s (resp: %s)", on, resp)

    async def disconnect_output(self, output_channel: int, input_count: int) -> None:
        """
        Disconnect the output by routing it to an invalid input channel (off).

        Args:
            output_channel: 1-based output channel index.
            input_count: Total number of inputs (used to determine invalid input).
        Command: FF 55 04 03 1D <output> <invalid_input>

        """
        cmd = bytearray.fromhex("FF5504031D") + bytes([output_channel - 1, input_count])
        resp = await self._send_command(cmd, expect=r"Start\s+Vol|0x|dB|Set\s+.*")
        # Tolerate varied responses and log outcome
        if "Audio Off" in resp:
            _LOGGER.info("Disconnected output %d (resp: %s)", output_channel, resp)
        else:
            _LOGGER.info(
                "Requested disconnect for output %d (resp: %s)", output_channel, resp
            )
