#!/usr/bin/env python3
"""Interactive / headless TCP command tester for Triad AMS audio matrices.

Covers the TS-AMS8 (8x8), TS-AMS16 (16x16) and TS-AMS24 (24x24). Adapted from
``pcap_captures/triad_command_tester.py`` (AMS16v2) in
bharat/homeassistant-triad-ams; it uses the same FF55/FF56 frames as
``triad_ams16v2_commands.md``. Written to validate the untested models (see
issue #137 for the AMS24), but nothing in it is tied to one model.

Changes vs the AMS16v2 tester:
  * Model selection (AMS8 / AMS16 / AMS24) sets the channel count, which
    drives channel ranges, the disconnect sentinel and the sweep.
  * Channels are entered 1-based (as printed on the unit and in responses)
    and converted to the 0-based wire byte (e.g. output 24 -> 0x17).
  * Disconnect uses the "input count" sentinel the integration already
    sends (``connection.disconnect_output``): 0x08 / 0x10 / 0x18. The fixed
    0x10 command is kept but warns on models where 0x10 is a real input.
  * Trigger menu labels each byte with its known or candidate meaning per
    model (AMS8: 00 = 1-8, 01 = ASG; AMS16: 00 = 1-8, 01 = 9-16, 02 = ASG;
    AMS24: 02/03 UNCONFIRMED), plus a raw-byte probe.
  * Validation menu: read-only sweep of every output/input, a guided
    route/disconnect test on one output, and a trigger-byte probe.
  * ``--sweep`` runs the read-only sweep headless (no prompts) and exits.
  * Every frame sent and every raw reply is appended to a session log file
    (hex + text) that can be attached to a GitHub issue as-is.
  * Replies are read up to their NUL terminator rather than always waiting
    the full 2 s timeout, so full sweeps take minutes less. Bytes left over
    before the next send (late replies, AudioSense events) are logged as
    STALE instead of being attributed to the next command.
  * The sweep retries an empty reply once (the firmware sometimes returns
    empty replies, see issue #102), so "no reply" means it failed twice.

Sends individual protocol frames to a real Triad AMS device over TCP so each
command can be manually validated.
The script prompts for an IP/port once, then presents a category/command
menu. Commands that need extra parameters (channel index, dB value, Hz,
etc.) prompt for them before building and sending the frame. The firmware
upgrade command is intentionally omitted (destructive/irreversible).

Typical usage:

    uv run python triad_matrix_tester.py

Headless read-only sweep (no prompts; writes the session log and exits):

    uv run python triad_matrix_tester.py --host 192.168.1.50 --model AMS24 --sweep

Any of --host/--port/--model/--log given on the command line skips the
matching startup prompt in interactive mode too.
"""

from __future__ import annotations

import argparse
import datetime as dt
import socket
import struct
import sys
import time
from pathlib import Path

DEFAULT_PORT = 52000
RECV_TIMEOUT = 2.0  # max wait for a reply (or the rest of one) to arrive
PAD_TIMEOUT = 0.05  # wait for NUL padding / stale bytes (integration uses 50 ms)
NUM_CHANNELS = 24  # overwritten at startup from the selected model
MODEL_CHANNELS = {"AMS8": 8, "AMS16": 16, "AMS24": 24}
MODEL = "AMS24"  # overwritten at startup
SWEEP_DELAY = 0.15  # seconds between sweep frames (integration uses 150 ms)
ROUTE_DELAY = 0.2  # routing wants ~100 ms before the next command
LOG_PATH: str | None = None
IPV4_OCTET_COUNT = 4
IPV4_OCTET_MAX = 255
ASCII_PRINTABLE_MIN = 32
ASCII_PRINTABLE_MAX = 127  # exclusive upper bound


# --------------------------------------------------------------------------- #
# Prompt helpers
# --------------------------------------------------------------------------- #
def prompt_str(text: str, default: str | None = None) -> str:
    """Prompts for a free-text string, optionally with a default."""
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{text}{suffix}: ").strip()
    return value or (default or "")


