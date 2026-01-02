"""Shared pytest fixtures for Triad AMS tests."""

from __future__ import annotations

import asyncio
import gc
import logging
import sys
import time
import traceback
import warnings
from io import StringIO
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.triad_ams.coordinator import (
    TriadCoordinator,
    TriadCoordinatorConfig,
)
from custom_components.triad_ams.models import TriadAmsOutput

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

# Import pytest_socket at module level to avoid PLC0415
try:
    import pytest_socket
except ImportError:
    pytest_socket = None  # Optional dependency

# Track coroutines created by our mocks for debugging
_CREATED_COROUTINES: dict[int, dict[str, Any]] = {}
_COROUTINE_COUNTER = 0
_CURRENT_TEST: str | None = None

_LOGGER = logging.getLogger(__name__)


def create_async_mock_method(
    return_value: Any = None, side_effect: Any = None
) -> MagicMock:
    """
    Create a MagicMock with an async function.

    This avoids AsyncMock's issue of creating coroutines on attribute access.
    Coroutines are only created when the method is actually called.
    """
    # Assignment happens in tracked_async_method, but we need global here too
    global _COROUTINE_COUNTER  # noqa: PLW0602

    # Store values in a mutable dict that can be updated
    state: dict[str, Any] = {"return_value": return_value, "side_effect": side_effect}

    async def async_method(*args: Any, **kwargs: Any) -> Any:
        # Check for side_effect first
        if state["side_effect"] is not None:
            se = state["side_effect"]
            if callable(se) and not isinstance(se, type):
                return se(*args, **kwargs)
            if not callable(se):
                raise se
        # Return the return_value
        return state["return_value"]

    def tracked_async_method(*args: Any, **kwargs: Any) -> Any:
        """Track coroutine creation."""
        # Use global to track across all mocks
        global _COROUTINE_COUNTER, _CURRENT_TEST  # noqa: PLW0602, PLW0603
        coro_id = _COROUTINE_COUNTER
        _COROUTINE_COUNTER += 1

        # Create the coroutine
        coro = async_method(*args, **kwargs)

        # Track it with stack trace
        stack = traceback.extract_stack()
        try:
            loop = asyncio.get_event_loop()
            created_at = loop.time() if loop.is_running() else None
        except RuntimeError:
            created_at = None

        # Try to get the current test name from pytest
        test_name = _CURRENT_TEST
        if test_name is None:
            # Try to extract from stack
            for frame in reversed(stack):
                if "test_" in frame.filename and "test_" in frame.name:
                    test_name = f"{frame.filename}::{frame.name}"
                    break

        # Get the mock method name by inspecting the call stack
        # Look for the frame that called this method - it should show
        # the attribute access
        mock_method_name = "unknown"
        for i, frame in enumerate(reversed(stack)):
            # Skip our own frames
            if (
                "create_async_mock_method" in frame.filename
                or "tracked_async_method" in str(frame.name)
            ):
                continue
            # Look at the previous frame to see what was called
            if i > 0 and frame.line:
                line_lower = frame.line.lower()
                # Check for common async method patterns
                for method in [
                    "connect",
                    "disconnect",
                    "get_output_volume",
                    "set_output_volume",
                    "get_output_mute",
                    "set_output_mute",
                    "volume_step_up",
                    "volume_step_down",
                    "set_output_to_input",
                    "get_output_source",
                    "disconnect_output",
                    "set_trigger_zone",
                    "start",
                    "stop",
                    "refresh_and_notify",
                    "async_forward_entry_setups",
                    "async_unload_platforms",
                    "async_reload",
                    "async_set_unique_id",
                    "async_step_channels",
                ]:
                    if method in line_lower:
                        mock_method_name = method
                        break
                if mock_method_name != "unknown":
                    break

        _CREATED_COROUTINES[coro_id] = {
            "coroutine": coro,
            "stack": stack,
            "args": args,
            "kwargs": kwargs,
            "created_at": created_at,
            "test_name": test_name,
            "mock_method_name": mock_method_name,
        }

        return coro

    mock = MagicMock(side_effect=tracked_async_method)
    # Store state on the mock so we can update it
    mock._async_mock_state = state

    # Override return_value and side_effect properties
    def _get_return_value(mock_self: MagicMock) -> Any:
        return mock_self._async_mock_state["return_value"]

    def _set_return_value(mock_self: MagicMock, value: Any) -> None:
        mock_self._async_mock_state["return_value"] = value

    def _get_side_effect(_mock_self: MagicMock) -> Any:
        # Always return the tracked wrapper to avoid creating coroutines
        return tracked_async_method

    def _set_side_effect(mock_self: MagicMock, value: Any) -> None:
        mock_self._async_mock_state["side_effect"] = value
        # Keep the async wrapper
        MagicMock.side_effect.fset(mock_self, tracked_async_method)

    # Use property descriptor
    type(mock).return_value = property(_get_return_value, _set_return_value)
    type(mock).side_effect = property(_get_side_effect, _set_side_effect)

    return mock


