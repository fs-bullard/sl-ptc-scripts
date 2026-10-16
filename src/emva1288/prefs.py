"""Preferences: JSON-backed settings with dotted-key access and validation.

The file lives at %APPDATA%/emva1288/preferences.json unless overridden by the
EMVA1288_CONFIG environment variable or an explicit path. Unknown keys are
rejected so a typo in `config set` fails loudly instead of being silently
stored and ignored.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

CONFIG_ENV_VAR = "EMVA1288_CONFIG"

DEFAULTS: dict[str, Any] = {
    "save_path": "C:/emva1288-data",
    "stem": "ptc",
    "sdk": {
        "dll_dir": "C:/SLDevice/SDK/dll/x64/Release",
        "interface": "USB",
    },
    "camera": {
        "driver": "sldevice",
        "full_well": "High",
        "dds": False,
        "bit_depth": 14,
        "buffer_depth": 10,
        "binning": "x11",
        "test_mode": False,
    },
    "capture": {
        "exposure_ms": 100,
        "repeats": 10,
        "settle_seconds": 0.5,
    },
    "roi": {
        "active": "centre50",
        "presets": {
            "full": {"mode": "full"},
            "centre50": {"mode": "centre_fraction", "fraction": 0.5},
            "centre25": {"mode": "centre_fraction", "fraction": 0.25},
        },
    },
    "illumination": {
        "unit": "mA",
        "levels": [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
    },
    "exposure_sweep": {
        "start_ms": 10,
        "stop_ms": 1000,
        "steps": 15,
        "spacing": "linear",
    },
    "analysis": {
        "fit_max_fraction_of_saturation": 0.7,
        "auto_detect_saturation": True,
        "saturation_adu": 16383,
    },
    "report": {
        "title": "EMVA 1288 Sensor Report",
        "author": "",
    },
}

# Dotted key -> (type, validator or None). Keys under roi.presets are dynamic
# and validated separately by the ROI helpers.
_SCHEMA: dict[str, type] = {
    "save_path": str,
    "stem": str,
    "sdk.dll_dir": str,
    "sdk.interface": str,
    "camera.driver": str,
    "camera.full_well": str,
    "camera.dds": bool,
    "camera.bit_depth": int,
    "camera.buffer_depth": int,
    "camera.binning": str,
    "camera.test_mode": bool,
    "capture.exposure_ms": float,
    "capture.repeats": int,
    "capture.settle_seconds": float,
    "roi.active": str,
    "illumination.unit": str,
    "illumination.levels": list,
    "exposure_sweep.start_ms": float,
    "exposure_sweep.stop_ms": float,
    "exposure_sweep.steps": int,
    "exposure_sweep.spacing": str,
    "analysis.fit_max_fraction_of_saturation": float,
    "analysis.auto_detect_saturation": bool,
    "analysis.saturation_adu": int,
    "report.title": str,
    "report.author": str,
}

_CHOICES: dict[str, tuple[str, ...]] = {
    "camera.driver": ("sldevice", "mock", "folder"),
    "camera.full_well": ("High", "Low"),
    "camera.binning": ("x11", "x22", "x44"),
    # Members of SLDevicePythonWrapper.DeviceInterface.
    "sdk.interface": ("USB", "EIO_USB", "CL", "S2I_GIGE", "PLEORA"),
    "exposure_sweep.spacing": ("linear", "log"),
}


class PreferencesError(Exception):
    """Raised for an invalid key, value or preferences file."""


def default_config_path() -> Path:
    """Location of the preferences file, honouring EMVA1288_CONFIG."""
    override = os.environ.get(CONFIG_ENV_VAR)
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    return Path(base) / "emva1288" / "preferences.json"


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Overlay onto base recursively; overlay wins for non-dict values."""
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _coerce(key: str, raw: Any) -> Any:
    """Coerce a value to the schema type for `key`, raising on mismatch."""
    expected = _SCHEMA.get(key)
    if expected is None:
        raise PreferencesError(f"Unknown preference key: {key}")

    if isinstance(raw, str):
        text = raw.strip()
        if expected is bool:
            lowered = text.lower()
            if lowered in ("true", "yes", "1", "on"):
                value: Any = True
            elif lowered in ("false", "no", "0", "off"):
                value = False
            else:
                raise PreferencesError(f"{key}: expected a boolean, got {raw!r}")
        elif expected is int:
            try:
                value = int(text, 10)
            except ValueError:
                raise PreferencesError(f"{key}: expected an integer, got {raw!r}") from None
        elif expected is float:
            try:
                value = float(text)
            except ValueError:
                raise PreferencesError(f"{key}: expected a number, got {raw!r}") from None
        elif expected is list:
            value = _parse_list(key, text)
        else:
            value = text
    else:
        value = raw
        if expected is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        # bool is a subclass of int, so check it before the int branch.
        if expected is not bool and isinstance(value, bool):
            raise PreferencesError(f"{key}: expected {expected.__name__}, got a boolean")
        if not isinstance(value, expected):
            raise PreferencesError(
                f"{key}: expected {expected.__name__}, got {type(value).__name__}"
            )

    choices = _CHOICES.get(key)
    if choices and value not in choices:
        raise PreferencesError(f"{key}: must be one of {', '.join(choices)} (got {value!r})")
    return value


