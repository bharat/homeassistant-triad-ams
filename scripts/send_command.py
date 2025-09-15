#!/usr/bin/env python3
"""
Send a raw hex command to a Triad AMS switch and print the response.

Usage:
  ./scripts/send_command.py <ip> <port> <hex>

Examples:
  ./scripts/send_command.py 192.168.0.22 52000 "FF 55 04 03 1E 03 13"

Notes:
  - This script is independent of the Home Assistant integration code.
  - It writes the provided bytes and reads one null-terminated frame back.

"""
# ruff: noqa: T201

from __future__ import annotations

import argparse
import binascii
import socket
import sys
import time


def _clean_hex(s: str) -> bytes:
    cleaned = "".join(ch for ch in s if ch in "0123456789abcdefABCDEF")
    if not cleaned or len(cleaned) % 2 != 0:
        msg = "hex must contain an even number of hex digits"
        raise ValueError(msg)
    try:
        return bytes.fromhex(cleaned)
    except binascii.Error as err:  # pragma: no cover - safety
        msg = "invalid hex input"
        raise ValueError(msg) from err


def _read_until_null(sock: socket.socket, *, timeout: float = 5.0) -> bytes:
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


def main(argv: list[str]) -> int:
    """Send a raw hex command to a Triad AMS switch and print the response."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ip", help="Triad AMS IP address")
    parser.add_argument("port", type=int, help="Triad AMS TCP port (e.g., 52000)")
    parser.add_argument(
        "hex", help="Hex string, spaces allowed (e.g., 'FF 55 03 05 50 00')"
    )
    parser.add_argument(
        "--timeout", type=float, default=5.0, help="Read timeout seconds (default: 5)"
    )
    args = parser.parse_args(argv)

    try:
        payload = _clean_hex(args.hex)
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2

    addr = (args.ip, args.port)
    print(f"Connecting to {addr[0]}:{addr[1]} ...")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(5.0)
        s.connect(addr)
        # Some devices need a small settle time after connect
        time.sleep(0.2)

        print(f"Sending ({len(payload)} bytes): {payload.hex()}")
        s.sendall(payload)
        # Read one null-terminated frame
        try:
            frame = _read_until_null(s, timeout=args.timeout)
        except TimeoutError as err:
            print(f"Timed out waiting for response: {err}", file=sys.stderr)
            return 1

        text = frame.decode(errors="replace").strip()
        print(f"Received ({len(frame)} bytes): {frame.hex()}")
        print(f"Decoded: {text}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