# Save the original warning handler BEFORE we replace it
_original_showwarning = warnings.showwarning


def _warn_unawaited_coroutine(  # noqa: PLR0913
    message: str,
    category: type[Warning],
    filename: str,
    lineno: int,
    file: Any = None,
    line: Any = None,
) -> None:
    """Show coroutine creation details when unawaited coroutine warning occurs."""
    if "coroutine" in str(message).lower() and "never awaited" in str(message).lower():
        # Use stderr for immediate output (logging might not be configured)
        sys.stderr.write("\n" + "=" * 80 + "\n")
        sys.stderr.write("UNWAITED COROUTINE DETECTED!\n")
        sys.stderr.write("=" * 80 + "\n")
        sys.stderr.write(f"Warning: {message}\n")
        sys.stderr.write(f"Location: {filename}:{lineno}\n")
        sys.stderr.write("\nTracked coroutines created by create_async_mock_method:\n")
        sys.stderr.write("-" * 80 + "\n")
        for coro_id, info in _CREATED_COROUTINES.items():
            coro = info["coroutine"]
            try:
                if coro.cr_frame is None:  # Coroutine was closed/awaited
                    continue
            except AttributeError:
                # Coroutine might be in a different state
                continue
            sys.stderr.write(f"\nCoroutine ID: {coro_id}\n")
            sys.stderr.write(f"Args: {info['args']}\n")
            sys.stderr.write(f"Kwargs: {info['kwargs']}\n")
            sys.stderr.write("Creation stack trace:\n")
            # Show last 10 frames of creation stack
            for frame in info["stack"][-10:]:
                sys.stderr.write(f"  {frame.filename}:{frame.lineno} in {frame.name}\n")
                if frame.line:
                    sys.stderr.write(f"    {frame.line}\n")
        sys.stderr.write("=" * 80 + "\n\n")
    # Call the ORIGINAL warning handler to ensure warning is still shown
    _original_showwarning(message, category, filename, lineno, file, line)


# Install custom warning handler and also hook into sys.stderr for RuntimeWarning
_original_stderr = sys.stderr


