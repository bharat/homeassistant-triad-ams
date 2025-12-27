"""
Coordinator for Triad AMS.

Fresh, minimal implementation that:
- Sequences commands through a single worker
- Enforces a minimum delay between commands
- Avoids race conditions via a single queue
- Drops transport on device-side errors (raised by connection)
- Propagates errors to callers without internal retries
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import weakref
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from .models import TriadAmsOutput

from .connection import TriadConnection

_LOGGER = logging.getLogger(__name__)


@dataclass
class _Command:
    """A queued coordinator command."""

    op: Callable[[TriadConnection], Awaitable[Any]]
    future: asyncio.Future


class TriadCoordinator:
    """Single-queue, single-worker command coordinator."""

    def __init__(
        self,
        host: str,
        port: int,
        input_count: int,
        *,
        min_send_interval: float = 0.15,
        poll_interval: float = 30.0,
    ) -> None:
        """Initialize a paced, single-worker queue."""
        self._host = host
        self._port = port
        self._input_count = input_count
        self._conn = TriadConnection(host, port)
        self._queue: asyncio.Queue[_Command] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None
        self._last_send_time: float = 0.0
        self._min_send_interval = max(0.0, min_send_interval)
        self._poll_interval = max(1.0, poll_interval)
        # Weak set of outputs to poll; avoids retaining entities
        self._outputs: weakref.WeakSet[TriadAmsOutput] = weakref.WeakSet()
        self._poll_index: int = 0

    @property
    def input_count(self) -> int:
        """Public accessor for the configured input count."""
        return self._input_count

    async def start(self) -> None:
        """Start the single worker."""
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run_worker(), name="triad_worker")
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._run_poll(), name="triad_poll")

    async def stop(self) -> None:
        """Stop the worker and cancel pending commands."""
        if self._worker is not None:
            self._worker.cancel()
            # Drain queue and cancel futures
            while not self._queue.empty():
                with contextlib.suppress(asyncio.QueueEmpty):
                    cmd = self._queue.get_nowait()
                    if not cmd.future.done():
                        cmd.future.set_exception(asyncio.CancelledError())
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None
        if self._poll_task is not None:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None

    async def disconnect(self) -> None:
        """Disconnect from the device."""
        await self._conn.disconnect()

    # Registration for rolling poll
    def register_output(self, output: TriadAmsOutput) -> None:
        """Register an output for lightweight rolling polling."""
        self._outputs.add(output)

    async def _ensure_connection(self) -> None:
        await asyncio.wait_for(self._conn.connect(), timeout=5)

    async def _run_worker(self) -> None:
        """Worker: dequeue, pace, ensure connection, execute, propagate result/error."""
        while True:
            cmd = await self._queue.get()
            try:
                # Enforce pacing
                now = asyncio.get_running_loop().time()
                delay = self._last_send_time + self._min_send_interval - now
                if delay > 0:
                    await asyncio.sleep(delay)

                # Execute
                await self._ensure_connection()
                result = await cmd.op(self._conn)
                self._last_send_time = asyncio.get_running_loop().time()
                if not cmd.future.done():
                    cmd.future.set_result(result)
            except (
                OSError,
                TimeoutError,
                asyncio.IncompleteReadError,
                asyncio.CancelledError,
            ) as exc:
                # Log, drop transport, attempt quick reconnect, and propagate error.
                _LOGGER.warning(
                    "Command failed; dropping and reopening connection: %s", exc
                )
                self._conn.close_nowait()
                # Best-effort immediate reconnect so subsequent commands are ready.
                try:
                    await asyncio.wait_for(self._conn.connect(), timeout=5)
                    _LOGGER.info("Reconnected to Triad AMS after error")
                except Exception as reconnect_exc:  # noqa: BLE001 - log and proceed
                    _LOGGER.warning(
                        "Reconnect attempt failed (will retry on next command): %s",
                        reconnect_exc,
                    )
                if not cmd.future.done():
                    cmd.future.set_exception(exc)
            finally:
                self._queue.task_done()

    async def _run_poll(self) -> None:
        """Round-robin poll: refresh one output every poll interval."""
        while True:
            outputs = [o for o in list(self._outputs) if o is not None]
            if not outputs:
                await asyncio.sleep(self._poll_interval)
                continue
            # Choose next output in a stable order
            self._poll_index = self._poll_index % len(outputs)
            target = outputs[self._poll_index]
            self._poll_index += 1
            try:
                await target.refresh_and_notify()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Rolling poll refresh failed for output")
            await asyncio.sleep(self._poll_interval)

    async def _execute(self, op: Callable[[TriadConnection], Awaitable[Any]]) -> Any:
        """Enqueue a command and await its result or error."""
        future = asyncio.get_running_loop().create_future()
        await self._queue.put(_Command(op=op, future=future))
        return await future

    # Public API
    async def set_output_volume(self, output_channel: int, percentage: float) -> None:
        """Set volume."""
        await self._execute(lambda c: c.set_output_volume(output_channel, percentage))

    async def get_output_volume(self, output_channel: int) -> float:
        """Get volume (0..1)."""
        return await self._execute(lambda c: c.get_output_volume(output_channel))

    async def get_output_volume_from_device(self, output_channel: int) -> float:
        """Explicit device read (testing)."""
        return await self.get_output_volume(output_channel)

    async def set_output_mute(self, output_channel: int, *, mute: bool) -> None:
        """Set mute state."""
        await self._execute(lambda c: c.set_output_mute(output_channel, mute=mute))

    async def get_output_mute(self, output_channel: int) -> bool:
        """Get mute state."""
        return await self._execute(lambda c: c.get_output_mute(output_channel))

    async def volume_step_up(self, output_channel: int, *, large: bool = False) -> None:
        """Step volume up."""
        await self._execute(lambda c: c.volume_step_up(output_channel, large=large))

    async def volume_step_down(
        self, output_channel: int, *, large: bool = False
    ) -> None:
        """Step volume down."""
        await self._execute(lambda c: c.volume_step_down(output_channel, large=large))

    async def set_output_to_input(
        self, output_channel: int, input_channel: int
    ) -> None:
        """Route output to input."""
        await self._execute(
            lambda c: c.set_output_to_input(output_channel, input_channel)
        )

    async def get_output_source(self, output_channel: int) -> int | None:
        """Get routed input (1-based) or None."""
        return await self._execute(lambda c: c.get_output_source(output_channel))

    async def disconnect_output(self, output_channel: int) -> None:
        """Disconnect output."""
        await self._execute(
            lambda c: c.disconnect_output(output_channel, self._input_count)
        )

    async def set_trigger_zone(self, zone: int = 1, *, on: bool) -> None:
        """Set a trigger zone on/off (zone is 1-based)."""
        await self._execute(lambda c: c.set_trigger_zone(zone=zone, on=on))
