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
from .const import CONNECTION_TIMEOUT, NETWORK_EXCEPTIONS, SHUTDOWN_TIMEOUT

_LOGGER = logging.getLogger(__name__)


@dataclass
class _Command:
    """A queued coordinator command."""

    op: Callable[[TriadConnection], Awaitable[Any]]
    future: asyncio.Future


@dataclass
class TriadCoordinatorConfig:
    """Configuration for TriadCoordinator initialization."""

    host: str
    port: int
    input_count: int
    min_send_interval: float = 0.15
    poll_interval: float = 30.0


class TriadCoordinator:
    """Single-queue, single-worker command coordinator."""

    def __init__(
        self,
        host: str | TriadCoordinatorConfig,
        port: int | None = None,
        input_count: int | None = None,
        *,
        min_send_interval: float = 0.15,
        poll_interval: float = 30.0,
        connection: TriadConnection | None = None,
    ) -> None:
        """Initialize a paced, single-worker queue."""
        # Support both old (individual params) and new (config dataclass) conventions
        if isinstance(host, TriadCoordinatorConfig):
            config = host
            host_val = config.host
            port_val = config.port
            input_count_val = config.input_count
            min_send_interval = config.min_send_interval
            poll_interval = config.poll_interval
        else:
            if port is None or input_count is None:
                msg = (
                    "Must provide port and input_count when using individual parameters"
                )
                raise TypeError(msg)
            host_val = host
            port_val = port
            input_count_val = input_count

        self._host = host_val
        self._port = port_val
        self._input_count = input_count_val
        self._conn = (
            connection
            if connection is not None
            else TriadConnection(host_val, port_val)
        )
        self._queue: asyncio.Queue[_Command] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None
        self._last_send_time: float = 0.0
        self._min_send_interval = max(0.0, min_send_interval)
        self._poll_interval = max(1.0, poll_interval)
        # Weak set of outputs to poll; avoids retaining entities
        self._outputs: weakref.WeakSet[TriadAmsOutput] = weakref.WeakSet()
        self._poll_index: int = 0
        # Track active outputs per zone (zone -> set of output numbers)
        # Zones are 1-based and mapped in groups of 8 outputs (clamped 1..3).
        self._zone_active_outputs: dict[int, set[int]] = {1: set(), 2: set(), 3: set()}
        # Availability tracking (Silver requirement)
        self._available: bool = True
        self._availability_listeners: weakref.WeakSet[Callable[[bool], None]] = (
            weakref.WeakSet()
        )
        # Track input link unsubscribe functions for cleanup
        self._input_link_unsubs: list[Callable[[], None]] = []

    @property
    def input_link_unsubs(self) -> list[Callable[[], None]]:
        """Return the list of input link unsubscribe functions."""
        return self._input_link_unsubs

    @property
    def input_count(self) -> int:
        """Public accessor for the configured input count."""
        return self._input_count

    @property
    def host(self) -> str:
        """Return the host address of the coordinator."""
        return self._host

    @property
    def port(self) -> int:
        """Return the port number of the coordinator."""
        return self._port

    @property
    def outputs(self) -> weakref.WeakSet[TriadAmsOutput]:
        """Return the weak set of registered outputs."""
        return self._outputs

    @property
    def is_available(self) -> bool:
        """Return True if the coordinator is available (connected to device)."""
        return self._available

    def add_availability_listener(
        self, callback: Callable[[bool], None]
    ) -> Callable[[], None]:
        """
        Register callback for availability changes.

        Returns an unsubscribe function.
        """
        self._availability_listeners.add(callback)

        def _unsub() -> None:
            with contextlib.suppress(ValueError):
                self._availability_listeners.discard(callback)

        return _unsub

    def add_input_link_unsub(self, unsub: Callable[[], None]) -> None:
        """Register an input link unsubscribe function for cleanup."""
        self._input_link_unsubs.append(unsub)

    def clear_input_link_unsubs(self) -> None:
        """Clear all input link unsubscribe functions."""
        self._input_link_unsubs.clear()

    def _notify_availability_listeners(self, *, is_available: bool) -> None:
        """Notify all listeners of availability change."""
        for cb in list(self._availability_listeners):
            try:
                cb(is_available=is_available)
            except Exception:
                _LOGGER.exception("Error in availability listener")

    async def start(self) -> None:
        """Start the single worker."""
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run_worker(), name="triad_worker")
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._run_poll(), name="triad_poll")

    async def stop(self) -> None:
        """Stop the worker and cancel pending commands."""
        # Close connection first to make any in-flight network calls fail immediately
        # This helps tasks stuck in network I/O respond to cancellation faster
        self._conn.close_nowait()
        if self._worker is not None:
            self._worker.cancel()
            # Drain queue and cancel futures
            while not self._queue.empty():
                with contextlib.suppress(asyncio.QueueEmpty):
                    cmd = self._queue.get_nowait()
                    if not cmd.future.done():
                        cmd.future.set_exception(asyncio.CancelledError())
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self._worker, timeout=SHUTDOWN_TIMEOUT)
            self._worker = None
        if self._poll_task is not None:
            self._poll_task.cancel()
            # Wait for polling task to finish, but with a timeout to avoid hanging
            # if the task is stuck in a network call
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self._poll_task, timeout=SHUTDOWN_TIMEOUT)
            self._poll_task = None

    async def disconnect(self) -> None:
        """Disconnect from the device."""
        await self._conn.disconnect()

    # Registration for rolling poll
    def register_output(self, output: TriadAmsOutput) -> None:
        """Register an output for lightweight rolling polling."""
        self._outputs.add(output)

    async def _ensure_connection(self) -> None:
        """Ensure connection is established and update availability state."""
        was_available = self._available
        await asyncio.wait_for(self._conn.connect(), timeout=CONNECTION_TIMEOUT)
        # If we were unavailable and now connected, mark as available
        if not was_available:
            self._available = True
            _LOGGER.info("Triad AMS device available")
            self._notify_availability_listeners(is_available=True)

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
            except NETWORK_EXCEPTIONS as exc:
                # Log, drop transport, attempt quick reconnect, and propagate error.
                _LOGGER.warning(
                    "Command failed; dropping and reopening connection: %s", exc
                )
                self._conn.close_nowait()
                # Mark as unavailable and notify listeners
                if self._available:
                    self._available = False
                    _LOGGER.warning("Triad AMS device unavailable: %s", exc)
                    self._notify_availability_listeners(is_available=False)
                # Best-effort immediate reconnect so subsequent commands are ready.
                try:
                    await asyncio.wait_for(
                        self._conn.connect(), timeout=CONNECTION_TIMEOUT
                    )
                    _LOGGER.info("Reconnected to Triad AMS after error")
                    # Mark as available again after successful reconnect
                    if not self._available:
                        self._available = True
                        _LOGGER.info("Triad AMS device available")
                        self._notify_availability_listeners(is_available=True)
                except (TimeoutError, OSError) as reconnect_exc:
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
        try:
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
                    # After refreshing the output, reconcile the coordinator's
                    # zone active sets with the polled device state. This ensures
                    # that external changes (or other controllers) are reflected
                    # and that trigger zone commands are sent when zones move
                    # between empty and non-empty.
                    try:
                        zone = self._zone_for_output(target.number)
                        active = self._zone_active_outputs.setdefault(zone, set())
                        if target.has_source:
                            was_empty = len(active) == 0
                            if target.number not in active:
                                active.add(target.number)
                                if was_empty and len(active) == 1:
                                    await self.set_trigger_zone(zone=zone, on=True)
                        elif target.number in active:
                            active.discard(target.number)
                            if len(active) == 0:
                                await self.set_trigger_zone(zone=zone, on=False)
                    except Exception:  # noqa: BLE001
                        # Catch all exceptions to prevent one error from breaking
                        # polling. This is a debug-level handler where we want to
                        # continue polling
                        _LOGGER.debug("Failed to reconcile zone sets after refresh")
                except asyncio.CancelledError:
                    # Task was cancelled during refresh, propagate immediately
                    raise
                except Exception:  # noqa: BLE001
                    # Catch all exceptions to prevent one error from breaking polling
                    # This is a debug-level handler where we want to continue polling
                    _LOGGER.debug("Rolling poll refresh failed for output")
                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            # Task was cancelled, exit cleanly
            _LOGGER.debug("Polling task cancelled")
            raise

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
        """
        Route output to input and update zone active set.

        This enqueues a single operation that performs the device routing and
        then updates the coordinator's zone set. If the output makes the zone
        transition from empty -> non-empty, the trigger zone ON command is
        issued on the same connection to preserve sequencing.
        """

        async def _op(c: TriadConnection) -> None:  # type: ignore[name-defined]
            await c.set_output_to_input(output_channel, input_channel)
            # Compute zone and add this output to the active set
            zone = self._zone_for_output(output_channel)
            active = self._zone_active_outputs.setdefault(zone, set())
            was_empty = len(active) == 0
            active.add(output_channel)
            if was_empty and len(active) == 1:
                await c.set_trigger_zone(zone=zone, on=True)

        await self._execute(_op)

    async def get_output_source(self, output_channel: int) -> int | None:
        """Get routed input (1-based) or None."""
        return await self._execute(lambda c: c.get_output_source(output_channel))

    async def disconnect_output(self, output_channel: int) -> None:
        """
        Disconnect output and update zone active set.

        After the device disconnect command succeeds, remove the output from
        the zone active set and issue a trigger zone OFF command only when the
        set becomes empty.
        """

        async def _op(c: TriadConnection) -> None:  # type: ignore[name-defined]
            await c.disconnect_output(output_channel, self._input_count)
            zone = self._zone_for_output(output_channel)
            active = self._zone_active_outputs.get(zone)
            if active and output_channel in active:
                active.discard(output_channel)
                if len(active) == 0:
                    await c.set_trigger_zone(zone=zone, on=False)

        await self._execute(_op)

    async def set_trigger_zone(self, zone: int, *, on: bool) -> None:
        """
        Send a trigger zone on/off command (passes through to device).

        Zone active tracking is handled by `set_output_to_input` and
        `disconnect_output`; this method provides a direct passthrough for
        manual or legacy calls.
        """
        await self._execute(lambda c: c.set_trigger_zone(zone=zone, on=on))

    def _zone_for_output(self, output: int) -> int:
        """
        Return the 1-based zone for an output, clamped to 1..3.

        Zones are grouped in blocks of 8 outputs as used elsewhere in the
        integration (see `TriadAmsOutput` initialization).
        """
        zone_raw = (output - 1) // 8 + 1
        return max(1, min(zone_raw, 3))
