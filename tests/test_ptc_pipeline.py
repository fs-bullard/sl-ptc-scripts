"""End-to-end verification against a detector with known parameters.

The mock driver is built from the EMVA 1288 sensor model with a system gain we
choose, so a correct capture-store-analyse-fit pipeline must recover it. These
tests are the reason the mock exists.
"""

from __future__ import annotations

import pytest

from emva1288.camera.mock import MockDriver
from emva1288.io.session import Session
from emva1288.prefs import Preferences
from emva1288.tests.ptc import PhotonTransferCurve


@pytest.fixture
def prefs(tmp_path):
    prefs = Preferences.load(tmp_path / "preferences.json")
    prefs.set("save_path", str(tmp_path / "data"))
    return prefs


def _capture(driver, prefs, **options):
    script = PhotonTransferCurve()
    defaults = {
        "mode": "exposure",
        "repeats": 10,
        "start_ms": 20.0,
        "stop_ms": 1000.0,
        "steps": 12,
        "spacing": "linear",
    }
    defaults.update(options)
    with driver:
        return script, script.acquire(driver, prefs, defaults, lambda _msg: None)


@pytest.mark.parametrize(
    ("system_gain", "read_noise_e"),
    [(0.25, 30.0), (0.5, 20.0), (0.125, 45.0)],
)
def test_recovers_known_system_gain(prefs, system_gain, read_noise_e):
    """The fitted slope must match the gain the simulator was built with."""
    # Scale the flux so each configuration still sweeps up to saturation.
    driver = MockDriver(
        width=128,
        height=128,
        system_gain=system_gain,
        read_noise_e=read_noise_e,
        photons_per_ms=70.0 * (0.25 / system_gain),
        seed=7,
    )
    script, session = _capture(driver, prefs)
    results = script.analyse(session, prefs, {})

    assert results.fit.system_gain == pytest.approx(system_gain, rel=0.03)
    assert results.fit.r_squared > 0.99

    # Read noise comes from the dark sets, not the intercept. The shortest
    # exposure's dark still carries some dark-current shot noise on top of the
    # read noise, so expect at or above the configured floor.
    assert results.fit.read_noise_e == pytest.approx(read_noise_e, rel=0.35)

    # The dark variance has already been subtracted, so a correct fit passes
    # near the origin.
    assert abs(results.fit.residual_noise_adu) < 0.1 * results.fit.read_noise_adu + 5


def test_saturation_is_detected_and_excluded(prefs):
    driver = MockDriver(width=128, height=128, seed=11)
    script, session = _capture(driver, prefs, stop_ms=1600.0, steps=14)
    results = script.analyse(session, prefs, {})

    saturated = [p for p in results.points if p.saturated_fraction > 0.5]
    assert saturated, "sweep should reach saturation"

    # No saturated point may enter the fit.
    fit_indices = set(results.fit.fit_indices)
    assert not any(p.index in fit_indices for p in saturated)
    assert results.fit.fit_limit < results.fit.mu_saturation


def test_unsaturated_sweep_is_flagged_as_a_lower_bound(prefs):
    """Never reaching saturation must not be reported as a measured full well."""
    driver = MockDriver(width=96, height=96, seed=17)
    # Stop well short of the rail.
    script, session = _capture(driver, prefs, stop_ms=300.0, steps=8)
    results = script.analyse(session, prefs, {})

    assert results.fit.saturation_reached is False
    assert any("lower bound" in warning for warning in results.warnings)
    # Every point is still usable, so none should be discarded.
    assert len(results.fit.fit_indices) == len(results.points)
    assert results.fit.system_gain == pytest.approx(0.25, rel=0.03)


def test_session_round_trips_and_reanalyses(prefs, tmp_path):
    """A stored session must be re-analysable with no camera present."""
    driver = MockDriver(width=96, height=96, seed=3)
    script, session = _capture(driver, prefs, steps=8)
    first = script.analyse(session, prefs, {})

    reloaded = Session.load(session.path)
    second = script.analyse(reloaded, prefs, {})

    assert reloaded.repeats == session.repeats
    assert len(reloaded.levels) == len(session.levels)
    assert second.fit.system_gain == pytest.approx(first.fit.system_gain, rel=1e-12)


def test_roi_choice_changes_pixels_not_gain(prefs):
    """A smaller ROI samples fewer pixels but must measure the same gain."""
    driver = MockDriver(width=128, height=128, seed=5)
    script, session = _capture(driver, prefs, steps=10)

    full = script.analyse(session, prefs, {"roi_spec": {"mode": "full"}})
    centre = script.analyse(
        session, prefs, {"roi_spec": {"mode": "centre_fraction", "fraction": 0.25}}
    )

    assert centre.roi.width == 32
    assert full.roi.width == 128
    assert centre.fit.system_gain == pytest.approx(full.fit.system_gain, rel=0.06)


def test_outputs_are_written(prefs):
    driver = MockDriver(width=96, height=96, seed=9)
    script, session = _capture(driver, prefs, steps=8)
    results = script.analyse(session, prefs, {})

    outputs = script.write_outputs(session, results, prefs)
    assert [path.name for path in outputs] == ["ptc.csv", "ptc.png"]
    for path in outputs:
        assert path.exists() and path.stat().st_size > 0

    header = outputs[0].read_text(encoding="utf-8").splitlines()[0]
    assert "variance_adu2" in header and "in_fit" in header


def test_illumination_mode_captures_levels(prefs):
    driver = MockDriver(width=64, height=64, photons_per_ms=700.0, seed=13)
    script = PhotonTransferCurve()
    options = {
        "mode": "illumination",
        "repeats": 6,
        "exposure_ms": 100.0,
        "levels": [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
    }
    with driver:
        session = script.acquire(driver, prefs, options, lambda _msg: None)

    assert session.mode == "illumination"
    assert len(session.levels) == 11
    # One shared dark set, since exposure is constant.
    assert len({level.dark_directory for level in session.levels}) == 1

    results = script.analyse(session, prefs, {})
    assert results.fit.system_gain == pytest.approx(0.25, rel=0.05)


def test_quantised_exposures_are_deduplicated_and_recorded(prefs):
    """A driver with integer exposures must not record fractional values.

    The SLDevice SDK takes whole milliseconds, so a fine sweep would otherwise
    store a requested exposure the detector never actually used, and repeat the
    same integer exposure several times.
    """

    class IntegerExposureDriver(MockDriver):
        @staticmethod
        def quantise_exposure(exposure_ms: float) -> float:
            return float(max(1, int(round(exposure_ms))))

    driver = IntegerExposureDriver(width=64, height=64, seed=21)
    # 10 steps across 10-14 ms collapses to the 5 distinct integers.
    script, session = _capture(driver, prefs, start_ms=10.0, stop_ms=14.0, steps=10)

    recorded = [level.exposure_ms for level in session.levels]
    assert recorded == [10.0, 11.0, 12.0, 13.0, 14.0]
    assert all(value == int(value) for value in recorded)


def test_too_few_repeats_is_rejected(prefs):
    driver = MockDriver(width=32, height=32)
    script = PhotonTransferCurve()
    with driver:
        with pytest.raises(ValueError, match="at least 2"):
            script.acquire(driver, prefs, {"repeats": 1}, lambda _msg: None)
