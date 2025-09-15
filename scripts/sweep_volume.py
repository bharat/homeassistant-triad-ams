#!/usr/bin/env python3
# sweep_volume.py
# Usage: ./sweep_volume.py <ip> <port> <output_channel 1..8>
#    [--start 1]
#    [--end 100]
#    [--sleep 0.15]
# ruff: noqa: T201
"""Sweep volume levels for a given output channel."""

from __future__ import annotations

import argparse
import re
import socket
import sys
import time


def read_until_null(sock: socket.socket, timeout: float = 5.0) -> bytes:
    """Read until a null terminator is received."""
    sock.settimeout(timeout)
    buf = bytearray()
    while True:
        b = sock.recv(1)
        if not b:
            msg = "connection closed before null terminator"
            raise TimeoutError(msg)
        if b == b"\x00":
            break
        buf.extend(b)
    return bytes(buf)


def send_and_read(sock: socket.socket, payload: bytes, timeout: float = 5.0) -> str:
    """Send a payload and read the response."""
    sock.sendall(payload)
    frame = read_until_null(sock, timeout=timeout)
    text = frame.decode(errors="replace").strip("\x00").strip()
    # Skip one unsolicited AudioSense event if it appears
    if re.search(r"^AudioSense:Input\[\d+\]\s*:\s*(0|1)\s*$", text, re.IGNORECASE):
        # Read next frame
        frame = read_until_null(sock, timeout=timeout)
        text = frame.decode(errors="replace").strip("\x00").strip()
    return text


def main(argv: list[str]) -> int:
    """Sweep volume levels for a given output channel."""
    p = argparse.ArgumentParser()
    p.add_argument("ip")
    p.add_argument("port", type=int)
    p.add_argument("output", type=int)
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--end", type=int, default=100)
    p.add_argument("--sleep", type=float, default=0.15, help="delay between commands")
    p.add_argument("--timeout", type=float, default=5.0)
    args = p.parse_args(argv)
    out_idx = args.output - 1
    if out_idx < 0 or out_idx > 7:  # noqa: PLR2004
        print("output must be 1..8", file=sys.stderr)
        return 2

    addr = (args.ip, args.port)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(5.0)
        s.connect(addr)
        time.sleep(0.2)

        print("step,db,raw")
        for step in range(args.start, args.end + 1):
            # Set volume: FF 55 04 03 1E <out> <step>
            set_cmd = bytes.fromhex("FF5504031E") + bytes([out_idx, step])
            _ = send_and_read(s, set_cmd, timeout=args.timeout)
            time.sleep(args.sleep)
            # Query dB: FF 55 04 03 1E F5 <out>
            get_cmd = bytes.fromhex("FF5504031EF5") + bytes([out_idx])
            txt2 = send_and_read(s, get_cmd, timeout=args.timeout)
            m = re.search(r"Volume\s*:\s*(-?\d+(?:\.\d+)?)", txt2)
            db = m.group(1) if m else ""
            print(f"{step},{db},{txt2}")
            time.sleep(args.sleep)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
