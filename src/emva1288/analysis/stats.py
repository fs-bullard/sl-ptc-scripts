"""EMVA 1288 temporal statistics.

The temporal variance is measured from differences of frame pairs, per EMVA
1288 section 6:

    sigma^2 = var(A - B) / 2

Differencing cancels every fixed spatial pattern (DSNU and PRNU), leaving only
temporal noise. Averaging the pixel-wise variance of a plain frame stack would
instead include that spatial structure and overstate the noise, giving a
systematically low system gain.

Dark correction subtracts dark *statistics*, not the dark *image*:

    mu    = mu_bright    - mu_dark
    sigma^2 = sigma^2_bright - sigma^2_dark

Subtracting a dark frame pixel-by-pixel would add its read noise to the result
rather than removing it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class StackStats:
    """Temporal statistics for one stack of repetitions over an ROI."""

    mean: float
    variance: float
    frames: int
    pairs: int
    #: Fraction of ROI pixels at or above the saturation rail in any frame.
    saturated_fraction: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "mean": self.mean,
            "variance": self.variance,
            "frames": self.frames,
            "pairs": self.pairs,
            "saturated_fraction": self.saturated_fraction,
        }


def stack_stats(
    stack: np.ndarray,
    saturation_adu: int | None = None,
) -> StackStats:
    """Temporal mean and paired-difference variance over a frame stack.

    `stack` is (n, h, w), already cropped to the ROI. Frames are paired as
    (0,1), (2,3), ...; a trailing odd frame contributes to the mean but not the
    variance.
    """
    if stack.ndim != 3:
        raise ValueError(f"Expected a 3D stack, got shape {stack.shape}")
    n_frames = stack.shape[0]
    if n_frames < 2:
        raise ValueError(
            f"Need at least 2 frames for a temporal variance, got {n_frames}"
        )

    data = stack.astype(np.float64, copy=False)

    # Mean over every frame and every ROI pixel.
    mean = float(data.mean())

    # Pair up frames and take the variance of each difference image. Using the
    # spatial variance of (A - B) rather than its mean square removes any
    # residual offset difference between the two frames.
    n_pairs = n_frames // 2
    variances = np.empty(n_pairs, dtype=np.float64)
    for pair in range(n_pairs):
        difference = data[2 * pair] - data[2 * pair + 1]
        variances[pair] = difference.var(ddof=1) / 2.0
    variance = float(variances.mean())

    if saturation_adu is None:
        saturated_fraction = 0.0
    else:
        saturated = np.any(stack >= saturation_adu, axis=0)
        saturated_fraction = float(saturated.mean())

    return StackStats(
        mean=mean,
        variance=variance,
        frames=n_frames,
        pairs=n_pairs,
        saturated_fraction=saturated_fraction,
    )


@dataclass(frozen=True)
class PTCPoint:
    """One dark-corrected point on the photon transfer curve."""

    index: int
    value: float
    unit: str
    exposure_ms: float
    bright: StackStats
    dark: StackStats

    @property
    def mean(self) -> float:
        """Dark-corrected mean signal, in ADU."""
        return self.bright.mean - self.dark.mean

    @property
    def variance(self) -> float:
        """Dark-corrected temporal variance, in ADU^2."""
        return self.bright.variance - self.dark.variance

    @property
    def saturated_fraction(self) -> float:
        return self.bright.saturated_fraction

    def to_row(self) -> dict[str, float | int | str]:
        return {
            "index": self.index,
            "value": self.value,
            "unit": self.unit,
            "exposure_ms": self.exposure_ms,
            "mean_bright_adu": self.bright.mean,
            "var_bright_adu2": self.bright.variance,
            "mean_dark_adu": self.dark.mean,
            "var_dark_adu2": self.dark.variance,
            "mean_adu": self.mean,
            "variance_adu2": self.variance,
            "frames": self.bright.frames,
            "saturated_fraction": self.saturated_fraction,
        }
