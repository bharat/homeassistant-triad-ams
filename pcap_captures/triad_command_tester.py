#!/usr/bin/env python3
"""Interactive TCP command tester for the Triad AMS16v2 audio matrix.

Sends individual protocol frames (from ``triad_ams16v2_commands.md``) to a
real Triad AMS device over TCP so each command can be manually validated.
The script prompts for an IP/port once, then presents a category/command
menu. Commands that need extra parameters (channel index, dB value, Hz,
etc.) prompt for them before building and sending the frame. The firmware
upgrade command is intentionally omitted (destructive/irreversible).

Typical usage:

    uv run python triad_command_tester.py
"""

from __future__ import annotations

import socket
import struct
import sys

DEFAULT_PORT = 52000
RECV_TIMEOUT = 2.0
NUM_CHANNELS = 16  # AMS16v2; override at the IP prompt if testing 8/24-ch models


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


def prompt_float(text: str, lo: float, hi: float, default: float | None = None) -> float:
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


def prompt_channel(text: str = "Channel index") -> int:
    """Prompts for a 0-based channel index within NUM_CHANNELS."""
    return prompt_int(text, 0, NUM_CHANNELS - 1)


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
        if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
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

    def send_and_receive(self, data: bytes) -> bytes:
        """Sends a frame and reads whatever the device replies within the timeout.

        Args:
            data: Raw frame bytes to send.

        Returns:
            The raw bytes received in response (may be empty).
        """
        if self.sock is None:
            self.connect()
        assert self.sock is not None
        self.sock.sendall(data)
        chunks: list[bytes] = []
        try:
            while True:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        except TimeoutError:
            pass
        except OSError:
            pass
        return b"".join(chunks)


def show_result(sent: bytes, received: bytes) -> None:
    """Prints the sent frame and the device's response in hex + ASCII."""
    print(f"  Sent ({len(sent)} bytes): {sent.hex(' ').upper()}")
    if received:
        printable = "".join(chr(b) if 32 <= b < 127 else "." for b in received)
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
    # Documented vendor quirk: LL=3 but only 2 payload bytes are sent.
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
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x0A, 0xA2, 0xF5, ch]))


def cmd_get_input_autosense_flag() -> bytes:
    ch = prompt_channel("Input channel index")
    return frame(0x55, bytes([0x0A, 0xA0, 0xF5, ch]))


def cmd_set_autosense_delay() -> bytes:
    delay = prompt_int("Off-delay (raw byte)", 0, 255)
    return frame(0x55, bytes([0x0A, 0xA3, 0x00, delay]))


def cmd_poll_audio_sense() -> bytes:
    ch = prompt_channel("Input channel index")
    return frame(0x56, bytes([0x02, 0x03, 0xF5, ch]))


def cmd_set_input_gain() -> bytes:
    ch = prompt_channel("Input channel index")
    db = prompt_float("Gain dB", -12.0, 12.0, 0.0)
    return frame(0x55, bytes([0x02, 0x04, ch, db_to_gain_byte(db)]))


def cmd_get_input_gain() -> bytes:
    ch = prompt_channel("Input channel index")
    return frame(0x55, bytes([0x02, 0x04, 0xF5, ch]))


def cmd_set_input_delay() -> bytes:
    ch = prompt_channel("Input channel index")
    ms = prompt_int("Delay (ms)", 0, 80)
    return frame(0x56, bytes([0x02, 0x04, ch, ms]))


def cmd_get_input_delay() -> bytes:
    ch = prompt_channel("Input channel index")
    return frame(0x56, bytes([0x02, 0x04, 0xF5, ch]))


def cmd_set_output_source() -> bytes:
    ch = prompt_channel("Output channel index")
    src = prompt_channel("Source input index")
    return frame(0x55, bytes([0x03, 0x1D, ch, src]))


def cmd_get_output_source() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x1D, 0xF5, ch]))


def cmd_disconnect_output_16() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x1D, ch, 0x10]))


def cmd_disconnect_output_8() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x1D, ch, 0x08]))


def cmd_set_output_delay() -> bytes:
    ch = prompt_channel("Output channel index")
    ms = prompt_int("Delay (ms)", 0, 80)
    return frame(0x56, bytes([0x03, 0x09, ch, ms]))