def prompt_int(text: str, lo: int, hi: int, default: int | None = None) -> int:
    """Prompts for an integer within [lo, hi], re-prompting on bad input."""
    suffix = f" ({lo}-{hi})" + (f" [{default}]" if default is not None else "")
    while True:
        raw = input(f"{text}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("  Not a number, try again.")
            continue
        if lo <= value <= hi:
            return value
        print(f"  Out of range ({lo}-{hi}), try again.")


def prompt_float(
    text: str, lo: float, hi: float, default: float | None = None
) -> float:
    """Prompts for a float within [lo, hi], re-prompting on bad input."""
    suffix = f" ({lo}-{hi})" + (f" [{default}]" if default is not None else "")
    while True:
        raw = input(f"{text}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        try:
            value = float(raw)
        except ValueError:
            print("  Not a number, try again.")
            continue
        if lo <= value <= hi:
            return value
        print(f"  Out of range ({lo}-{hi}), try again.")


def prompt_channel(text: str = "Channel") -> int:
    """Prompts for a 1-based channel number and returns the 0-based wire byte.

    Responses from the device are 1-based (``Out[24]``) while the wire byte
    is 0-based (0x17), so the prompt is 1-based to match the unit's labels.
    """
    number = prompt_int(f"{text} number", 1, NUM_CHANNELS)
    wire = number - 1
    print(f"  -> wire byte 0x{wire:02X}")
    return wire


def prompt_choice(text: str, options: list[tuple[str, int]]) -> int:
    """Prompts for one of a fixed set of (label, value) options."""
    print(f"{text}:")
    for idx, (label, _val) in enumerate(options, start=1):
        print(f"  {idx}. {label}")
    choice = prompt_int("Select", 1, len(options))
    return options[choice - 1][1]


def prompt_ip(text: str) -> tuple[int, int, int, int]:
    """Prompts for a dotted-quad IPv4 address, returns it as 4 octets."""
    while True:
        raw = input(f"{text} (a.b.c.d): ").strip()
        parts = raw.split(".")
        if len(parts) == IPV4_OCTET_COUNT and all(
            p.isdigit() and 0 <= int(p) <= IPV4_OCTET_MAX for p in parts
        ):
            return tuple(int(p) for p in parts)  # type: ignore[return-value]
        print("  Invalid IPv4 address, try again.")


# --------------------------------------------------------------------------- #
# Encoding helpers
# --------------------------------------------------------------------------- #
def enc_4b(value: int) -> bytes:
    """Encodes an unsigned integer as a 4-byte big-endian field."""
    return struct.pack(">I", value & 0xFFFFFFFF)


def enc_4b_signed_x100(value: float) -> bytes:
    """Encodes a float as a 4-byte big-endian signed value, scaled x100."""
    return struct.pack(">i", round(value * 100))


def db_to_gain_byte(db: float) -> int:
    """Encodes a +/-12 dB value into the 0x00-0x30 gain byte format."""
    return round((db + 12) * 2)


def frame(group: int, payload: bytes, length_override: int | None = None) -> bytes:
    """Builds a full ``FF <GG> <LL> <payload>`` frame.

    Args:
        group: Group byte, 0x55 or 0x56.
        payload: Payload bytes following the length byte.
        length_override: If set, use this value for LL instead of
            len(payload) - needed for the documented firmware-version
            quirk where LL=3 but only 2 payload bytes are actually sent.

    Returns:
        The complete frame as bytes.
    """
    length = length_override if length_override is not None else len(payload)
    return bytes([0xFF, group, length]) + payload


# --------------------------------------------------------------------------- #
# Connection
# --------------------------------------------------------------------------- #
class TriadConn:
    """A simple persistent TCP connection to the Triad AMS for manual testing."""

    def __init__(self, host: str, port: int) -> None:
        """Initializes the connection wrapper without connecting yet.

        Args:
            host: Device IP address or hostname.
            port: TCP port (default 52000).
        """
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None

    def connect(self) -> None:
        """Opens the TCP connection, closing any prior one first."""
        self.close()
        self.sock = socket.create_connection((self.host, self.port), timeout=5.0)
        self.sock.settimeout(RECV_TIMEOUT)

    def close(self) -> None:
        """Closes the connection if open."""
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _read_stale(self, sock: socket.socket) -> bytes:
        """Reads anything already buffered before a new frame is sent.

        Such bytes cannot belong to the next command's reply (a late reply,
        or an unsolicited AudioSense event), so the caller logs them as
        stale instead of letting them land in the next exchange.

        Raises:
            ConnectionResetError: The device closed the connection.
        """
        chunks: list[bytes] = []
        sock.settimeout(PAD_TIMEOUT)
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    log_stale(b"".join(chunks))
                    msg = "device closed the connection"
                    raise ConnectionResetError(msg)
                chunks.append(chunk)
        except TimeoutError:
            pass
        return b"".join(chunks)

    def send_and_receive(self, data: bytes) -> bytes:
        """Sends a frame and reads the device's reply up to its NUL terminator.

        Args:
            data: Raw frame bytes to send.

        Returns:
            The raw bytes received in response (may be empty).

        Raises:
            OSError: The connection failed or the device closed it.
        """
        if self.sock is None:
            self.connect()
        if self.sock is None:
            msg = "connect() did not establish a socket"
            raise RuntimeError(msg)
        log_stale(self._read_stale(self.sock))
        self.sock.sendall(data)
        chunks: list[bytes] = []
        self.sock.settimeout(RECV_TIMEOUT)
        try:
            while True:
                chunk = self.sock.recv(4096)
                if not chunk:
                    if not chunks:
                        msg = "device closed the connection"
                        raise ConnectionResetError(msg)
                    break
                chunks.append(chunk)
                # Replies end in NUL (the integration reads up to it). Once it
                # has arrived, only wait briefly for trailing NUL padding;
                # until then keep waiting, so a reply that arrives in pieces
                # is not cut short.
                if b"\x00" in chunk:
                    self.sock.settimeout(PAD_TIMEOUT)
        except TimeoutError:
            pass
        return b"".join(chunks)


def to_text(received: bytes) -> str:
    """Returns the printable ASCII of a reply, NUL padding stripped."""
    return "".join(
        chr(b) if ASCII_PRINTABLE_MIN <= b < ASCII_PRINTABLE_MAX else "."
        for b in received.rstrip(b"\x00")
    )


def log_exchange(label: str, sent: bytes, received: bytes) -> None:
    """Appends one exchange to the session log (if logging is enabled)."""
    if not LOG_PATH:
        return
    stamp = dt.datetime.now(dt.UTC).astimezone().isoformat(timespec="milliseconds")
    with Path(LOG_PATH).open("a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {MODEL} {label}\n")
        fh.write(f"  sent: {sent.hex(' ').upper()}\n")
        fh.write(f"  recv_len: {len(received)}\n")
        fh.write(f"  recv_hex: {received.hex(' ').upper()}\n")
        fh.write(f"  recv_text: {to_text(received)}\n\n")


def log_stale(stale: bytes) -> None:
    """Prints and logs bytes that arrived outside any exchange.

    NUL padding alone is ignored; anything else is kept as evidence (it is
    usually a late reply to the previous command or an AudioSense event).
    """
    if not stale.strip(b"\x00"):
        return
    print(f"  STALE ({len(stale)} bytes, not part of the next reply): {to_text(stale)}")
    log_exchange("STALE (arrived after the previous exchange)", b"", stale)


def show_result(sent: bytes, received: bytes, label: str = "") -> None:
    """Prints the sent frame and the device's response in hex + ASCII."""
    log_exchange(label or "raw", sent, received)
    print(f"  Sent ({len(sent)} bytes): {sent.hex(' ').upper()}")
    if received:
        printable = "".join(
            chr(b) if ASCII_PRINTABLE_MIN <= b < ASCII_PRINTABLE_MAX else "."
            for b in received
        )
        print(f"  Recv ({len(received)} bytes): {received.hex(' ').upper()}")
        print(f"  Recv (text): {printable}")
    else:
        print("  Recv: (no response / timeout)")


# --------------------------------------------------------------------------- #
# Command builders - each returns a full frame ready to send
# --------------------------------------------------------------------------- #
def cmd_power_on() -> bytes:
    return frame(0x55, bytes([0x01, 0x01]))


def cmd_power_off() -> bytes:
    return frame(0x55, bytes([0x01, 0x02]))


def cmd_power_toggle() -> bytes:
    return frame(0x55, bytes([0x01, 0x03]))


def cmd_get_power_status() -> bytes:
    return frame(0x55, bytes([0x01, 0x01, 0xF5]))


def cmd_net_standby_on() -> bytes:
    return frame(0x55, bytes([0x08, 0x83, 0x01]))


def cmd_net_standby_off() -> bytes:
    return frame(0x55, bytes([0x08, 0x83, 0x00]))


def cmd_get_mac_address() -> bytes:
    return frame(0x55, bytes([0x08, 0x80, 0xF5]))


def cmd_get_firmware_version() -> bytes:
    # Documented vendor quirk: LL=3 but only 2 payload bytes are sent. Seen
    # in AMS16 captures only; a unit that honours LL may swallow the first
    # byte of the next frame, so the sweep sends the MAC query straight after
    # this one and flags it if that query gets no reply.
    return frame(0x55, bytes([0x06, 0x65]), length_override=0x03)


def cmd_reboot() -> bytes:
    return frame(0x55, bytes([0x06, 0xB4, 0x00]))


def cmd_factory_reset() -> bytes:
    return frame(0x55, bytes([0x0B, 0xB0]))


def cmd_get_webui_credentials() -> bytes:
    return frame(0x56, bytes([0x06, 0x02, 0xF5]))


def cmd_set_webui_credentials() -> bytes:
    username = prompt_str("Username")
    password = prompt_str("Password (8-32 chars)")
    ub = username.encode("ascii")
    pb = password.encode("ascii")
    payload = bytes([0x06, 0x02, len(ub)]) + ub + bytes([len(pb)]) + pb
    return frame(0x56, payload)


def cmd_get_ip_method() -> bytes:
    return frame(0x55, bytes([0x08, 0x81, 0xF5]))


def cmd_set_ip_dhcp() -> bytes:
    return frame(0x55, bytes([0x08, 0x81]))


def cmd_set_static_ip() -> bytes:
    ip = prompt_ip("IP address")
    mask = prompt_ip("Subnet mask")
    gw = prompt_ip("Gateway")
    payload = bytes([0x08, 0x82]) + bytes(ip) + bytes(mask) + bytes(gw)
    return frame(0x55, payload)


def cmd_set_autosense_global() -> bytes:
    on = prompt_choice("Auto-Sense", [("On", 0x01), ("Off", 0x00)])
    return frame(0x55, bytes([0x0A, 0xA2, on, 0xFF]))


def cmd_get_autosense_channel() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x0A, 0xA2, 0xF5, ch]))


