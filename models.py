"""Data models for Triad AMS integration."""

from dataclasses import dataclass


@dataclass
class TriadAmsOutput:
    """Represents an output channel on the Triad AMS."""

    number: int
    name: str
    volume: float | None = None
    is_on: bool = False
    source: int | None = None


# Add additional models as needed for inputs or device info
