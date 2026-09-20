"""Unit tests for TriadConnection."""

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from custom_components.triad_ams.connection import TriadConnection
from custom_components.triad_ams.const import CLEAN_EXCHANGES_TO_SKIP_DRAIN
from custom_components.triad_ams.exceptions import TransientDeviceError
from tests.conftest import create_async_mock_method


@pytest.fixture
def mock_stream_reader() -> MagicMock:
    """Create a mock StreamReader."""
    reader = MagicMock()
    reader.readuntil = create_async_mock_method(return_value=b"Response\x00")
    # Padding drain / stale-buffer flush find nothing buffered by default.
    reader.readexactly = create_async_mock_method(side_effect=TimeoutError())
    reader.read = create_async_mock_method(side_effect=TimeoutError())
    return reader


@pytest.fixture
def mock_stream_writer() -> MagicMock:
    """Create a mock StreamWriter."""
    writer = MagicMock()
    writer.write = MagicMock()
    writer.drain = create_async_mock_method()
    writer.close = MagicMock()
    writer.wait_closed = create_async_mock_method()
    return writer


@pytest.fixture
def connection() -> TriadConnection:
    """Create a TriadConnection instance."""
    return TriadConnection("192.168.1.100", 52000)


class TestTriadConnectionInitialization:
    """Test TriadConnection initialization."""

    def test_initialization(self) -> None:
        """Test basic initialization."""
        conn = TriadConnection("192.168.1.100", 52000)
        assert conn.host == "192.168.1.100"
        assert conn.port == 52000
        assert conn._reader is None
        assert conn._writer is None

    def test_initial_state(self, connection: TriadConnection) -> None:
        """Test initial connection state."""
        assert connection._reader is None
        assert connection._writer is None