def cmd_get_output_delay() -> bytes:
    ch = prompt_channel("Output channel index")
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
    ch = prompt_channel("Output channel index")
    mode = prompt_choice("Output mode", OUTPUT_MODES)
    return frame(0x56, bytes([0x03, 0x0B, ch, mode]))


def cmd_get_output_mode() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x56, bytes([0x03, 0x0B, 0xF5, ch]))


def cmd_set_output_mute_on() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x17, ch]))


def cmd_set_output_mute_off() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x18, ch]))


def cmd_get_mute_status() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x17, 0xF5, ch]))


def cmd_set_output_volume() -> bytes:
    ch = prompt_channel("Output channel index")
    vol = prompt_int("Volume", 0, 100)
    return frame(0x55, bytes([0x03, 0x1E, ch, vol]))


def cmd_get_output_volume() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x1E, 0xF5, ch]))


def cmd_set_max_volume() -> bytes:
    ch = prompt_channel("Output channel index")
    vol = prompt_int("Max volume", 0, 100)
    return frame(0x55, bytes([0x03, 0x1F, ch, vol]))


def cmd_get_max_volume() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x1F, 0xF5, ch]))


def cmd_set_turnon_volume() -> bytes:
    ch = prompt_channel("Output channel index")
    vol = prompt_int("Turn-on volume", 0, 100)
    return frame(0x55, bytes([0x03, 0x33, ch, vol]))


def cmd_get_turnon_volume() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x33, 0xF5, ch]))


def cmd_set_output_balance() -> bytes:
    ch = prompt_channel("Output channel index")
    bal = prompt_float("Balance (-12=L12, 0=center, +12=R12)", -12.0, 12.0, 0.0)
    return frame(0x55, bytes([0x03, 0x31, ch, db_to_gain_byte(bal)]))


def cmd_get_output_balance() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x31, 0xF5, ch]))


def cmd_set_output_loudness_on() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x1A, ch]))


def cmd_set_output_loudness_off() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x1B, ch]))


def cmd_get_output_loudness() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x1A, 0xF5, ch]))


def cmd_set_test_tone_volume() -> bytes:
    ch = prompt_channel("Output channel index")
    vol = prompt_int("Test-tone level (0-100, ~-24..0 dB scale)", 0, 100)
    return frame(0x56, bytes([0x04, 0x01, ch, vol]))


# --- Legacy / parallel command paths ---
def cmd_old_set_stereo() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x10, ch]))


def cmd_old_get_mono_stereo() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x10, 0xF5, ch]))


def cmd_old_set_mono() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x11, ch]))


def cmd_old_set_bass() -> bytes:
    ch = prompt_channel("Output channel index")
    db = prompt_float("Bass gain dB", -12.0, 12.0, 0.0)
    return frame(0x55, bytes([0x03, 0x2F, ch, db_to_gain_byte(db)]))


def cmd_old_get_bass() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x2F, 0xF5, ch]))


def cmd_old_set_treble() -> bytes:
    ch = prompt_channel("Output channel index")
    db = prompt_float("Treble gain dB", -12.0, 12.0, 0.0)
    return frame(0x55, bytes([0x03, 0x30, ch, db_to_gain_byte(db)]))


def cmd_old_get_treble() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x30, 0xF5, ch]))


# --- Commented-out in driver source (dead code, but real frames) ---
def cmd_dead_toggle_mono() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x12, ch]))


def cmd_dead_toggle_mute() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x19, ch]))


def cmd_dead_vol_up() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x13, ch]))


def cmd_dead_vol_down() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x14, ch]))


def cmd_dead_vol_up3() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x15, ch]))


def cmd_dead_vol_down3() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x16, ch]))


def cmd_dead_toggle_loudness() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x55, bytes([0x03, 0x1C, ch]))


# --- Tone control / shelving filters ---
def cmd_set_low_shelf_freq() -> bytes:
    ch = prompt_channel("Output channel index")
    hz = prompt_int("Low shelf frequency (Hz)", 20, 2000, 100)
    return frame(0x56, bytes([0x03, 0x03, ch]) + enc_4b(hz))


def cmd_get_low_shelf_freq() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x56, bytes([0x03, 0x03, 0xF5, ch]))