class InstrumentedStderr:
    """Stderr wrapper that detects unawaited coroutine warnings."""

    def __init__(self, original: Any) -> None:
        """Initialize the stderr wrapper."""
        self._original = original
        self._buffer = StringIO()

    def write(self, text: str) -> None:
        """Write to stderr and check for coroutine warnings."""
        # Always write to original first to ensure warnings are shown
        self._original.write(text)

        # Buffer text to check for warnings that might be written in chunks
        global _STDERR_BUFFER  # noqa: PLW0603
        _STDERR_BUFFER.append(text)

        # Keep only last 20 chunks to avoid memory issues
        # (warnings might span multiple chunks)
        if len(_STDERR_BUFFER) > 20:
            _STDERR_BUFFER = _STDERR_BUFFER[-20:]

        # Check the combined buffer for the warning
        combined_text = "".join(_STDERR_BUFFER).lower()
        # Very lenient matching - just check for the key phrases
        # Also check current text in case it's written in one chunk
        current_text_lower = text.lower()
        full_text = (combined_text + " " + current_text_lower).lower()
        is_coroutine_warning = "coroutine" in full_text and "never awaited" in full_text

        # Then show diagnostics if we detected the warning
        if is_coroutine_warning:
            # Clear buffer to avoid showing diagnostics multiple times
            _STDERR_BUFFER.clear()
            # Small delay to ensure all chunks are written
            time.sleep(0.1)  # Longer delay to ensure everything is written
            self._show_coroutine_details()

    def _show_coroutine_details(self) -> None:
        """Show details about tracked coroutines."""
        self._original.write("\n" + "=" * 80 + "\n")
        self._original.write("UNWAITED COROUTINE DETECTED!\n")
        self._original.write("=" * 80 + "\n")
        self._original.write(
            "\nTracked coroutines created by create_async_mock_method:\n"
        )
        self._original.write("-" * 80 + "\n")
        found_unawaited = False
        for coro_id, info in _CREATED_COROUTINES.items():
            coro = info["coroutine"]
            try:
                if coro.cr_frame is None:  # Coroutine was closed/awaited
                    continue
            except AttributeError:
                # Coroutine might be in a different state
                continue
            found_unawaited = True
            self._original.write(f"\nCoroutine ID: {coro_id}\n")
            self._original.write(
                f"Mock Method: {info.get('mock_method_name', 'unknown')}\n"
            )
            self._original.write(f"Test: {info.get('test_name', 'unknown')}\n")
            self._original.write(f"Args: {info['args']}\n")
            self._original.write(f"Kwargs: {info['kwargs']}\n")
            self._original.write("Creation stack trace:\n")
            # Show last 10 frames of creation stack
            for frame in info["stack"][-10:]:
                self._original.write(
                    f"  {frame.filename}:{frame.lineno} in {frame.name}\n"
                )
                if frame.line:
                    self._original.write(f"    {frame.line}\n")
        if not found_unawaited:
            self._original.write("\nNo unawaited coroutines found in tracked list.\n")
            self._original.write(
                "This might be a coroutine created outside our tracking.\n"
            )
        self._original.write("=" * 80 + "\n\n")

    def __getattr__(self, name: str) -> Any:
        """Delegate all other attributes to original stderr."""
        return getattr(self._original, name)


# Install custom warning handler
warnings.showwarning = _warn_unawaited_coroutine
# Also wrap stderr to catch warnings that bypass warnings.showwarning
sys.stderr = InstrumentedStderr(sys.stderr)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    """Track which test is currently running."""
    global _CURRENT_TEST  # noqa: PLW0603
    _CURRENT_TEST = item.nodeid


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item: pytest.Item) -> None:
    """Check for unawaited coroutines after each test."""
    # Force garbage collection to trigger warnings
    gc.collect()

    # Check if any tracked coroutines are still unawaited
    unawaited = []
    for coro_id, info in _CREATED_COROUTINES.items():
        coro = info["coroutine"]
        try:
            if coro.cr_frame is not None:  # Coroutine is still active
                unawaited.append((coro_id, info))
        except AttributeError:
            # Coroutine might be in a different state, skip
            continue

    if unawaited:
        # Only fail if the unawaited coroutine was created in THIS test
        # This prevents failing tests that didn't create the coroutine
        current_test_unawaited = [
            (coro_id, info)
            for coro_id, info in unawaited
            if info.get("test_name") == item.nodeid
        ]

        if current_test_unawaited:
            # Build error message
            error_msg = f"\n{'=' * 80}\n"
            error_msg += f"UNWAITED COROUTINES DETECTED after test: {item.nodeid}\n"
            error_msg += f"{'=' * 80}\n"
            for coro_id, info in current_test_unawaited:
                error_msg += f"\nCoroutine ID: {coro_id}\n"
                error_msg += f"Mock Method: {info.get('mock_method_name', 'unknown')}\n"
                error_msg += f"Test: {info.get('test_name', 'unknown')}\n"
                error_msg += f"Args: {info['args']}\n"
                error_msg += f"Kwargs: {info['kwargs']}\n"
                error_msg += "Creation stack trace:\n"
                for frame in info["stack"][-10:]:
                    error_msg += f"  {frame.filename}:{frame.lineno} in {frame.name}\n"
                    if frame.line:
                        error_msg += f"    {frame.line}\n"
            error_msg += f"{'=' * 80}\n"

            # Write to stderr for visibility
            sys.stderr.write(error_msg)

            # Raise an exception to fail the test
            raise RuntimeError(error_msg)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(
    session: pytest.Session,  # noqa: ARG001
    exitstatus: int,  # noqa: ARG001
) -> None:
    """Check for unawaited coroutines at the very end of the test session."""
    # Final garbage collection
    gc.collect()

    # Give it a moment for warnings to be written
    time.sleep(0.1)

    # Check if any tracked coroutines are still unawaited
    unawaited = []
    for coro_id, info in _CREATED_COROUTINES.items():
        coro = info["coroutine"]
        try:
            if coro.cr_frame is not None:  # Coroutine is still active
                unawaited.append((coro_id, info))
        except AttributeError:
            # Coroutine might be in a different state, skip
            continue

    if unawaited:
        # Build error message
        error_msg = f"\n{'=' * 80}\n"
        error_msg += "UNWAITED COROUTINES DETECTED at end of test session\n"
        error_msg += f"{'=' * 80}\n"
        for coro_id, info in unawaited:
            error_msg += f"\nCoroutine ID: {coro_id}\n"
            error_msg += f"Mock Method: {info.get('mock_method_name', 'unknown')}\n"
            error_msg += f"Test: {info.get('test_name', 'unknown')}\n"
            error_msg += f"Args: {info['args']}\n"
            error_msg += f"Kwargs: {info['kwargs']}\n"
            error_msg += "Creation stack trace:\n"
            for frame in info["stack"][-10:]:
                error_msg += f"  {frame.filename}:{frame.lineno} in {frame.name}\n"
                if frame.line:
                    error_msg += f"    {frame.line}\n"
        error_msg += f"{'=' * 80}\n"

        # Write to stderr for visibility
        sys.stderr.write(error_msg)

        # Note: We can't raise an exception here as the session is finishing
        # But we can set the exit status to indicate failure
        # However, pytest doesn't allow modifying exitstatus in this hook
        # So we'll just log it - the teardown hook will catch it for individual tests


