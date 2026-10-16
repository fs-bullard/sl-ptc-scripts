"""Reading and writing 16-bit TIFF frames."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import tifffile


def write_frame(path: Path, array: np.ndarray) -> None:
    """Write a single 2D frame as a 16-bit TIFF."""
    if array.ndim != 2:
        raise ValueError(f"Expected a 2D frame, got shape {array.shape}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(str(path), array.astype(np.uint16, copy=False))


def write_stack(directory: Path, stack: np.ndarray, prefix: str = "frame") -> list[Path]:
    """Write each frame of a (n, h, w) stack as its own TIFF."""
    if stack.ndim != 3:
        raise ValueError(f"Expected a 3D stack, got shape {stack.shape}")
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, frame in enumerate(stack):
        path = directory / f"{prefix}_{index:03d}.tif"
        write_frame(path, frame)
        paths.append(path)
    return paths


def read_frame(path: Path) -> np.ndarray:
    """Read a single TIFF frame."""
    return np.asarray(tifffile.imread(str(path)))


def read_stack(directory: Path, prefix: str = "frame") -> np.ndarray:
    """Read all frames in a directory into a (n, h, w) array, in name order."""
    paths = sorted(directory.glob(f"{prefix}_*.tif"))
    if not paths:
        raise FileNotFoundError(f"No {prefix}_*.tif frames found in {directory}")
    frames = [read_frame(path) for path in paths]
    shapes = {frame.shape for frame in frames}
    if len(shapes) > 1:
        raise ValueError(f"Frames in {directory} have differing shapes: {shapes}")
    return np.stack(frames)


def count_frames(directory: Path, prefix: str = "frame") -> int:
    return len(list(directory.glob(f"{prefix}_*.tif")))
