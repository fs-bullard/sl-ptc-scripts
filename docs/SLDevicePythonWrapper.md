# SLDevicePythonWrapper — API Reference

Handoff summary for an agent working in another project. Compiled from the binary's own embedded pybind11 docstrings plus verified working usage in this codebase.

## What it is

`SLDevicePythonWrapper` is a **pybind11 C++ extension** (`.pyd`) wrapping the Spectral Logic / SLDevice X-ray flat-panel detector SDK. Per its own module docstring:

> "The main Classes are SLDevice for interfacing with detectors and SLImage for image manipulation of captured frames. Many of the functions will return an SLError, SL_ERROR_SUCCESS indicates successful operation"

**Windows-only, CPython-version-locked.** It is a compiled binary — you cannot read its source. Introspect with `dir()` / `help()` at runtime.

### Runtime dependencies

These DLLs must sit beside the `.pyd`:

| File | Purpose |
|---|---|
| `SLDevicePythonWrapper.pyd` | The Python module |
| `SLDeviceLib.dll` | Core device/driver layer |
| `SLImage.dll` | Image stack + corrections |
| `SLDefectCorrection.dll` | Defect correction kernels |
| `SLHelperLibrary.dll` | Support |
| `MSVCP140.dll`, `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll` | MSVC runtime |

Not pip-installable. For PyInstaller, bundle all of the above as binaries.

## Error handling — the central idiom

**Most methods return an `SLError` enum rather than raising.** Unchecked return values are the single most common source of silent failure.

```python
from SLDevicePythonWrapper import SLError

err = device.OpenCamera()
if err != SLError.SL_ERROR_SUCCESS:
    raise RuntimeError(f"open failed: {err}")
```

Members: `SL_ERROR_SUCCESS`, `_NOT_FOUND` (device absent), `_NO_DEVICE`, `_DEVICE_CLOSED`, `_DEVICE_STREAMING`, `_TIMEOUT`, `_BUSY`, `_ACCESS`, `_INVALID_PARAM`, `_NOT_SUPPORTED`, `_NOT_INIT`, `_CONFIG_FAILED`, `_CONFIG_FILE_NOT_FOUND`, `_NOT_ENOUGH_MEMORY`, `_OVERFLOW`, `_IO`, `_READ_FAILED`, `_WRITE_FAILED`, `_PIPE`, `_MISSING_PACKETS`, `_RESENDS`, `_NOT_FILLED`, `_CORRECTION`, `_INTERRUPTED`, `_ABROTED` *(sic — the typo is in the library)*, `_ALREADY_EXISTS`, `_REQUIRES_ADMIN`, `_INTERNAL`, `_CRITICAL`, `_OTHER`.

Some getters instead return a **tuple** of `(SLError, value)` — e.g. `GetExposureTime`, `GetExposureMode`, `GetTestMode`, and the DDS and fan getters. Check `help()` before assuming a scalar return.

## Enums

```python
DeviceInterface.USB          # also EIO_USB; CameraLink / GigE-Pleora exist
ExposureModes.seq_mode       # sequence mode (verified in use)
FullWellModes.High / .Low    # dynamic range vs sensitivity
BinningModes.x11 / .x22 / .x44 / .BinningUnknown
ExposureTimeUnits            # Milliseconds, TenMicroseconds, (seconds)
```

`ExposureTimeUnits` matters: "ExposureTime units can be seconds, milliseconds or 10 microseconds." Getters may report **10-microsecond units** — the exposure getter docstring says it returns the "current exposure time setting in 10 microsecond units", which will not match the value you set in ms.

## SLDevice

Construct with an interface: `SLDevice(DeviceInterface.USB)`.

### Lifecycle

- `ScanCameras()` — "Scans connected detectors and returns all found devices into a SLDeviceInfo list"
- `OpenCamera(bufferDepth)` — "Opens the connection to the device an sets the number of buffers to use/allocate." `bufferDepth` is the on-device ring buffer size in frames.
- `CloseCamera()` — "Every open should be matched with a close to free resources."
- `IsConnected() -> bool`
- `SetPvcfgPath(path)` — Pleora only; "Call before OpenCamera."

### Configuration (set before streaming)

- `SetExposureMode(mode)` / `GetExposureMode()`
- `SetExposureTime(expTime)` / `GetExposureTime()`
- `SetFullWell(fullWell=...)` / `GetFullWell()`
- `SetNumberOfFrames(n)` / `GetNumberOfSequenceFrames()` — frames per trigger
- `SetBinningMode(bMode)` / `GetBinningMode()` / `Set1point5Binning()`
- `SetDDS(bool)` — double delta sampling
- `SetSkipFrames(numSkips)` — "frames to skip ... when detector goes into live mode"
- `SetTestMode(bool)` / `GetTestMode()` — "read FW defined test images instead of reading the actual sensor". **Useful for developing without hardware.**
- `SetROI(...)` / `GetROI()` → `ROIinfo`

### Acquisition

- `StartStream()` / `StopStream()` — "Every StartStream should be matched with a StopStream after all frames are captured."
- `SoftwareTrigger()`
- `AcquireImage(image, frame=n)` → `SLBufferInfo` (error is on `.error`)
- `GetLatestFrame(buf)` / `ReadFrame(buf)` — newest / oldest frame in the ring buffer
- `GetFrameCount()` — "Can be used to poll for increments to see when new frames arrive"
- `GoLiveWithAutoTrigger(thresholdADU)` — USB; "The device waits for the ADU to reach a relative threshold and then captures a sequence."
- `ForceAutoTrigger()` — "trigger the device autotrigger without requiring an ADU increase"
- `ClearFrameGrabberMemory(numberOfBuffers)` — CameraLink / Epix only

