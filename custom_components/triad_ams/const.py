"""Constants for the Triad AMS integration."""

DOMAIN = "triad_ams"

VOLUME_STEPS = 0x64  # Device expects 0..0x64 (0..100) for volume-related values

# Connection and timeout constants
CONNECTION_TIMEOUT = 5.0  # Timeout for connection operations (seconds)
SHUTDOWN_TIMEOUT = 1.0  # Timeout for graceful shutdown of workers (seconds)
DEVICE_COMMAND_DELAY = 0.1  # Delay between command send and response read (seconds)
POST_CONNECT_DELAY = 0.2  # Delay after establishing connection (seconds)
