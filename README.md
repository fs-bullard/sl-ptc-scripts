# EMVA 1288 sensor characterisation

Command line tool for characterising Spectrum Logic detectors to the EMVA 1288
standard. Currently implements the **photon transfer curve** (temporal variance
against mean signal); the test-script library is structured so further
measurements slot in beside it.

## Install

```powershell
python -m pip install -e .
```

The vendor SDK (`SLDevicePythonWrapper.pyd` and its DLLs) is installed
separately -- point `sdk.dll_dir` at the folder containing it. The tool runs
without the SDK using the `mock` driver.

## Quick start

```powershell
emva1288 config init                       # write a preferences file
emva1288 config set save_path D:/emva-data
emva1288 devices                           # check the detector is seen

emva1288 capture ptc                       # acquire, analyse and report
```

To try the whole pipeline with no hardware:

```powershell
emva1288 capture ptc --driver mock --yes
```

## How the measurement works

Temporal variance is measured from **differences of frame pairs**, per EMVA 1288
§6:

    sigma^2 = var(A - B) / 2

Differencing cancels fixed spatial patterns (DSNU and PRNU), leaving only
temporal noise. Dark correction subtracts the dark set's **statistics**, not the
dark image:

    mu       = mu_bright - mu_dark
    sigma^2  = sigma^2_bright - sigma^2_dark

Subtracting a dark frame pixel-by-pixel would add its read noise to the result
instead of removing it.

The linear region (up to 70% of saturation by default, with saturated points
always excluded) is fitted by least squares. The slope is the **system gain K**
in ADU per electron.

### Two acquisition modes

| Mode | What varies | Operator involvement |
|---|---|---|
| `--mode exposure` *(default)* | exposure time, fixed illumination | none -- fully automated |
| `--mode illumination` | LED level, fixed exposure | prompted at each level |

Exposure-sweep mode captures a dark set at every exposure, because dark signal
and its noise both scale with integration time. Illumination mode captures one
dark set at the start.

## Commands

```
emva1288 config list | get <key> | set <key> <value> | init | edit | path
emva1288 config roi list | show | add | use | remove
emva1288 devices                     scan for detectors
emva1288 tests                       list available test scripts
emva1288 capture ptc [options]       acquire, then analyse and report
emva1288 analyse <session> [--roi] [--fit-range LOW HIGH]
emva1288 report  <session> [--open]
```

`analyse` and `report` never touch the camera, so any stored session can be
re-processed with a different ROI or fit range.

## Session layout

```
<save_path>/<stem>_<timestamp>/
    session.json              settings, detector info, level index
    dark_000_20ms/            frame_000.tif ... (dark set)
    level_000_20ms/           frame_000.tif ... (bright set)
    ...
    results/                  ptc.csv, ptc.png, report.pdf
```

Frames are stored raw, exactly as the detector produced them. Everything else
is derived and can be regenerated.

## ROI presets

Statistics are computed over a region of interest, applied at analysis time.
The default is the centre 50%, which avoids panel edge artefacts.

```powershell
emva1288 config roi add centre80 --centre-fraction 0.8 --use
emva1288 config roi add patch --x0 100 --y0 100 --width 256 --height 256
emva1288 analyse <session> --roi patch
emva1288 analyse <session> --roi 0,0,512,512        # one-off, no preset
```

## Preferences

JSON at `%APPDATA%\emva1288\preferences.json`, overridable with `--config` or
the `EMVA1288_CONFIG` environment variable. Edit via `config set` (validated,
dotted keys) or `config edit`.

## Adding a test script

Subclass `TestScript`, implement `acquire`, `analyse` and `write_outputs`, and
decorate with `@register` in `src/emva1288/tests/`. The CLI, preferences,
storage and report scaffolding pick it up automatically.

## Tests

```powershell
python -m pytest
```

The suite verifies the analysis against a simulated detector built from the EMVA
sensor model with a **known** system gain and read noise, so a correct pipeline
must recover them.
