"""TriadAMS TCP protocol simulator for integration tests."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from custom_components.triad_ams.const import VOLUME_STEPS

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

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

    async def _handle_client(  # noqa: PLR0912, PLR0915
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a client connection."""
        _LOGGER.debug("Client connected")
        try:
            while self._running:
                try:
                    # Read command header first (5 bytes) to determine command type
                    header_bytes = await asyncio.wait_for(
                        reader.readexactly(5), timeout=5.0
                    )
                    if len(header_bytes) < 5:
                        break

                    _LOGGER.debug("Received header: %s", header_bytes.hex())

                    # Determine command length based on header
                    header_hex = header_bytes.hex().upper()
                    cmd_data_length = 5  # Start with header length

                    # Commands with 6 bytes total: FF 55 03 03 XX <output>
                    if header_hex.startswith("FF550303"):
                        cmd_data_length = 6
                    # Commands with 7 bytes: FF 55 04 03 XX <output> <value>
                    # or FF 55 04 03 XX F5 <output>
                    elif header_hex.startswith("FF550403"):
                        cmd_data_length = 7
                    # Commands with 6 bytes: FF 55 03 05 XX <zone>
                    elif header_hex.startswith("FF550305"):
                        cmd_data_length = 6
                    else:
                        # Unknown header, try to read until null terminator as fallback
                        try:
                            remaining = await asyncio.wait_for(
                                reader.readuntil(b"\x00"), timeout=5.0
                            )
                            command = (
                                header_bytes + remaining[:-1]
                            )  # Exclude null terminator
                        except (asyncio.IncompleteReadError, TimeoutError) as e:
                            _LOGGER.debug("Error reading unknown command: %s", e)
                            break
                        # Process and continue
                        try:
                            response = self._process_command(command)
                            if not response:
                                response = "command error"
                        except Exception:
                            _LOGGER.exception("Error processing command")
                            response = "command error"
                        writer.write(response.encode() + b"\x00")
                        await writer.drain()
                        await asyncio.sleep(0.1)
                        continue

                    # Read remaining data bytes
                    # (commands don't have null terminators, only responses do)
                    data_bytes_to_read = cmd_data_length - 5
                    _LOGGER.debug("Reading %d data bytes", data_bytes_to_read)
                    remaining_data = await asyncio.wait_for(
                        reader.readexactly(data_bytes_to_read), timeout=5.0
                    )
                    if len(remaining_data) < data_bytes_to_read:
                        _LOGGER.warning(
                            "Incomplete data read: got %d, expected %d",
                            len(remaining_data),
                            data_bytes_to_read,
                        )
                        break

                    _LOGGER.debug("Received data: %s", remaining_data.hex())

                    # Combine header and data bytes
                    # (commands don't include null terminator)
                    command = header_bytes + remaining_data
                    _LOGGER.debug(
                        "Processing command: %s (len=%d)", command.hex(), len(command)
                    )

                    # Process command
                    try:
                        response = self._process_command(command)
                        # Always write a response, even if empty,
                        # to prevent client from hanging
                        if not response:
                            response = "command error"
                        _LOGGER.debug("Command processed, response: %s", response)
                    except Exception:
                        _LOGGER.exception("Error processing command")
                        response = "command error"
                    _LOGGER.debug("Sending response: %s", response)
                    writer.write(response.encode() + b"\x00")
                    await writer.drain()
                    _LOGGER.debug("Response sent")
                    # Small delay for device tolerance
                    await asyncio.sleep(0.1)

                except TimeoutError:
                    _LOGGER.debug("Client timeout")
                    break
                except asyncio.IncompleteReadError as e:
                    _LOGGER.debug("Client disconnected: %s", e)
                    break
                except Exception:
                    _LOGGER.exception("Unexpected error in client handler")
                    break

        except Exception:
            _LOGGER.exception("Error handling client")
        finally:
            writer.close()
            await writer.wait_closed()
            _LOGGER.debug("Client disconnected")

    def _process_command(self, command: bytes) -> str:  # noqa: C901, PLR0911, PLR0912, PLR0915
        """Process a command and return response."""
        # readuntil(b"\x00") stops at the first null byte and includes it in the result.
        # The command format is: <command_bytes>\x00
        # However, if the last data byte is 0x00 (e.g., output channel 1 = 0),
        # readuntil will stop there and include it. So we need to check:
        # - If command ends with \x00, it might be a terminator OR a data byte
        # - We know the expected command lengths, so we can determine which it is
        # For now, assume the last byte is always part of the command data
        # (the null terminator would be an 8th byte that readuntil doesn't include)
        cmd_bytes = command

        if len(cmd_bytes) < 5:
            return "command error"

        # Parse command header
        header = cmd_bytes[0:5].hex().upper()

        # Get output volume: FF 55 04 03 1E F5 <output>
        # Check this BEFORE "Set output volume" since both have the same header
        if header == "FF5504031E" and len(cmd_bytes) == 7 and cmd_bytes[5] == 0xF5:
            output = cmd_bytes[6] + 1  # 0-based to 1-based
            if 1 <= output <= self.output_count:
                volume = self._volumes.get(output, 50)
                return f"Volume : 0x{volume:02X}"

        # Set output volume: FF 55 04 03 1E <output> <value>
        if header == "FF5504031E" and len(cmd_bytes) == 7:
            output = cmd_bytes[5] + 1  # 0-based to 1-based
            value = cmd_bytes[6]
            if 1 <= output <= self.output_count:
                self._volumes[output] = min(100, max(0, value))
                return f"Output Volume : 0x{self._volumes[output]:02X}"

        # Set mute on: FF 55 03 03 17 <output>
        if header == "FF55030317" and len(cmd_bytes) == 6:
            output = cmd_bytes[5] + 1
            if 1 <= output <= self.output_count:
                self._mutes[output] = True
                return f"Get Out[{output}] Mute status : mute"

        # Set mute off: FF 55 03 03 18 <output>
        if header == "FF55030318" and len(cmd_bytes) == 6:
            output = cmd_bytes[5] + 1
            if 1 <= output <= self.output_count:
                self._mutes[output] = False
                return f"Get Out[{output}] Mute status : Unmute"

        # Get mute: FF 55 04 03 17 F5 <output>
        # Check this BEFORE "Set mute" commands since they share similar headers
        if header == "FF55040317" and len(cmd_bytes) == 7 and cmd_bytes[5] == 0xF5:
            output = cmd_bytes[6] + 1
            if 1 <= output <= self.output_count:
                muted = self._mutes.get(output, False)
                status = "mute" if muted else "Unmute"
                return f"Get Out[{output}] Mute status : {status}"

        # Volume step up small: FF 55 03 03 13 <output>
        if header == "FF55030313" and len(cmd_bytes) == 6:
            output = cmd_bytes[5] + 1
            if 1 <= output <= self.output_count:
                self._volumes[output] = min(100, self._volumes.get(output, 50) + 1)
                return "Input Source : input 1"

        # Volume step up large: FF 55 03 03 15 <output>
        if header == "FF55030315" and len(cmd_bytes) == 6:
            output = cmd_bytes[5] + 1
            if 1 <= output <= self.output_count:
                self._volumes[output] = min(100, self._volumes.get(output, 50) + 5)
                return "Input Source : input 1"

        # Volume step down small: FF 55 03 03 14 <output>
        if header == "FF55030314" and len(cmd_bytes) == 6:
            output = cmd_bytes[5] + 1
            if 1 <= output <= self.output_count:
                self._volumes[output] = max(0, self._volumes.get(output, 50) - 1)
                if self._volumes[output] == 0:
                    return "Audio Off"
                return "Input Source : input 1"

        # Volume step down large: FF 55 03 03 16 <output>
        if header == "FF55030316" and len(cmd_bytes) == 6:
            output = cmd_bytes[5] + 1
            if 1 <= output <= self.output_count:
                self._volumes[output] = max(0, self._volumes.get(output, 50) - 5)
                if self._volumes[output] == 0:
                    return "Audio Off"
                return "Input Source : input 1"

        # Get output source: FF 55 04 03 1D F5 <output>
        # Check this BEFORE "Set output to input" since both have the same header
        if header == "FF5504031D" and len(cmd_bytes) == 7 and cmd_bytes[5] == 0xF5:
            output = cmd_bytes[6] + 1
            if 1 <= output <= self.output_count:
                source = self._sources.get(output)
                if source is None:
                    return "Audio Off"
                return f"Input Source : input {source}"

        # Disconnect output (route to invalid input): FF 55 04 03 1D <output> <invalid>
        # Check this BEFORE "Set output to input" to handle disconnects first
        if header == "FF5504031D" and len(cmd_bytes) == 7:
            output = cmd_bytes[5] + 1
            input_ch_raw = cmd_bytes[6]  # Raw byte value (0-based input_count)
            # If input_ch_raw >= input_count (0-based), it's a disconnect
            # The command sends input_count directly (0-based), so if it's >=
            # input_count, it's invalid
            if 1 <= output <= self.output_count and input_ch_raw >= self.input_count:
                self._sources[output] = None
                # Update zone state
                zone = self._zone_for_output(output)
                # Check if zone is now empty
                zone_empty = all(
                    self._sources.get(o) is None
                    for o in range(1, self.output_count + 1)
                    if self._zone_for_output(o) == zone
                )
                if zone_empty:
                    self._zones[zone] = False
                # Return a response matching expected pattern:
                # r"Start\s+Vol|0x|dB|Set\s+.*"
                return "Set Output : 0x00"

        # Set output to input: FF 55 04 03 1D <output> <input>
        # Check this AFTER "Get output source" and "Disconnect"
        # since they're more specific
        if header == "FF5504031D" and len(cmd_bytes) == 7:
            output = cmd_bytes[5] + 1
            input_ch = cmd_bytes[6] + 1
            if 1 <= output <= self.output_count and 1 <= input_ch <= self.input_count:
                self._sources[output] = input_ch
                # Update zone state
                zone = self._zone_for_output(output)
                if not self._zones[zone]:
                    self._zones[zone] = True
                return f"Set output {output} to input {input_ch}"

        # Set trigger zone on: FF 55 03 05 50 <zone-1>
        if header == "FF55030550" and len(cmd_bytes) == 6:
            zone = cmd_bytes[5] + 1  # 0-based to 1-based
            if 1 <= zone <= 3:
                self._zones[zone] = True
                return "Max Volume : 0x64"

        # Set trigger zone off: FF 55 03 05 51 <zone-1>
        if header == "FF55030551" and len(cmd_bytes) == 6:
            zone = cmd_bytes[5] + 1  # 0-based to 1-based
            if 1 <= zone <= 3:
                self._zones[zone] = False
                return "Max Volume : 0x64"

        # Unknown command
        _LOGGER.warning("Unknown command: %s", cmd_bytes.hex())
        return "command error"

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
