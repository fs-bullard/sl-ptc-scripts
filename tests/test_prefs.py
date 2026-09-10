"""Preferences validation and ROI presets."""

from __future__ import annotations

import json

import pytest

from emva1288.prefs import Preferences, PreferencesError


@pytest.fixture
def prefs(tmp_path):
    return Preferences.load(tmp_path / "preferences.json")


def test_defaults_load_without_a_file(prefs):
    assert prefs.get("capture.repeats") == 10
    assert prefs.get("roi.active") == "centre50"


def test_set_coerces_types(prefs):
    assert prefs.set("capture.repeats", "24") == 24
    assert prefs.set("capture.exposure_ms", "12.5") == 12.5
    assert prefs.set("camera.dds", "true") is True


def test_unknown_key_is_rejected(prefs):
    with pytest.raises(PreferencesError, match="Unknown preference key"):
        prefs.set("camera.nonsense", "1")


def test_bad_value_is_rejected(prefs):
    with pytest.raises(PreferencesError, match="expected an integer"):
        prefs.set("capture.repeats", "many")


def test_choice_is_enforced(prefs):
    with pytest.raises(PreferencesError, match="must be one of"):
        prefs.set("camera.full_well", "Medium")
    assert prefs.set("camera.full_well", "Low") == "Low"


def test_levels_parse_from_csv_and_json(prefs):
    assert prefs.set("illumination.levels", "0, 25, 50") == [0, 25, 50]
    assert prefs.set("illumination.levels", "[0, 10.5]") == [0, 10.5]


def test_round_trip_through_disk(prefs, tmp_path):
    prefs.set("capture.repeats", 32)
    prefs.set("stem", "run")
    prefs.save()

    reloaded = Preferences.load(tmp_path / "preferences.json")
    assert reloaded.get("capture.repeats") == 32
    assert reloaded.get("stem") == "run"
    # Values absent from the file still come from defaults.
    assert reloaded.get("analysis.saturation_adu") == 16383


def test_partial_file_merges_with_defaults(tmp_path):
    path = tmp_path / "preferences.json"
    path.write_text(json.dumps({"capture": {"repeats": 4}}), encoding="utf-8")
    prefs = Preferences.load(path)
    assert prefs.get("capture.repeats") == 4
    assert prefs.get("capture.exposure_ms") == 100


def test_roi_preset_lifecycle(prefs):
    prefs.set_roi_preset("corner", {"mode": "rect", "x0": 0, "y0": 0, "width": 64, "height": 64})
    prefs.use_roi_preset("corner")
    assert prefs.active_roi()["width"] == 64

    with pytest.raises(PreferencesError, match="active ROI"):
        prefs.remove_roi_preset("corner")

    prefs.use_roi_preset("full")
    prefs.remove_roi_preset("corner")
    assert "corner" not in prefs.roi_presets()


def test_invalid_roi_preset_is_rejected(prefs):
    with pytest.raises(PreferencesError, match="fraction"):
        prefs.set_roi_preset("bad", {"mode": "centre_fraction", "fraction": 2.0})
