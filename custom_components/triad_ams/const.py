"""Constants for the Triad AMS integration."""

import asyncio

DOMAIN = "triad_ams"

VOLUME_STEPS = 0x64  # Device expects 0..0x64 (0..100) for volume-related values

# Connection and timeout constants
CONNECTION_TIMEOUT = 5.0  # Timeout for connection operations (seconds)
SHUTDOWN_TIMEOUT = 1.0  # Timeout for graceful shutdown of workers (seconds)
DEVICE_COMMAND_DELAY = 0.1  # Delay between command send and response read (seconds)
POST_CONNECT_DELAY = 0.2  # Delay after establishing connection (seconds)
BUFFER_DRAIN_TIMEOUT = 0.05  # Max wait when draining padding/stale bytes (seconds)
# Consecutive clean exchanges (no padding drained, no stale bytes flushed)
# before a connection decides the firmware uses single-NUL framing and stops
# paying the timed drain/flush windows on every command.
CLEAN_EXCHANGES_TO_SKIP_DRAIN = 3

# Network-related exceptions that should trigger connection reset
NETWORK_EXCEPTIONS: tuple[type[Exception], ...] = (
    OSError,
    TimeoutError,
    asyncio.IncompleteReadError,
    asyncio.CancelledError,
)