def cmd_get_input_autosense_flag() -> bytes:
    ch = prompt_channel("Input")
    return frame(0x55, bytes([0x0A, 0xA0, 0xF5, ch]))


def cmd_set_autosense_delay() -> bytes:
    delay = prompt_int("Off-delay (raw byte)", 0, 255)
    return frame(0x55, bytes([0x0A, 0xA3, 0x00, delay]))


def cmd_poll_audio_sense() -> bytes:
    ch = prompt_channel("Input")
    return frame(0x56, bytes([0x02, 0x03, 0xF5, ch]))


def cmd_set_input_gain() -> bytes:
    ch = prompt_channel("Input")
    db = prompt_float("Gain dB", -12.0, 12.0, 0.0)
    return frame(0x55, bytes([0x02, 0x04, ch, db_to_gain_byte(db)]))


def cmd_get_input_gain() -> bytes:
    ch = prompt_channel("Input")
    return frame(0x55, bytes([0x02, 0x04, 0xF5, ch]))


def cmd_set_input_delay() -> bytes:
    ch = prompt_channel("Input")
    ms = prompt_int("Delay (ms)", 0, 80)
    return frame(0x56, bytes([0x02, 0x04, ch, ms]))


def cmd_get_input_delay() -> bytes:
    ch = prompt_channel("Input")
    return frame(0x56, bytes([0x02, 0x04, 0xF5, ch]))


def cmd_set_output_source() -> bytes:
    ch = prompt_channel("Output")
    src = prompt_channel("Source input")
    return frame(0x55, bytes([0x03, 0x1D, ch, src]))


def cmd_get_output_source() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x1D, 0xF5, ch]))


def cmd_disconnect_output_model() -> bytes:
    """Disconnect using the sentinel the integration sends: input count."""
    ch = prompt_channel("Output")
    sentinel = NUM_CHANNELS  # 0x08 / 0x10 / 0x18 - first invalid input byte
    print(f"  Sentinel for {MODEL}: 0x{sentinel:02X}")
    return frame(0x55, bytes([0x03, 0x1D, ch, sentinel]))


def cmd_disconnect_output_16() -> bytes:
    if NUM_CHANNELS > 16:  # noqa: PLR2004
        print(
            "  WARNING: on a 24-input model 0x10 is INPUT 17, so this will"
            " probably route input 17 rather than disconnect."
        )
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x1D, ch, 0x10]))


def cmd_disconnect_output_8() -> bytes:
    if NUM_CHANNELS > 8:  # noqa: PLR2004
        print(
            f"  WARNING: on a {NUM_CHANNELS}-input model 0x08 is INPUT 9, so this"
            " will probably route input 9 rather than disconnect."
        )
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x1D, ch, 0x08]))


def cmd_set_output_delay() -> bytes:
    ch = prompt_channel("Output")
    ms = prompt_int("Delay (ms)", 0, 80)
    return frame(0x56, bytes([0x03, 0x09, ch, ms]))


def cmd_get_output_delay() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x56, bytes([0x03, 0x09, 0xF5, ch]))


OUTPUT_MODES = [
    ("DSP Bypass Stereo", 0),
    ("Stereo", 1),
    ("Mono", 2),
    ("2.1 Stereo", 3),
    ("2.1 Mono", 4),
    ("Test Signal", 5),
]


def cmd_set_output_mode() -> bytes:
    ch = prompt_channel("Output")
    mode = prompt_choice("Output mode", OUTPUT_MODES)
    return frame(0x56, bytes([0x03, 0x0B, ch, mode]))


def cmd_get_output_mode() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x56, bytes([0x03, 0x0B, 0xF5, ch]))


def cmd_set_output_mute_on() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x17, ch]))


def cmd_set_output_mute_off() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x18, ch]))


def cmd_get_mute_status() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x17, 0xF5, ch]))


def cmd_set_output_volume() -> bytes:
    ch = prompt_channel("Output")
    vol = prompt_int("Volume", 0, 100)
    return frame(0x55, bytes([0x03, 0x1E, ch, vol]))


def cmd_get_output_volume() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x1E, 0xF5, ch]))


def cmd_set_max_volume() -> bytes:
    ch = prompt_channel("Output")
    vol = prompt_int("Max volume", 0, 100)
    return frame(0x55, bytes([0x03, 0x1F, ch, vol]))


def cmd_get_max_volume() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x1F, 0xF5, ch]))


