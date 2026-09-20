"""
Connection management for Triad AMS.

Provides async helpers to control and query device state.
"""

import asyncio
import contextlib
import logging
import re
import socket
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from asyncio import StreamReader, StreamWriter

from .const import (
    BUFFER_DRAIN_TIMEOUT,
    CLEAN_EXCHANGES_TO_SKIP_DRAIN,
    CONNECTION_TIMEOUT,
    DEVICE_COMMAND_DELAY,
    POST_CONNECT_DELAY,
    VOLUME_STEPS,
)
from .exceptions import TransientDeviceError
from .volume_lut import step_for_db

_LOGGER = logging.getLogger(__name__)


class TriadConnection:
    """Manage a persistent connection to the Triad AMS device."""

    def __init__(self, host: str, port: int, *, protocol_debug: bool = False) -> None:
        """Initialize a persistent connection to the Triad AMS device."""
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._protocol_debug = protocol_debug
        # Single byte read past a frame boundary while draining NUL padding;
        # prepended to the next frame read so no real data is lost.
        self._read_ahead: bytes = b""
        # Per-connection framing detection (reset on every connect/close):
        # once padding or stale bytes are seen, the timed drain/flush windows
        # stay active for the life of the connection. After enough consecutive
        # clean exchanges the windows are skipped, so single-NUL firmware does
        # not pay their timeouts on every command.
        self._padding_seen: bool = False
        self._clean_exchanges: int = 0

    def _log_protocol(self, msg: str, *args: object) -> None:
        """Emit protocol logs when enabled via options."""
        if self._protocol_debug:
            _LOGGER.debug(msg, *args)

    def set_protocol_debug(self, *, enabled: bool) -> None:
        """Enable or disable protocol-level logging."""
        self._protocol_debug = enabled

    def _reset_framing_state(self) -> None:
        """Forget learned framing so the next connection re-learns from scratch."""
        self._read_ahead = b""
        self._padding_seen = False
        self._clean_exchanges = 0

    def _skip_timed_windows(self) -> bool:
        """Return True once single-NUL framing has been learned."""
        return (
            not self._padding_seen
            and self._clean_exchanges >= CLEAN_EXCHANGES_TO_SKIP_DRAIN
        )

    @staticmethod
    def _summarize_bytes(data: bytes, *, max_bytes: int = 16) -> str:
        """Return a compact hex summary of a payload."""
        if not data:
            return "len=0"
        prefix = data[:max_bytes].hex()
        suffix = "..." if len(data) > max_bytes else ""
        return f"len={len(data)} hex={prefix}{suffix}"

    @staticmethod
    def _summarize_text(text: str, *, max_len: int = 80) -> str:
        """Return a compact, single-line summary of response text."""
        compact = " ".join(text.split())
        if len(compact) > max_len:
            compact = f"{compact[:max_len]}..."
        return compact

    async def connect(self) -> None:
        """Establish a connection to the Triad AMS device if not already connected."""
        if self._writer is not None:
            self._log_protocol("connect(): already connected; skipping")
            return
        self._log_protocol("connect(): begin to %s:%s", self.host, self.port)
        self._reset_framing_state()
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        self._log_protocol("connect(): connected to %s:%s", self.host, self.port)
        # Some devices need a short delay after connect before accepting commands
        await asyncio.sleep(POST_CONNECT_DELAY)
        self._log_protocol("connect(): ready (post-sleep)")

    async def disconnect(self) -> None:
        """Close the connection to the Triad AMS device if open."""
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            self._reader = None
            self._writer = None
            self._reset_framing_state()
            self._log_protocol("disconnect(): closed connection")

    def close_nowait(self) -> None:
        """Close the transport without awaiting shutdown (non-blocking)."""
        self._log_protocol(
            "close_nowait(): writer is %s", "present" if self._writer else "None"
        )
        # Note: We don't acquire the lock here because:
        # 1. This is called from coordinator.stop() which needs to interrupt
        #    in-flight operations
        # 2. The lock might be held by a network call that's stuck
        # 3. Setting _reader/_writer to None will cause subsequent operations
        #    to fail
        if self._writer is not None:
            with contextlib.suppress(Exception):
                # Shutdown the socket to interrupt any pending reads immediately
                # This causes reader.readuntil() to fail with ConnectionResetError
                socket_obj = self._writer.get_extra_info("socket")
                if socket_obj is not None:
                    socket_obj.shutdown(socket.SHUT_RDWR)
                self._writer.close()
        self._reader = None
        self._writer = None
        self._reset_framing_state()
        self._log_protocol("close_nowait(): cleared reader/writer")

    async def _ensure_connection_for_send(self) -> None:
        """Ensure connection is established before sending."""
        if self._writer is None or self._reader is None:
            self._log_protocol("_send_command(): transport missing; calling connect()")
            await self.connect()

    async def _write_command_bytes(
        self, writer: "StreamWriter", command: bytes
    ) -> None:
        """Write command bytes to the connection."""
        self._log_protocol("TX %s", self._summarize_bytes(command))
        writer.write(command)
        await writer.drain()
        # Add a very small delay for device tolerance
        await asyncio.sleep(DEVICE_COMMAND_DELAY)

    async def _read_response_bytes(self, reader: "StreamReader") -> bytes:
        """Read response bytes from the connection."""
        # Check connection state before reading - if closed, fail immediately
        if self._reader is None or self._writer is None:
            msg = "Connection closed"
            raise OSError(msg)
        try:
            response = await asyncio.wait_for(
                reader.readuntil(b"\x00"), timeout=CONNECTION_TIMEOUT
            )
        except (
            asyncio.CancelledError,
            ConnectionResetError,
            BrokenPipeError,
            asyncio.IncompleteReadError,
        ):
            # If cancelled or connection was closed, check state and raise
            # appropriate error
            if self._reader is None or self._writer is None:
                msg = "Connection closed"
                raise OSError(msg) from None
            # Re-raise the original exception
            raise
        except OSError:
            # Re-raise OSError as-is (might be from socket shutdown)
            raise
        if self._read_ahead:
            response = self._read_ahead + response
            self._read_ahead = b""
        self._log_protocol("RX %s", self._summarize_bytes(response))
        await self._drain_nul_padding(reader)
        return response

    async def _drain_nul_padding(self, reader: "StreamReader") -> None:
        """
        Discard NUL padding that may trail a response frame.

        Some firmware revisions pad every response to a fixed-length frame
        (observed: 150 bytes) with trailing 0x00 bytes, while others terminate
        with a single 0x00. readuntil() consumes only the first NUL, so the
        padding would otherwise be read as the next command's response and
        desync every subsequent exchange (issue #164). A non-NUL byte ends the
        drain and is kept in ``_read_ahead`` for the next frame read, so no
        real data can be lost.

        Framing is learned per connection: once enough consecutive exchanges
        finish with nothing buffered (single-NUL firmware), the timed drain is
        skipped so steady-state commands pay no timeout. Draining any padding
        pins the full drain behavior for the life of the connection.
        """
        if self._skip_timed_windows():
            return
        drained = 0
        held_byte = False
        while True:
            try:
                byte = await asyncio.wait_for(
                    reader.readexactly(1), timeout=BUFFER_DRAIN_TIMEOUT
                )
            except (OSError, asyncio.IncompleteReadError):
                # Timeout means no more buffered bytes; EOF/connection errors
                # will surface on the next read.
                break
            if byte != b"\x00":
                self._read_ahead = byte
                held_byte = True
                break
            drained += 1
        if drained:
            self._padding_seen = True
            self._clean_exchanges = 0
            self._log_protocol("Drained %d trailing NUL padding byte(s)", drained)
        elif held_byte:
            self._clean_exchanges = 0
        else:
            self._clean_exchanges += 1
            if self._skip_timed_windows():
                self._log_protocol(
                    "Learned single-NUL framing after %d clean exchange(s); "
                    "skipping timed drain/flush windows",
                    self._clean_exchanges,
                )

    async def _flush_stale_buffer(self, reader: "StreamReader") -> None:
        """
        Discard any stale bytes buffered from previous exchanges.

        Belt-and-braces companion to _drain_nul_padding(): anything still
        buffered right before a new command is written cannot belong to that
        command's response, so it is logged and dropped.

        The timed read is skipped once single-NUL framing has been learned;
        finding stale bytes pins the full windows for the connection's life.
        """
        stale = bytearray(self._read_ahead)
        self._read_ahead = b""
        while not self._skip_timed_windows():
            try:
                chunk = await asyncio.wait_for(
                    reader.read(1024), timeout=BUFFER_DRAIN_TIMEOUT
                )
            except (OSError, asyncio.IncompleteReadError):
                break
            if not chunk:
                # EOF; the next read will surface the closed connection.
                break
            stale += chunk
        if stale:
            self._padding_seen = True
            self._clean_exchanges = 0
            self._log_protocol(
                "Flushed stale buffered bytes before send: %s",
                self._summarize_bytes(bytes(stale)),
            )

    def _validate_response(
        self, text: str, _expect: str | None, command: bytes
    ) -> None:
        """Validate response text against expected pattern."""
        # Detect device-side command error or protocol desync (nulls).
        # The matrix firmware intermittently returns empty responses on
        # otherwise-healthy TCP connections (most often for `get_output_mute`,
        # also seen on volume / source queries). Treat these as transient
        # *application-layer* failures — propagate to the caller without
        # tearing down the socket. See issue #102.
        if text == "" or re.search(r"^command\s+error$", text, re.IGNORECASE):
            _LOGGER.debug(
                "Device returned error/empty response for command: %s",
                command.hex(),
            )
            msg = "Triad command error or empty response"
            raise TransientDeviceError(msg)

    async def _send_command(self, command: bytes, *, expect: str | None = None) -> str:
        """
        Send a command and return the response string.

        Adds a small inter-command delay, logs raw traffic, and applies a
        reasonable timeout to reads.
        """
        self._log_protocol("_send_command(): waiting for lock")
        async with self._lock:
            self._log_protocol("_send_command(): acquired lock")
            await self._ensure_connection_for_send()
            # Create local non-optional references for type checkers
            writer = cast("asyncio.StreamWriter", self._writer)
            reader = cast("asyncio.StreamReader", self._reader)
            await self._flush_stale_buffer(reader)
            await self._write_command_bytes(writer, command)
            response = await self._read_response_bytes(reader)
            text = response.decode(errors="replace").strip("\x00").strip()
            self._log_protocol("RX text=%s", self._summarize_text(text))
            # Evaluate the first (and only) frame. If it doesn't match the
            # expected pattern, allow exactly one skip for an unsolicited
            # AudioSense event, then re-evaluate the next frame.
            if (
                expect is not None
                and text
                and not re.search(expect, text, re.IGNORECASE)
            ):
                if re.search(
                    # Some firmware appends a literal "$" to AudioSense events.
                    r"^AudioSense:Input\[\d+\]\s*:\s*(0|1)\s*\$?\s*$",
                    text,
                    re.IGNORECASE,
                ):
                    self._log_protocol(
                        "Skipping unsolicited AudioSense event: %s", text
                    )
                    response = await self._read_response_bytes(reader)
                    text = response.decode(errors="replace").strip("\x00").strip()
                    self._log_protocol("RX text=%s", self._summarize_text(text))
                # After optional skip, if still not matching -> error
                if text and not re.search(expect, text, re.IGNORECASE):
                    _LOGGER.warning("Unexpected response: %s", text)
                    self.close_nowait()
                    err_msg = "Unexpected response from device"
                    raise OSError(err_msg)
            self._validate_response(text, expect, command)
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
        _LOGGER.info("Set volume for output %d to %.2f", output_channel, capped)
        self._log_protocol(
            "Set volume response for output %d: %s", output_channel, resp
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
        _LOGGER.warning("Could not parse output volume from response: %s", resp)
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
        _LOGGER.info("Set mute for output %d to %s", output_channel, mute)
        self._log_protocol("Set mute response for output %d: %s", output_channel, resp)

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
            self._log_protocol(
                "Volume step up (large) response for output %d: %s",
                output_channel,
                resp,
            )
        else:
            self._log_protocol(
                "Volume step up (small) response for output %d: %s",
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
        resp = await self._send_command(cmd, expect=r"(Input\s+Source|Audio\s+Off)")
        if large:
            _LOGGER.info("Volume step down (large) for output %d", output_channel)
            self._log_protocol(
                "Volume step down (large) response for output %d: %s",
                output_channel,
                resp,
            )
        else:
            self._log_protocol(
                "Volume step down (small) response for output %d: %s",
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
        _LOGGER.info("Set output %d to input %d", output_channel, input_channel)
        self._log_protocol(
            "Set output response for output %d -> input %d: %s",
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
        _LOGGER.warning("Could not parse output source from response: %s", resp)
        return None

    async def set_trigger_zone(self, zone: int = 1, *, on: bool) -> None:
        """
        Set a trigger zone on or off.

        Args:
            zone: 1-based trigger zone index (1..3).
                Default 1 for backwards compatibility.
            on: True to enable, False to disable.

        Command mapping:
            Zone 1 on:  FF 55 03 05 50 00, Zone 1 off: FF 55 03 05 51 00
            Zone 2 on:  FF 55 03 05 50 01, Zone 2 off: FF 55 03 05 51 01
            Zone 3 on:  FF 55 03 05 50 02, Zone 3 off: FF 55 03 05 51 02

        The pattern is: FF 55 03 05 <base> <zone-1>
        where <base> is 0x50 for on or 0x51 for off.

        """
        # Normalize zone to 1..3
        zone = max(1, min(zone, 3))

        zone_byte = zone - 1  # 0 for zone 1, 1 for zone 2, 2 for zone 3
        # Build explicit hex command per observed device opcodes
        hex_zone = f"{zone_byte:02X}"
        if on:
            # Examples: zone1 on: FF5503055000, zone2 on: FF5503055001
            cmd = bytearray.fromhex(f"FF55030550{hex_zone}")
        else:
            # Examples: zone1 off: FF5503055100, zone2 off: FF5503055101
            cmd = bytearray.fromhex(f"FF55030551{hex_zone}")
        resp = await self._send_command(cmd, expect=r"Max\s+Volume|0x|dB|Set\s+.*")
        _LOGGER.info("Set trigger zone %d to %s", zone, on)
        self._log_protocol("Set trigger zone response for zone %d: %s", zone, resp)

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
            _LOGGER.info("Disconnected output %d", output_channel)
        else:
            _LOGGER.info("Requested disconnect for output %d", output_channel)
        self._log_protocol(
            "Disconnect output response for %d: %s", output_channel, resp
        )