def cmd_set_low_shelf_gain() -> bytes:
    ch = prompt_channel("Output channel index")
    db = prompt_float("Low shelf gain dB", -12.0, 12.0, 0.0)
    return frame(0x56, bytes([0x03, 0x0D, ch]) + enc_4b_signed_x100(db))


def cmd_get_low_shelf_gain() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x56, bytes([0x03, 0x0D, 0xF5, ch]))


def cmd_set_low_shelf_q() -> bytes:
    ch = prompt_channel("Output channel index")
    q = prompt_float("Low shelf Q", 0.5, 15.0, 0.58)
    return frame(0x56, bytes([0x03, 0x04, ch]) + enc_4b_signed_x100(q))


def cmd_get_low_shelf_q() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x56, bytes([0x03, 0x04, 0xF5, ch]))


def cmd_set_high_shelf_freq() -> bytes:
    ch = prompt_channel("Output channel index")
    hz = prompt_int("High shelf frequency (Hz)", 20, 20000, 8000)
    return frame(0x56, bytes([0x03, 0x01, ch]) + enc_4b(hz))


def cmd_get_high_shelf_freq() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x56, bytes([0x03, 0x01, 0xF5, ch]))


def cmd_set_high_shelf_gain() -> bytes:
    ch = prompt_channel("Output channel index")
    db = prompt_float("High shelf gain dB", -12.0, 12.0, 0.0)
    return frame(0x56, bytes([0x03, 0x0C, ch]) + enc_4b_signed_x100(db))


def cmd_get_high_shelf_gain() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x56, bytes([0x03, 0x0C, 0xF5, ch]))


def cmd_set_high_shelf_q() -> bytes:
    ch = prompt_channel("Output channel index")
    q = prompt_float("High shelf Q", 0.5, 15.0, 0.58)
    return frame(0x56, bytes([0x03, 0x02, ch]) + enc_4b_signed_x100(q))


def cmd_get_high_shelf_q() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x56, bytes([0x03, 0x02, 0xF5, ch]))


# --- 2.1 crossover ---
def cmd_set_crossover_freq() -> bytes:
    ch = prompt_channel("Primary output channel index")
    hz = prompt_int("Crossover frequency (Hz)", 20, 20000, 80)
    return frame(0x56, bytes([0x03, 0x05, ch]) + enc_4b(hz))


def cmd_get_crossover_freq() -> bytes:
    ch = prompt_channel("Primary output channel index")
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
    ch = prompt_channel("Primary output channel index")
    slope = prompt_choice("Crossover type/slope", CROSSOVER_TYPES)
    return frame(0x56, bytes([0x03, 0x06, ch, slope]))


def cmd_get_crossover_type() -> bytes:
    ch = prompt_channel("Primary output channel index")
    return frame(0x56, bytes([0x03, 0x06, 0xF5, ch]))


def cmd_set_sub_offset() -> bytes:
    ch = prompt_channel("Primary output channel index")
    db = prompt_float("Sub-output volume offset dB", -12.0, 12.0, 0.0)
    return frame(0x56, bytes([0x03, 0x07, ch, db_to_gain_byte(db)]))


def cmd_get_sub_offset() -> bytes:
    ch = prompt_channel("Primary output channel index")
    return frame(0x56, bytes([0x03, 0x07, 0xF5, ch]))


# --- Room / Speaker EQ (12 bands) ---
def band_selector(band: int, param: int) -> int:
    """Computes the band-selector byte: ((band-1) << 4) | param."""
    return ((band - 1) << 4) | param


def prompt_band() -> int:
    return prompt_int("Band number (1-6 Speaker EQ, 7-12 Room EQ)", 1, 12)


def cmd_set_band_freq() -> bytes:
    ch = prompt_channel("Output channel index")
    band = prompt_band()
    hz = prompt_int("Frequency (Hz)", 20, 20000, 1000)
    sel = band_selector(band, 0)
    return frame(0x56, bytes([0x05, sel, ch]) + enc_4b(hz))


def cmd_get_band_freq() -> bytes:
    ch = prompt_channel("Output channel index")
    band = prompt_band()
    sel = band_selector(band, 0)
    return frame(0x56, bytes([0x05, sel, 0xF5, ch]))