### Info, registers, temperature

- `GetModelInfo()` → `.Model`, `.Code`; `GetDeviceInfo()`; `GetFirmwareVersion()` (maj.min.rev format); `GetImageXDim()` / `GetImageYDim()`
- `RegisterRead(addr)` / `RegisterWrite(addr, value)` — "Max value may be device dependent and passing anything above this will result in undefined behavior."
- `MeasureTemperature(sensorNum)`, `NumTemperatureSensors`, `CalibrateTemperatureSensor(measuredTemp1, measuredTemp2, refTemp1, refTemp2)` — requires `refTemp1 != refTemp2` and `measuredTemp1 != measuredTemp2`, and `abs(dMeasured / dRef) < 128/363`.

## SLImage

A **stack of frames**, not a single 2D image — most calls take a frame/slice index.

### Construction

```python
SLImage(x_dim, y_dim, n_frames)   # blank, pre-built
SLImage(path)                     # load from file
SLImage.Array2Frame(np_uint16)    # from numpy
img.Frame2Array(0)                # -> numpy.ndarray[uint16]
```

### I/O

`ReadTiffImage`, `WriteTiffImage` ("Writes 2D uint16 numpy array 'image' to tiff file 'filename'"), `ReadRawImage` / `WriteRawImage` (`swapEndianness` flag; "the SLImage must already be built with correct dimensions"), `ReadBuffer`.

### Corrections

- `OffsetCorrection(darkMap, darkOffset)` — dark subtraction; `darkOffset` keeps values non-negative. "darkMap ... must have same dimensions as 'inImage'."
- `GainCorrection(fldImage, ...)` — flood / flat-field. Pre-mark the map with `SetAsGainMap()` "for faster gain correction".
- `DefectCorrection(defectMap)` / `KernelDefectCorrection(...)` — "5x5 mask kernel and weighed kernel". Pre-mark the map with `SetAsKernelDefectMap()`.
- `GenerateDefectMap(...)`
- Flags: `IsDarkCorrected()`, `IsGainCorrected()`, `IsDefectCorrected()`

### Stack ops and statistics

`GetAverageImage()` (temporal mean over slices), `GetMedianImage()`, `GetSubImage()`, sub-stack by slice range or index vector ("0-indexed vector of frame numbers. All frames must be in ascending order with no duplication"), delete last n slices, rotate 90/180/270 — note "Rotating 90 or 270 degrees changes the width and height of the image (mxn) -> (nxm) so in some cases it may be unwise to rotate your image in place" — and `GetMeanAndStdExcludingDefects()`, which "Excludes values <20 or >16000 as these are likely from defective pixels" and takes an optional `pRect` region.

## Canonical capture sequence

Verified working order — configuration **must** precede `StartStream`:

```python
device.SetExposureTime(exposure_ms)
device.SetNumberOfFrames(n_frames)
device.SetFullWell(fullWell=FullWellModes.High)
device.StartStream()
try:
    device.SoftwareTrigger()
    image = SLImage(x_dim, y_dim, n_frames)
    for i in range(n_frames):
        info = device.AcquireImage(image, frame=i)   # check info.error
finally:
    device.StopStream()                              # always pair with StartStream
```

Set `SetExposureMode(ExposureModes.seq_mode)` and `SetDDS(False)` once after `OpenCamera()`. Detector output is **14-bit in a uint16 container** (max 16383), so invert as `2**14 - arr` and clip corrections to `[0, 2**14 - 1]`.

## Gotchas

1. **Return values are error codes, not exceptions.** Wrap every call.
2. **`AcquireImage` returns `SLBufferInfo`** — the error is `.error`, not the return value itself.
3. **Some getters return tuples**, some scalars. Verify per method.
4. **The exposure getter reports 10µs units**, not the ms you set.
5. **Every `StartStream` needs a `StopStream`**, even on error — use `try/finally`.
6. **`SLImage` is a stack.** `Frame2Array(0)` gets the first frame only.
7. **Corrections require matching dimensions**, else `SL_ERROR_CORRECTION`.
8. **Rotation changes dimensions** for 90/270 — don't rotate in place.
9. `SL_ERROR_ABROTED` is misspelled in the library.
10. **No stubs or type hints.** Use `help(SLDevice)` at runtime.
11. **DLLs must be co-located** with the `.pyd`.

## Recommended wrapper pattern

Wrap it rather than calling directly — this isolates error checking and enables hardware-free testing via a fake implementing the same surface:

```python
class CameraDevice:
    def __init__(self, iface):
        self.device = SLDevice(iface)

    def _check(self, err, op):
        if err == SLError.SL_ERROR_NOT_FOUND:
            raise CameraNotConnectedError(f"Failed to {op}: not connected")
        if err != SLError.SL_ERROR_SUCCESS:
            raise CameraError(f"Failed to {op}: {err}")

    def open_camera(self):
        self._check(self.device.OpenCamera(), 'open camera')
```

`SetTestMode(True)` gives firmware-generated test images without a sensor.

## Verification note

Enum members, method names and all quoted text were extracted from the shipped binary's embedded docstrings; call sequences were taken from working code in this repo. The binary could not be imported on the machine where this was written, so the exact **arity and keyword names** of less-common methods are unconfirmed — check `help(SLDevice.MethodName)` at runtime before relying on a signature.
