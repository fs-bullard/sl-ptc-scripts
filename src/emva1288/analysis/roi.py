"""Resolving ROI specifications against a frame shape."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..prefs import PreferencesError, validate_roi_spec


@dataclass(frozen=True)
class Rect:
    """A concrete pixel rectangle."""

    x0: int
    y0: int
    width: int
    height: int

    @property
    def slices(self) -> tuple[slice, slice]:
        """Numpy slices in (row, column) order."""
        return (
            slice(self.y0, self.y0 + self.height),
            slice(self.x0, self.x0 + self.width),
        )

    def apply(self, array: np.ndarray) -> np.ndarray:
        """Crop a 2D array (or a stack's trailing 2 axes) to this rectangle."""
        rows, cols = self.slices
        return array[..., rows, cols]

    def to_dict(self) -> dict:
        return {"x0": self.x0, "y0": self.y0, "width": self.width, "height": self.height}


def resolve_roi(spec: dict, shape: tuple[int, int]) -> Rect:
    """Turn an ROI spec into a Rect for a frame of `shape` (height, width)."""
    validate_roi_spec(spec)
    height, width = shape
    mode = spec["mode"]

    if mode == "full":
        return Rect(0, 0, width, height)

    if mode == "centre_fraction":
        fraction = float(spec["fraction"])
        # Round to even so paired-difference maths stays symmetric about centre.
        roi_w = max(1, int(round(width * fraction)))
        roi_h = max(1, int(round(height * fraction)))
        return Rect((width - roi_w) // 2, (height - roi_h) // 2, roi_w, roi_h)

    # mode == "rect"
    rect = Rect(int(spec["x0"]), int(spec["y0"]), int(spec["width"]), int(spec["height"]))
    if rect.x0 + rect.width > width or rect.y0 + rect.height > height:
        raise PreferencesError(
            f"ROI {rect.x0},{rect.y0} {rect.width}x{rect.height} "
            f"does not fit in a {width}x{height} frame"
        )
    return rect


def parse_roi_argument(text: str) -> dict:
    """Parse a CLI ROI argument: a preset name is handled by the caller, while
    'x0,y0,width,height' and 'centre:0.5' produce a spec here."""
    text = text.strip()
    if text.lower().startswith("centre:") or text.lower().startswith("center:"):
        _, _, value = text.partition(":")
        try:
            fraction = float(value)
        except ValueError:
            raise PreferencesError(f"Invalid centre fraction: {value!r}") from None
        return {"mode": "centre_fraction", "fraction": fraction}

    parts = [part.strip() for part in text.split(",")]
    if len(parts) == 4:
        try:
            x0, y0, width, height = (int(part) for part in parts)
        except ValueError:
            raise PreferencesError(f"Invalid ROI rectangle: {text!r}") from None
        return {"mode": "rect", "x0": x0, "y0": y0, "width": width, "height": height}

    raise PreferencesError(
        f"Cannot parse ROI {text!r}; expected a preset name, "
        "'x0,y0,width,height' or 'centre:<fraction>'"
    )