def cmd_set_turnon_volume() -> bytes:
    ch = prompt_channel("Output")
    vol = prompt_int("Turn-on volume", 0, 100)
    return frame(0x55, bytes([0x03, 0x33, ch, vol]))


def cmd_get_turnon_volume() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x33, 0xF5, ch]))


def cmd_set_output_balance() -> bytes:
    ch = prompt_channel("Output")
    bal = prompt_float("Balance (-12=L12, 0=center, +12=R12)", -12.0, 12.0, 0.0)
    return frame(0x55, bytes([0x03, 0x31, ch, db_to_gain_byte(bal)]))


def cmd_get_output_balance() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x31, 0xF5, ch]))


def cmd_set_output_loudness_on() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x1A, ch]))


def cmd_set_output_loudness_off() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x1B, ch]))


def cmd_get_output_loudness() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x1A, 0xF5, ch]))


def cmd_set_test_tone_volume() -> bytes:
    ch = prompt_channel("Output")
    vol = prompt_int("Test-tone level (0-100, ~-24..0 dB scale)", 0, 100)
    return frame(0x56, bytes([0x04, 0x01, ch, vol]))


# --- Legacy / parallel command paths ---
def cmd_old_set_stereo() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x10, ch]))


def cmd_old_get_mono_stereo() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x10, 0xF5, ch]))


def cmd_old_set_mono() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x11, ch]))


def cmd_old_set_bass() -> bytes:
    ch = prompt_channel("Output")
    db = prompt_float("Bass gain dB", -12.0, 12.0, 0.0)
    return frame(0x55, bytes([0x03, 0x2F, ch, db_to_gain_byte(db)]))


def cmd_old_get_bass() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x2F, 0xF5, ch]))


def cmd_old_set_treble() -> bytes:
    ch = prompt_channel("Output")
    db = prompt_float("Treble gain dB", -12.0, 12.0, 0.0)
    return frame(0x55, bytes([0x03, 0x30, ch, db_to_gain_byte(db)]))


def cmd_old_get_treble() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x30, 0xF5, ch]))


# --- Commented-out in driver source (dead code, but real frames) ---
def cmd_dead_toggle_mono() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x12, ch]))


def cmd_dead_toggle_mute() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x19, ch]))


def cmd_dead_vol_up() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x13, ch]))


def cmd_dead_vol_down() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x14, ch]))


def cmd_dead_vol_up3() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x15, ch]))


def cmd_dead_vol_down3() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x16, ch]))


def cmd_dead_toggle_loudness() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x55, bytes([0x03, 0x1C, ch]))


# --- Tone control / shelving filters ---
def cmd_set_low_shelf_freq() -> bytes:
    ch = prompt_channel("Output")
    hz = prompt_int("Low shelf frequency (Hz)", 20, 2000, 100)
    return frame(0x56, bytes([0x03, 0x03, ch]) + enc_4b(hz))


def cmd_get_low_shelf_freq() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x56, bytes([0x03, 0x03, 0xF5, ch]))


def cmd_set_low_shelf_gain() -> bytes:
    ch = prompt_channel("Output")
    db = prompt_float("Low shelf gain dB", -12.0, 12.0, 0.0)
    return frame(0x56, bytes([0x03, 0x0D, ch]) + enc_4b_signed_x100(db))


def cmd_get_low_shelf_gain() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x56, bytes([0x03, 0x0D, 0xF5, ch]))


def cmd_set_low_shelf_q() -> bytes:
    ch = prompt_channel("Output")
    q = prompt_float("Low shelf Q", 0.5, 15.0, 0.58)
    return frame(0x56, bytes([0x03, 0x04, ch]) + enc_4b_signed_x100(q))


def cmd_get_low_shelf_q() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x56, bytes([0x03, 0x04, 0xF5, ch]))


def cmd_set_high_shelf_freq() -> bytes:
    ch = prompt_channel("Output")
    hz = prompt_int("High shelf frequency (Hz)", 20, 20000, 8000)
    return frame(0x56, bytes([0x03, 0x01, ch]) + enc_4b(hz))


def cmd_get_high_shelf_freq() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x56, bytes([0x03, 0x01, 0xF5, ch]))


def cmd_set_high_shelf_gain() -> bytes:
    ch = prompt_channel("Output")
    db = prompt_float("High shelf gain dB", -12.0, 12.0, 0.0)
    return frame(0x56, bytes([0x03, 0x0C, ch]) + enc_4b_signed_x100(db))


def cmd_get_high_shelf_gain() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x56, bytes([0x03, 0x0C, 0xF5, ch]))


def cmd_set_high_shelf_q() -> bytes:
    ch = prompt_channel("Output")
    q = prompt_float("High shelf Q", 0.5, 15.0, 0.58)
    return frame(0x56, bytes([0x03, 0x02, ch]) + enc_4b_signed_x100(q))


def cmd_get_high_shelf_q() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x56, bytes([0x03, 0x02, 0xF5, ch]))


# --- 2.1 crossover ---
def cmd_set_crossover_freq() -> bytes:
    ch = prompt_channel("Primary output")
    hz = prompt_int("Crossover frequency (Hz)", 20, 20000, 80)
    return frame(0x56, bytes([0x03, 0x05, ch]) + enc_4b(hz))


def cmd_get_crossover_freq() -> bytes:
    ch = prompt_channel("Primary output")
    return frame(0x56, bytes([0x03, 0x05, 0xF5, ch]))


CROSSOVER_TYPES = [
    ("Butterworth 12dB", 0),
    ("Butterworth 24dB", 1),
    ("Butterworth 48dB", 2),
    ("Linkwitz-Riley 12dB", 3),
    ("Linkwitz-Riley 24dB (default)", 4),
    ("Linkwitz-Riley 48dB", 5),
]


def cmd_set_crossover_type() -> bytes:
    ch = prompt_channel("Primary output")
    slope = prompt_choice("Crossover type/slope", CROSSOVER_TYPES)
    return frame(0x56, bytes([0x03, 0x06, ch, slope]))


def cmd_get_crossover_type() -> bytes:
    ch = prompt_channel("Primary output")
    return frame(0x56, bytes([0x03, 0x06, 0xF5, ch]))


def cmd_set_sub_offset() -> bytes:
    ch = prompt_channel("Primary output")
    db = prompt_float("Sub-output volume offset dB", -12.0, 12.0, 0.0)
    return frame(0x56, bytes([0x03, 0x07, ch, db_to_gain_byte(db)]))


def cmd_get_sub_offset() -> bytes:
    ch = prompt_channel("Primary output")
    return frame(0x56, bytes([0x03, 0x07, 0xF5, ch]))