class TestTriadConnectionConnect:
    """Test connection management."""

    @pytest.mark.asyncio
    async def test_connect(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test connecting to device."""

        async def mock_open_connection(*_args: Any, **_kwargs: Any) -> tuple:
            return (mock_stream_reader, mock_stream_writer)

        with patch(
            "asyncio.open_connection", side_effect=mock_open_connection
        ) as mock_open:
            await connection.connect()

            mock_open.assert_called_once_with("192.168.1.100", 52000)
            assert connection._reader == mock_stream_reader
            assert connection._writer == mock_stream_writer

    @pytest.mark.asyncio
    async def test_connect_already_connected(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test connecting when already connected."""
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        async def mock_open_connection(*_args: Any, **_kwargs: Any) -> tuple:
            return (mock_stream_reader, mock_stream_writer)

        with patch(
            "asyncio.open_connection", side_effect=mock_open_connection
        ) as mock_open:
            await connection.connect()
            # Should not call open_connection again
            mock_open.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnect(
        self, connection: TriadConnection, mock_stream_writer: MagicMock
    ) -> None:
        """Test disconnecting."""
        connection._writer = mock_stream_writer
        await connection.disconnect()

        mock_stream_writer.close.assert_called_once()
        mock_stream_writer.wait_closed.assert_called_once()
        assert connection._reader is None
        assert connection._writer is None

    @pytest.mark.asyncio
    async def test_disconnect_not_connected(self, connection: TriadConnection) -> None:
        """Test disconnecting when not connected."""
        await connection.disconnect()
        # Should not raise

    def test_close_nowait(
        self, connection: TriadConnection, mock_stream_writer: MagicMock
    ) -> None:
        """Test close_nowait."""
        connection._writer = mock_stream_writer
        connection.close_nowait()

        mock_stream_writer.close.assert_called_once()
        assert connection._reader is None
        assert connection._writer is None

    def test_close_nowait_not_connected(self, connection: TriadConnection) -> None:
        """Test close_nowait when not connected."""
        connection.close_nowait()
        # Should not raise


class TestTriadConnectionSendCommand:
    """Test command sending."""

    @pytest.mark.asyncio
    async def test_send_command_success(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test successful command send."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Output Volume : 0x32\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        result = await connection._send_command(
            b"\xff\x55\x04\x03\x1e\x00\x32", expect=r"Volume"
        )

        assert "Volume" in result
        mock_stream_writer.write.assert_called_once()
        mock_stream_writer.drain.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_command_auto_connect(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test that send_command auto-connects if needed."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Response\x00"
        )

        async def mock_open_connection(*_args: Any, **_kwargs: Any) -> tuple:
            return (mock_stream_reader, mock_stream_writer)

        with patch(
            "asyncio.open_connection", side_effect=mock_open_connection
        ) as mock_open:
            await connection._send_command(b"\xff\x55")

            mock_open.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_command_handles_audiosense(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test handling of unsolicited AudioSense events."""
        # First response is AudioSense, second is actual response
        responses = [
            b"AudioSense:Input[1] : 1\x00",
            b"Output Volume : 0x32\x00",
        ]

        def readuntil_side_effect(*_args: Any, **_kwargs: Any) -> bytes:
            return responses.pop(0) if responses else b"Done\x00"

        mock_stream_reader.readuntil = create_async_mock_method(
            side_effect=readuntil_side_effect
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        result = await connection._send_command(b"\xff\x55", expect=r"Volume")

        assert "Volume" in result
        assert mock_stream_reader.readuntil.call_count == 2

    @pytest.mark.asyncio
    async def test_send_command_error_response(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """
        An "error" / empty payload raises TransientDeviceError, NOT OSError.

        The connection MUST remain open (this is the issue #102 fix: empty
        responses come from a healthy TCP socket, so the coordinator should
        not tear down + reconnect on them).
        """
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"command error\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer
        # Spy on close_nowait so we can assert it's NOT called on this path.
        with patch.object(connection, "close_nowait") as close_spy:
            with pytest.raises(TransientDeviceError, match="Triad command error"):
                await connection._send_command(b"\xff\x55")
            close_spy.assert_not_called()

        # Sanity: TransientDeviceError is intentionally NOT an OSError, so
        # callers that catch only OSError will let it propagate. That's the
        # point — `_run_worker`'s NETWORK_EXCEPTIONS path must not swallow it.
        assert not issubclass(TransientDeviceError, OSError)

    @pytest.mark.asyncio
    async def test_send_command_empty_response(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """An empty payload also raises TransientDeviceError without closing."""
        mock_stream_reader.readuntil = create_async_mock_method(return_value=b"\x00")
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        with patch.object(connection, "close_nowait") as close_spy:
            with pytest.raises(TransientDeviceError, match="Triad command error"):
                await connection._send_command(b"\xff\x55")
            close_spy.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_command_timeout(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test handling of timeout."""
        mock_stream_reader.readuntil = create_async_mock_method(
            side_effect=TimeoutError()
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        with pytest.raises(asyncio.TimeoutError):
            await connection._send_command(b"\xff\x55")


class TestTriadConnectionPaddedFrames:
    """
    Test NUL-padding drain and stale-buffer flush (issue #164).

    Some firmware pads every response to a fixed 150-byte frame with
    trailing NULs; readuntil() only consumes the first NUL, so the read
    path must drain the rest to avoid desyncing later exchanges.
    """

    @pytest.mark.asyncio
    async def test_drain_discards_trailing_nul_padding(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Trailing NUL padding after a frame is drained, not left buffered."""
        padding = [b"\x00"] * 5

        def readexactly_side_effect(*_args: Any, **_kwargs: Any) -> bytes:
            if padding:
                return padding.pop(0)
            raise TimeoutError

        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Volume : 0x32\x00"
        )
        mock_stream_reader.readexactly = create_async_mock_method(
            side_effect=readexactly_side_effect
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        result = await connection._send_command(b"\xff\x55", expect=r"Volume")

        assert "Volume" in result
        # 5 padding bytes plus the final timed-out read
        assert mock_stream_reader.readexactly.call_count == 6
        assert connection._read_ahead == b""

    @pytest.mark.asyncio
    async def test_drain_preserves_first_non_nul_byte(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """A non-NUL byte ending the drain is kept for the next frame read."""
        drain_bytes = [b"\x00", b"\x00", b"N"]

        def readexactly_side_effect(*_args: Any, **_kwargs: Any) -> bytes:
            if drain_bytes:
                return drain_bytes.pop(0)
            raise TimeoutError

        frames = [b"Frame1\x00", b"ext\x00"]

        def readuntil_side_effect(*_args: Any, **_kwargs: Any) -> bytes:
            return frames.pop(0)

        mock_stream_reader.readuntil = create_async_mock_method(
            side_effect=readuntil_side_effect
        )
        mock_stream_reader.readexactly = create_async_mock_method(
            side_effect=readexactly_side_effect
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        first = await connection._read_response_bytes(mock_stream_reader)
        assert first == b"Frame1\x00"
        assert connection._read_ahead == b"N"

        # The held byte is prepended to the next frame, so nothing is lost.
        second = await connection._read_response_bytes(mock_stream_reader)
        assert second == b"Next\x00"
        assert connection._read_ahead == b""

    @pytest.mark.asyncio
    async def test_flush_discards_stale_bytes_before_send(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Stale buffered bytes are flushed before a new command is written."""
        stale_chunks = [b"\x00\x00\x00leftover"]

        def read_side_effect(*_args: Any, **_kwargs: Any) -> bytes:
            if stale_chunks:
                return stale_chunks.pop(0)
            raise TimeoutError

        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Volume : 0x32\x00"
        )
        mock_stream_reader.read = create_async_mock_method(side_effect=read_side_effect)
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        result = await connection._send_command(b"\xff\x55", expect=r"Volume")

        assert "Volume" in result
        # One chunk of stale data plus the final timed-out read
        assert mock_stream_reader.read.call_count == 2

    @pytest.mark.asyncio
    async def test_flush_discards_pending_read_ahead(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """A held read-ahead byte from a stale exchange is flushed pre-send."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Volume : 0x32\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer
        connection._read_ahead = b"X"

        result = await connection._send_command(b"\xff\x55", expect=r"Volume")

        assert "Volume" in result
        assert connection._read_ahead == b""

    @pytest.mark.asyncio
    async def test_audiosense_with_trailing_dollar_is_skipped(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """AudioSense events with a literal trailing "$" are skipped."""
        responses = [
            b"AudioSense:Input[3] : 0$\x00",
            b"Output Volume : 0x32\x00",
        ]

        def readuntil_side_effect(*_args: Any, **_kwargs: Any) -> bytes:
            return responses.pop(0)

        mock_stream_reader.readuntil = create_async_mock_method(
            side_effect=readuntil_side_effect
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        result = await connection._send_command(b"\xff\x55", expect=r"Volume")

        assert "Volume" in result
        assert mock_stream_reader.readuntil.call_count == 2

    def test_close_nowait_clears_read_ahead(
        self, connection: TriadConnection, mock_stream_writer: MagicMock
    ) -> None:
        """close_nowait() must not leak a read-ahead byte across connections."""
        connection._writer = mock_stream_writer
        connection._read_ahead = b"X"

        connection.close_nowait()

        assert connection._read_ahead == b""


class TestTriadConnectionAdaptiveDrain:
    """
    Test per-connection learning of response framing.

    Single-NUL firmware should stop paying the timed drain/flush windows
    after a few consecutive clean exchanges; padded firmware must keep the
    full windows for the life of the connection.
    """

    @pytest.mark.asyncio
    async def test_clean_exchanges_learn_to_skip_timed_windows(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """After enough clean exchanges the drain and flush are skipped."""
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        for _ in range(CLEAN_EXCHANGES_TO_SKIP_DRAIN):
            await connection._send_command(b"\xff\x55")

        assert connection._skip_timed_windows() is True
        drain_calls = mock_stream_reader.readexactly.call_count
        flush_calls = mock_stream_reader.read.call_count
        assert drain_calls == CLEAN_EXCHANGES_TO_SKIP_DRAIN
        assert flush_calls == CLEAN_EXCHANGES_TO_SKIP_DRAIN

        # Steady state: no timed reads at all on later commands.
        await connection._send_command(b"\xff\x55")
        await connection._send_command(b"\xff\x55")
        assert mock_stream_reader.readexactly.call_count == drain_calls
        assert mock_stream_reader.read.call_count == flush_calls

    @pytest.mark.asyncio
    async def test_connection_that_sees_padding_never_skips(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Once padding is drained, the full windows stay for the connection."""
        padding = [b"\x00"] * 3

        def readexactly_side_effect(*_args: Any, **_kwargs: Any) -> bytes:
            if padding:
                return padding.pop(0)
            raise TimeoutError

        mock_stream_reader.readexactly = create_async_mock_method(
            side_effect=readexactly_side_effect
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        # First exchange drains padding; every later one is clean.
        for _ in range(CLEAN_EXCHANGES_TO_SKIP_DRAIN + 3):
            await connection._send_command(b"\xff\x55")

        assert connection._padding_seen is True
        assert connection._skip_timed_windows() is False
        # Drain ran on every exchange, including the last one.
        assert mock_stream_reader.readexactly.call_count > (
            CLEAN_EXCHANGES_TO_SKIP_DRAIN + 3
        )

    @pytest.mark.asyncio
    async def test_stale_flush_pins_full_windows(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Stale bytes found at flush time also disable skipping."""
        stale_chunks = [b"\x00\x00leftover"]

        def read_side_effect(*_args: Any, **_kwargs: Any) -> bytes:
            if stale_chunks:
                return stale_chunks.pop(0)
            raise TimeoutError

        mock_stream_reader.read = create_async_mock_method(side_effect=read_side_effect)
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer
        connection._clean_exchanges = CLEAN_EXCHANGES_TO_SKIP_DRAIN - 1

        await connection._send_command(b"\xff\x55")

        assert connection._padding_seen is True
        assert connection._skip_timed_windows() is False

    @pytest.mark.asyncio
    async def test_held_read_ahead_byte_resets_clean_count(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """A non-NUL byte found during the drain resets the clean counter."""
        drain_bytes = [b"A"]

        def readexactly_side_effect(*_args: Any, **_kwargs: Any) -> bytes:
            if drain_bytes:
                return drain_bytes.pop(0)
            raise TimeoutError

        mock_stream_reader.readexactly = create_async_mock_method(
            side_effect=readexactly_side_effect
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer
        connection._clean_exchanges = CLEAN_EXCHANGES_TO_SKIP_DRAIN - 1

        await connection._read_response_bytes(mock_stream_reader)

        assert connection._clean_exchanges == 0
        assert connection._skip_timed_windows() is False

    def test_close_nowait_resets_learned_state(
        self, connection: TriadConnection, mock_stream_writer: MagicMock
    ) -> None:
        """close_nowait() must reset framing state for the next connection."""
        connection._writer = mock_stream_writer
        connection._padding_seen = True
        connection._clean_exchanges = CLEAN_EXCHANGES_TO_SKIP_DRAIN

        connection.close_nowait()

        assert connection._padding_seen is False
        assert connection._clean_exchanges == 0

    @pytest.mark.asyncio
    async def test_connect_resets_learned_state(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """connect() must re-learn framing from scratch."""
        connection._clean_exchanges = CLEAN_EXCHANGES_TO_SKIP_DRAIN

        async def mock_open_connection(*_args: Any, **_kwargs: Any) -> tuple:
            return (mock_stream_reader, mock_stream_writer)

        with patch("asyncio.open_connection", side_effect=mock_open_connection):
            await connection.connect()

        assert connection._clean_exchanges == 0
        assert connection._skip_timed_windows() is False


class TestTriadConnectionVolume:
    """Test volume commands."""

    @pytest.mark.asyncio
    async def test_set_output_volume(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test setting output volume."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Output Volume : 0x32\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        await connection.set_output_volume(1, 0.5)

        # Verify command was sent
        mock_stream_writer.write.assert_called_once()
        written = mock_stream_writer.write.call_args[0][0]
        assert written[0:5] == bytearray.fromhex("FF5504031E")
        assert written[5] == 0  # Output 1 (0-based)
        assert written[6] == 50  # 0.5 * 100

    @pytest.mark.asyncio
    async def test_set_output_volume_clamping(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test volume clamping."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Output Volume : 0x64\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        await connection.set_output_volume(1, 1.5)  # Over 1.0
        written = mock_stream_writer.write.call_args[0][0]
        assert written[6] == 100  # Clamped to max

    @pytest.mark.asyncio
    async def test_get_output_volume_hex(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test getting volume with hex response."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Volume : 0x32\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        volume = await connection.get_output_volume(1)

        assert volume == 0.5  # 0x32 = 50, 50/100 = 0.5

    @pytest.mark.asyncio
    async def test_get_output_volume_db(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test getting volume with dB response."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Volume : -25.1\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        volume = await connection.get_output_volume(1)

        assert volume == 0.44  # -25.1 dB is exactly step 44 in the LUT

    @pytest.mark.asyncio
    async def test_volume_db_round_trip_is_noop(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """set(get()) must write back the exact step the device reported."""
        # Device at step 25 reports its LUT dB value on the text path
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Get Out[1] Volume : -39.7\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        volume = await connection.get_output_volume(1)
        assert volume == 0.25

        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Output Volume : 0x19\x00"
        )
        await connection.set_output_volume(1, volume)
        written = mock_stream_writer.write.call_args[0][0]
        assert written[6] == 25  # same step written back, no decay

    @pytest.mark.asyncio
    async def test_get_output_volume_parse_error(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test getting volume with unparseable response."""
        # Response that doesn't match expected pattern causes OSError
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Invalid response\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        # Should raise OSError due to unexpected response
        with pytest.raises(OSError, match="Unexpected response"):
            await connection.get_output_volume(1)


class TestTriadConnectionMute:
    """Test mute commands."""

    @pytest.mark.asyncio
    async def test_set_output_mute_on(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test setting mute on."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Response\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        await connection.set_output_mute(1, mute=True)

        written = mock_stream_writer.write.call_args[0][0]
        assert written[0:5] == bytearray.fromhex("FF55030317")  # Mute on command

    @pytest.mark.asyncio
    async def test_set_output_mute_off(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test setting mute off."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Response\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        await connection.set_output_mute(1, mute=False)

        written = mock_stream_writer.write.call_args[0][0]
        assert written[0:5] == bytearray.fromhex("FF55030318")  # Mute off command

    @pytest.mark.asyncio
    async def test_get_output_mute_true(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test getting mute state (muted)."""
        responses = [
            b"Mute status : mute\x00",
            b"Mute : On\x00",
            b"Muted\x00",
        ]
        for response in responses:
            mock_stream_reader.readuntil = create_async_mock_method(
                return_value=response
            )
            connection._reader = mock_stream_reader
            connection._writer = mock_stream_writer

            muted = await connection.get_output_mute(1)
            assert muted is True

    @pytest.mark.asyncio
    async def test_get_output_mute_false(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test getting mute state (unmuted)."""
        responses = [
            b"Mute status : Unmute\x00",
            b"Mute : Off\x00",
            b"Unmuted\x00",
        ]
        for response in responses:
            mock_stream_reader.readuntil = create_async_mock_method(
                return_value=response
            )
            connection._reader = mock_stream_reader
            connection._writer = mock_stream_writer

            muted = await connection.get_output_mute(1)
            assert muted is False


class TestTriadConnectionSource:
    """Test source routing commands."""

    @pytest.mark.asyncio
    async def test_set_output_to_input(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test routing output to input."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Set output 1 to input 2\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        await connection.set_output_to_input(1, 2)

        written = mock_stream_writer.write.call_args[0][0]
        assert written[0:5] == bytearray.fromhex("FF5504031D")
        assert written[5] == 0  # Output 1 (0-based)
        assert written[6] == 1  # Input 2 (0-based)

    @pytest.mark.asyncio
    async def test_get_output_source(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test getting output source."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Input Source : input 2\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        source = await connection.get_output_source(1)

        assert source == 2

    @pytest.mark.asyncio
    async def test_get_output_source_audio_off(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test getting output source when audio is off."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Audio Off\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        source = await connection.get_output_source(1)

        assert source is None

    @pytest.mark.asyncio
    async def test_disconnect_output(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test disconnecting output."""
        # Response needs to match expected pattern
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Set output 1 to input 9\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        await connection.disconnect_output(1, 8)

        written = mock_stream_writer.write.call_args[0][0]
        assert written[0:5] == bytearray.fromhex("FF5504031D")
        assert written[5] == 0  # Output 1 (0-based)
        assert written[6] == 8  # Invalid input (input_count)


class TestTriadConnectionVolumeSteps:
    """Test volume step commands."""

    @pytest.mark.asyncio
    async def test_volume_step_up_small(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test small volume step up."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Input Source\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        await connection.volume_step_up(1, large=False)

        written = mock_stream_writer.write.call_args[0][0]
        assert written[0:5] == bytearray.fromhex("FF55030313")  # Small step up

    @pytest.mark.asyncio
    async def test_volume_step_up_large(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test large volume step up."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Input Source\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        await connection.volume_step_up(1, large=True)

        written = mock_stream_writer.write.call_args[0][0]
        assert written[0:5] == bytearray.fromhex("FF55030315")  # Large step up

    @pytest.mark.asyncio
    async def test_volume_step_down_small(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test small volume step down."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Input Source\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        await connection.volume_step_down(1, large=False)

        written = mock_stream_writer.write.call_args[0][0]
        assert written[0:5] == bytearray.fromhex("FF55030314")  # Small step down

    @pytest.mark.asyncio
    async def test_volume_step_down_large(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test large volume step down."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Input Source\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        await connection.volume_step_down(1, large=True)

        written = mock_stream_writer.write.call_args[0][0]
        assert written[0:5] == bytearray.fromhex("FF55030316")  # Large step down


class TestTriadConnectionTriggerZone:
    """Test trigger zone commands."""

    @pytest.mark.asyncio
    async def test_set_trigger_zone_on(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test setting trigger zone on."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Max Volume\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        await connection.set_trigger_zone(zone=1, on=True)

        written = mock_stream_writer.write.call_args[0][0]
        assert written[0:5] == bytearray.fromhex("FF55030550")
        assert written[5] == 0  # Zone 1 (0-based)

    @pytest.mark.asyncio
    async def test_set_trigger_zone_off(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test setting trigger zone off."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Max Volume\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        await connection.set_trigger_zone(zone=1, on=False)

        written = mock_stream_writer.write.call_args[0][0]
        assert written[0:5] == bytearray.fromhex("FF55030551")
        assert written[5] == 0  # Zone 1 (0-based)

    @pytest.mark.asyncio
    async def test_set_trigger_zone_clamping(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test zone number clamping."""
        mock_stream_reader.readuntil = create_async_mock_method(
            return_value=b"Max Volume\x00"
        )
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        # Zone 0 should clamp to 1
        await connection.set_trigger_zone(zone=0, on=True)
        written = mock_stream_writer.write.call_args[0][0]
        assert written[5] == 0  # Zone 1 (0-based)

        # Zone 5 should clamp to 3
        await connection.set_trigger_zone(zone=5, on=True)
        written = mock_stream_writer.write.call_args[0][0]
        assert written[5] == 2  # Zone 3 (0-based)
