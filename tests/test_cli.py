"""CLI behaviour."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from emva1288.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def config_path(tmp_path):
    return tmp_path / "preferences.json"


def invoke(runner, config_path, *args):
    return runner.invoke(main, ["--config", str(config_path), *args])


def test_tests_listing(runner, config_path):
    result = invoke(runner, config_path, "tests")
    assert result.exit_code == 0
    assert "ptc" in result.output


def test_config_set_and_get(runner, config_path):
    assert invoke(runner, config_path, "config", "set", "capture.repeats", "16").exit_code == 0
    result = invoke(runner, config_path, "config", "get", "capture.repeats")
    assert result.exit_code == 0
    assert result.output.strip() == "16"
    assert json.loads(config_path.read_text())["capture"]["repeats"] == 16


def test_config_set_rejects_bad_key(runner, config_path):
    result = invoke(runner, config_path, "config", "set", "capture.nope", "1")
    assert result.exit_code != 0
    assert "Unknown preference key" in result.output


def test_roi_preset_add_and_use(runner, config_path):
    result = invoke(
        runner, config_path, "config", "roi", "add", "patch",
        "--x0", "10", "--y0", "10", "--width", "64", "--height", "64", "--use",
    )
    assert result.exit_code == 0

    listing = invoke(runner, config_path, "config", "roi", "list")
    assert "* patch" in listing.output


def test_roi_add_requires_a_mode(runner, config_path):
    result = invoke(runner, config_path, "config", "roi", "add", "bad")
    assert result.exit_code != 0
    assert "--full" in result.output


def test_capture_analyse_report_round_trip(runner, config_path, tmp_path):
    """The documented hardware-free path must work end to end."""
    data_dir = tmp_path / "data"
    result = invoke(
        runner, config_path, "capture", "ptc",
        "--driver", "mock", "--yes",
        "--repeats", "6", "--steps", "8",
        "--start-ms", "20", "--stop-ms", "900",
        "--save-path", str(data_dir),
    )
    assert result.exit_code == 0, result.output
    assert "System gain K" in result.output

    sessions = list(data_dir.iterdir())
    assert len(sessions) == 1
    session = sessions[0]
    for name in ("ptc.csv", "ptc.png", "report.pdf"):
        assert (session / "results" / name).exists()

    # Re-analysing a stored session needs no camera.
    again = invoke(runner, config_path, "analyse", str(session), "--roi", "full")
    assert again.exit_code == 0, again.output
    assert "System gain K" in again.output


def test_analyse_rejects_a_non_session_directory(runner, config_path, tmp_path):
    result = invoke(runner, config_path, "analyse", str(tmp_path))
    assert result.exit_code != 0
    assert "not a session directory" in result.output
