"""
Integration tests against firmware that NUL-pads responses to fixed frames.

Some Triad AMS firmware revisions return fixed-length 150-byte response
frames where the response text is followed by NUL padding (issue #164).
These tests run the full coordinator/connection stack against the simulator
in padded-frame mode to prove the read path drains the padding and stays in
sync across many consecutive commands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from custom_components.triad_ams.coordinator import (
    TriadCoordinator,
    TriadCoordinatorConfig,
)
from custom_components.triad_ams.models import TriadAmsOutput
from tests.integration.simulator import TriadAmsSimulator, triad_ams_simulator

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

PADDED_FRAME_SIZE = 150


@pytest.fixture
async def padded_simulator_fixture() -> AsyncGenerator[
    tuple[TriadAmsSimulator, str, int]
]:
    """Provide a simulator that pads every response to a fixed 150-byte frame."""
    async with triad_ams_simulator(frame_size=PADDED_FRAME_SIZE) as (
        simulator,
        host,
        port,
    ):
        yield (simulator, host, port)


@pytest.fixture
async def padded_coordinator_fixture(
    padded_simulator_fixture: tuple[TriadAmsSimulator, str, int],
) -> AsyncGenerator[TriadCoordinator]:
    """Provide a started coordinator connected to the padded-frame simulator."""
    _simulator, host, port = padded_simulator_fixture
    config = TriadCoordinatorConfig(
        host=host, port=port, input_count=8, min_send_interval=0.01, poll_interval=1.0
    )
    coordinator = TriadCoordinator(config)
    await coordinator.start()
    try:
        yield coordinator
    finally:
        await coordinator.stop()
        await coordinator.disconnect()


@pytest.fixture
async def padded_output_fixture(
    padded_coordinator_fixture: TriadCoordinator,
) -> TriadAmsOutput:
    """Provide an output backed by the padded-frame simulator."""
    input_names = {i: f"Input {i}" for i in range(1, 9)}
    return TriadAmsOutput(1, "Output 1", padded_coordinator_fixture, None, input_names)


@pytest.mark.integration
class TestPaddedFrameFirmware:
    """End-to-end tests for fixed-length NUL-padded response frames."""

    @pytest.mark.asyncio
    async def test_volume_round_trip(
        self,
        padded_simulator_fixture: tuple[TriadAmsSimulator, str, int],
        padded_coordinator_fixture: TriadCoordinator,
    ) -> None:
        """Volume set/get round-trips despite trailing NUL padding."""
        simulator, _host, _port = padded_simulator_fixture
        coordinator = padded_coordinator_fixture

        await coordinator.set_output_volume(1, 0.75)
        assert abs(simulator.get_volume(1) - 0.75) < 0.1

        volume = await coordinator.get_output_volume(1)
        assert abs(volume - 0.75) < 0.1

    @pytest.mark.asyncio
    async def test_mute_round_trip(
        self,
        padded_simulator_fixture: tuple[TriadAmsSimulator, str, int],
        padded_output_fixture: TriadAmsOutput,
    ) -> None:
        """Mute set/get round-trips despite trailing NUL padding."""
        simulator, _host, _port = padded_simulator_fixture
        output = padded_output_fixture

        await output.set_muted(muted=True)
        assert simulator.get_mute(1) is True
        assert output.muted is True

        await output.set_muted(muted=False)
        assert simulator.get_mute(1) is False
        assert output.muted is False

    @pytest.mark.asyncio
    async def test_source_select_round_trip(
        self,
        padded_simulator_fixture: tuple[TriadAmsSimulator, str, int],
        padded_output_fixture: TriadAmsOutput,
    ) -> None:
        """Source routing round-trips despite trailing NUL padding."""
        simulator, _host, _port = padded_simulator_fixture
        output = padded_output_fixture

        await output.set_source(2)
        assert simulator.get_source(1) == 2
        assert output.source == 2

        await output.turn_off()
        assert simulator.get_source(1) is None
        assert output.source is None

    @pytest.mark.asyncio
    async def test_multi_command_sequence_no_desync(
        self,
        padded_simulator_fixture: tuple[TriadAmsSimulator, str, int],
        padded_coordinator_fixture: TriadCoordinator,
    ) -> None:
        """
        A long command sequence stays in sync frame-by-frame.

        This is the regression from issue #164: with padded frames the second
        and later commands used to read leftover padding as their response,
        raising "Unexpected response from device" and dropping the connection.
        """
        _simulator, _host, _port = padded_simulator_fixture
        coordinator = padded_coordinator_fixture

        for round_num, (volume, source) in enumerate(
            [(0.25, 1), (0.5, 3), (0.9, 5)], start=1
        ):
            await coordinator.set_output_volume(1, volume)
            got_volume = await coordinator.get_output_volume(1)
            assert abs(got_volume - volume) < 0.1, f"desync in round {round_num}"

            await coordinator.set_output_to_input(1, source)
            got_source = await coordinator.get_output_source(1)
            assert got_source == source, f"desync in round {round_num}"

            await coordinator.set_output_mute(1, mute=True)
            assert await coordinator.get_output_mute(1) is True
            await coordinator.set_output_mute(1, mute=False)
            assert await coordinator.get_output_mute(1) is False
