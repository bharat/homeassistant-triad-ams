"""Unit tests for volume LUT utilities."""

import pytest

from custom_components.triad_ams.volume_lut import (
    db_for_step,
    percentage_for_step,
    step_for_db,
    step_for_percentage,
)


class TestDbForStep:
    """Test db_for_step function."""

    def test_valid_steps(self) -> None:
        """Test valid step values."""
        assert db_for_step(1) == -100.3
        assert db_for_step(50) == -21.2
        assert db_for_step(100) == 0.0

    def test_boundary_values(self) -> None:
        """Test boundary step values."""
        assert db_for_step(1) == -100.3
        assert db_for_step(100) == 0.0

    def test_invalid_low_step(self) -> None:
        """Test invalid low step value."""
        with pytest.raises(ValueError, match=r"step must be in 1\.\.100"):
            db_for_step(0)

    def test_invalid_high_step(self) -> None:
        """Test invalid high step value."""
        with pytest.raises(ValueError, match=r"step must be in 1\.\.100"):
            db_for_step(101)

    def test_negative_step(self) -> None:
        """Test negative step value."""
        with pytest.raises(ValueError, match=r"step must be in 1\.\.100"):
            db_for_step(-1)


class TestStepForDb:
    """Test step_for_db function."""

    def test_exact_matches(self) -> None:
        """Test exact dB matches."""
        assert step_for_db(-100.3) == 1
        assert step_for_db(0.0) == 99  # 0.0 dB maps to step 99, not 100

    def test_near_matches(self) -> None:
        """Test near dB matches."""
        # Should round to nearest step
        assert step_for_db(-21.0) in [49, 50, 51]  # Around step 50
        assert step_for_db(-50.0) in [13, 14, 15]  # Around step 14

    def test_boundary_values(self) -> None:
        """Test boundary dB values."""
        # Very low dB should map to step 1
        assert step_for_db(-200.0) == 1
        # Very high dB should map to step 100
        assert step_for_db(10.0) == 100

    def test_mid_range_values(self) -> None:
        """Test mid-range dB values."""
        step = step_for_db(-30.0)
        assert 1 <= step <= 100
        assert isinstance(step, int)


class TestPercentageForStep:
    """Test percentage_for_step function."""

    def test_valid_steps(self) -> None:
        """Test valid step values."""
        assert percentage_for_step(1) == 0.01
        assert percentage_for_step(50) == 0.5
        assert percentage_for_step(100) == 1.0

    def test_boundary_clamping(self) -> None:
        """Test that out-of-range steps are clamped."""
        assert percentage_for_step(0) == 0.01  # Clamped to 1
        assert percentage_for_step(101) == 1.0  # Clamped to 100
        assert percentage_for_step(-1) == 0.01  # Clamped to 1

    def test_precision(self) -> None:
        """Test precision of percentage calculation."""
        assert percentage_for_step(25) == 0.25
        assert percentage_for_step(33) == 0.33
        assert percentage_for_step(75) == 0.75


class TestStepForPercentage:
    """Test step_for_percentage function."""

    def test_valid_percentages(self) -> None:
        """Test valid percentage values."""
        assert step_for_percentage(0.0) == 1  # Minimum step
        assert step_for_percentage(0.5) == 50
        assert step_for_percentage(1.0) == 100

    def test_boundary_clamping(self) -> None:
        """Test that out-of-range percentages are clamped."""
        assert step_for_percentage(-0.1) == 1  # Clamped to 0.0 -> step 1
        assert step_for_percentage(1.5) == 100  # Clamped to 1.0 -> step 100

    def test_rounding(self) -> None:
        """Test rounding behavior."""
        assert step_for_percentage(0.25) == 25
        assert step_for_percentage(0.33) == 33
        assert step_for_percentage(0.75) == 75
        assert step_for_percentage(0.123) == 12  # Rounded
        assert step_for_percentage(0.999) == 100  # Rounded to max

    def test_minimum_step(self) -> None:
        """Test that zero percentage maps to minimum step."""
        assert step_for_percentage(0.0) == 1
        assert step_for_percentage(0.001) == 1  # Very small -> step 1
