"""TriadAMS TCP protocol simulator for integration tests."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from custom_components.triad_ams.const import VOLUME_STEPS

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

_LOGGER = logging.getLogger(__name__)


class TriadAmsSimulator:
    """Simulates a Triad AMS device over TCP."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        input_count: int = 8,
        output_count: int = 8,
    ) -> None:
        """Initialize the simulator."""
        self.host = host
        self.port = port
        self.input_count = input_count
        self.output_count = output_count

        # Device state
        self._volumes: dict[int, int] = dict.fromkeys(
            range(1, output_count + 1), 50
        )  # 0-100
        self._mutes: dict[int, bool] = dict.fromkeys(range(1, output_count + 1), False)
        self._sources: dict[int, int | None] = dict.fromkeys(range(1, output_count + 1))
        self._zones: dict[int, bool] = {1: False, 2: False, 3: False}

        self._server: asyncio.Server | None = None
        self._running = False

    async def start(self) -> tuple[str, int]:
        """Start the simulator server."""
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        addr = self._server.sockets[0].getsockname()
        self._running = True
        _LOGGER.info("TriadAMS simulator started on %s:%s", addr[0], addr[1])
        return (addr[0], addr[1])

    async def stop(self) -> None:
        """Stop the simulator server."""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            _LOGGER.info("TriadAMS simulator stopped")

    async def _read_command_header(
        self, reader: asyncio.StreamReader
    ) -> tuple[bytes, str] | None:
        """Read command header (5 bytes) and return header bytes and hex string."""
        try:
            header_bytes = await asyncio.wait_for(reader.readexactly(5), timeout=5.0)
        except (asyncio.IncompleteReadError, TimeoutError) as e:
            _LOGGER.debug("Error reading command header: %s", e)
            return None
        if len(header_bytes) < 5:
            return None
        header_hex = header_bytes.hex().upper()
        _LOGGER.debug("Received header: %s", header_hex)
        return (header_bytes, header_hex)

    def _get_command_length(self, header_hex: str) -> int | None:
        """Determine command length based on header."""
        if header_hex.startswith("FF550303"):
            return 6
        if header_hex.startswith("FF550403"):
            return 7
        if header_hex.startswith("FF550305"):
            return 6
        return None

    async def _read_command_data(
        self, reader: asyncio.StreamReader, expected_length: int
    ) -> bytes | None:
        """Read remaining command data bytes."""
        data_bytes_to_read = expected_length - 5
        _LOGGER.debug("Reading %d data bytes", data_bytes_to_read)
        try:
            remaining_data = await asyncio.wait_for(
                reader.readexactly(data_bytes_to_read), timeout=5.0
            )
        except (asyncio.IncompleteReadError, TimeoutError) as e:
            _LOGGER.debug("Error reading command data: %s", e)
            return None
        if len(remaining_data) < data_bytes_to_read:
            _LOGGER.warning(
                "Incomplete data read: got %d, expected %d",
                len(remaining_data),
                data_bytes_to_read,
            )
            return None
        _LOGGER.debug("Received data: %s", remaining_data.hex())
        return remaining_data

    async def _read_unknown_command(
        self, reader: asyncio.StreamReader, header_bytes: bytes
    ) -> bytes | None:
        """Read unknown command using null terminator fallback."""
        try:
            remaining = await asyncio.wait_for(reader.readuntil(b"\x00"), timeout=5.0)
            return header_bytes + remaining[:-1]  # Exclude null terminator
        except (asyncio.IncompleteReadError, TimeoutError) as e:
            _LOGGER.debug("Error reading unknown command: %s", e)
            return None

    async def _send_response(self, writer: asyncio.StreamWriter, response: str) -> None:
        """Send response to client."""
        _LOGGER.debug("Sending response: %s", response)
        writer.write(response.encode() + b"\x00")
        await writer.drain()
        _LOGGER.debug("Response sent")
        # Small delay for device tolerance
        await asyncio.sleep(0.1)

    async def _handle_command_loop(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle command processing loop."""
        while self._running:
            try:
                # Read command header
                header_result = await self._read_command_header(reader)
                if header_result is None:
                    break
                header_bytes, header_hex = header_result

                # Determine command length
                cmd_data_length = self._get_command_length(header_hex)
                if cmd_data_length is None:
                    # Unknown header, try fallback
                    command = await self._read_unknown_command(reader, header_bytes)
                    if command is None:
                        break
                    response = self._process_command(command)
                    if not response:
                        response = "command error"
                    await self._send_response(writer, response)
                    continue

                # Read remaining data bytes
                remaining_data = await self._read_command_data(reader, cmd_data_length)
                if remaining_data is None:
                    break

                # Combine header and data
                command = header_bytes + remaining_data
                _LOGGER.debug(
                    "Processing command: %s (len=%d)", command.hex(), len(command)
                )

                # Process command
                try:
                    response = self._process_command(command)
                    if not response:
                        response = "command error"
                    _LOGGER.debug("Command processed, response: %s", response)
                except Exception:
                    _LOGGER.exception("Error processing command")
                    response = "command error"

                await self._send_response(writer, response)

            except TimeoutError:
                _LOGGER.debug("Client timeout")
                break
            except asyncio.IncompleteReadError as e:
                _LOGGER.debug("Client disconnected: %s", e)
                break
            except Exception:
                _LOGGER.exception("Unexpected error in client handler")
                break

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a client connection."""
        _LOGGER.debug("Client connected")
        try:
            await self._handle_command_loop(reader, writer)
        except Exception:
            _LOGGER.exception("Error handling client")
        finally:
            writer.close()
            await writer.wait_closed()
            _LOGGER.debug("Client disconnected")

    def _handle_get_volume(self, cmd_bytes: bytes) -> str | None:
        """Handle get output volume command: FF 55 04 03 1E F5 <output>."""
        output = self._parse_output_channel(cmd_bytes, 6)
        if not self._validate_output(output):
            return None
        volume = self._volumes.get(output, 50)
        return f"Volume : 0x{volume:02X}"

    def _handle_set_volume(self, cmd_bytes: bytes) -> str | None:
        """Handle set output volume command: FF 55 04 03 1E <output> <value>."""
        output = self._parse_output_channel(cmd_bytes, 5)
        value = cmd_bytes[6]
        if not self._validate_output(output):
            return None
        self._volumes[output] = min(100, max(0, value))
        return f"Output Volume : 0x{self._volumes[output]:02X}"

    def _handle_set_mute_on(self, cmd_bytes: bytes) -> str | None:
        """Handle set mute on command: FF 55 03 03 17 <output>."""
        output = self._parse_output_channel(cmd_bytes, 5)
        if not self._validate_output(output):
            return None
        self._mutes[output] = True
        return f"Get Out[{output}] Mute status : mute"

    def _handle_set_mute_off(self, cmd_bytes: bytes) -> str | None:
        """Handle set mute off command: FF 55 03 03 18 <output>."""
        output = self._parse_output_channel(cmd_bytes, 5)
        if not self._validate_output(output):
            return None
        self._mutes[output] = False
        return f"Get Out[{output}] Mute status : Unmute"

    def _handle_get_mute(self, cmd_bytes: bytes) -> str | None:
        """Handle get mute command: FF 55 04 03 17 F5 <output>."""
        output = self._parse_output_channel(cmd_bytes, 6)
        if not self._validate_output(output):
            return None
        muted = self._mutes.get(output, False)
        status = "mute" if muted else "Unmute"
        return f"Get Out[{output}] Mute status : {status}"

    def _handle_volume_step_up_small(self, cmd_bytes: bytes) -> str | None:
        """Handle volume step up small: FF 55 03 03 13 <output>."""
        output = self._parse_output_channel(cmd_bytes, 5)
        if not self._validate_output(output):
            return None
        self._volumes[output] = min(100, self._volumes.get(output, 50) + 1)
        return "Input Source : input 1"

    def _handle_volume_step_up_large(self, cmd_bytes: bytes) -> str | None:
        """Handle volume step up large: FF 55 03 03 15 <output>."""
        output = self._parse_output_channel(cmd_bytes, 5)
        if not self._validate_output(output):
            return None
        self._volumes[output] = min(100, self._volumes.get(output, 50) + 5)
        return "Input Source : input 1"

    def _handle_volume_step_down_small(self, cmd_bytes: bytes) -> str | None:
        """Handle volume step down small: FF 55 03 03 14 <output>."""
        output = self._parse_output_channel(cmd_bytes, 5)
        if not self._validate_output(output):
            return None
        self._volumes[output] = max(0, self._volumes.get(output, 50) - 1)
        if self._volumes[output] == 0:
            return "Audio Off"
        return "Input Source : input 1"

    def _handle_volume_step_down_large(self, cmd_bytes: bytes) -> str | None:
        """Handle volume step down large: FF 55 03 03 16 <output>."""
        output = self._parse_output_channel(cmd_bytes, 5)
        if not self._validate_output(output):
            return None
        self._volumes[output] = max(0, self._volumes.get(output, 50) - 5)
        if self._volumes[output] == 0:
            return "Audio Off"
        return "Input Source : input 1"

    def _handle_get_source(self, cmd_bytes: bytes) -> str | None:
        """Handle get output source: FF 55 04 03 1D F5 <output>."""
        output = self._parse_output_channel(cmd_bytes, 6)
        if not self._validate_output(output):
            return None
        source = self._sources.get(output)
        if source is None:
            return "Audio Off"
        return f"Input Source : input {source}"

    def _handle_disconnect_output(self, cmd_bytes: bytes) -> str | None:
        """Handle disconnect output: FF 55 04 03 1D <output> <invalid>."""
        output = self._parse_output_channel(cmd_bytes, 5)
        input_ch_raw = cmd_bytes[6]  # Raw byte value (0-based input_count)
        # If input_ch_raw >= input_count (0-based), it's a disconnect
        if not self._validate_output(output) or input_ch_raw < self.input_count:
            return None
        self._sources[output] = None
        self._update_zone_state(output)
        return "Set Output : 0x00"

    def _handle_set_source(self, cmd_bytes: bytes) -> str | None:
        """Handle set output to input: FF 55 04 03 1D <output> <input>."""
        output = self._parse_output_channel(cmd_bytes, 5)
        input_ch = cmd_bytes[6] + 1
        if not self._validate_output(output) or not (1 <= input_ch <= self.input_count):
            return None
        self._sources[output] = input_ch
        zone = self._zone_for_output(output)
        if not self._zones[zone]:
            self._zones[zone] = True
        return f"Set output {output} to input {input_ch}"

    def _handle_set_zone_on(self, cmd_bytes: bytes) -> str | None:
        """Handle set trigger zone on: FF 55 03 05 50 <zone-1>."""
        zone = cmd_bytes[5] + 1  # 0-based to 1-based
        if not (1 <= zone <= 3):
            return None
        self._zones[zone] = True
        return "Max Volume : 0x64"

    def _handle_set_zone_off(self, cmd_bytes: bytes) -> str | None:
        """Handle set trigger zone off: FF 55 03 05 51 <zone-1>."""
        zone = cmd_bytes[5] + 1  # 0-based to 1-based
        if not (1 <= zone <= 3):
            return None
        self._zones[zone] = False
        return "Max Volume : 0x64"

    def _process_command(self, command: bytes) -> str:
        """Process a command and return response using dispatcher pattern."""
        if len(command) < 5:
            return "command error"

        header = command[0:5].hex().upper()
        cmd_len = len(command)

        # Command matchers: (header, length, optional_byte_check, handler)
        # Most specific matches first
        matchers: list[
            tuple[str, int, int | None, int | None, Callable[[bytes], str | None]]
        ] = [
            # Get commands (have 0xF5 byte)
            ("FF5504031E", 7, 5, 0xF5, self._handle_get_volume),
            ("FF55040317", 7, 5, 0xF5, self._handle_get_mute),
            ("FF5504031D", 7, 5, 0xF5, self._handle_get_source),
            # Disconnect (specific pattern)
            ("FF5504031D", 7, None, None, self._handle_disconnect_output),
            # Set commands
            ("FF5504031E", 7, None, None, self._handle_set_volume),
            ("FF5504031D", 7, None, None, self._handle_set_source),
            ("FF55030317", 6, None, None, self._handle_set_mute_on),
            ("FF55030318", 6, None, None, self._handle_set_mute_off),
            ("FF55030313", 6, None, None, self._handle_volume_step_up_small),
            ("FF55030315", 6, None, None, self._handle_volume_step_up_large),
            ("FF55030314", 6, None, None, self._handle_volume_step_down_small),
            ("FF55030316", 6, None, None, self._handle_volume_step_down_large),
            ("FF55030550", 6, None, None, self._handle_set_zone_on),
            ("FF55030551", 6, None, None, self._handle_set_zone_off),
        ]

        for match_header, match_len, check_index, check_value, handler in matchers:
            byte_check = (
                check_index is None
                or check_value is None
                or command[check_index] == check_value
            )
            if header == match_header and cmd_len == match_len and byte_check:
                result = handler(command)
                if result:
                    return result

        # Unknown command
        _LOGGER.warning("Unknown command: %s", command.hex())
        return "command error"

    def _parse_output_channel(self, cmd_bytes: bytes, index: int) -> int:
        """Parse output channel from command bytes (0-based to 1-based)."""
        return cmd_bytes[index] + 1

    def _validate_output(self, output: int) -> bool:
        """Validate output channel is in valid range."""
        return 1 <= output <= self.output_count

    def _update_zone_state(self, output: int) -> None:
        """Update zone state based on output source assignment."""
        zone = self._zone_for_output(output)
        # Check if zone is now empty
        zone_empty = all(
            self._sources.get(o) is None
            for o in range(1, self.output_count + 1)
            if self._zone_for_output(o) == zone
        )
        if zone_empty:
            self._zones[zone] = False
        elif self._sources.get(output) is not None:
            # Zone has at least one active output
            self._zones[zone] = True

    def _zone_for_output(self, output: int) -> int:
        """Calculate zone for output (1-based zones, 1-3)."""
        zone_raw = (output - 1) // 8 + 1
        return max(1, min(zone_raw, 3))

    def get_volume(self, output: int) -> float:
        """Get volume for output (0.0-1.0)."""
        if 1 <= output <= self.output_count:
            return self._volumes.get(output, 50) / VOLUME_STEPS
        return 0.0

    def get_mute(self, output: int) -> bool:
        """Get mute state for output."""
        return self._mutes.get(output, False)

    def get_source(self, output: int) -> int | None:
        """Get source for output."""
        return self._sources.get(output)

    def get_zone_state(self, zone: int) -> bool:
        """Get zone trigger state."""
        return self._zones.get(zone, False)


@contextlib.asynccontextmanager
async def triad_ams_simulator(
    host: str = "127.0.0.1",
    port: int = 0,
    input_count: int = 8,
    output_count: int = 8,
) -> AsyncGenerator[tuple[TriadAmsSimulator, str, int]]:
    """Context manager for TriadAMS simulator."""
    simulator = TriadAmsSimulator(host, port, input_count, output_count)
    try:
        host_addr, port_addr = await simulator.start()
        yield (simulator, host_addr, port_addr)
    finally:
        await simulator.stop()
