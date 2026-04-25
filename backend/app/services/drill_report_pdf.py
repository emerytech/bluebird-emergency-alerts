from __future__ import annotations

import io
from typing import TYPE_CHECKING

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

if TYPE_CHECKING:
    from app.services.drill_report_service import DrillReport

# Colours
_BLUE = colors.HexColor("#1a56db")
_AMBER = colors.HexColor("#d97706")
_RED = colors.HexColor("#dc2626")
_GREEN = colors.HexColor("#16a34a")
_LIGHT_GRAY = colors.HexColor("#f3f4f6")
_MID_GRAY = colors.HexColor("#6b7280")


def _rate_color(rate: float):
    if rate >= 90:
        return _GREEN
    if rate >= 60:
        return _AMBER
    return _RED


def generate_pdf(report: "DrillReport", school_name: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.85 * inch,
        bottomMargin=0.85 * inch,
    )
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        fontSize=20,
        textColor=_BLUE,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=11,
        textColor=_MID_GRAY,
        spaceAfter=2,
    )
    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontSize=13,
        textColor=_BLUE,
        spaceBefore=14,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        spaceAfter=4,
    )
    small_style = ParagraphStyle(
        "Small",
        parent=styles["Normal"],
        fontSize=8,
        textColor=_MID_GRAY,
        leading=11,
    )

    # ── Title block ──────────────────────────────────────────────────
    alert_type = "TRAINING DRILL" if report.is_training else "LIVE ALARM"
    type_color = _AMBER if report.is_training else _RED
    story.append(Paragraph("BlueBird Alerts", title_style))
    story.append(Paragraph(f"Alert Report — {school_name}", subtitle_style))
    story.append(Paragraph(
        f'<font color="{type_color.hexval()}">{alert_type}</font>  |  '
        f'Alert #{report.alert_id}  |  {report.created_at[:10]}',
        subtitle_style,
    ))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1, color=_BLUE))
    story.append(Spacer(1, 10))

    # ── Alert summary ─────────────────────────────────────────────────
    story.append(Paragraph("Alert Summary", section_style))
    summary_data = [
        ["Field", "Value"],
        ["Message", report.message],
        ["Type", "Training Drill" if report.is_training else "Live Alarm"],
        ["Training label", report.training_label or "—"],
        ["Created at", report.created_at],
        ["Activated by", report.activated_by or "Unknown"],
        ["Deactivated at", report.deactivated_at or "Not yet deactivated"],
        ["Deactivated by", report.deactivated_by or "—"],
    ]
    t = Table(summary_data, colWidths=[1.8 * inch, 4.8 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT_GRAY]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)

    # ── Acknowledgement stats ─────────────────────────────────────────
    story.append(Paragraph("Acknowledgement Stats", section_style))
    rate = report.acknowledgement_rate
    rate_col = _rate_color(rate)
    ack_data = [
        ["Metric", "Value"],
        ["Users expected", str(report.total_users_expected)],
        ["Users acknowledged", str(report.total_acknowledged)],
        ["Acknowledgement rate", f"{rate:.1f}%"],
        ["First acknowledgement", report.first_ack_time or "—"],
        ["Last acknowledgement", report.last_ack_time or "—"],
    ]
    t2 = Table(ack_data, colWidths=[2.2 * inch, 4.4 * inch])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT_GRAY]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("TEXTCOLOR", (1, 3), (1, 3), rate_col),
        ("FONTNAME", (1, 3), (1, 3), "Helvetica-Bold"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t2)

    # ── Delivery stats ────────────────────────────────────────────────
    if report.is_training:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "Push notifications are not sent during training drills.",
            small_style,
        ))
    elif report.delivery_total > 0:
        story.append(Paragraph("Delivery Stats", section_style))
        del_data = [
            ["Metric", "Value"],
            ["Push attempts", str(report.delivery_total)],
            ["Delivered", str(report.delivery_ok)],
            ["Failed", str(report.delivery_failed)],
        ]
        t3 = Table(del_data, colWidths=[2.2 * inch, 4.4 * inch])
        t3.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT_GRAY]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
            ("TEXTCOLOR", (1, 3), (1, 3), _RED if report.delivery_failed > 0 else _GREEN),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t3)

    # ── Timeline ──────────────────────────────────────────────────────
    if report.timeline:
        story.append(Paragraph("Event Timeline", section_style))
        tl_data = [["Timestamp", "Event", "Actor", "Detail"]]
        for evt in report.timeline:
            tl_data.append([
                evt.timestamp[:19].replace("T", " "),
                evt.event_type,
                evt.actor_label or "—",
                evt.detail,
            ])
        t4 = Table(tl_data, colWidths=[1.45 * inch, 1.2 * inch, 1.1 * inch, 2.85 * inch])
        t4.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT_GRAY]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(t4)

    # ── Acknowledgement list ──────────────────────────────────────────
    story.append(Paragraph("Acknowledgement List", section_style))
    if report.acknowledgements:
        ack_list = [["User ID", "User", "Title", "Acknowledged At"]]
        for ack in report.acknowledgements:
            ack_list.append([
                str(ack.user_id),
                ack.user_label or "—",
                ack.title or "—",
                ack.acknowledged_at[:19].replace("T", " "),
            ])
        t5 = Table(ack_list, colWidths=[0.7 * inch, 1.9 * inch, 1.5 * inch, 2.5 * inch])
        t5.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT_GRAY]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t5)
    else:
        story.append(Paragraph("No acknowledgements recorded.", body_style))

    # ── Footer ────────────────────────────────────────────────────────
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_MID_GRAY))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Generated by BlueBird Alerts  |  Tenant: {report.tenant_slug}  |  "
        f"Alert #{report.alert_id}  |  This document is for official recordkeeping.",
        small_style,
    ))

    doc.build(story)
    return buf.getvalue()
