"""Camera driver interface.

Every driver exposes the same small surface: open, configure, grab a stack of
frames, close. Drivers return raw, signal-positive uint16 arrays exactly as the
detector produced them -- no inversion, no dark correction. All EMVA processing
happens in the analysis layer so the on-disk frames stay a faithful record.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np


class CameraError(Exception):
    """A camera operation failed."""


class CameraNotConnectedError(CameraError):
    """No detector is connected."""


class FrameDropError(CameraError):
    """The detector delivered fewer frames than requested.

    Raised rather than returning a short stack: a dropped frame silently
    inflates the paired-difference variance and would corrupt the PTC.
    """


@dataclass
class DeviceInfo:
    """Identifying details recorded in the session metadata and report."""

    model: str = "unknown"
    code: str = ""
    firmware: str = ""
    serial: str = ""
    width: int = 0
    height: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "code": self.code,
            "firmware": self.firmware,
            "serial": self.serial,
            "width": self.width,
            "height": self.height,
            **({"extra": self.extra} if self.extra else {}),
        }


class CameraDriver(ABC):
    """Abstract detector."""

    #: Name used in preferences (`camera.driver`) and on the CLI.
    name: str = "base"

    @abstractmethod
    def open(self) -> None:
        """Open the device and apply one-time configuration."""

    @abstractmethod
    def close(self) -> None:
        """Release the device. Safe to call when already closed."""

    @abstractmethod
    def device_info(self) -> DeviceInfo:
        """Identifying details for the session record."""

    @abstractmethod
    def grab(self, exposure_ms: float, frames: int) -> np.ndarray:
        """Capture `frames` repetitions at `exposure_ms`.

        Returns a (frames, height, width) uint16 array. Raises FrameDropError
        if the detector delivered fewer frames than asked for.
        """

    def set_illumination(self, level: float) -> None:
        """Set the incident flux, where 0 means dark.

        Real detectors have no control over the light source -- the operator
        sets it when prompted -- so this is a no-op by default. Simulated
        drivers override it so an unattended run can model dark and bright
        acquisitions.
        """

    def __enter__(self) -> "CameraDriver":
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