# --- Room / Speaker EQ (12 bands) ---
def band_selector(band: int, param: int) -> int:
    """Computes the band-selector byte: ((band-1) << 4) | param."""
    return ((band - 1) << 4) | param


def prompt_band() -> int:
    return prompt_int("Band number (1-6 Speaker EQ, 7-12 Room EQ)", 1, 12)


def cmd_set_band_freq() -> bytes:
    ch = prompt_channel("Output")
    band = prompt_band()
    hz = prompt_int("Frequency (Hz)", 20, 20000, 1000)
    sel = band_selector(band, 0)
    return frame(0x56, bytes([0x05, sel, ch]) + enc_4b(hz))


def cmd_get_band_freq() -> bytes:
    ch = prompt_channel("Output")
    band = prompt_band()
    sel = band_selector(band, 0)
    return frame(0x56, bytes([0x05, sel, 0xF5, ch]))


def cmd_set_band_gain() -> bytes:
    ch = prompt_channel("Output")
    band = prompt_band()
    db = prompt_float("Gain dB", -12.0, 12.0, 0.0)
    sel = band_selector(band, 1)
    return frame(0x56, bytes([0x05, sel, ch]) + enc_4b_signed_x100(db))


def cmd_get_band_gain() -> bytes:
    ch = prompt_channel("Output")
    band = prompt_band()
    sel = band_selector(band, 1)
    return frame(0x56, bytes([0x05, sel, 0xF5, ch]))


def cmd_set_band_q() -> bytes:
    ch = prompt_channel("Output")
    band = prompt_band()
    q = prompt_float("Q", 0.5, 15.0, 1.0)
    sel = band_selector(band, 2)
    return frame(0x56, bytes([0x05, sel, ch]) + enc_4b_signed_x100(q))


def cmd_get_band_q() -> bytes:
    ch = prompt_channel("Output")
    band = prompt_band()
    sel = band_selector(band, 2)
    return frame(0x56, bytes([0x05, sel, 0xF5, ch]))


def cmd_lock_room_eq() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x56, bytes([0x03, 0x08, ch, 0x01]))


def cmd_unlock_room_eq() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x56, bytes([0x03, 0x08, ch, 0x00]))


def cmd_query_room_eq_lock() -> bytes:
    ch = prompt_channel("Output")
    return frame(0x56, bytes([0x03, 0x08, 0xF5, ch]))


# --- Triggers / Zones ---
def cmd_zone1_8_on() -> bytes:
    return frame(0x55, bytes([0x05, 0x50, 0x00]))


def cmd_zone1_8_off() -> bytes:
    return frame(0x55, bytes([0x05, 0x51, 0x00]))


def cmd_zone9_16_on() -> bytes:
    return frame(0x55, bytes([0x05, 0x50, 0x01]))


def cmd_zone9_16_off() -> bytes:
    return frame(0x55, bytes([0x05, 0x51, 0x01]))


def cmd_asg_on() -> bytes:
    return frame(0x55, bytes([0x05, 0x50, 0x02]))


def cmd_asg_off() -> bytes:
    return frame(0x55, bytes([0x05, 0x51, 0x02]))


# Byte meanings per model. AMS16v2 (documented): 00=1-8, 01=9-16, 02=ASG.
# AMS8 (per the Control4 triad_ams8_v2 driver, see triad_ams16v2_commands.md):
# 00=1-8, 01=ASG. The HA integration clamps outputs 17-24 to zone 3, so on an
# AMS24 it already sends 02 for them. AMS24: if the pattern is
# "one byte per bank of 8, ASG last", 02=17-24 and 03=ASG - a hypothesis, not
# documented.
def cmd_trigger_03_on_candidate() -> bytes:
    return frame(0x55, bytes([0x05, 0x50, 0x03]))


def cmd_trigger_03_off_candidate() -> bytes:
    return frame(0x55, bytes([0x05, 0x51, 0x03]))


def cmd_trigger_raw() -> bytes:
    on = prompt_choice("State", [("ON (0x50)", 0x50), ("OFF (0x51)", 0x51)])
    val = prompt_int("Trigger byte", 0, 0xFF)
    return frame(0x55, bytes([0x05, on, val]))