def _parse_list(key: str, text: str) -> list:
    """Parse a list from JSON or a comma-separated string."""
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PreferencesError(f"{key}: invalid JSON list ({exc})") from None
        if not isinstance(parsed, list):
            raise PreferencesError(f"{key}: expected a list")
        return parsed
    items = [part.strip() for part in text.split(",") if part.strip()]
    out: list = []
    for item in items:
        try:
            out.append(int(item))
        except ValueError:
            try:
                out.append(float(item))
            except ValueError:
                out.append(item)
    return out


class Preferences:
    """Mutable preferences backed by a JSON file."""

    def __init__(self, data: dict[str, Any], path: Path):
        self.data = data
        self.path = path

    @classmethod
    def load(cls, path: Path | None = None) -> "Preferences":
        """Load preferences, filling in defaults for anything absent."""
        path = Path(path) if path else default_config_path()
        if path.exists():
            try:
                stored = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise PreferencesError(f"Invalid JSON in {path}: {exc}") from None
            if not isinstance(stored, dict):
                raise PreferencesError(f"{path}: expected a JSON object at the top level")
            data = _deep_merge(DEFAULTS, stored)
        else:
            data = copy.deepcopy(DEFAULTS)
        return cls(data, path)

    def save(self) -> Path:
        """Write preferences to disk, creating parent directories."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")
        return self.path

    def get(self, key: str) -> Any:
        """Fetch a value by dotted key."""
        node: Any = self.data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                raise PreferencesError(f"Unknown preference key: {key}")
            node = node[part]
        return node

    def set(self, key: str, raw: Any) -> Any:
        """Validate and store a value by dotted key. Returns the stored value."""
        value = _coerce(key, raw)
        parts = key.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        return value

    def flatten(self) -> dict[str, Any]:
        """All settings as dotted keys, for display."""
        out: dict[str, Any] = {}

        def walk(node: Any, prefix: str) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    walk(value, f"{prefix}.{key}" if prefix else key)
            else:
                out[prefix] = node

        walk(self.data, "")
        return out

    # -- ROI presets -----------------------------------------------------

    def roi_presets(self) -> dict[str, dict]:
        return self.data["roi"]["presets"]

    def active_roi(self) -> dict:
        """The currently selected ROI preset."""
        name = self.data["roi"]["active"]
        presets = self.roi_presets()
        if name not in presets:
            raise PreferencesError(
                f"Active ROI preset {name!r} is not defined. "
                f"Available: {', '.join(sorted(presets)) or 'none'}"
            )
        return presets[name]

    def set_roi_preset(self, name: str, spec: dict) -> None:
        validate_roi_spec(spec)
        self.roi_presets()[name] = spec

    def remove_roi_preset(self, name: str) -> None:
        presets = self.roi_presets()
        if name not in presets:
            raise PreferencesError(f"No such ROI preset: {name}")
        if self.data["roi"]["active"] == name:
            raise PreferencesError(
                f"Cannot remove {name!r} while it is the active ROI; "
                "select another preset first"
            )
        del presets[name]

    def use_roi_preset(self, name: str) -> None:
        if name not in self.roi_presets():
            raise PreferencesError(f"No such ROI preset: {name}")
        self.data["roi"]["active"] = name


def validate_roi_spec(spec: dict) -> None:
    """Check an ROI preset is well formed, raising PreferencesError if not."""
    if not isinstance(spec, dict) or "mode" not in spec:
        raise PreferencesError("ROI spec must be an object with a 'mode' field")
    mode = spec["mode"]
    if mode == "full":
        return
    if mode == "centre_fraction":
        fraction = spec.get("fraction")
        if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
            raise PreferencesError("centre_fraction ROI needs a numeric 'fraction'")
        if not 0 < fraction <= 1:
            raise PreferencesError("ROI fraction must be in (0, 1]")
        return
    if mode == "rect":
        for field in ("x0", "y0", "width", "height"):
            value = spec.get(field)
            if not isinstance(value, int) or isinstance(value, bool):
                raise PreferencesError(f"rect ROI needs an integer '{field}'")
        if spec["width"] <= 0 or spec["height"] <= 0:
            raise PreferencesError("rect ROI width and height must be positive")
        if spec["x0"] < 0 or spec["y0"] < 0:
            raise PreferencesError("rect ROI x0 and y0 must be non-negative")
        return
    raise PreferencesError(f"Unknown ROI mode: {mode!r} (use full, centre_fraction or rect)")
