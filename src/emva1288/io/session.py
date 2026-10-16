"""Session folder layout and metadata.

A session is a self-contained, re-analysable record of one acquisition:

    <save_path>/<stem>_<YYYYmmdd-HHMMSS>/
        session.json                  metadata, settings, level index
        dark/                         dark frames (illumination mode)
        dark_000_100ms/               per-exposure darks (exposure mode)
        level_000_50mA/               frames at one illumination level
        results/                      ptc.csv, ptc.png, report.pdf

Frames are stored raw, exactly as the detector produced them. Every derived
quantity is recomputed from these by `analyse`, so a session can be re-analysed
with a different ROI or fit range without re-acquiring.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

SESSION_FILE = "session.json"
RESULTS_DIR = "results"


def _slug(value: Any) -> str:
    """Filesystem-safe fragment for a level label."""
    text = str(value).strip().replace(" ", "")
    text = re.sub(r"[^A-Za-z0-9._+-]", "_", text)
    return text or "level"


@dataclass
class LevelRecord:
    """One acquired point on the curve."""

    index: int
    #: Illumination value (illumination mode) or exposure in ms (exposure mode).
    value: float
    unit: str
    exposure_ms: float
    frames: int
    directory: str
    #: Directory of the dark set this level is corrected against.
    dark_directory: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Session:
    """Metadata for one acquisition run."""

    path: Path
    test: str = "ptc"
    mode: str = "exposure"
    created: str = ""
    stem: str = "ptc"
    exposure_ms: float = 0.0
    repeats: int = 0
    illumination_unit: str = "mA"
    fixed_illumination: float | None = None
    device: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    levels: list[LevelRecord] = field(default_factory=list)

    # -- creation --------------------------------------------------------

    @classmethod
    def create(
        cls,
        save_path: Path,
        stem: str,
        test: str,
        mode: str,
        **kwargs: Any,
    ) -> "Session":
        """Make a new timestamped session directory."""
        timestamp = datetime.now()
        directory = Path(save_path) / f"{stem}_{timestamp:%Y%m%d-%H%M%S}"
        directory.mkdir(parents=True, exist_ok=False)
        session = cls(
            path=directory,
            test=test,
            mode=mode,
            created=timestamp.isoformat(timespec="seconds"),
            stem=stem,
            **kwargs,
        )
        session.save()
        return session

    @classmethod
    def load(cls, path: Path) -> "Session":
        """Load an existing session directory."""
        path = Path(path)
        meta_path = path / SESSION_FILE
        if not meta_path.exists():
            raise FileNotFoundError(
                f"{path} is not a session directory (no {SESSION_FILE})"
            )
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        levels = [LevelRecord(**item) for item in data.pop("levels", [])]
        data.pop("path", None)
        return cls(path=path, levels=levels, **data)

    def save(self) -> Path:
        """Write session.json."""
        data = {
            key: value
            for key, value in asdict(self).items()
            if key not in ("path", "levels")
        }
        data["levels"] = [level.to_dict() for level in self.levels]
        meta_path = self.path / SESSION_FILE
        meta_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return meta_path

    # -- layout ----------------------------------------------------------

    @property
    def results_dir(self) -> Path:
        directory = self.path / RESULTS_DIR
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def dark_dir(self, index: int | None = None, exposure_ms: float | None = None) -> Path:
        """Directory for a dark set.

        A single shared dark set in illumination mode; one per exposure in
        exposure-sweep mode, since dark signal scales with integration time.
        """
        if index is None:
            return self.path / "dark"
        return self.path / f"dark_{index:03d}_{_slug(f'{exposure_ms:g}ms')}"

    def level_dir(self, index: int, value: float, unit: str) -> Path:
        return self.path / f"level_{index:03d}_{_slug(f'{value:g}{unit}')}"

    def add_level(self, record: LevelRecord) -> None:
        self.levels.append(record)
        self.save()

    def relative(self, path: Path) -> str:
        """Store paths relative to the session so a folder stays portable."""
        return str(Path(path).relative_to(self.path).as_posix())

    def resolve(self, relative_path: str) -> Path:
        return self.path / relative_path
