"""Exceptions for the Triad AMS integration."""

from __future__ import annotations


class TransientDeviceError(Exception):
    """
    Empty / malformed device response on a healthy TCP socket.

    Distinct from `OSError` / `TimeoutError` / `asyncio.IncompleteReadError`
    (transport-layer failures) — those still belong in
    `const.NETWORK_EXCEPTIONS` and trigger the coordinator's reconnect path.

    `TransientDeviceError` is the integration's signal that the matrix
    firmware shrugged at an application-layer query (typical pattern: empty
    response on ~10% of polls for certain commands). Callers should
    propagate / log / skip the query *without* tearing down the socket.

    Background: https://github.com/bharat/homeassistant-triad-ams/issues/102
    """
