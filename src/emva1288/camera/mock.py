"""Synthetic detector with known ground-truth parameters.

Lets the whole pipeline -- capture, storage, analysis, fit, report -- run and be
verified without hardware. The generated frames follow the EMVA 1288 sensor
model, so a correct analysis recovers `system_gain` from the PTC slope.

Signal model per pixel, in ADU:

    y = offset + K * (photoelectrons + dark electrons) + read noise

where photoelectrons ~ Poisson(mu_e), scaled per pixel by PRNU, and the offset
carries a fixed DSNU pattern. Response clips at `saturation_adu`, which is what
makes the PTC turn over at the top end.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .base import CameraDriver, DeviceInfo


class MockDriver(CameraDriver):
    """Simulated 14-bit detector."""

    name = "mock"

    def __init__(
        self,
        width: int = 256,
        height: int = 256,
        system_gain: float = 0.25,
        read_noise_e: float = 30.0,
        offset_adu: float = 200.0,
        dark_current_e_per_ms: float = 5.0,
        saturation_adu: int = 16383,
        prnu: float = 0.01,
        dsnu_adu: float = 3.0,
        # Chosen so the default 10-1000 ms sweep crosses saturation near its
        # top end: at 1000 ms this fills ~65k e-, which is 16383 ADU at K=0.25.
        photons_per_ms: float = 70.0,
        illumination: float = 1.0,
        seed: int | None = 12345,
    ):
        self.width = width
        self.height = height
        self.system_gain = system_gain
        self.read_noise_e = read_noise_e
        self.offset_adu = offset_adu
        self.dark_current_e_per_ms = dark_current_e_per_ms
        self.saturation_adu = saturation_adu
        self.photons_per_ms = photons_per_ms
        #: Scales the incident flux; the capture layer sets this to model an
        #: LED level, leaving it at 0 for dark frames.
        self.illumination = illumination
        self._rng = np.random.default_rng(seed)
        self._opened = False

        shape = (height, width)
        pattern_rng = np.random.default_rng(0 if seed is None else seed + 1)
        #: Fixed-pattern gain and offset. These are frozen for the life of the
        #: driver, so paired differencing cancels them exactly as on real
        #: hardware.
        self._prnu_map = 1.0 + prnu * pattern_rng.standard_normal(shape)
        self._dsnu_map = dsnu_adu * pattern_rng.standard_normal(shape)

    @classmethod
    def from_prefs(cls, prefs: Any) -> "MockDriver":
        mock_cfg = prefs.data.get("mock", {})
        return cls(
            saturation_adu=prefs.get("analysis.saturation_adu"),
            **{k: v for k, v in mock_cfg.items() if k != "saturation_adu"},
        )

    def open(self) -> None:
        self._opened = True

    def close(self) -> None:
        self._opened = False

    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            model="MockDetector",
            code="MOCK",
            firmware="0.0.0",
            serial="SIMULATED",
            width=self.width,
            height=self.height,
            extra={
                "ground_truth": {
                    "system_gain_adu_per_e": self.system_gain,
                    "read_noise_e": self.read_noise_e,
                    "offset_adu": self.offset_adu,
                    "dark_current_e_per_ms": self.dark_current_e_per_ms,
                }
            },
        )

    def set_illumination(self, level: float) -> None:
        """Set the relative incident flux (0 for dark)."""
        self.illumination = float(level)

    def grab(self, exposure_ms: float, frames: int) -> np.ndarray:
        shape = (frames, self.height, self.width)

        mean_photo_e = self.photons_per_ms * exposure_ms * self.illumination
        mean_dark_e = self.dark_current_e_per_ms * exposure_ms

        # Shot noise on signal and dark current. PRNU scales the signal only,
        # matching the physical picture of per-pixel sensitivity variation.
        signal_e = self._rng.poisson(mean_photo_e, size=shape) * self._prnu_map
        dark_e = self._rng.poisson(mean_dark_e, size=shape)

        read_e = self._rng.normal(0.0, self.read_noise_e, size=shape)

        adu = (
            self.offset_adu
            + self._dsnu_map
            + self.system_gain * (signal_e + dark_e + read_e)
        )
        # Quantise, then clip: saturation is a hard rail at the ADC top end.
        adu = np.rint(adu)
        np.clip(adu, 0, self.saturation_adu, out=adu)
        return adu.astype(np.uint16)