# --------------------------------------------------------------------------- #
# Menu structure: category -> list of (label, builder)
# --------------------------------------------------------------------------- #
MENU: dict[str, list[tuple[str, callable]]] = {
    "Power / Network / System": [
        ("Power On", cmd_power_on),
        ("Power Off", cmd_power_off),
        ("Power Toggle", cmd_power_toggle),
        ("Get Power Status", cmd_get_power_status),
        ("Network Standby On", cmd_net_standby_on),
        ("Network Standby Off", cmd_net_standby_off),
        ("Get MAC Address", cmd_get_mac_address),
        ("Get Firmware Version", cmd_get_firmware_version),
        ("Reboot", cmd_reboot),
        ("Factory Reset", cmd_factory_reset),
        ("Get Web-UI Credentials", cmd_get_webui_credentials),
        ("Set Web-UI Credentials", cmd_set_webui_credentials),
        ("Get IP Assignment Method", cmd_get_ip_method),
        ("Set IP to DHCP", cmd_set_ip_dhcp),
        ("Set Static IP", cmd_set_static_ip),
        ("Set Auto-Sense (global)", cmd_set_autosense_global),
        ("Get Auto-Sense (per-channel query form)", cmd_get_autosense_channel),
        ("Get per-input Auto-Sense flag", cmd_get_input_autosense_flag),
        ("Set Auto-Sense Off-Delay", cmd_set_autosense_delay),
        ("Poll Audio Sense", cmd_poll_audio_sense),
    ],
    "Input Configuration": [
        ("Set Input Gain", cmd_set_input_gain),
        ("Get Input Gain", cmd_get_input_gain),
        ("Set Input Delay", cmd_set_input_delay),
        ("Get Input Delay", cmd_get_input_delay),
    ],
    "Output Configuration": [
        ("Set Output Source", cmd_set_output_source),
        ("Get Output Source", cmd_get_output_source),
        (
            "Disconnect Output (sentinel = model input count)",
            cmd_disconnect_output_model,
        ),
        ("Disconnect Output (fixed 0x10, 16-output models)", cmd_disconnect_output_16),
        ("Disconnect Output (8-output models)", cmd_disconnect_output_8),
        ("Set Output Delay", cmd_set_output_delay),
        ("Get Output Delay", cmd_get_output_delay),
        ("Set Output Mode", cmd_set_output_mode),
        ("Get Output Mode", cmd_get_output_mode),
        ("Set Output Mute On", cmd_set_output_mute_on),
        ("Set Output Mute Off", cmd_set_output_mute_off),
        ("Get Mute Status", cmd_get_mute_status),
        ("Set Output Volume", cmd_set_output_volume),
        ("Get Output Volume", cmd_get_output_volume),
        ("Set Max Volume", cmd_set_max_volume),
        ("Get Max Volume", cmd_get_max_volume),
        ("Set Turn-On (Start) Volume", cmd_set_turnon_volume),
        ("Get Turn-On (Start) Volume", cmd_get_turnon_volume),
        ("Set Output Balance", cmd_set_output_balance),
        ("Get Output Balance", cmd_get_output_balance),
        ("Set Output Loudness On", cmd_set_output_loudness_on),
        ("Set Output Loudness Off", cmd_set_output_loudness_off),
        ("Get Output Loudness", cmd_get_output_loudness),
        ("Set Test-Tone Volume", cmd_set_test_tone_volume),
    ],
    "Legacy / Parallel Command Paths": [
        ("Old Set Stereo", cmd_old_set_stereo),
        ("Old Get Mono/Stereo", cmd_old_get_mono_stereo),
        ("Old Set Mono", cmd_old_set_mono),
        ("Old Set Bass (flat gain)", cmd_old_set_bass),
        ("Old Get Bass", cmd_old_get_bass),
        ("Old Set Treble (flat gain)", cmd_old_set_treble),
        ("Old Get Treble", cmd_old_get_treble),
        ("[dead code] Toggle Output Mono", cmd_dead_toggle_mono),
        ("[dead code] Toggle Output Mute", cmd_dead_toggle_mute),
        ("[dead code] Volume Up (single step)", cmd_dead_vol_up),
        ("[dead code] Volume Down (single step)", cmd_dead_vol_down),
        ("[dead code] Volume Up x3", cmd_dead_vol_up3),
        ("[dead code] Volume Down x3", cmd_dead_vol_down3),
        ("[dead code] Toggle Output Loudness", cmd_dead_toggle_loudness),
    ],
    "Tone Control - Shelving Filters": [
        ("Set Low Shelf Frequency", cmd_set_low_shelf_freq),
        ("Get Low Shelf Frequency", cmd_get_low_shelf_freq),
        ("Set Low Shelf Gain", cmd_set_low_shelf_gain),
        ("Get Low Shelf Gain", cmd_get_low_shelf_gain),
        ("Set Low Shelf Q", cmd_set_low_shelf_q),
        ("Get Low Shelf Q", cmd_get_low_shelf_q),
        ("Set High Shelf Frequency", cmd_set_high_shelf_freq),
        ("Get High Shelf Frequency", cmd_get_high_shelf_freq),
        ("Set High Shelf Gain", cmd_set_high_shelf_gain),
        ("Get High Shelf Gain", cmd_get_high_shelf_gain),
        ("Set High Shelf Q", cmd_set_high_shelf_q),
        ("Get High Shelf Q", cmd_get_high_shelf_q),
    ],
    "2.1 Audio Zone / Crossover": [
        ("Set Crossover Frequency", cmd_set_crossover_freq),
        ("Get Crossover Frequency", cmd_get_crossover_freq),
        ("Set Crossover Type/Slope", cmd_set_crossover_type),
        ("Get Crossover Type/Slope", cmd_get_crossover_type),
        ("Set Sub-Output Volume Offset", cmd_set_sub_offset),
        ("Get Sub-Output Volume Offset", cmd_get_sub_offset),
    ],
    "Room / Speaker Equalizer (12 bands)": [
        ("Set Band Frequency", cmd_set_band_freq),
        ("Get Band Frequency", cmd_get_band_freq),
        ("Set Band Gain", cmd_set_band_gain),
        ("Get Band Gain", cmd_get_band_gain),
        ("Set Band Q", cmd_set_band_q),
        ("Get Band Q", cmd_get_band_q),
        ("Lock Room EQ", cmd_lock_room_eq),
        ("Unlock Room EQ", cmd_unlock_room_eq),
        ("Query Room EQ Lock State", cmd_query_room_eq_lock),
    ],
    "Triggers / Zones": [
        ("Byte 0x00 ON (all models: zones 1-8)", cmd_zone1_8_on),
        ("Byte 0x00 OFF (all models: zones 1-8)", cmd_zone1_8_off),
        ("Byte 0x01 ON (AMS16/24: zones 9-16 / AMS8: ASG)", cmd_zone9_16_on),
        ("Byte 0x01 OFF (AMS16/24: zones 9-16 / AMS8: ASG)", cmd_zone9_16_off),
        ("Byte 0x02 ON (AMS16: ASG / AMS24 candidate: zones 17-24)", cmd_asg_on),
        ("Byte 0x02 OFF (AMS16: ASG / AMS24 candidate: zones 17-24)", cmd_asg_off),
        ("Byte 0x03 ON (AMS24 candidate: ASG)", cmd_trigger_03_on_candidate),
        ("Byte 0x03 OFF (AMS24 candidate: ASG)", cmd_trigger_03_off_candidate),
        ("Trigger with any byte (probe)", cmd_trigger_raw),
    ],
}


# --------------------------------------------------------------------------- #
# Validation routines (multi-frame; log everything)
# --------------------------------------------------------------------------- #
def query(group: int, b1: int, b2: int, wire: int) -> bytes:
    """Builds a GET frame: FF <group> 04 <b1> <b2> F5 <channel>."""
    return frame(group, bytes([b1, b2, 0xF5, wire]))


OUTPUT_QUERIES = [
    ("Output source", 0x55, 0x03, 0x1D),
    ("Output volume", 0x55, 0x03, 0x1E),
    ("Mute status", 0x55, 0x03, 0x17),
    ("Max volume", 0x55, 0x03, 0x1F),
    ("Turn-on volume", 0x55, 0x03, 0x33),
    ("Loudness", 0x55, 0x03, 0x1A),
    ("Output mode", 0x56, 0x03, 0x0B),
    ("Output delay", 0x56, 0x03, 0x09),
]
INPUT_QUERIES = [
    ("Input gain", 0x55, 0x02, 0x04),
    ("Input delay", 0x56, 0x02, 0x04),
    ("Audio sense", 0x56, 0x02, 0x03),
]