@pytest.hookimpl(tryfirst=True)
def pytest_warning_recorded(
    warning_message: warnings.WarningMessage,
    when: str,
    nodeid: str,
    location: tuple[str, int, str] | None,
) -> None:
    """Detect unawaited coroutines via pytest's warning system."""
    msg_str = str(warning_message.message).lower()
    if (
        isinstance(warning_message.category, type)
        and issubclass(warning_message.category, RuntimeWarning)
        and "coroutine" in msg_str
        and "never awaited" in msg_str
        and ("create_async_mock_method" in msg_str or "async_method" in msg_str)
    ):
        sys.stderr.write("\n" + "=" * 80 + "\n")
        sys.stderr.write("UNWAITED COROUTINE DETECTED (via pytest hook)!\n")
        sys.stderr.write("=" * 80 + "\n")
        sys.stderr.write(f"Warning: {warning_message.message}\n")
        sys.stderr.write(f"Location: {location}\n")
        sys.stderr.write(f"When: {when}\n")
        sys.stderr.write(f"Node ID: {nodeid}\n")
        sys.stderr.write("\nTracked coroutines created by create_async_mock_method:\n")
        sys.stderr.write("-" * 80 + "\n")
        found_unawaited = False
        for coro_id, info in _CREATED_COROUTINES.items():
            coro = info["coroutine"]
            try:
                if coro.cr_frame is None:  # Coroutine was closed/awaited
                    continue
            except AttributeError:
                # Coroutine might be in a different state
                continue
            found_unawaited = True
            sys.stderr.write(f"\nCoroutine ID: {coro_id}\n")
            sys.stderr.write(
                f"Mock Method: {info.get('mock_method_name', 'unknown')}\n"
            )
            sys.stderr.write(f"Test: {info.get('test_name', 'unknown')}\n")
            sys.stderr.write(f"Args: {info['args']}\n")
            sys.stderr.write(f"Kwargs: {info['kwargs']}\n")
            sys.stderr.write("Creation stack trace:\n")
            # Show last 10 frames of creation stack
            for frame in info["stack"][-10:]:
                sys.stderr.write(f"  {frame.filename}:{frame.lineno} in {frame.name}\n")
                if frame.line:
                    sys.stderr.write(f"    {frame.line}\n")
        if not found_unawaited:
            sys.stderr.write("\nNo unawaited coroutines found in tracked list.\n")
            sys.stderr.write(
                "This might be a coroutine created outside our tracking.\n"
            )
        sys.stderr.write("=" * 80 + "\n\n")


@pytest.fixture
def mock_hass() -> MagicMock:
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    hass.async_create_task = MagicMock()
    return hass


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Create a mock config entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry_123"
    entry.data = {
        "host": "192.168.1.100",
        "port": 52000,
        "model": "AMS8",
        "input_count": 8,
        "output_count": 8,
    }
    entry.options = {
        "active_inputs": [1, 2, 3, 4],
        "active_outputs": [1, 2],
        "input_links": {},
    }
    entry.title = "Test Triad AMS"
    entry.runtime_data = None
    return entry


