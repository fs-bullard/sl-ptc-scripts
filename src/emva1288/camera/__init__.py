"""Camera drivers."""

from __future__ import annotations

from typing import Any

from .base import (
    CameraDriver,
    CameraError,
    CameraNotConnectedError,
    DeviceInfo,
    FrameDropError,
)


def create_driver(name: str, prefs: Any) -> CameraDriver:
    """Instantiate a driver by name, importing it lazily.

    The SLDevice driver is imported only when asked for, so the tool runs on a
    machine with no SDK or detector present.
    """
    if name == "mock":
        from .mock import MockDriver

        return MockDriver.from_prefs(prefs)
    if name == "sldevice":
        from .sldevice import SLDeviceDriver

        return SLDeviceDriver.from_prefs(prefs)
    if name == "folder":
        from .folder import FolderDriver

        return FolderDriver.from_prefs(prefs)
    raise CameraError(f"Unknown camera driver: {name!r} (use sldevice, mock or folder)")


__all__ = [
    "CameraDriver",
    "CameraError",
    "CameraNotConnectedError",
    "DeviceInfo",
    "FrameDropError",
    "create_driver",
]