def cmd_set_band_gain() -> bytes:
    ch = prompt_channel("Output channel index")
    band = prompt_band()
    db = prompt_float("Gain dB", -12.0, 12.0, 0.0)
    sel = band_selector(band, 1)
    return frame(0x56, bytes([0x05, sel, ch]) + enc_4b_signed_x100(db))


def cmd_get_band_gain() -> bytes:
    ch = prompt_channel("Output channel index")
    band = prompt_band()
    sel = band_selector(band, 1)
    return frame(0x56, bytes([0x05, sel, 0xF5, ch]))


def cmd_set_band_q() -> bytes:
    ch = prompt_channel("Output channel index")
    band = prompt_band()
    q = prompt_float("Q", 0.5, 15.0, 1.0)
    sel = band_selector(band, 2)
    return frame(0x56, bytes([0x05, sel, ch]) + enc_4b_signed_x100(q))


def cmd_get_band_q() -> bytes:
    ch = prompt_channel("Output channel index")
    band = prompt_band()
    sel = band_selector(band, 2)
    return frame(0x56, bytes([0x05, sel, 0xF5, ch]))


def cmd_lock_room_eq() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x56, bytes([0x03, 0x08, ch, 0x01]))


def cmd_unlock_room_eq() -> bytes:
    ch = prompt_channel("Output channel index")
    return frame(0x56, bytes([0x03, 0x08, ch, 0x00]))


def cmd_query_room_eq_lock() -> bytes:
    ch = prompt_channel("Output channel index")
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


# --------------------------------------------------------------------------- #
# Menu structure: category -> list of (label, builder)
# --------------------------------------------------------------------------- #
MENU: dict[str, list[tuple[str, "callable"]]] = {
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
        ("Disconnect Output (16-output models)", cmd_disconnect_output_16),
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
        ("Zone 1-8 Trigger ON", cmd_zone1_8_on),
        ("Zone 1-8 Trigger OFF", cmd_zone1_8_off),
        ("Zone 9-16 Trigger ON", cmd_zone9_16_on),
        ("Zone 9-16 Trigger OFF", cmd_zone9_16_off),
        ("ASG Trigger ON", cmd_asg_on),
        ("ASG Trigger OFF", cmd_asg_off),
    ],
}


def send_raw_hex(conn: TriadConn) -> None:
    """Prompts for a raw hex string and sends it verbatim (no framing added)."""
    raw = prompt_str("Hex bytes, space or no separators (e.g. 'FF 55 03 01 01 F5')")
    cleaned = raw.replace(" ", "").replace(",", "")
    try:
        data = bytes.fromhex(cleaned)
    except ValueError as exc:
        print(f"  Invalid hex: {exc}")
        return
    received = conn.send_and_receive(data)
    show_result(data, received)


def run_menu(conn: TriadConn) -> None:
    """Runs the top-level category menu loop until the user quits."""
    categories = list(MENU.keys())
    while True:
        print("\n=== Triad AMS Command Tester ===")
        for idx, cat in enumerate(categories, start=1):
            print(f"  {idx}. {cat}")
        print(f"  {len(categories) + 1}. Send raw hex frame")
        print("  0. Quit")
        choice = prompt_int("Select category", 0, len(categories) + 1)
        if choice == 0:
            return
        if choice == len(categories) + 1:
            send_raw_hex(conn)
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
        show_result(data, received)


def main() -> int:
    """Entry point: prompts for connection details, then runs the menu."""
    global NUM_CHANNELS

    print("Triad AMS16v2 Command Tester")
    print("(firmware upgrade is intentionally not offered - all other commands are testable)\n")

    host = prompt_str("Triad AMS IP address")
    if not host:
        print("An IP address is required.")
        return 1
    port = prompt_int("TCP port", 1, 65535, DEFAULT_PORT)
    NUM_CHANNELS = prompt_int("Number of channels on this model", 1, 24, 16)

    conn = TriadConn(host, port)
    try:
        conn.connect()
    except OSError as exc:
        print(f"Could not connect to {host}:{port}: {exc}")
        return 1
    print(f"Connected to {host}:{port}")

    try:
        run_menu(conn)
    except (KeyboardInterrupt, EOFError):
        print("\nExiting.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
