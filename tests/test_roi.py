"""ROI resolution and parsing."""

from __future__ import annotations

import numpy as np
import pytest

from emva1288.analysis.roi import parse_roi_argument, resolve_roi
from emva1288.prefs import PreferencesError


def test_full_roi_covers_frame():
    rect = resolve_roi({"mode": "full"}, (480, 640))
    assert (rect.x0, rect.y0, rect.width, rect.height) == (0, 0, 640, 480)


def test_centre_fraction_is_centred():
    rect = resolve_roi({"mode": "centre_fraction", "fraction": 0.5}, (480, 640))
    assert (rect.width, rect.height) == (320, 240)
    assert (rect.x0, rect.y0) == (160, 120)


def test_rect_outside_frame_is_rejected():
    spec = {"mode": "rect", "x0": 600, "y0": 0, "width": 100, "height": 10}
    with pytest.raises(PreferencesError, match="does not fit"):
        resolve_roi(spec, (480, 640))


def test_apply_crops_a_stack():
    rect = resolve_roi({"mode": "centre_fraction", "fraction": 0.5}, (100, 100))
    stack = np.zeros((5, 100, 100))
    assert rect.apply(stack).shape == (5, 50, 50)


def test_parse_rectangle_and_centre():
    assert parse_roi_argument("10,20,30,40") == {
        "mode": "rect",
        "x0": 10,
        "y0": 20,
        "width": 30,
        "height": 40,
    }
    assert parse_roi_argument("centre:0.25") == {
        "mode": "centre_fraction",
        "fraction": 0.25,
    }


def test_parse_rejects_nonsense():
    with pytest.raises(PreferencesError):
        parse_roi_argument("not-an-roi")
