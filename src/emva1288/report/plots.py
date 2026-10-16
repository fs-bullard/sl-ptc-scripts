"""Photon transfer curve plotting.

Two panels: the PTC on linear axes with the fitted line, and the same data on
log-log axes where the read-noise, shot-noise and PRNU regimes separate into
distinguishable slopes.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib

matplotlib.use("Agg")  # No GUI: the CLI only ever writes files.

import matplotlib.pyplot as plt
import numpy as np

if TYPE_CHECKING:
    from ..tests.ptc import PTCResults

# Validated palette slots 1 and 2 plus chart chrome (see dataviz reference).
SERIES_FIT = "#2a78d6"
SERIES_DATA = "#eb6834"
SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
AXIS = "#c3c2b7"

FONT_STACK = ["Segoe UI", "DejaVu Sans", "sans-serif"]


def _style_axes(ax: plt.Axes) -> None:
    """Recessive grid and axes, so the data carries the emphasis."""
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRIDLINE, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
        ax.spines[side].set_linewidth(1.0)
    ax.tick_params(colors=INK_MUTED, labelsize=9)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_color(INK_SECONDARY)


def plot_ptc(path: Path, results: "PTCResults", title: str | None = None) -> Path:
    """Render the PTC figure to `path`."""
    plt.rcParams["font.sans-serif"] = FONT_STACK
    plt.rcParams["font.family"] = "sans-serif"

    means = np.array([point.mean for point in results.points])
    variances = np.array([point.variance for point in results.points])
    fit = results.fit
    in_fit = np.zeros(len(results.points), dtype=bool)
    in_fit[fit.fit_indices] = True

    figure, (ax_linear, ax_log) = plt.subplots(1, 2, figsize=(11, 4.6))
    figure.patch.set_facecolor(SURFACE)

    # -- linear panel --------------------------------------------------
    _style_axes(ax_linear)

    # Shade the region excluded from the fit, so the reader sees why the line
    # stops where it does.
    if fit.fit_limit < means.max():
        # Span to the axis edge rather than the last point, so the band does
        # not appear to stop mid-region.
        ax_linear.axvspan(
            fit.fit_limit,
            means.max() * 1.12,
            color=INK_MUTED,
            alpha=0.09,
            zorder=1,
            linewidth=0,
        )
        # Reserve headroom above the data, then label the band inside it, so
        # the text cannot collide with a point.
        span_v = variances.max() - min(variances.min(), 0.0)
        top = variances.max() + span_v * 0.16
        ax_linear.set_ylim(min(variances.min(), 0.0) - span_v * 0.06, top)
        ax_linear.set_xlim(means.min() - means.max() * 0.04, means.max() * 1.12)
        ax_linear.text(
            fit.fit_limit + (means.max() * 1.12 - fit.fit_limit) * 0.5,
            top - span_v * 0.03,
            "excluded (above fit limit)",
            ha="center",
            va="top",
            fontsize=8,
            color=INK_MUTED,
        )

    line_x = np.array([0.0, fit.fit_limit])
    ax_linear.plot(
        line_x,
        fit.system_gain * line_x + fit.intercept,
        color=SERIES_FIT,
        linewidth=2,
        zorder=3,
        label=f"fit: K = {fit.system_gain:.4f} ADU/e⁻",
    )
    ax_linear.scatter(
        means[in_fit],
        variances[in_fit],
        s=42,
        color=SERIES_DATA,
        edgecolor=SURFACE,
        linewidth=2,
        zorder=4,
        label="measured (in fit)",
    )
    if (~in_fit).any():
        ax_linear.scatter(
            means[~in_fit],
            variances[~in_fit],
            s=42,
            facecolor="none",
            edgecolor=SERIES_DATA,
            linewidth=1.6,
            zorder=4,
            label="measured (excluded)",
        )

    ax_linear.set_xlabel("Mean signal μ  (ADU, dark corrected)", color=INK_SECONDARY, fontsize=10)
    ax_linear.set_ylabel("Temporal variance σ²  (ADU²)", color=INK_SECONDARY, fontsize=10)
    ax_linear.set_title("Photon transfer curve", color=INK_PRIMARY, fontsize=12, loc="left", pad=10)
    # Upper left is the only reliably empty corner: the curve rises to the
    # right and the excluded-band label occupies the top centre.
    legend = ax_linear.legend(frameon=False, fontsize=9, loc="upper left", borderpad=0.2)
    for text in legend.get_texts():
        text.set_color(INK_SECONDARY)

    # -- log-log panel -------------------------------------------------
    _style_axes(ax_log)
    positive = (means > 0) & (variances > 0)
    if positive.any():
        shown_in_fit = positive & in_fit
        shown_excluded = positive & ~in_fit
        ax_log.loglog(
            means[shown_in_fit],
            variances[shown_in_fit],
            marker="o",
            markersize=6,
            linestyle="none",
            color=SERIES_DATA,
            markeredgecolor=SURFACE,
            markeredgewidth=1.5,
            zorder=4,
        )
        if shown_excluded.any():
            ax_log.loglog(
                means[shown_excluded],
                variances[shown_excluded],
                marker="o",
                markersize=6,
                linestyle="none",
                markerfacecolor="none",
                markeredgecolor=SERIES_DATA,
                markeredgewidth=1.4,
                zorder=4,
            )
        # Draw the fit only across the region it was fitted over; extending it
        # would imply the relationship holds through saturation.
        fit_means = means[fit.fit_indices]
        span = np.array([max(fit_means.min(), 1e-6), fit_means.max()])
        ax_log.loglog(
            span,
            fit.system_gain * span + fit.intercept,
            color=SERIES_FIT,
            linewidth=2,
            zorder=3,
        )
    ax_log.set_xlabel("Mean signal μ  (ADU)", color=INK_SECONDARY, fontsize=10)
    ax_log.set_ylabel("Temporal variance σ²  (ADU²)", color=INK_SECONDARY, fontsize=10)
    ax_log.set_title("Log-log view", color=INK_PRIMARY, fontsize=12, loc="left", pad=10)

    if title:
        figure.suptitle(title, color=INK_PRIMARY, fontsize=13, x=0.01, ha="left")
        figure.tight_layout(rect=(0, 0, 1, 0.94))
    else:
        figure.tight_layout()

    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(figure)
    return path