def exchange(
    conn: TriadConn,
    label: str,
    data: bytes,
    delay: float,
    *,
    retry_empty: bool = False,
) -> bytes:
    """Sends one frame, prints and logs it, then waits ``delay`` seconds.

    With ``retry_empty``, an empty reply is retried once (both attempts are
    logged): the firmware intermittently returns empty replies on healthy
    connections (issue #102), which should not read as "unsupported".
    """
    print(f"\n>>> {label}")
    try:
        received = conn.send_and_receive(data)
    except OSError as exc:
        print(f"  Connection error: {exc}. Reconnecting...")
        conn.connect()
        received = conn.send_and_receive(data)
    show_result(data, received, label)
    time.sleep(delay)
    if retry_empty and not received:
        return exchange(conn, f"{label} (retry)", data, delay)
    return received


def run_readonly_sweep(conn: TriadConn) -> list[str]:
    """Queries every output and input. Changes nothing on the unit.

    Returns:
        Labels of the queries that got no reply.
    """
    print(f"\nRead-only sweep of {NUM_CHANNELS} outputs and inputs...")
    exchange(conn, "Power status", cmd_get_power_status(), SWEEP_DELAY)
    exchange(conn, "Firmware version", cmd_get_firmware_version(), SWEEP_DELAY)
    # Sent straight after the firmware query on purpose (see its comment).
    mac = exchange(
        conn, "MAC address", cmd_get_mac_address(), SWEEP_DELAY, retry_empty=True
    )
    silent: list[str] = []
    for n in range(1, NUM_CHANNELS + 1):
        channel_queries = [
            (f"Out {n}: {name}", query(grp, b1, b2, n - 1))
            for name, grp, b1, b2 in OUTPUT_QUERIES
        ] + [
            (f"In {n}: {name}", query(grp, b1, b2, n - 1))
            for name, grp, b1, b2 in INPUT_QUERIES
        ]
        for label, data in channel_queries:
            if not exchange(conn, label, data, SWEEP_DELAY, retry_empty=True):
                silent.append(label)
    print("\nSweep done.")
    if not mac:
        print(
            "  MAC address query got no reply. It follows the firmware query,"
            " whose length byte is a known quirk - this unit may be reading it"
            " differently."
        )
    if silent:
        print(f"  {len(silent)} queries got no reply (after one retry):")
        for label in silent:
            print(f"   - {label}")
    else:
        print("  Every query got a reply.")
    low = NUM_CHANNELS - 7
    if low > 1:
        print(
            f"  Check the log: do Out/In {low}-{NUM_CHANNELS} answer the same"
            " way as the lower channels?"
        )
    return silent


def run_route_test(conn: TriadConn) -> None:
    """Routes one input to one output, then tests the disconnect sentinel.

    Sets the output volume to 0 first so nothing loud plays.
    """
    print("\nWrite test. Sets the chosen output's volume to 0 first.")
    top = f"{max(NUM_CHANNELS - 7, 1)}-{NUM_CHANNELS}"
    out = prompt_channel(f"Output to test (top bank {top} is least tested)")
    src = prompt_channel(f"Input to route (top bank {top} is least tested)")
    sentinel = NUM_CHANNELS
    steps = [
        ("BEFORE: source", query(0x55, 0x03, 0x1D, out), SWEEP_DELAY),
        ("BEFORE: volume", query(0x55, 0x03, 0x1E, out), SWEEP_DELAY),
        ("Set volume 0", frame(0x55, bytes([0x03, 0x1E, out, 0])), SWEEP_DELAY),
        ("Read back volume (expect 0)", query(0x55, 0x03, 0x1E, out), SWEEP_DELAY),
        (
            f"Route input {src + 1}",
            frame(0x55, bytes([0x03, 0x1D, out, src])),
            ROUTE_DELAY,
        ),
        ("Read back source", query(0x55, 0x03, 0x1D, out), SWEEP_DELAY),
        (
            f"Disconnect via 0x{sentinel:02X}",
            frame(0x55, bytes([0x03, 0x1D, out, sentinel])),
            ROUTE_DELAY,
        ),
        (
            "Read back source (expect Audio Off)",
            query(0x55, 0x03, 0x1D, out),
            SWEEP_DELAY,
        ),
    ]
    for label, data, delay in steps:
        exchange(conn, f"Out {out + 1}: {label}", data, delay)
    print(
        "\nIf the last read-back is not 'Audio Off', the disconnect byte is"
        " different on this unit - note what it says. The output is left"
        " disconnected at volume 0. Its previous source and volume are in the"
        " BEFORE lines; restore both from the Output menu if wanted."
    )


def run_trigger_probe(conn: TriadConn) -> None:
    """Fires trigger bytes 00-03 one at a time and records what happened."""
    print(
        "\nTrigger probe. For each byte, watch which 12V trigger jack (or"
        " connected amp) switches, then type what you saw."
        "\nWARNING: each byte is switched ON then OFF, so every trigger"
        " 0x00-0x03 is left OFF at the end. Any amp powered by those triggers"
        " will switch off. Use the Triggers menu to turn them back on."
    )
    if prompt_str("Continue? (y/N)", "n").lower() not in ("y", "yes"):
        print("  Skipped.")
        return
    for val in range(4):
        exchange(
            conn,
            f"Trigger 0x{val:02X} ON",
            frame(0x55, bytes([0x05, 0x50, val])),
            SWEEP_DELAY,
        )
        seen = prompt_str("What turned on? (e.g. '9-16', 'ASG', 'nothing')")
        exchange(
            conn,
            f"Trigger 0x{val:02X} OFF",
            frame(0x55, bytes([0x05, 0x51, val])),
            SWEEP_DELAY,
        )
        log_note(f"Trigger byte 0x{val:02X} observed: {seen or '(no note)'}")


def log_note(note: str) -> None:
    """Appends a free-text observation to the session log."""
    if LOG_PATH:
        with Path(LOG_PATH).open("a", encoding="utf-8") as fh:
            fh.write(f"NOTE: {note}\n\n")


VALIDATION = [
    ("Read-only sweep of all outputs/inputs (safe)", run_readonly_sweep),
    ("Route + disconnect test on one output (writes)", run_route_test),
    ("Trigger byte probe 0x00-0x03 (writes, interactive)", run_trigger_probe),
]


