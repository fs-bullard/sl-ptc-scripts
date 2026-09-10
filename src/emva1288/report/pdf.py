"""PDF report assembly.

Sections are built independently and concatenated, so a future test script adds
its own section without restructuring the document.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..io.session import Session

INK_PRIMARY = colors.HexColor("#0b0b0b")
INK_SECONDARY = colors.HexColor("#52514e")
INK_MUTED = colors.HexColor("#898781")
GRIDLINE = colors.HexColor("#e1e0d9")
SURFACE_ALT = colors.HexColor("#f4f4f1")
ACCENT = colors.HexColor("#2a78d6")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            alignment=TA_LEFT,
            textColor=INK_PRIMARY,
            spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            textColor=INK_MUTED,
            spaceAfter=14,
        ),
        "heading": ParagraphStyle(
            "heading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=INK_PRIMARY,
            spaceBefore=14,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            textColor=INK_SECONDARY,
            spaceAfter=6,
        ),
        "warn": ParagraphStyle(
            "warn",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#b4560f"),
            spaceAfter=3,
        ),
    }


def _table(data: list[list[str]], widths: list[float], header: bool = True) -> Table:
    table = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.2),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK_SECONDARY),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, GRIDLINE),
    ]
    if header:
        style += [
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 0), (-1, 0), INK_PRIMARY),
            ("BACKGROUND", (0, 0), (-1, 0), SURFACE_ALT),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK_MUTED),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ]
    table.setStyle(TableStyle(style))
    return table


def _key_value_rows(pairs: list[tuple[str, Any]]) -> list[list[str]]:
    return [[key, "" if value is None else str(value)] for key, value in pairs]


def build_ptc_section(session: Session, results: Any, styles: dict, width: float) -> list:
    """Flowables for the photon transfer curve section."""
    fit = results.fit
    story: list = []

    story.append(Paragraph("Photon transfer curve", styles["heading"]))
    story.append(
        Paragraph(
            "Temporal variance measured from paired frame differences "
            "(σ² = var(A−B)/2, EMVA 1288 §6), corrected by subtracting the dark "
            "set's mean and variance. The system gain K is the slope of the "
            "fitted linear region.",
            styles["body"],
        )
    )

    summary = _key_value_rows(
        [
            ("System gain K (ADU/e⁻)", f"{fit.system_gain:.4f}"),
            ("Inverse gain 1/K (e⁻/ADU)", f"{fit.inverse_gain:.3f}"),
            ("Temporal dark noise (ADU)", f"{fit.read_noise_adu:.2f}"),
            ("Temporal dark noise (e⁻)", f"{fit.read_noise_e:.2f}"),
            ("Residual at zero signal (ADU)", f"{fit.residual_noise_adu:.2f}"),
            (
                "Saturation μ (ADU)",
                f"{fit.mu_saturation:.1f}"
                + ("" if fit.saturation_reached else "  (lower bound)"),
            ),
            (
                "Saturation capacity (e⁻)",
                f"{fit.saturation_capacity_e:.0f}"
                + ("" if fit.saturation_reached else "  (lower bound)"),
            ),
            ("Fit limit (ADU)", f"{fit.fit_limit:.1f}"),
            ("Points used in fit", f"{len(fit.fit_indices)} of {len(results.points)}"),
            ("Fit R²", f"{fit.r_squared:.5f}"),
        ]
    )
    story.append(_table([["Quantity", "Value"]] + summary, [width * 0.55, width * 0.45]))

    plot_path = session.results_dir / "ptc.png"
    if plot_path.exists():
        story.append(Spacer(1, 10))
        # Figure is rendered 11x4.6in; scale to the frame width.
        story.append(Image(str(plot_path), width=width, height=width * 4.6 / 11.0))

    story.append(PageBreak())
    story.append(Paragraph("Measured data", styles["heading"]))

    unit = results.unit
    header = [
        f"Level ({unit})",
        "Exp (ms)",
        "μ bright",
        "μ dark",
        "μ (ADU)",
        "σ² (ADU²)",
        "Sat %",
        "In fit",
    ]
    in_fit = set(fit.fit_indices)
    rows = [header]
    for point in results.points:
        rows.append(
            [
                f"{point.value:g}",
                f"{point.exposure_ms:g}",
                f"{point.bright.mean:.1f}",
                f"{point.dark.mean:.1f}",
                f"{point.mean:.1f}",
                f"{point.variance:.1f}",
                f"{point.saturated_fraction * 100:.1f}",
                "yes" if point.index in in_fit else "—",
            ]
        )
    column = width / len(header)
    story.append(_table(rows, [column] * len(header)))

    if results.warnings:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Warnings", styles["heading"]))
        for warning in results.warnings:
            story.append(Paragraph(f"• {warning}", styles["warn"]))

    return story


def build_report(
    path: Path,
    session: Session,
    results: Any,
    title: str = "EMVA 1288 Sensor Report",
    author: str = "",
) -> Path:
    """Assemble the PDF for one session."""
    styles = _styles()
    margin = 18 * mm
    frame_width = A4[0] - 2 * margin

    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=title,
        author=author or "emva1288",
    )

    story: list = [Paragraph(title, styles["title"])]
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    byline = f"Generated {generated}" + (f" · {author}" if author else "")
    story.append(Paragraph(byline, styles["subtitle"]))

    # -- session and detector metadata ---------------------------------
    story.append(Paragraph("Measurement conditions", styles["heading"]))
    device = session.device or {}
    settings = session.settings or {}
    roi = results.roi

    mode_label = (
        "Exposure sweep at fixed illumination"
        if session.mode == "exposure"
        else "Illumination series at fixed exposure"
    )
    pairs = [
        ("Session", session.path.name),
        ("Acquired", session.created),
        ("Mode", mode_label),
        ("Detector", device.get("model", "unknown")),
        ("Model code", device.get("code", "")),
        ("Firmware", device.get("firmware", "")),
        ("Frame size", f"{device.get('width', '?')} × {device.get('height', '?')} px"),
        ("Driver", settings.get("driver", "")),
        ("Full well mode", settings.get("full_well", "")),
        ("Binning", settings.get("binning", "")),
        ("DDS", settings.get("dds", "")),
        ("Bit depth", settings.get("bit_depth", "")),
        ("Repetitions per level", session.repeats),
        ("ROI", f"{roi.width} × {roi.height} px at ({roi.x0}, {roi.y0})"),
    ]
    if session.mode == "illumination":
        pairs.insert(3, ("Exposure time", f"{session.exposure_ms:g} ms"))
    elif session.fixed_illumination is not None:
        pairs.insert(3, ("Fixed illumination", str(session.fixed_illumination)))

    story.append(
        _table(
            [["Parameter", "Value"]] + _key_value_rows(pairs),
            [frame_width * 0.4, frame_width * 0.6],
        )
    )

    story.extend(build_ptc_section(session, results, styles, frame_width))

    path.parent.mkdir(parents=True, exist_ok=True)
    document.build(story)
    return path
