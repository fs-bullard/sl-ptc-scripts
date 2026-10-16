"""Photon transfer curve fitting.

In the shot-noise-limited region the sensor model gives a straight line:

    sigma^2 = K^2 * mu_e + sigma_read^2   and   mu = K * mu_e
    => sigma^2 = K * mu + sigma_dark^2

so the slope of variance against dark-corrected mean signal is the system gain
K in ADU per electron, and the intercept is the temporal dark noise in ADU^2.

EMVA 1288 section 6.6 fits over 0 to 70% of saturation. Beyond that the curve
turns over as pixels clip, and including those points drags the slope down.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .stats import PTCPoint


@dataclass
class PTCFit:
    """Result of fitting the linear region of a photon transfer curve."""

    system_gain: float
    """Slope K, in ADU per electron."""

    intercept: float
    """Temporal dark noise variance, in ADU^2."""

    r_squared: float
    fit_indices: list[int]
    mu_saturation: float
    fit_limit: float
    #: Inverse gain, electrons per ADU.
    inverse_gain: float
    read_noise_adu: float
    read_noise_e: float
    saturation_capacity_e: float

    residual_noise_adu: float = 0.0
    """Root of the fit intercept. A correct dark-corrected PTC leaves this near
    zero; a large value indicates the dark reference does not match the bright
    acquisitions."""

    saturation_reached: bool = True
    """False when the sweep never saturated, making `mu_saturation` and
    `saturation_capacity_e` lower bounds rather than measurements."""

    def to_dict(self) -> dict[str, float | bool | list[int]]:
        return {
            "system_gain_adu_per_e": self.system_gain,
            "inverse_gain_e_per_adu": self.inverse_gain,
            "intercept_adu2": self.intercept,
            "read_noise_adu": self.read_noise_adu,
            "read_noise_e": self.read_noise_e,
            "residual_noise_adu": self.residual_noise_adu,
            "saturation_capacity_e": self.saturation_capacity_e,
            "mu_saturation_adu": self.mu_saturation,
            "saturation_reached": self.saturation_reached,
            "fit_limit_adu": self.fit_limit,
            "r_squared": self.r_squared,
            "fit_indices": self.fit_indices,
        }


class FitError(Exception):
    """The curve could not be fitted."""


def find_saturation(
    points: list[PTCPoint], saturated_threshold: float = 0.01
) -> tuple[float, bool]:
    """Estimate the mean signal at saturation, in ADU.

    Returns (mu_saturation, reached), where `reached` is False if the sweep
    never actually saturated -- in that case the value is only a lower bound
    from the highest measured point, and any full-well figure derived from it
    understates the true capacity.

    Two signals are used, and the smaller wins:

    * the first level where an appreciable fraction of ROI pixels hit the ADC
      rail, and
    * the peak of the variance curve, since temporal variance collapses once
      pixels clip.
    """
    means = np.array([point.mean for point in points], dtype=float)
    variances = np.array([point.variance for point in points], dtype=float)

    candidates: list[float] = []

    # Signal 1: pixels sitting on the ADC rail.
    for point in points:
        if point.saturated_fraction > saturated_threshold:
            candidates.append(point.mean)
            break

    # Signal 2: the variance peak. Only trust it if the curve actually falls
    # away afterwards -- otherwise the run simply never reached saturation.
    if len(variances) >= 3:
        peak = int(np.argmax(variances))
        if peak < len(variances) - 1 and variances[-1] < 0.7 * variances[peak]:
            candidates.append(float(means[peak]))

    if candidates:
        return min(candidates), True

    # Never saturated: the highest measured point bounds the usable range.
    return float(means.max()), False


def dark_noise_adu(points: list[PTCPoint]) -> float:
    """Temporal dark noise, in ADU, from the dark sets themselves.

    This is the physically meaningful read-noise estimate: the standard
    deviation of the dark frames. The PTC intercept cannot supply it, because
    the dark variance has already been subtracted out of every point.
    """
    variances = [point.dark.variance for point in points if point.dark.variance > 0]
    if not variances:
        return 0.0
    # Shortest exposure has least dark-current shot noise, so it is closest to
    # the read noise floor.
    shortest = min(points, key=lambda point: point.exposure_ms)
    return float(np.sqrt(max(shortest.dark.variance, 0.0)))


def fit_ptc(
    points: list[PTCPoint],
    max_fraction: float = 0.7,
    auto_detect_saturation: bool = True,
    fit_range: tuple[float, float] | None = None,
    saturation_adu: int | None = None,
) -> PTCFit:
    """Fit the linear region of the photon transfer curve.

    `fit_range` overrides automatic selection with explicit (low, high) bounds
    on the dark-corrected mean signal, in ADU.
    """
    if len(points) < 2:
        raise FitError("Need at least 2 measured levels to fit a curve")

    means = np.array([point.mean for point in points], dtype=float)
    variances = np.array([point.variance for point in points], dtype=float)

    saturation_reached = True
    if auto_detect_saturation:
        mu_saturation, saturation_reached = find_saturation(points)
    elif saturation_adu is not None:
        mu_saturation = float(saturation_adu)
    else:
        mu_saturation = float(means.max())

    # Without saturation there is no fraction-of-saturation to work from, so
    # fit everything measured rather than discarding the top 30% of a valid
    # linear range.
    if not saturation_reached and fit_range is None:
        max_fraction = 1.0

    # A clipped point carries no usable temporal noise regardless of where the
    # fit limit lands, so it never belongs in the fit.
    clipped = np.array(
        [point.saturated_fraction > 0.01 or point.variance < 0 for point in points]
    )

    if fit_range is not None:
        low, high = fit_range
        fit_limit = high
        selected = (means >= low) & (means <= high) & ~clipped
    else:
        fit_limit = max_fraction * mu_saturation
        # The dark point (mean ~ 0) is a legitimate part of the line, so keep
        # non-negative means rather than requiring a positive signal.
        selected = (means <= fit_limit) & (means >= 0) & ~clipped

    indices = np.flatnonzero(selected)
    if indices.size < 2:
        raise FitError(
            f"Only {indices.size} point(s) fall inside the fit region "
            f"(mean <= {fit_limit:.1f} ADU). Acquire more levels below "
            "saturation, or set an explicit --fit-range."
        )

    x = means[indices]
    y = variances[indices]

    slope, intercept = np.polyfit(x, y, 1)

    predicted = slope * x + intercept
    residual_ss = float(np.sum((y - predicted) ** 2))
    total_ss = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1.0 - residual_ss / total_ss if total_ss > 0 else float("nan")

    if slope <= 0:
        raise FitError(
            f"Fitted slope is non-positive ({slope:.4g} ADU/e-), so the data do "
            "not follow the expected photon transfer relationship. Check that "
            "illumination increases signal and that the dark set matches the "
            "exposure."
        )

    # The intercept is the residual variance at zero signal. Because the dark
    # set's variance has already been subtracted, a correct measurement leaves
    # this at approximately zero -- the read noise itself comes from the dark
    # statistics, not from the intercept. A negative value is ordinary noise
    # about zero, so clamp rather than taking the root of a negative number.
    residual_noise_adu = float(np.sqrt(intercept)) if intercept > 0 else 0.0
    read_noise_adu = dark_noise_adu(points)

    return PTCFit(
        system_gain=float(slope),
        intercept=float(intercept),
        r_squared=r_squared,
        fit_indices=[int(i) for i in indices],
        mu_saturation=float(mu_saturation),
        fit_limit=float(fit_limit),
        inverse_gain=1.0 / float(slope),
        read_noise_adu=read_noise_adu,
        read_noise_e=read_noise_adu / float(slope),
        residual_noise_adu=residual_noise_adu,
        saturation_capacity_e=float(mu_saturation) / float(slope),
        saturation_reached=saturation_reached,
    )