def run_validation(conn: TriadConn) -> None:
    """Menu for the multi-step validation routines."""
    while True:
        print(f"\n--- {MODEL} validation ---")
        for idx, (label, _fn) in enumerate(VALIDATION, start=1):
            print(f"  {idx}. {label}")
        print("  0. Back")
        choice = prompt_int("Select", 0, len(VALIDATION))
        if choice == 0:
            return
        try:
            VALIDATION[choice - 1][1](conn)
        except (KeyboardInterrupt, EOFError):
            print("\n  Cancelled.")
        except OSError as exc:
            print(f"  Connection error: {exc}")


def send_raw_hex(conn: TriadConn) -> None:
    """Prompts for a raw hex string and sends it verbatim (no framing added)."""
    raw = prompt_str("Hex bytes, space or no separators (e.g. 'FF 55 03 01 01 F5')")
    cleaned = raw.replace(" ", "").replace(",", "")
    try:
        data = bytes.fromhex(cleaned)
    except ValueError as exc:
        print(f"  Invalid hex: {exc}")
        return
    try:
        received = conn.send_and_receive(data)
    except OSError as exc:
        print(f"  Connection error: {exc}. Reconnecting...")
        try:
            conn.connect()
        except OSError as reconnect_exc:
            print(f"  Reconnect failed: {reconnect_exc}")
        return
    show_result(data, received, "raw hex")


def run_menu(conn: TriadConn) -> None:
    """Runs the top-level category menu loop until the user quits."""
    categories = list(MENU.keys())
    while True:
        print(f"\n=== Triad {MODEL} Command Tester ({NUM_CHANNELS}x{NUM_CHANNELS}) ===")
        for idx, cat in enumerate(categories, start=1):
            print(f"  {idx}. {cat}")
        print(f"  {len(categories) + 1}. Send raw hex frame")
        print(f"  {len(categories) + 2}. {MODEL} validation (sweep / route / triggers)")
        print("  0. Quit")
        choice = prompt_int("Select category", 0, len(categories) + 2)
        if choice == 0:
            return
        if choice == len(categories) + 1:
            send_raw_hex(conn)
            continue
        if choice == len(categories) + 2:
            run_validation(conn)
            continue
        run_category(conn, categories[choice - 1])


def run_category(conn: TriadConn, category: str) -> None:
    """Runs the command selection loop for a single category."""
    commands = MENU[category]
    while True:
        print(f"\n--- {category} ---")
        for idx, (label, _builder) in enumerate(commands, start=1):
            print(f"  {idx}. {label}")
        print("  0. Back")
        choice = prompt_int("Select command", 0, len(commands))
        if choice == 0:
            return
        label, builder = commands[choice - 1]
        print(f"\n>>> {label}")
        try:
            data = builder()
        except (KeyboardInterrupt, EOFError):
            print("\n  Cancelled.")
            continue
        try:
            received = conn.send_and_receive(data)
        except OSError as exc:
            print(f"  Connection error: {exc}. Reconnecting...")
            try:
                conn.connect()
            except OSError as reconnect_exc:
                print(f"  Reconnect failed: {reconnect_exc}")
                continue
            continue
        show_result(data, received, label)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses optional command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Interactive / headless command tester for Triad AMS matrices.",
    )
    parser.add_argument("--host", help="Triad AMS IP address or hostname")
    parser.add_argument("--port", type=int, help=f"TCP port (default {DEFAULT_PORT})")
    parser.add_argument(
        "--model",
        choices=sorted(MODEL_CHANNELS),
        type=str.upper,
        help="AMS8, AMS16 or AMS24 (required with --sweep)",
    )
    parser.add_argument(
        "--log",
        help="session log path ('-' to disable; default: timestamped file)",
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="run the read-only sweep with no prompts, then exit",
    )
    return parser.parse_args(argv)


def resolve_port(args: argparse.Namespace) -> int:
    """Returns the port from the CLI, the default (sweep), or a prompt."""
    if args.port is not None:
        return args.port
    if args.sweep:
        return DEFAULT_PORT
    return prompt_int("TCP port", 1, 65535, DEFAULT_PORT)


def resolve_model(args: argparse.Namespace) -> str:
    """Returns the model from the CLI or a prompt."""
    if args.model:
        return args.model
    return ("AMS8", "AMS16", "AMS24")[
        prompt_choice(
            "Model",
            [
                ("TS-AMS8 (8x8)", 0),
                ("TS-AMS16 (16x16)", 1),
                ("TS-AMS24 (24x24)", 2),
            ],
        )
    ]


def resolve_log(args: argparse.Namespace, model: str) -> str | None:
    """Returns the log path from the CLI, a timestamped default, or a prompt."""
    stamp = dt.datetime.now(dt.UTC).astimezone().strftime("%Y%m%dT%H%M%S")
    default_log = f"triad_{model.lower()}_session_{stamp}.log"
    if args.log is not None:
        path = args.log
    elif args.sweep:
        path = default_log
    else:
        path = prompt_str("Session log file ('-' to disable)", default_log)
    return None if path == "-" else path


def main(argv: list[str] | None = None) -> int:
    """Entry point: sets up the connection, then runs the menu or a sweep."""
    global NUM_CHANNELS, MODEL, LOG_PATH

    args = parse_args(argv)
    if args.sweep and not (args.host and args.model):
        print("--sweep needs --host and --model (AMS8, AMS16 or AMS24).")
        return 2

    print("Triad AMS Command Tester")
    if not args.sweep:
        print(
            "(firmware upgrade is intentionally not offered - all other commands"
            " are testable)\n"
        )

    host = args.host or prompt_str("Triad AMS IP address")
    if not host:
        print("An IP address is required.")
        return 1
    port = resolve_port(args)
    MODEL = resolve_model(args)
    NUM_CHANNELS = MODEL_CHANNELS[MODEL]
    LOG_PATH = resolve_log(args, MODEL)
    if LOG_PATH:
        print(f"Logging every frame to {LOG_PATH}")

    conn = TriadConn(host, port)
    try:
        conn.connect()
    except OSError as exc:
        print(f"Could not connect to {host}:{port}: {exc}")
        return 1
    print(f"Connected to {host}:{port} as {MODEL}")

    try:
        if args.sweep:
            silent = run_readonly_sweep(conn)
            total = 3 + NUM_CHANNELS * (len(OUTPUT_QUERIES) + len(INPUT_QUERIES))
            if len(silent) >= total - 3:
                print("No channel queries were answered - check model/firmware.")
                return 1
        else:
            run_menu(conn)
    except (KeyboardInterrupt, EOFError):
        print("\nExiting.")
    except OSError as exc:
        print(f"Connection error: {exc}")
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
