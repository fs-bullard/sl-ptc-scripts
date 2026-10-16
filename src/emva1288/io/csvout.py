"""CSV serialisation of results."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..analysis.fitting import PTCFit
    from ..analysis.stats import PTCPoint

PTC_COLUMNS = [
    "index",
    "value",
    "unit",
    "exposure_ms",
    "mean_bright_adu",
    "var_bright_adu2",
    "mean_dark_adu",
    "var_dark_adu2",
    "mean_adu",
    "variance_adu2",
    "frames",
    "saturated_fraction",
    "in_fit",
]


def write_ptc_csv(path: Path, points: list["PTCPoint"], fit: "PTCFit") -> Path:
    """Write one row per measured level, flagging those used in the fit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    in_fit = set(fit.fit_indices)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PTC_COLUMNS)
        writer.writeheader()
        for point in points:
            row = point.to_row()
            row["in_fit"] = int(point.index in in_fit)
            writer.writerow(row)

    return path
