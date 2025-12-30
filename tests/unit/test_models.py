"""Unit tests for TriadAmsOutput model."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.triad_ams.models import TriadAmsOutput


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Create a mock coordinator."""
    coordinator = MagicMock()
    coordinator.input_count = 8
    coordinator.set_output_to_input = AsyncMock()
    coordinator.set_output_volume = AsyncMock()
    coordinator.set_output_mute = AsyncMock()
    coordinator.volume_step_up = AsyncMock()
    coordinator.volume_step_down = AsyncMock()
    coordinator.disconnect_output = AsyncMock()
    coordinator.get_output_volume = AsyncMock(return_value=0.5)
    coordinator.get_output_mute = AsyncMock(return_value=False)
    coordinator.get_output_source = AsyncMock(return_value=1)
    return coordinator


@pytest.fixture
def input_names() -> dict[int, str]:
    """Return default input names."""
    return {i: f"Input {i}" for i in range(1, 9)}


@pytest.fixture
def output(mock_coordinator: MagicMock, input_names: dict[int, str]) -> TriadAmsOutput:
    """Create a TriadAmsOutput instance."""
    return TriadAmsOutput(1, "Output 1", mock_coordinator, None, input_names)


class TestTriadAmsOutputInitialization:
    """Test TriadAmsOutput initialization."""

    def test_initialization(
        self, mock_coordinator: MagicMock, input_names: dict[int, str]
    ) -> None:
        """Test basic initialization."""
        output = TriadAmsOutput(1, "Test Output", mock_coordinator, None, input_names)
        assert output.number == 1
        assert output.name == "Test Output"
        assert output.coordinator == mock_coordinator
        assert output.input_names == input_names

    def test_default_input_names(self, mock_coordinator: MagicMock) -> None:
        """Test initialization with default input names."""
        # Provide input_names explicitly since coordinator.input_count is needed
        input_names = {i: f"Input {i}" for i in range(1, 9)}
        output = TriadAmsOutput(1, "Output 1", mock_coordinator, None, input_names)
        assert len(output.input_names) == 8
        assert output.input_names[1] == "Input 1"
        assert output.input_names[8] == "Input 8"

    def test_initial_state(self, output: TriadAmsOutput) -> None:
        """Test initial state values."""
        assert output.volume is None
        assert output.muted is False
        assert output.source is None
        assert output.is_on is False


