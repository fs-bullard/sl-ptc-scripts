"""Command line interface."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from . import __version__
from .analysis.roi import parse_roi_argument
from .camera import CameraError, create_driver
from .io.session import Session
from .prefs import Preferences, PreferencesError, validate_roi_spec
from .report.pdf import build_report
from .tests.registry import UnknownTestError, available_tests, get_test

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def _fail(message: str) -> None:
    raise click.ClickException(message)


def _prefs(ctx: click.Context) -> Preferences:
    return ctx.obj["prefs"]


def _resolve_roi_option(prefs: Preferences, roi: str | None) -> dict | None:
    """Turn a --roi argument into a spec: a preset name or an inline ROI."""
    if roi is None:
        return None
    presets = prefs.roi_presets()
    if roi in presets:
        return presets[roi]
    return parse_roi_argument(roi)


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(__version__, prog_name="emva1288")
@click.option(
    "--config",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Preferences file to use (default: %APPDATA%/emva1288/preferences.json).",
)
@click.pass_context
def main(ctx: click.Context, config: Path | None) -> None:
    """EMVA 1288 sensor characterisation toolkit."""
    ctx.ensure_object(dict)
    try:
        ctx.obj["prefs"] = Preferences.load(config)
    except PreferencesError as exc:
        _fail(str(exc))


# ---------------------------------------------------------------- config


@main.group()
def config() -> None:
    """View and edit preferences."""


@config.command("path")
@click.pass_context
def config_path(ctx: click.Context) -> None:
    """Print the preferences file location."""
    prefs = _prefs(ctx)
    exists = "" if prefs.path.exists() else "  (not yet created)"
    click.echo(f"{prefs.path}{exists}")


@config.command("list")
@click.pass_context
def config_list(ctx: click.Context) -> None:
    """Show every setting."""
    flat = _prefs(ctx).flatten()
    width = max(len(key) for key in flat)
    for key in sorted(flat):
        click.echo(f"{key.ljust(width)}  {json.dumps(flat[key])}")


@config.command("get")
@click.argument("key")
@click.pass_context
def config_get(ctx: click.Context, key: str) -> None:
    """Read one setting by dotted key."""
    try:
        click.echo(json.dumps(_prefs(ctx).get(key)))
    except PreferencesError as exc:
        _fail(str(exc))


@config.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx: click.Context, key: str, value: str) -> None:
    """Write one setting by dotted key."""
    prefs = _prefs(ctx)
    try:
        stored = prefs.set(key, value)
    except PreferencesError as exc:
        _fail(str(exc))
    path = prefs.save()
    click.echo(f"{key} = {json.dumps(stored)}")
    click.echo(f"Saved to {path}")


@config.command("init")
@click.option("--force", is_flag=True, help="Overwrite an existing file.")
@click.pass_context
def config_init(ctx: click.Context, force: bool) -> None:
    """Write a preferences file with the current (default) values."""
    prefs = _prefs(ctx)
    if prefs.path.exists() and not force:
        _fail(f"{prefs.path} already exists; pass --force to overwrite")
    click.echo(f"Wrote {prefs.save()}")


@config.command("edit")
@click.pass_context
def config_edit(ctx: click.Context) -> None:
    """Open the preferences file in your editor."""
    prefs = _prefs(ctx)
    if not prefs.path.exists():
        prefs.save()
    click.edit(filename=str(prefs.path))


# ------------------------------------------------------------ config roi


@config.group("roi")
def config_roi() -> None:
    """Manage ROI presets."""


@config_roi.command("list")
@click.pass_context
def roi_list(ctx: click.Context) -> None:
    """Show all ROI presets."""
    prefs = _prefs(ctx)
    active = prefs.get("roi.active")
    for name, spec in sorted(prefs.roi_presets().items()):
        marker = "*" if name == active else " "
        click.echo(f"{marker} {name:12s} {json.dumps(spec)}")
    click.echo("\n* = active")


@config_roi.command("show")
@click.argument("name")
@click.pass_context
def roi_show(ctx: click.Context, name: str) -> None:
    """Print one ROI preset."""
    presets = _prefs(ctx).roi_presets()
    if name not in presets:
        _fail(f"No such ROI preset: {name}")
    click.echo(json.dumps(presets[name], indent=2))


@config_roi.command("add")
@click.argument("name")
@click.option("--centre-fraction", type=float, help="Centred ROI covering this fraction.")
@click.option("--full", is_flag=True, help="Whole frame.")
@click.option("--x0", type=int, help="Rectangle left edge, px.")
@click.option("--y0", type=int, help="Rectangle top edge, px.")
@click.option("--width", type=int, help="Rectangle width, px.")
@click.option("--height", type=int, help="Rectangle height, px.")
@click.option("--use", is_flag=True, help="Make this the active ROI.")
@click.pass_context
def roi_add(
    ctx: click.Context,
    name: str,
    centre_fraction: float | None,
    full: bool,
    x0: int | None,
    y0: int | None,
    width: int | None,
    height: int | None,
    use: bool,
) -> None:
    """Add or replace an ROI preset."""
    prefs = _prefs(ctx)
    rect_fields = (x0, y0, width, height)

    if full:
        spec: dict[str, Any] = {"mode": "full"}
    elif centre_fraction is not None:
        spec = {"mode": "centre_fraction", "fraction": centre_fraction}
    elif all(field is not None for field in rect_fields):
        spec = {"mode": "rect", "x0": x0, "y0": y0, "width": width, "height": height}
    else:
        _fail(
            "Specify --full, --centre-fraction, or all of --x0 --y0 --width --height"
        )

    try:
        prefs.set_roi_preset(name, spec)
        if use:
            prefs.use_roi_preset(name)
    except PreferencesError as exc:
        _fail(str(exc))

    prefs.save()
    click.echo(f"{name} = {json.dumps(spec)}")
    if use:
        click.echo(f"Active ROI is now {name}")


@config_roi.command("use")
@click.argument("name")
@click.pass_context
def roi_use(ctx: click.Context, name: str) -> None:
    """Select the active ROI preset."""
    prefs = _prefs(ctx)
    try:
        prefs.use_roi_preset(name)
    except PreferencesError as exc:
        _fail(str(exc))
    prefs.save()
    click.echo(f"Active ROI is now {name}")


@config_roi.command("remove")
@click.argument("name")
@click.pass_context
def roi_remove(ctx: click.Context, name: str) -> None:
    """Delete an ROI preset."""
    prefs = _prefs(ctx)
    try:
        prefs.remove_roi_preset(name)
    except PreferencesError as exc:
        _fail(str(exc))
    prefs.save()
    click.echo(f"Removed {name}")


# ----------------------------------------------------------------- info


@main.command("tests")
def list_tests() -> None:
    """List the available test scripts."""
    for name, cls in sorted(available_tests().items()):
        click.echo(f"{name:8s} {cls.description}")


@main.command("devices")
@click.pass_context
def devices(ctx: click.Context) -> None:
    """Scan for connected detectors."""
    prefs = _prefs(ctx)
    try:
        driver = create_driver(prefs.get("camera.driver"), prefs)
        scan = getattr(driver, "scan", None)
        if scan is None:
            with driver:
                info = driver.device_info()
            click.echo(f"{info.model} ({info.width}×{info.height})  [{driver.name}]")
            return
        found = scan()
    except CameraError as exc:
        _fail(str(exc))

    if not found:
        click.echo("No detectors found.")
    for item in found:
        click.echo(item)


# -------------------------------------------------------------- capture


@main.command()
@click.argument("test", default="ptc")
@click.option(
    "--mode",
    type=click.Choice(["exposure", "illumination"]),
    default="exposure",
    show_default=True,
    help="Sweep exposure at fixed light, or step illumination at fixed exposure.",
)
@click.option("--repeats", type=int, help="Frames per level (minimum 2).")
@click.option("--exposure-ms", type=float, help="Exposure for illumination mode.")
@click.option("--start-ms", type=float, help="Exposure sweep start.")
@click.option("--stop-ms", type=float, help="Exposure sweep end.")
@click.option("--steps", type=int, help="Number of exposure steps.")
@click.option("--spacing", type=click.Choice(["linear", "log"]), help="Sweep spacing.")
@click.option("--levels", help="Illumination levels, comma separated.")
@click.option("--stem", help="Session folder name stem.")
@click.option("--save-path", type=click.Path(path_type=Path), help="Where to write the session.")
@click.option("--driver", help="Override camera.driver for this run.")
@click.option("--yes", is_flag=True, help="Do not pause for illumination prompts.")
@click.option("--no-analyse", is_flag=True, help="Capture only; skip analysis and report.")
@click.pass_context
def capture(ctx: click.Context, test: str, **options: Any) -> None:
    """Acquire a measurement session."""
    prefs = _prefs(ctx)

    try:
        script = get_test(test)
    except UnknownTestError as exc:
        _fail(str(exc))

    levels = options.pop("levels")
    if levels:
        options["levels"] = [float(part) for part in levels.split(",") if part.strip()]

    auto = options.pop("yes")
    no_analyse = options.pop("no_analyse")
    driver_name = options.pop("driver") or prefs.get("camera.driver")

    def prompt(message: str) -> None:
        if auto:
            click.echo(f"  {message}")
        else:
            click.echo()
            click.pause(f"  {message} Press any key to continue...")

    def progress(index: int, total: int, label: str) -> None:
        click.echo(f"[{index + 1}/{total}] {label}")

    options = {key: value for key, value in options.items() if value is not None}
    options["progress"] = progress

    try:
        driver = create_driver(driver_name, prefs)
    except CameraError as exc:
        _fail(str(exc))

    click.echo(f"Capturing {test} using the {driver_name} driver...")
    try:
        with driver:
            session = script.acquire(driver, prefs, options, prompt)
    except (CameraError, ValueError) as exc:
        _fail(str(exc))

    click.echo(f"\nSaved {len(session.levels)} levels to {session.path}")

    if not no_analyse:
        _run_analysis(prefs, session, script, {}, write_report=True)


# -------------------------------------------------------------- analyse


@main.command()
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--roi", help="ROI preset name, 'x0,y0,w,h' or 'centre:<fraction>'.")
@click.option(
    "--fit-range",
    nargs=2,
    type=float,
    help="Explicit fit bounds on mean signal, in ADU: LOW HIGH.",
)
@click.option("--max-fraction", type=float, help="Fit up to this fraction of saturation.")
@click.option("--report/--no-report", default=False, help="Also build the PDF.")
@click.pass_context
def analyse(
    ctx: click.Context,
    session_dir: Path,
    roi: str | None,
    fit_range: tuple[float, float] | None,
    max_fraction: float | None,
    report: bool,
) -> None:
    """Recompute results from a stored session."""
    prefs = _prefs(ctx)
    session = _load_session(session_dir)
    script = _script_for(session)

    options: dict[str, Any] = {}
    try:
        roi_spec = _resolve_roi_option(prefs, roi)
    except PreferencesError as exc:
        _fail(str(exc))
    if roi_spec:
        options["roi_spec"] = roi_spec
    if fit_range:
        options["fit_range"] = fit_range
    if max_fraction is not None:
        options["max_fraction"] = max_fraction

    _run_analysis(prefs, session, script, options, write_report=report)


# --------------------------------------------------------------- report


@main.command("report")
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--roi", help="ROI preset name, 'x0,y0,w,h' or 'centre:<fraction>'.")
@click.option("--open", "open_after", is_flag=True, help="Open the PDF when done.")
@click.pass_context
def report_command(
    ctx: click.Context,
    session_dir: Path,
    roi: str | None,
    open_after: bool,
) -> None:
    """Build the PDF report for a session."""
    prefs = _prefs(ctx)
    session = _load_session(session_dir)
    script = _script_for(session)

    options: dict[str, Any] = {}
    try:
        roi_spec = _resolve_roi_option(prefs, roi)
    except PreferencesError as exc:
        _fail(str(exc))
    if roi_spec:
        options["roi_spec"] = roi_spec

    pdf_path = _run_analysis(prefs, session, script, options, write_report=True)
    if open_after and pdf_path:
        click.launch(str(pdf_path))


# ------------------------------------------------------------- internals


def _load_session(session_dir: Path) -> Session:
    try:
        return Session.load(session_dir)
    except (FileNotFoundError, ValueError) as exc:
        _fail(str(exc))
        raise  # unreachable; keeps type checkers happy


def _script_for(session: Session) -> Any:
    try:
        return get_test(session.test)
    except UnknownTestError as exc:
        _fail(str(exc))


def _run_analysis(
    prefs: Preferences,
    session: Session,
    script: Any,
    options: dict[str, Any],
    write_report: bool,
) -> Path | None:
    """Analyse, write outputs and optionally build the PDF."""
    try:
        results = script.analyse(session, prefs, options)
    except (ValueError, PreferencesError, FileNotFoundError) as exc:
        _fail(str(exc))
    except Exception as exc:  # fit errors carry actionable messages
        _fail(f"Analysis failed: {exc}")

    outputs = script.write_outputs(session, results, prefs)

    fit = results.fit
    click.echo()
    click.echo(f"System gain K      {fit.system_gain:.4f} ADU/e-")
    click.echo(f"Inverse gain 1/K   {fit.inverse_gain:.3f} e-/ADU")
    click.echo(f"Temporal dark noise {fit.read_noise_adu:.2f} ADU  ({fit.read_noise_e:.2f} e-)")
    bound = "" if fit.saturation_reached else "  (lower bound; never saturated)"
    click.echo(
        f"Saturation         {fit.mu_saturation:.1f} ADU  "
        f"({fit.saturation_capacity_e:.0f} e-){bound}"
    )
    click.echo(f"Fit                {len(fit.fit_indices)} points, R2 = {fit.r_squared:.5f}")

    for warning in results.warnings:
        click.secho(f"warning: {warning}", fg="yellow", err=True)

    pdf_path = None
    if write_report:
        pdf_path = session.results_dir / "report.pdf"
        build_report(
            pdf_path,
            session,
            results,
            title=prefs.get("report.title"),
            author=prefs.get("report.author"),
        )
        outputs.append(pdf_path)

    click.echo()
    for path in outputs:
        click.echo(f"  {path}")

    return pdf_path


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
