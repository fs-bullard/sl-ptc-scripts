"""Photon transfer curve: temporal variance against mean signal.

Two acquisition modes:

* ``exposure`` -- hold the illumination fixed and sweep exposure time. Fully
  automated. A dark set is captured at every exposure, because dark signal and
  its noise both scale with integration time.
* ``illumination`` -- hold exposure fixed and step the illumination, prompting
  the operator at each level. One dark set at the start suffices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..analysis.fitting import PTCFit, fit_ptc
from ..analysis.roi import Rect, resolve_roi
from ..analysis.stats import PTCPoint, StackStats, stack_stats
from ..camera.base import CameraDriver
from ..io import frames as frame_io
from ..io.csvout import write_ptc_csv
from ..io.session import LevelRecord, Session
from ..prefs import Preferences
from ..report.plots import plot_ptc
from .base import PromptFn, TestScript
from .registry import register


@dataclass
class PTCResults:
    """Everything computed from a PTC session."""

    points: list[PTCPoint]
    fit: PTCFit
    roi: Rect
    roi_spec: dict
    mode: str
    unit: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "unit": self.unit,
            "roi": self.roi.to_dict(),
            "roi_spec": self.roi_spec,
            "fit": self.fit.to_dict(),
            "points": [point.to_row() for point in self.points],
            "warnings": self.warnings,
        }


@register
class PhotonTransferCurve(TestScript):
    name = "ptc"
    description = "Photon transfer curve: temporal variance vs mean signal (EMVA 1288 s6)"

    # -- acquisition -----------------------------------------------------

    def acquire(
        self,
        driver: CameraDriver,
        prefs: Preferences,
        options: dict[str, Any],
        prompt: PromptFn,
    ) -> Session:
        mode = options.get("mode", "exposure")
        repeats = int(options.get("repeats") or prefs.get("capture.repeats"))
        if repeats < 2:
            raise ValueError(
                f"repeats must be at least 2 for a temporal variance (got {repeats})"
            )

        info = driver.device_info()
        common = {
            "repeats": repeats,
            "device": info.to_dict(),
            "settings": {
                "full_well": prefs.get("camera.full_well"),
                "binning": prefs.get("camera.binning"),
                "dds": prefs.get("camera.dds"),
                "bit_depth": prefs.get("camera.bit_depth"),
                "driver": driver.name,
                "roi_preset": prefs.get("roi.active"),
                "saturation_adu": prefs.get("analysis.saturation_adu"),
            },
        }

        if mode == "exposure":
            return self._acquire_exposure_sweep(driver, prefs, options, prompt, common)
        if mode == "illumination":
            return self._acquire_illumination(driver, prefs, options, prompt, common)
        raise ValueError(f"Unknown capture mode {mode!r} (use exposure or illumination)")

    def _acquire_exposure_sweep(
        self,
        driver: CameraDriver,
        prefs: Preferences,
        options: dict[str, Any],
        prompt: PromptFn,
        common: dict[str, Any],
    ) -> Session:
        # Snap to what the detector can be set to, then drop duplicates: a fine
        # sweep at short exposures can otherwise ask for the same integer
        # exposure several times over.
        requested = _exposure_steps(prefs, options)
        exposures: list[float] = []
        for value in requested:
            quantised = float(driver.quantise_exposure(value))
            if quantised not in exposures:
                exposures.append(quantised)

        repeats = common["repeats"]

        session = Session.create(
            save_path=Path(options.get("save_path") or prefs.get("save_path")),
            stem=options.get("stem") or prefs.get("stem"),
            test=self.name,
            mode="exposure",
            illumination_unit="ms",
            fixed_illumination=options.get("illumination"),
            **common,
        )

        progress = options.get("progress")
        prompt(
            "Set the LED illumination to a fixed level and leave it there for "
            "the whole sweep, then continue."
        )

        for index, exposure_ms in enumerate(exposures):
            if progress:
                progress(index, len(exposures), f"{exposure_ms:g} ms")

            # Dark first at this exposure: dark signal scales with integration
            # time, so each exposure needs its own reference.
            prompt(f"[{index + 1}/{len(exposures)}] Block all light for the dark set.")
            driver.set_illumination(0.0)
            dark_dir = session.dark_dir(index, exposure_ms)
            dark_stack = driver.grab(exposure_ms, repeats)
            frame_io.write_stack(dark_dir, dark_stack)

            prompt(f"[{index + 1}/{len(exposures)}] Restore the illumination.")
            driver.set_illumination(1.0)
            level_dir = session.level_dir(index, exposure_ms, "ms")
            bright_stack = driver.grab(exposure_ms, repeats)
            frame_io.write_stack(level_dir, bright_stack)

            session.add_level(
                LevelRecord(
                    index=index,
                    value=float(exposure_ms),
                    unit="ms",
                    exposure_ms=float(exposure_ms),
                    frames=repeats,
                    directory=session.relative(level_dir),
                    dark_directory=session.relative(dark_dir),
                )
            )

        return session

    def _acquire_illumination(
        self,
        driver: CameraDriver,
        prefs: Preferences,
        options: dict[str, Any],
        prompt: PromptFn,
        common: dict[str, Any],
    ) -> Session:
        exposure_ms = float(options.get("exposure_ms") or prefs.get("capture.exposure_ms"))
        unit = prefs.get("illumination.unit")
        levels = options.get("levels")
        if levels is None:
            levels = list(prefs.get("illumination.levels"))
        repeats = common["repeats"]

        session = Session.create(
            save_path=Path(options.get("save_path") or prefs.get("save_path")),
            stem=options.get("stem") or prefs.get("stem"),
            test=self.name,
            mode="illumination",
            exposure_ms=exposure_ms,
            illumination_unit=unit,
            **common,
        )

        progress = options.get("progress")

        # One dark set at the start; exposure is constant throughout.
        prompt("Turn the illumination off completely for the dark reference.")
        driver.set_illumination(0.0)
        dark_dir = session.dark_dir()
        dark_stack = driver.grab(exposure_ms, repeats)
        frame_io.write_stack(dark_dir, dark_stack)
        dark_rel = session.relative(dark_dir)

        # Simulated drivers need the level as a relative flux; scale against the
        # largest requested level so the sweep spans the sensor's range.
        max_level = max((abs(float(value)) for value in levels), default=0.0) or 1.0

        for index, level in enumerate(levels):
            if progress:
                progress(index, len(levels), f"{level:g} {unit}")
            prompt(f"[{index + 1}/{len(levels)}] Set the illumination to {level:g} {unit}.")
            driver.set_illumination(float(level) / max_level)

            level_dir = session.level_dir(index, float(level), unit)
            stack = driver.grab(exposure_ms, repeats)
            frame_io.write_stack(level_dir, stack)

            session.add_level(
                LevelRecord(
                    index=index,
                    value=float(level),
                    unit=unit,
                    exposure_ms=exposure_ms,
                    frames=repeats,
                    directory=session.relative(level_dir),
                    dark_directory=dark_rel,
                )
            )

        return session

    # -- analysis --------------------------------------------------------

    def analyse(
        self,
        session: Session,
        prefs: Preferences,
        options: dict[str, Any],
    ) -> PTCResults:
        if not session.levels:
            raise ValueError(f"Session {session.path} contains no acquired levels")

        roi_spec = options.get("roi_spec") or prefs.active_roi()
        saturation_adu = int(
            options.get("saturation_adu") or prefs.get("analysis.saturation_adu")
        )

        # Shape comes from the first stack, so the ROI can be resolved without
        # trusting the recorded device dimensions.
        first_stack = frame_io.read_stack(session.resolve(session.levels[0].directory))
        roi = resolve_roi(roi_spec, first_stack.shape[-2:])

        warnings: list[str] = []
        points: list[PTCPoint] = []
        dark_cache: dict[str, StackStats] = {}

        for level in session.levels:
            bright_stack = frame_io.read_stack(session.resolve(level.directory))
            if bright_stack.shape[0] != level.frames:
                warnings.append(
                    f"Level {level.index}: expected {level.frames} frames, "
                    f"found {bright_stack.shape[0]}"
                )
            bright = stack_stats(roi.apply(bright_stack), saturation_adu)

            if level.dark_directory not in dark_cache:
                dark_stack = frame_io.read_stack(session.resolve(level.dark_directory))
                dark_cache[level.dark_directory] = stack_stats(
                    roi.apply(dark_stack), saturation_adu
                )
            dark = dark_cache[level.dark_directory]

            point = PTCPoint(
                index=level.index,
                value=level.value,
                unit=level.unit,
                exposure_ms=level.exposure_ms,
                bright=bright,
                dark=dark,
            )
            points.append(point)

        fit = fit_ptc(
            points,
            max_fraction=float(
                options.get("max_fraction")
                or prefs.get("analysis.fit_max_fraction_of_saturation")
            ),
            auto_detect_saturation=bool(prefs.get("analysis.auto_detect_saturation")),
            fit_range=options.get("fit_range"),
            saturation_adu=saturation_adu,
        )

        # A negative corrected variance is expected once pixels clip: the
        # bright frames flatten out and lose temporal noise. Below saturation
        # it means something is wrong with the dark reference, so only warn
        # about those.
        for point in points:
            # Ignore the dark level itself: it is the reference subtracted from
            # its own statistics, so it sits at zero within rounding.
            if abs(point.mean) < 1.0 and abs(point.variance) < 1.0:
                continue
            # Compare against the clipping flag, not the mean: once pixels
            # clip, the mean stops tracking illumination and can sit either
            # side of the estimated saturation signal.
            if (
                point.variance < 0
                and point.saturated_fraction <= 0.01
                and point.mean < fit.fit_limit
            ):
                warnings.append(
                    f"Level {point.index} ({point.value:g} {point.unit}): negative "
                    f"corrected variance ({point.variance:.1f} ADU²) below "
                    "saturation, so the dark set is noisier than the bright set. "
                    "Check the dark frames were taken at the same exposure."
                )

        if not fit.saturation_reached:
            warnings.append(
                "The sweep never reached saturation, so the saturation signal "
                f"({fit.mu_saturation:.0f} ADU) and full-well capacity "
                f"({fit.saturation_capacity_e:.0f} e-) are lower bounds, not "
                "measurements. Extend the exposure or illumination range to "
                "measure them."
            )

        if fit.r_squared < 0.99:
            warnings.append(
                f"Fit R^2 is {fit.r_squared:.4f}; the selected region may not be "
                "linear. Inspect the plot and consider --fit-range."
            )

        return PTCResults(
            points=points,
            fit=fit,
            roi=roi,
            roi_spec=roi_spec,
            mode=session.mode,
            unit=session.levels[0].unit,
            warnings=warnings,
        )

    # -- outputs ---------------------------------------------------------

    def write_outputs(
        self,
        session: Session,
        results: PTCResults,
        prefs: Preferences,
    ) -> list[Path]:
        csv_path = session.results_dir / "ptc.csv"
        write_ptc_csv(csv_path, results.points, results.fit)

        plot_path = session.results_dir / "ptc.png"
        plot_ptc(plot_path, results)

        return [csv_path, plot_path]


def _exposure_steps(prefs: Preferences, options: dict[str, Any]) -> list[float]:
    """Exposure values for a sweep, honouring CLI overrides."""
    start = float(options.get("start_ms") or prefs.get("exposure_sweep.start_ms"))
    stop = float(options.get("stop_ms") or prefs.get("exposure_sweep.stop_ms"))
    steps = int(options.get("steps") or prefs.get("exposure_sweep.steps"))
    spacing = options.get("spacing") or prefs.get("exposure_sweep.spacing")

    if steps < 2:
        raise ValueError(f"Need at least 2 exposure steps, got {steps}")
    if start <= 0 or stop <= 0:
        raise ValueError("Exposure times must be positive")
    if stop <= start:
        raise ValueError(f"stop_ms ({stop}) must exceed start_ms ({start})")

    if spacing == "log":
        values = np.geomspace(start, stop, steps)
    else:
        values = np.linspace(start, stop, steps)
    return [float(value) for value in values]
