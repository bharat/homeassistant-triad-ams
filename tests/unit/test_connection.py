"""Unit tests for TriadConnection."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.triad_ams.connection import TriadConnection


@pytest.fixture
def mock_stream_reader() -> MagicMock:
    """Create a mock StreamReader."""
    reader = MagicMock()
    reader.readuntil = AsyncMock(return_value=b"Response\x00")
    return reader


@pytest.fixture
def mock_stream_writer() -> MagicMock:
    """Create a mock StreamWriter."""
    writer = MagicMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
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
        with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
            mock_open.return_value = (mock_stream_reader, mock_stream_writer)
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

        with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
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
        mock_stream_reader.readuntil = AsyncMock(
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
        mock_stream_reader.readuntil = AsyncMock(return_value=b"Response\x00")
        with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
            mock_open.return_value = (mock_stream_reader, mock_stream_writer)
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
        mock_stream_reader.readuntil = AsyncMock(
            side_effect=[
                b"AudioSense:Input[1] : 1\x00",
                b"Output Volume : 0x32\x00",
            ]
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
        """Test handling of error response."""
        mock_stream_reader.readuntil = AsyncMock(return_value=b"command error\x00")
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        with pytest.raises(OSError, match="Triad command error"):
            await connection._send_command(b"\xff\x55")

    @pytest.mark.asyncio
    async def test_send_command_empty_response(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test handling of empty response."""
        mock_stream_reader.readuntil = AsyncMock(return_value=b"\x00")
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        with pytest.raises(OSError, match="Triad command error"):
            await connection._send_command(b"\xff\x55")

    @pytest.mark.asyncio
    async def test_send_command_timeout(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test handling of timeout."""
        mock_stream_reader.readuntil = AsyncMock(side_effect=TimeoutError())
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        with pytest.raises(asyncio.TimeoutError):
            await connection._send_command(b"\xff\x55")


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
        mock_stream_reader.readuntil = AsyncMock(
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
        mock_stream_reader.readuntil = AsyncMock(
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
        mock_stream_reader.readuntil = AsyncMock(return_value=b"Volume : 0x32\x00")
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
        mock_stream_reader.readuntil = AsyncMock(return_value=b"Volume : -25.1\x00")
        connection._reader = mock_stream_reader
        connection._writer = mock_stream_writer

        volume = await connection.get_output_volume(1)

        assert 0.0 <= volume <= 1.0

    @pytest.mark.asyncio
    async def test_get_output_volume_parse_error(
        self,
        connection: TriadConnection,
        mock_stream_reader: MagicMock,
        mock_stream_writer: MagicMock,
    ) -> None:
        """Test getting volume with unparseable response."""
        # Response that doesn't match expected pattern causes OSError
        mock_stream_reader.readuntil = AsyncMock(return_value=b"Invalid response\x00")
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
        mock_stream_reader.readuntil = AsyncMock(return_value=b"Response\x00")
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
        mock_stream_reader.readuntil = AsyncMock(return_value=b"Response\x00")
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
            mock_stream_reader.readuntil = AsyncMock(return_value=response)
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
            mock_stream_reader.readuntil = AsyncMock(return_value=response)
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
        mock_stream_reader.readuntil = AsyncMock(
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
        mock_stream_reader.readuntil = AsyncMock(
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
        mock_stream_reader.readuntil = AsyncMock(return_value=b"Audio Off\x00")
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
        mock_stream_reader.readuntil = AsyncMock(
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
        mock_stream_reader.readuntil = AsyncMock(return_value=b"Input Source\x00")
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
        mock_stream_reader.readuntil = AsyncMock(return_value=b"Input Source\x00")
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
        mock_stream_reader.readuntil = AsyncMock(return_value=b"Input Source\x00")
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
        mock_stream_reader.readuntil = AsyncMock(return_value=b"Input Source\x00")
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
        mock_stream_reader.readuntil = AsyncMock(return_value=b"Max Volume\x00")
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
        mock_stream_reader.readuntil = AsyncMock(return_value=b"Max Volume\x00")
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
        mock_stream_reader.readuntil = AsyncMock(return_value=b"Max Volume\x00")
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
