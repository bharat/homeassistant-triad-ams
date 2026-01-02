"""Shared pytest fixtures for integration tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from custom_components.triad_ams.coordinator import (
    TriadCoordinator,
    TriadCoordinatorConfig,
)
from custom_components.triad_ams.models import TriadAmsOutput
from tests.integration.simulator import triad_ams_simulator

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
async def simulator_fixture() -> AsyncGenerator[tuple]:
    """Provide simulator, host, and port for integration tests."""
    async with triad_ams_simulator() as (simulator, host, port):
        yield (simulator, host, port)


@pytest.fixture
async def coordinator_fixture(
    simulator_fixture: tuple,
) -> AsyncGenerator[TriadCoordinator]:
    """Provide a started coordinator with automatic cleanup."""
    _simulator, host, port = simulator_fixture
    config = TriadCoordinatorConfig(
        host=host, port=port, input_count=8, min_send_interval=0.01, poll_interval=0.1
    )
    coordinator = TriadCoordinator(config)
    await coordinator.start()
    try:
        yield coordinator
    finally:
        await coordinator.stop()
        await coordinator.disconnect()


@pytest.fixture
def input_names() -> dict[int, str]:
    """Provide default input names for testing."""
    return {i: f"Input {i}" for i in range(1, 9)}


@pytest.fixture
async def output_fixture(
    coordinator_fixture: TriadCoordinator,
    input_names: dict[int, str],
) -> TriadAmsOutput:
    """Provide a default output for testing."""
    return TriadAmsOutput(1, "Output 1", coordinator_fixture, None, input_names)