@pytest.fixture
def mock_connection() -> MagicMock:
    """Create a mock TriadConnection."""
    conn = MagicMock()
    # Set synchronous attributes
    conn.host = "192.168.1.100"
    conn.port = 52000
    conn.close_nowait = MagicMock()

    # Set async methods using explicit coroutines
    conn.connect = create_async_mock_method()
    conn.disconnect = create_async_mock_method()
    conn.set_output_volume = create_async_mock_method()
    conn.get_output_volume = create_async_mock_method(return_value=0.5)
    conn.set_output_mute = create_async_mock_method()
    conn.get_output_mute = create_async_mock_method(return_value=False)
    conn.volume_step_up = create_async_mock_method()
    conn.volume_step_down = create_async_mock_method()
    conn.set_output_to_input = create_async_mock_method()
    conn.get_output_source = create_async_mock_method(return_value=1)
    conn.disconnect_output = create_async_mock_method()
    conn.set_trigger_zone = create_async_mock_method()

    return conn


@pytest.fixture
def mock_coordinator(mock_connection: MagicMock) -> MagicMock:
    """Create a mock TriadCoordinator."""
    coordinator = MagicMock(spec=TriadCoordinator)
    coordinator._conn = mock_connection
    coordinator.input_count = 8
    coordinator.start = create_async_mock_method()
    coordinator.stop = create_async_mock_method()
    coordinator.disconnect = create_async_mock_method()
    coordinator.set_output_volume = create_async_mock_method()
    coordinator.get_output_volume = create_async_mock_method(return_value=0.5)
    coordinator.set_output_mute = create_async_mock_method()
    coordinator.get_output_mute = create_async_mock_method(return_value=False)
    coordinator.volume_step_up = create_async_mock_method()
    coordinator.volume_step_down = create_async_mock_method()
    coordinator.set_output_to_input = create_async_mock_method()
    coordinator.get_output_source = create_async_mock_method(return_value=1)
    coordinator.disconnect_output = create_async_mock_method()
    coordinator.set_trigger_zone = create_async_mock_method()
    coordinator.register_output = MagicMock()
    return coordinator


@pytest.fixture
def coordinator_with_mock_connection(
    mock_connection: MagicMock,
) -> Generator[TriadCoordinator]:
    """Create a real TriadCoordinator with a mocked connection."""
    config = TriadCoordinatorConfig(host="192.168.1.100", port=52000, input_count=8)
    return TriadCoordinator(config, connection=mock_connection)


@pytest.fixture
def triad_ams_output(
    coordinator_with_mock_connection: TriadCoordinator,
) -> TriadAmsOutput:
    """Create a TriadAmsOutput instance for testing."""
    input_names = {i: f"Input {i}" for i in range(1, 9)}
    return TriadAmsOutput(
        1, "Output 1", coordinator_with_mock_connection, None, input_names
    )


@pytest.fixture
def input_names() -> dict[int, str]:
    """Return default input names for testing."""
    return {i: f"Input {i}" for i in range(1, 9)}


@pytest.fixture
def event_loop() -> Generator[asyncio.AbstractEventLoop]:
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def enable_sockets_for_integration_tests(request: pytest.FixtureRequest) -> None:
    """Enable socket usage for integration tests."""
    # Check if this is an integration test by looking at the test path
    if "integration" in str(request.node.fspath) and pytest_socket is not None:
        pytest_socket.enable_socket()


@pytest.fixture
async def hass_fixture() -> AsyncGenerator[HomeAssistant]:
    """Create a Home Assistant instance for testing."""
    # This will be provided by pytest-homeassistant-custom-component
    # For now, we'll use a mock
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    hass.async_create_task = MagicMock()
    return hass


@pytest.fixture
def mock_state() -> MagicMock:
    """Create a mock state object."""
    state = MagicMock()
    state.name = "Test Entity"
    state.state = "playing"
    state.attributes = {
        "media_title": "Test Song",
        "media_artist": "Test Artist",
        "media_album_name": "Test Album",
        "media_duration": 180,
        "media_content_id": "test://content",
        "media_content_type": "music",
        "entity_picture": "http://example.com/art.jpg",
    }
    return state
