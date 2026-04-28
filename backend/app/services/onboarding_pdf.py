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
from reportlab.platypus.flowables import KeepTogether

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

# Badge tuple: (code_text, role_label, qr_png_bytes, assigned_name)
BadgeTuple = Tuple[str, str, bytes, Optional[str]]


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


# ── Badge / Laminated Card PDF ─────────────────────────────────────────────────

# Badge card dimensions: 3.5" × 2.5" (fits 4 per Letter page in 2×2 grid)
_BADGE_W = 3.5 * inch
_BADGE_H = 2.5 * inch
_BADGE_COLS = 2
_BADGE_ROWS = 2
_BADGE_PAD = 0.15 * inch


def _badge_cell(
    code_text: str,
    role_label: str,
    qr_png_bytes: bytes,
    assigned_name: Optional[str],
) -> Table:
    """Build a single badge card as a bordered Table."""
    base = getSampleStyleSheet()
    title_s = ParagraphStyle("BT", parent=base["Normal"], fontSize=7, fontName="Helvetica-Bold",
                              textColor=_BLUE, alignment=1, leading=9)
    name_s = ParagraphStyle("BN", parent=base["Normal"], fontSize=8, fontName="Helvetica-Bold",
                             alignment=1, leading=10, spaceAfter=2)
    role_s = ParagraphStyle("BR", parent=base["Normal"], fontSize=7, textColor=_MID_GRAY,
                             alignment=1, leading=9)
    code_s = ParagraphStyle("BC", parent=base["Normal"], fontSize=9, fontName="Helvetica-Bold",
                             textColor=_BLUE, alignment=1, leading=11)
    inst_s = ParagraphStyle("BI", parent=base["Normal"], fontSize=6, textColor=_MID_GRAY,
                             alignment=1, leading=8)

    qr_img_buf = io.BytesIO(qr_png_bytes)
    qr_img = Image(qr_img_buf, width=1.0 * inch, height=1.0 * inch)
    name_para = Paragraph(assigned_name, name_s) if assigned_name else Spacer(1, 2)

    inner = [
        [Paragraph("BlueBird Alerts", title_s)],
        [name_para],
        [Paragraph(role_label, role_s)],
        [Spacer(1, 4)],
        [qr_img],
        [Paragraph(code_text, code_s)],
        [Paragraph("Scan with BlueBird Alerts app", inst_s)],
    ]
    inner_t = Table(inner, colWidths=[_BADGE_W - 2 * _BADGE_PAD])
    inner_t.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))

    card = Table(
        [[inner_t]],
        colWidths=[_BADGE_W],
        rowHeights=[_BADGE_H],
    )
    card.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1.5, _BLUE),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), _BADGE_PAD),
        ("RIGHTPADDING", (0, 0), (-1, -1), _BADGE_PAD),
        ("TOPPADDING", (0, 0), (-1, -1), _BADGE_PAD),
        ("BOTTOMPADDING", (0, 0), (-1, -1), _BADGE_PAD),
    ]))
    return card


def generate_badge_pdf(
    code_text: str,
    role_label: str,
    qr_png_bytes: bytes,
    assigned_name: Optional[str] = None,
) -> bytes:
    """Single badge card, centered on a Letter page."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=2.0 * inch,
        bottomMargin=2.0 * inch,
    )
    card = _badge_cell(code_text, role_label, qr_png_bytes, assigned_name)
    page_w = _W - 1.7 * inch
    wrapper = Table([[card]], colWidths=[page_w])
    wrapper.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    doc.build([wrapper])
    return buf.getvalue()


def generate_bulk_badges_pdf(badges: List[BadgeTuple]) -> bytes:
    """Pack 4 badges per Letter page in a 2×2 grid."""
    if not badges:
        raise ValueError("badges list is empty")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
    )
    story = []
    per_page = _BADGE_COLS * _BADGE_ROWS  # 4
    col_gap = 0.2 * inch
    grid_col_w = _BADGE_W + col_gap / 2
    for page_start in range(0, len(badges), per_page):
        page_badges = list(badges[page_start: page_start + per_page])
        while len(page_badges) < per_page:
            page_badges.append(None)  # type: ignore[arg-type]
        rows = []
        for row_idx in range(_BADGE_ROWS):
            row_cells = []
            for col_idx in range(_BADGE_COLS):
                b = page_badges[row_idx * _BADGE_COLS + col_idx]
                if b is not None:
                    code_text, role_label, qr_png_bytes, assigned_name = b
                    row_cells.append(_badge_cell(code_text, role_label, qr_png_bytes, assigned_name))
                else:
                    row_cells.append("")
            rows.append(row_cells)
        grid = Table(
            rows,
            colWidths=[grid_col_w, grid_col_w],
            rowHeights=[_BADGE_H + 0.15 * inch, _BADGE_H + 0.15 * inch],
        )
        grid.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), col_gap / 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), col_gap / 4),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(grid)
        if page_start + per_page < len(badges):
            story.append(PageBreak())
    doc.build(story)
    return buf.getvalue()
