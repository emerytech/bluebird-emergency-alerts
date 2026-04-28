from __future__ import annotations

import io
from typing import List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_BLUE = colors.HexColor("#1a56db")
_LIGHT_BLUE = colors.HexColor("#dbeafe")
_MID_GRAY = colors.HexColor("#6b7280")
_LIGHT_GRAY = colors.HexColor("#f3f4f6")
_RED_BANNER = colors.HexColor("#dc2626")

_W, _H = LETTER
_CONTENT_W = _W - 1.7 * inch  # 0.85" margins each side


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "OBTitle",
            parent=base["Heading1"],
            fontSize=22,
            textColor=_BLUE,
            alignment=1,  # center
            spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "OBSubtitle",
            parent=base["Normal"],
            fontSize=12,
            textColor=_MID_GRAY,
            alignment=1,
            spaceAfter=4,
        ),
        "code": ParagraphStyle(
            "OBCode",
            parent=base["Normal"],
            fontSize=28,
            fontName="Helvetica-Bold",
            textColor=_BLUE,
            alignment=1,
            spaceAfter=2,
        ),
        "label": ParagraphStyle(
            "OBLabel",
            parent=base["Normal"],
            fontSize=11,
            textColor=_MID_GRAY,
            alignment=1,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "OBBody",
            parent=base["Normal"],
            fontSize=10,
            leading=14,
            spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "OBSmall",
            parent=base["Normal"],
            fontSize=8,
            textColor=_MID_GRAY,
            leading=11,
            alignment=1,
        ),
        "assigned": ParagraphStyle(
            "OBAssigned",
            parent=base["Normal"],
            fontSize=11,
            leading=15,
            alignment=1,
            spaceAfter=4,
        ),
        "warn": ParagraphStyle(
            "OBWarn",
            parent=base["Normal"],
            fontSize=9,
            textColor=colors.HexColor("#92400e"),
            leading=13,
            alignment=1,
        ),
    }


def _packet_story(
    school_name: str,
    code_text: str,
    role_label: str,
    qr_png_bytes: bytes,
    expires_at: Optional[str],
    label: Optional[str],
    assigned_name: Optional[str],
    assigned_email: Optional[str],
    s: dict,
) -> list:
    story = []

    # Header
    story.append(Paragraph("BlueBird Alerts", s["title"]))
    story.append(Paragraph("Staff Onboarding Packet", s["subtitle"]))
    story.append(Paragraph(school_name, s["subtitle"]))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1.5, color=_BLUE))
    story.append(Spacer(1, 14))

    # QR code — centered via 1-cell table
    img_buf = io.BytesIO(qr_png_bytes)
    qr_img = Image(img_buf, width=2.4 * inch, height=2.4 * inch)
    qr_table = Table([[qr_img]], colWidths=[_CONTENT_W])
    qr_table.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    story.append(qr_table)
    story.append(Spacer(1, 10))

    # Access code
    story.append(Paragraph(code_text, s["code"]))
    story.append(Paragraph(f"Role: {role_label}", s["label"]))

    if label:
        story.append(Paragraph(f"Group: {label}", s["label"]))

    if expires_at:
        exp_display = expires_at[:10] if len(expires_at) >= 10 else expires_at
        story.append(Paragraph(f"Expires: {exp_display}", s["label"]))

    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="60%", thickness=0.5, color=_MID_GRAY))
    story.append(Spacer(1, 10))

    # Pre-assignment block
    if assigned_name or assigned_email:
        assign_lines = ["<b>Assigned To</b>"]
        if assigned_name:
            assign_lines.append(assigned_name)
        if assigned_email:
            assign_lines.append(assigned_email)
        story.append(Paragraph("<br/>".join(assign_lines), s["assigned"]))
        story.append(Spacer(1, 4))
        # Warning: single-use
        story.append(Paragraph(
            "This code is pre-assigned. Please do not share it with anyone else.",
            s["warn"],
        ))
        story.append(Spacer(1, 8))

    # Instructions table
    instructions = [
        ["Step", "Instructions"],
        ["1", "Download the BlueBird Alerts app from the App Store or Google Play."],
        ["2", "Open the app and tap \"Join with Access Code\"."],
        ["3", "Scan the QR code above or enter the code manually."],
        ["4", "Complete your profile setup and confirm your school."],
        ["5", "You are all set. You will receive emergency alerts for your school."],
    ]
    inst_table = Table(instructions, colWidths=[0.45 * inch, _CONTENT_W - 0.45 * inch])
    inst_table.setStyle(TableStyle([
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
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
    ]))
    story.append(inst_table)
    story.append(Spacer(1, 14))

    # Footer
    story.append(HRFlowable(width="100%", thickness=0.5, color=_MID_GRAY))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"BlueBird Alerts  |  {school_name}  |  Keep this document confidential.",
        s["small"],
    ))

    return story


def generate_packet_pdf(
    school_name: str,
    code_text: str,
    role_label: str,
    qr_png_bytes: bytes,
    expires_at: Optional[str] = None,
    label: Optional[str] = None,
    assigned_name: Optional[str] = None,
    assigned_email: Optional[str] = None,
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.85 * inch,
        bottomMargin=0.85 * inch,
    )
    s = _styles()
    story = _packet_story(
        school_name, code_text, role_label, qr_png_bytes,
        expires_at, label, assigned_name, assigned_email, s,
    )
    doc.build(story)
    return buf.getvalue()


# Each packet tuple: (code_text, role_label, qr_png_bytes, expires_at, label, assigned_name, assigned_email)
PacketTuple = Tuple[str, str, bytes, Optional[str], Optional[str], Optional[str], Optional[str]]


def generate_bulk_packets_pdf(packets: List[PacketTuple], school_name: str) -> bytes:
    if not packets:
        raise ValueError("packets list is empty")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.85 * inch,
        bottomMargin=0.85 * inch,
    )
    s = _styles()
    story = []
    for idx, packet in enumerate(packets):
        code_text, role_label, qr_png_bytes, expires_at, label, assigned_name, assigned_email = packet
        story.extend(_packet_story(
            school_name, code_text, role_label, qr_png_bytes,
            expires_at, label, assigned_name, assigned_email, s,
        ))
        if idx < len(packets) - 1:
            story.append(PageBreak())
    doc.build(story)
    return buf.getvalue()
