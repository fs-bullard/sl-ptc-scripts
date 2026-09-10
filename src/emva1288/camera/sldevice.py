"""Spectrum Logic SLDevice driver.

Wraps SLDevicePythonWrapper, whose methods return SLError codes rather than
raising. Every call is checked. The SDK's own OffsetCorrection is deliberately
not used: it does dark-image subtraction, which adds the dark frame's read
noise into the temporal variance. Dark handling is done statistically in the
analysis layer instead.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import numpy as np

from .base import (
    CameraDriver,
    CameraError,
    CameraNotConnectedError,
    DeviceInfo,
    FrameDropError,
)

_sdk: Any = None


def load_sdk(dll_dir: str | None = None) -> Any:
    """Import SLDevicePythonWrapper, adding its DLL directory first.

    The .pyd ships alongside DLLs it needs (SLDeviceLib, SLImage and the MSVC
    runtime). Python will not find those unless the directory is registered, so
    a bare import fails with "DLL load failed" even when the module is on the
    path.
    """
    global _sdk
    if _sdk is not None:
        return _sdk

    if dll_dir:
        directory = Path(dll_dir)
        if not directory.is_dir():
            raise CameraError(f"SDK DLL directory does not exist: {directory}")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(directory))
        # The .pyd itself may not be importable by name unless its directory is
        # also searched for modules.
        import sys

        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))

    try:
        import SLDevicePythonWrapper as sdk  # type: ignore[import-not-found]
    except ImportError as exc:
        raise CameraError(_import_help(exc, dll_dir)) from None

    _sdk = sdk
    return sdk


def _required_python(dll_dir: str | None) -> str | None:
    """The CPython version the extension was linked against, if discoverable.

    The .pyd embeds the name of the interpreter DLL it needs (e.g.
    python310.dll). A mismatch produces the same opaque "DLL load failed" as a
    genuinely missing dependency, so it is worth naming explicitly.
    """
    if not dll_dir:
        return None
    pyd = Path(dll_dir) / "SLDevicePythonWrapper.pyd"
    if not pyd.exists():
        return None
    try:
        import re

        match = re.search(rb"python3([0-9]{1,2})\.dll", pyd.read_bytes(), re.IGNORECASE)
    except OSError:
        return None
    return f"3.{match.group(1).decode()}" if match else None


def _import_help(exc: Exception, dll_dir: str | None) -> str:
    """Build an actionable message for an import failure."""
    import sys

    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    required = _required_python(dll_dir)

    if required and required != running:
        return (
            f"SLDevicePythonWrapper was built for Python {required}, but this "
            f"is Python {running}. The extension cannot be loaded by a "
            f"different version. Install Python {required} and run the tool "
            f"with it (or use --driver mock to work without hardware)."
        )
    return (
        f"Could not import SLDevicePythonWrapper ({exc}). Check sdk.dll_dir "
        f"points at the folder holding the .pyd and its DLLs (SLDeviceLib.dll, "
        f"SLImage.dll, SLDefectCorrection.dll, SLHelperLibrary.dll and the MSVC "
        f"runtime), and that they match Python {running} (x64)."
    )


class SLDeviceDriver(CameraDriver):
    """Real detector via the vendor SDK."""

    name = "sldevice"

    def __init__(
        self,
        dll_dir: str | None = None,
        interface: str = "USB",
        full_well: str = "High",
        dds: bool = False,
        buffer_depth: int = 10,
        binning: str = "x11",
        test_mode: bool = False,
        settle_seconds: float = 0.0,
    ):
        self.dll_dir = dll_dir
        self.interface_name = interface
        self.full_well_name = full_well
        self.dds = dds
        self.buffer_depth = buffer_depth
        self.binning_name = binning
        self.test_mode = test_mode
        self.settle_seconds = settle_seconds

        self._sdk: Any = None
        self._device: Any = None
        self._opened = False
        self._width = 0
        self._height = 0

    @classmethod
    def from_prefs(cls, prefs: Any) -> "SLDeviceDriver":
        return cls(
            dll_dir=prefs.get("sdk.dll_dir"),
            interface=prefs.get("sdk.interface"),
            full_well=prefs.get("camera.full_well"),
            dds=prefs.get("camera.dds"),
            buffer_depth=prefs.get("camera.buffer_depth"),
            binning=prefs.get("camera.binning"),
            test_mode=prefs.get("camera.test_mode"),
            settle_seconds=prefs.get("capture.settle_seconds"),
        )

    # -- error handling --------------------------------------------------

    def _check(self, err: Any, operation: str) -> None:
        """Raise if an SLError is anything other than success."""
        sdk = self._sdk
        if err == sdk.SLError.SL_ERROR_SUCCESS:
            return
        if err == sdk.SLError.SL_ERROR_NOT_FOUND:
            raise CameraNotConnectedError(f"Failed to {operation}: detector not connected")
        raise CameraError(f"Failed to {operation}: {err}")

    def _enum(self, enum_name: str, member: str, label: str) -> Any:
        enum_type = getattr(self._sdk, enum_name)
        try:
            return getattr(enum_type, member)
        except AttributeError:
            available = [n for n in dir(enum_type) if not n.startswith("_")]
            raise CameraError(
                f"Unknown {label} {member!r}; available: {', '.join(available)}"
            ) from None

    # -- lifecycle -------------------------------------------------------

    def open(self) -> None:
        self._sdk = load_sdk(self.dll_dir)
        sdk = self._sdk

        interface = self._enum("DeviceInterface", self.interface_name, "device interface")
        self._device = sdk.SLDevice(interface)

        self._check(self._device.OpenCamera(self.buffer_depth), "open camera")
        self._opened = True

        try:
            self._check(
                self._device.SetExposureMode(sdk.ExposureModes.seq_mode),
                "set exposure mode",
            )
            self._check(self._device.SetDDS(self.dds), "set DDS")
            if self.binning_name != "x11":
                binning = self._enum("BinningModes", self.binning_name, "binning mode")
                self._check(self._device.SetBinningMode(binning), "set binning mode")
            if self.test_mode:
                self._check(self._device.SetTestMode(True), "enable test mode")

            self._width = self._device.GetImageXDim()
            self._height = self._device.GetImageYDim()
            if self._width <= 0 or self._height <= 0:
                raise CameraError(
                    f"Detector reported an invalid frame size: {self._width}x{self._height}"
                )
        except Exception:
            # Leave no half-configured device open behind us.
            self.close()
            raise

    def close(self) -> None:
        if self._device is not None and self._opened:
            try:
                self._device.CloseCamera()
            finally:
                self._opened = False
        self._device = None

    def device_info(self) -> DeviceInfo:
        if self._device is None:
            raise CameraError("Device is not open")
        model_info = self._device.GetModelInfo()
        return DeviceInfo(
            model=str(getattr(model_info, "Model", "unknown")),
            code=str(getattr(model_info, "Code", "")),
            firmware=str(self._device.GetFirmwareVersion()),
            width=self._width,
            height=self._height,
            extra={
                "interface": self.interface_name,
                "full_well": self.full_well_name,
                "binning": self.binning_name,
                "dds": self.dds,
                "test_mode": self.test_mode,
            },
        )

    # -- acquisition -----------------------------------------------------

    @staticmethod
    def quantise_exposure(exposure_ms: float) -> int:
        """Round to the whole milliseconds the detector actually accepts.

        A linear sweep produces fractional steps, but SetExposureTime takes an
        integer. Quantising here (and recording the quantised value) keeps the
        stored exposure equal to the one the detector used.
        """
        return max(1, int(round(exposure_ms)))

    def grab(self, exposure_ms: float, frames: int) -> np.ndarray:
        if self._device is None or not self._opened:
            raise CameraError("Device is not open")

        sdk = self._sdk
        device = self._device
        full_well = self._enum("FullWellModes", self.full_well_name, "full well mode")

        # Configuration must precede StartStream. SetExposureTime takes whole
        # milliseconds, so round rather than letting a fractional sweep step
        # fail the pybind11 overload resolution.
        exposure_ms = self.quantise_exposure(exposure_ms)

        self._check(device.SetExposureTime(int(exposure_ms)), "set exposure time")
        self._check(device.SetNumberOfFrames(frames), "set number of frames")
        self._check(device.SetFullWell(fullWell=full_well), "set full well mode")

        if self.settle_seconds:
            time.sleep(self.settle_seconds)

        self._check(device.StartStream(), "start stream")
        try:
            image = sdk.SLImage(self._width, self._height, frames)
            self._check(device.SoftwareTrigger(), "send software trigger")

            for index in range(frames):
                # The detector free-runs the sequence; wait out the integration
                # before pulling each frame from the ring buffer.
                time.sleep(exposure_ms / 1000.0)
                buffer_info = device.AcquireImage(image, frame=index)
                self._check(buffer_info.error, f"acquire frame {index}")

            self._verify_frame_count(device, frames)

            stack = np.empty((frames, self._height, self._width), dtype=np.uint16)
            for index in range(frames):
                stack[index] = image.Frame2Array(index)
        finally:
            # Every StartStream must be matched, including on the error path.
            device.StopStream()

        return stack

    def _verify_frame_count(self, device: Any, expected: int) -> None:
        """Fail loudly on dropped frames rather than yielding a corrupt PTC."""
        try:
            result = device.GetFrameCount()
        except Exception:
            return  # Not all interfaces expose a usable counter.

        # GetFrameCount returns (SLError, count), not a bare integer.
        if isinstance(result, tuple):
            if len(result) != 2 or result[0] != self._sdk.SLError.SL_ERROR_SUCCESS:
                return
            delivered = result[1]
        else:
            delivered = result

        if isinstance(delivered, int) and 0 < delivered < expected:
            raise FrameDropError(
                f"Detector delivered {delivered} of {expected} frames. "
                "Dropped frames inflate the measured temporal variance; "
                "increase camera.buffer_depth or lengthen the exposure."
            )

    def scan(self) -> list[str]:
        """Enumerate connected detectors."""
        sdk = load_sdk(self.dll_dir)
        try:
            # ScanCameras is a static method; constructing an SLDevice purely
            # to call it leaves an object whose teardown at interpreter exit
            # faults inside the native library.
            found = sdk.SLDevice.ScanCameras()
        except Exception as exc:
            raise CameraError(f"Failed to scan for detectors: {exc}") from None

        results = []
        for item in found or []:
            model = getattr(item, "Model", None)
            serial = getattr(item, "SerialNumber", None) or getattr(item, "Serial", None)
            if model:
                results.append(f"{model}" + (f"  serial {serial}" if serial else ""))
            else:
                results.append(str(item))
        return results