class TestTriadAmsOutputSource:
    """Test source management."""

    @pytest.mark.asyncio
    async def test_set_source(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test setting a source."""
        await output.set_source(2)
        mock_coordinator.set_output_to_input.assert_called_once_with(1, 2)
        assert output.source == 2
        assert output.is_on is True

    @pytest.mark.asyncio
    async def test_set_source_handles_error(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test that set_source handles OSError."""
        mock_coordinator.set_output_to_input.side_effect = OSError("Connection failed")
        await output.set_source(2)
        # Source should not be set on error
        assert output.source is None

    def test_source_name(self, output: TriadAmsOutput) -> None:
        """Test source_name property."""
        assert output.source_name is None
        output._assigned_input = 2
        assert output.source_name == "Input 2"

    def test_source_list(self, output: TriadAmsOutput) -> None:
        """Test source_list property."""
        sources = output.source_list
        assert len(sources) == 8
        assert "Input 1" in sources
        assert "Input 8" in sources
        assert sources == sorted(sources)  # Should be sorted

    def test_source_id_for_name(self, output: TriadAmsOutput) -> None:
        """Test source_id_for_name method."""
        assert output.source_id_for_name("Input 1") == 1
        assert output.source_id_for_name("Input 5") == 5
        assert output.source_id_for_name("Unknown") is None

    def test_has_source(self, output: TriadAmsOutput) -> None:
        """Test has_source property."""
        assert output.has_source is False
        output._assigned_input = 1
        assert output.has_source is True


class TestTriadAmsOutputVolume:
    """Test volume operations."""

    @pytest.mark.asyncio
    async def test_set_volume(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test setting volume."""
        await output.set_volume(0.75)
        mock_coordinator.set_output_volume.assert_called_once()
        # Volume should be quantized and clamped
        assert output.volume is not None
        assert 0.0 <= output.volume <= 1.0

    @pytest.mark.asyncio
    async def test_set_volume_zero_becomes_minimum(
        self,
        output: TriadAmsOutput,
        mock_coordinator: MagicMock,  # noqa: ARG002
    ) -> None:
        """Test that volume 0 becomes minimum step."""
        await output.set_volume(0.0)
        # Should be set to minimum (step 1)
        assert output.volume is not None
        assert output.volume > 0.0

    @pytest.mark.asyncio
    async def test_set_volume_handles_error(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test that set_volume handles OSError."""
        mock_coordinator.set_output_volume.side_effect = OSError("Connection failed")
        await output.set_volume(0.5)
        # Volume should remain unchanged on error

    @pytest.mark.asyncio
    async def test_volume_up_step(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test volume up step."""
        await output.volume_up_step(large=False)
        mock_coordinator.volume_step_up.assert_called_once_with(1, large=False)

    @pytest.mark.asyncio
    async def test_volume_up_step_large(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test large volume up step."""
        await output.volume_up_step(large=True)
        mock_coordinator.volume_step_up.assert_called_once_with(1, large=True)

    @pytest.mark.asyncio
    async def test_volume_down_step(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test volume down step."""
        await output.volume_down_step(large=False)
        mock_coordinator.volume_step_down.assert_called_once_with(1, large=False)

    @pytest.mark.asyncio
    async def test_volume_step_handles_error(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test that volume steps handle OSError."""
        mock_coordinator.volume_step_up.side_effect = OSError("Connection failed")
        await output.volume_up_step()
        # Should not raise


class TestTriadAmsOutputMute:
    """Test mute operations."""

    @pytest.mark.asyncio
    async def test_set_muted_true(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test setting mute to True."""
        await output.set_muted(muted=True)
        mock_coordinator.set_output_mute.assert_called_once_with(1, mute=True)
        assert output.muted is True

    @pytest.mark.asyncio
    async def test_set_muted_false(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test setting mute to False."""
        output._muted = True
        await output.set_muted(muted=False)
        mock_coordinator.set_output_mute.assert_called_once_with(1, mute=False)
        assert output.muted is False

    @pytest.mark.asyncio
    async def test_set_muted_handles_error(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test that set_muted handles OSError."""
        mock_coordinator.set_output_mute.side_effect = OSError("Connection failed")
        await output.set_muted(muted=True)
        # Should not raise


class TestTriadAmsOutputPower:
    """Test power operations."""

    @pytest.mark.asyncio
    async def test_turn_off(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test turning off output."""
        output._assigned_input = 2
        output._ui_on = True
        await output.turn_off()
        mock_coordinator.disconnect_output.assert_called_once_with(1)
        assert output.source is None
        assert output.is_on is False
        assert output._last_assigned_input == 2  # Should remember last source

    @pytest.mark.asyncio
    async def test_turn_off_handles_error(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test that turn_off handles OSError."""
        mock_coordinator.disconnect_output.side_effect = OSError("Connection failed")
        await output.turn_off()
        # Should not raise

    @pytest.mark.asyncio
    async def test_turn_on_with_remembered_source(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test turning on with remembered source."""
        output._last_assigned_input = 3
        await output.turn_on()
        # Should restore the remembered source
        mock_coordinator.set_output_to_input.assert_called_once_with(1, 3)
        assert output.is_on is True

    @pytest.mark.asyncio
    async def test_turn_on_without_remembered_source(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test turning on without remembered source."""
        output._last_assigned_input = None
        await output.turn_on()
        # Should just mark UI as on
        assert output.is_on is True
        mock_coordinator.set_output_to_input.assert_not_called()


class TestTriadAmsOutputRefresh:
    """Test refresh operations."""

    @pytest.mark.asyncio
    async def test_refresh(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test refreshing state."""
        mock_coordinator.get_output_volume.return_value = 0.6
        mock_coordinator.get_output_mute.return_value = True
        mock_coordinator.get_output_source.return_value = 2

        await output.refresh()

        assert output.volume == 0.6
        assert output.muted is True
        assert output.source == 2
        assert output.is_on is True

    @pytest.mark.asyncio
    async def test_refresh_with_audio_off(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test refresh when output is off."""
        mock_coordinator.get_output_source.return_value = None

        await output.refresh()

        assert output.source is None
        assert output.is_on is False

    @pytest.mark.asyncio
    async def test_refresh_with_invalid_source(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test refresh with invalid source number."""
        mock_coordinator.get_output_source.return_value = 99  # Out of range

        await output.refresh()

        assert output.source is None
        assert output.is_on is False

    @pytest.mark.asyncio
    async def test_refresh_handles_error(
        self, output: TriadAmsOutput, mock_coordinator: MagicMock
    ) -> None:
        """Test that refresh handles OSError."""
        mock_coordinator.get_output_volume.side_effect = OSError("Connection failed")
        await output.refresh()
        # Should not raise

    @pytest.mark.asyncio
    async def test_refresh_and_notify(
        self,
        output: TriadAmsOutput,
        mock_coordinator: MagicMock,  # noqa: ARG002
    ) -> None:
        """Test refresh_and_notify calls listeners."""
        listener_called = False

        def listener() -> None:
            nonlocal listener_called
            listener_called = True

        unsub = output.add_listener(listener)
        await output.refresh_and_notify()

        assert listener_called
        unsub()


class TestTriadAmsOutputListeners:
    """Test listener management."""

    def test_add_listener(self, output: TriadAmsOutput) -> None:
        """Test adding a listener."""
        called = False

        def listener() -> None:
            nonlocal called
            called = True

        unsub = output.add_listener(listener)
        output._notify_listeners()
        assert called

        # Unsubscribe
        unsub()
        called = False
        output._notify_listeners()
        assert not called

    def test_listener_error_handling(self, output: TriadAmsOutput) -> None:
        """Test that listener errors don't break notification."""
        good_listener_called = False

        def bad_listener() -> None:
            error_msg = "Test error"
            raise ValueError(error_msg)

        def good_listener() -> None:
            nonlocal good_listener_called
            good_listener_called = True

        output.add_listener(bad_listener)
        output.add_listener(good_listener)

        # Should not raise, and good listener should be called
        output._notify_listeners()
        assert good_listener_called
