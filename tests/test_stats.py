"""Temporal statistics behave as EMVA 1288 requires."""

from __future__ import annotations

import numpy as np
import pytest

from emva1288.analysis.stats import stack_stats


def _stack(rng, mean, sigma, n=20, shape=(64, 64)):
    return rng.normal(mean, sigma, size=(n,) + shape)


def test_paired_variance_matches_known_noise():
    rng = np.random.default_rng(1)
    stats = stack_stats(_stack(rng, 1000.0, 12.0))
    assert stats.mean == pytest.approx(1000.0, abs=0.5)
    assert stats.variance == pytest.approx(144.0, rel=0.05)


def test_fixed_pattern_does_not_inflate_variance():
    """The whole point of paired differencing: DSNU/PRNU must cancel.

    A plain per-pixel variance over the stack would also be immune, but the
    spatial average of a *single frame's* variance would not; this pins the
    behaviour that a large fixed offset pattern leaves the temporal variance
    untouched.
    """
    rng = np.random.default_rng(2)
    temporal = _stack(rng, 1000.0, 10.0)
    pattern = rng.normal(0.0, 300.0, size=temporal.shape[1:])

    plain = stack_stats(temporal)
    patterned = stack_stats(temporal + pattern)

    assert patterned.variance == pytest.approx(plain.variance, rel=1e-9)
    assert patterned.mean == pytest.approx(plain.mean + pattern.mean(), abs=1e-6)


def test_odd_frame_count_uses_whole_pairs():
    rng = np.random.default_rng(3)
    stats = stack_stats(_stack(rng, 500.0, 8.0, n=7))
    assert stats.frames == 7
    assert stats.pairs == 3


def test_saturated_fraction_counts_rail_pixels():
    stack = np.full((4, 10, 10), 100, dtype=np.uint16)
    stack[:, 0, :] = 16383  # one row of ten pinned at the rail
    stats = stack_stats(stack, saturation_adu=16383)
    assert stats.saturated_fraction == pytest.approx(0.1)


def test_single_frame_is_rejected():
    with pytest.raises(ValueError, match="at least 2 frames"):
        stack_stats(np.zeros((1, 8, 8)))
