"""
Measured Triad AMS volume lookup table (device-reported dB per step).

Source: scripts/sweep_volume.py capturing Get Out[X] Volume : <dB> for steps 1..100.
This table was measured on one output and appears consistent across outputs.

STEP_TO_DB[step] -> dB value (float). Index 0 is unused (None) for 1-based steps.
"""

from __future__ import annotations

from bisect import bisect_left

# Index 0 is a placeholder so that index == step
STEP_TO_DB: list[float | None] = [
    None,
    -100.3,
    -92.7,
    -85.8,
    -79.5,
    -73.9,
    -69.0,
    -64.6,
    -61.0,
    -58.0,
    -55.6,
    -53.9,
    -52.0,
    -50.5,
    -49.6,
    -48.7,
    -47.7,
    -46.8,
    -45.9,
    -45.0,
    -44.1,
    -43.2,
    -42.3,
    -41.4,
    -40.6,
    -39.7,
    -38.9,
    -38.0,
    -37.2,
    -36.4,
    -35.6,
    -34.8,
    -34.0,
    -33.2,
    -32.4,
    -31.7,
    -30.9,
    -30.2,
    -29.4,
    -28.7,
    -28.0,
    -27.2,
    -26.5,
    -25.8,
    -25.1,
    -24.5,
    -23.8,
    -23.1,
    -22.5,
    -21.8,
    -21.2,
    -20.5,
    -19.9,
    -19.3,
    -18.7,
    -18.1,
    -17.5,
    -16.9,
    -16.4,
    -15.8,
    -15.3,
    -14.7,
    -14.2,
    -13.7,
    -13.1,
    -12.6,
    -12.1,
    -11.6,
    -11.1,
    -10.7,
    -10.2,
    -9.7,
    -9.3,
    -8.9,
    -8.4,
    -8.0,
    -7.6,
    -7.2,
    -6.8,
    -6.4,
    -6.0,
    -5.6,
    -5.3,
    -4.9,
    -4.6,
    -4.2,
    -3.9,
    -3.6,
    -3.3,
    -3.0,
    -2.7,
    -2.4,
    -2.1,
    -1.8,
    -1.6,
    -1.3,
    -1.1,
    -0.9,
    -0.6,
    -0.4,
    0.0,
]

# Build a monotonic list of (dB, step) for reverse lookup
_DBS: list[float] = [db for db in STEP_TO_DB[1:] if db is not None]  # type: ignore[arg-type]


def db_for_step(step: int) -> float:
    """
    Return measured dB for a device step (1..100).

    Raises ValueError if out of range.
    """
    if step < 1 or step >= len(STEP_TO_DB):
        msg = "step must be in 1..100"
        raise ValueError(msg)
    val = STEP_TO_DB[step]
    if val is None:
        msg = f"Unexpected None value for step {step}"
        raise RuntimeError(msg)
    return float(val)


def step_for_db(db: float) -> int:
    """
    Return the nearest device step (1..100) for a desired dB value.

    Uses nearest neighbor on the measured monotonic curve.
    """
    # Find insertion point
    i = bisect_left(_DBS, db)
    if i <= 0:
        return 1
    if i >= len(_DBS):
        return 100
    # Choose closer neighbor
    before = _DBS[i - 1]
    after = _DBS[i]
    dist_before = abs(db - before)
    dist_after = abs(after - db)
    return i if dist_after < dist_before else i - 1


def percentage_for_step(step: int) -> float:
    """Map device step to 0..1 percentage (exact quantization)."""
    step = max(step, 1)
    step = min(step, 100)
    return step / 100.0


def step_for_percentage(pct: float) -> int:
    """Map 0..1 percentage to nearest device step (1..100)."""
    pct = max(0.0, min(1.0, float(pct)))
    step = round(pct * 100)
    step = max(step, 1)
    step = min(step, 100)
    return int(step)
