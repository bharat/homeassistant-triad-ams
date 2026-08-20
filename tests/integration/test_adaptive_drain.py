"""
Integration tests for adaptive drain/flush skipping (single-NUL firmware).

Firmware that terminates responses with a single NUL should stop paying the
timed padding-drain and stale-flush windows once the connection has seen a
few consecutive clean exchanges. Padded-frame firmware (issue #164) must
keep the full windows for the life of the connection, and any reconnect must
re-learn framing from scratch.
"""

from __future__ import annotations

import contextlib

import pytest

from custom_components.triad_ams.connection import TriadConnection
from custom_components.triad_ams.const import CLEAN_EXCHANGES_TO_SKIP_DRAIN
from custom_components.triad_ams.exceptions import TransientDeviceError
from tests.integration.simulator import triad_ams_simulator

PADDED_FRAME_SIZE = 150
# Small enough to keep the mixed-framing test fast: "Volume : 0xNN\0" is 14
# bytes, so this leaves a handful of padding NULs per frame.
SMALL_FRAME_SIZE = 20


async def _run_mixed_queries_until_desync(connection: TriadConnection) -> None:
    """
    Alternate query types until a stale frame mismatches and raises OSError.

    Empty reads of bare padding NULs raise TransientDeviceError, which is
    transient by design and suppressed here; the desync surfaces once a query
    reads a stale response of the other type.
    """
    for _ in range(30):
        with contextlib.suppress(TransientDeviceError):
            await connection.get_output_volume(1)
            await connection.get_output_mute(1)
    pytest.fail("desync never surfaced")


@pytest.mark.integration
class TestAdaptiveDrain:
    """End-to-end framing detection against the TCP simulator."""

    @pytest.mark.asyncio
    async def test_single_nul_firmware_learns_to_skip(self) -> None:
        """Clean exchanges on single-NUL firmware disable the timed windows."""
        async with triad_ams_simulator() as (_simulator, host, port):
            connection = TriadConnection(host, port)
            await connection.connect()
            try:
                for _ in range(CLEAN_EXCHANGES_TO_SKIP_DRAIN):
                    assert connection._skip_timed_windows() is False
                    await connection.get_output_volume(1)

                assert connection._padding_seen is False
                assert connection._skip_timed_windows() is True

                # Steady state keeps working with the windows skipped.
                await connection.set_output_volume(1, 0.75)
                volume = await connection.get_output_volume(1)
                assert abs(volume - 0.75) < 0.1
                assert connection._skip_timed_windows() is True
            finally:
                await connection.disconnect()

    @pytest.mark.asyncio
    async def test_padded_firmware_never_skips(self) -> None:
        """A connection that sees padding keeps the full windows forever."""
        async with triad_ams_simulator(frame_size=PADDED_FRAME_SIZE) as (
            _simulator,
            host,
            port,
        ):
            connection = TriadConnection(host, port)
            await connection.connect()
            try:
                for _ in range(CLEAN_EXCHANGES_TO_SKIP_DRAIN + 2):
                    await connection.get_output_volume(1)

                assert connection._padding_seen is True
                assert connection._skip_timed_windows() is False

                await connection.set_output_volume(1, 0.5)
                volume = await connection.get_output_volume(1)
                assert abs(volume - 0.5) < 0.1
            finally:
                await connection.disconnect()

    @pytest.mark.asyncio
    async def test_learned_state_resets_on_reconnect(self) -> None:
        """Disconnecting and reconnecting re-learns framing from scratch."""
        async with triad_ams_simulator() as (_simulator, host, port):
            connection = TriadConnection(host, port)
            await connection.connect()
            try:
                for _ in range(CLEAN_EXCHANGES_TO_SKIP_DRAIN):
                    await connection.get_output_volume(1)
                assert connection._skip_timed_windows() is True

                await connection.disconnect()
                assert connection._skip_timed_windows() is False
                assert connection._clean_exchanges == 0

                await connection.connect()
                assert connection._skip_timed_windows() is False
                for _ in range(CLEAN_EXCHANGES_TO_SKIP_DRAIN):
                    await connection.get_output_volume(1)
                assert connection._skip_timed_windows() is True
            finally:
                await connection.disconnect()

    @pytest.mark.asyncio
    async def test_desync_forces_reconnect_and_relearning_recovers(self) -> None:
        """
        Mixed framing: a desync closes the connection and re-learning recovers.

        The connection first learns single-NUL framing and skips the windows.
        The simulator then switches to padded frames, so padding accumulates
        unseen until a stale mismatched frame trips the unexpected-response
        path, which closes the connection and resets the learned state. The
        next commands reconnect, observe the padding, and keep full drain
        behavior, so round-trips are correct again.
        """
        async with triad_ams_simulator() as (simulator, host, port):
            connection = TriadConnection(host, port)
            await connection.connect()
            try:
                for _ in range(CLEAN_EXCHANGES_TO_SKIP_DRAIN):
                    await connection.get_output_volume(1)
                assert connection._skip_timed_windows() is True

                simulator.frame_size = SMALL_FRAME_SIZE
                with pytest.raises(OSError, match="Unexpected response"):
                    await _run_mixed_queries_until_desync(connection)

                # The unexpected-response path closed the connection and
                # reset the learned framing.
                assert connection._writer is None
                assert connection._padding_seen is False
                assert connection._clean_exchanges == 0

                # Reconnect happens implicitly; padding is now observed and
                # the full windows stay active, so state round-trips again.
                await connection.set_output_volume(1, 0.25)
                for _ in range(CLEAN_EXCHANGES_TO_SKIP_DRAIN + 1):
                    volume = await connection.get_output_volume(1)
                    assert abs(volume - 0.25) < 0.1
                assert connection._padding_seen is True
                assert connection._skip_timed_windows() is False
            finally:
                await connection.disconnect()
