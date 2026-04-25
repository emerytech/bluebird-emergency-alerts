from __future__ import annotations

from collections import Counter
from functools import lru_cache
from html import escape
import json
from pathlib import Path
from typing import Mapping, Optional, Sequence

from app.services.alert_log import AlertRecord
from app.services.audit_log_service import AuditEventRecord
from app.services.alarm_store import AlarmStateRecord
from app.services.device_registry import RegisteredDevice
from app.services.incident_store import TeamAssistRecord
from app.services.quiet_period_store import QuietPeriodRecord
from app.services.report_store import AdminMessageRecord, BroadcastUpdateRecord, ReportRecord
from app.services.school_registry import SchoolRecord
from app.services.user_store import UserRecord


LOGO_PATH = "/static/bluebird-alert-logo.png"


def _favicon_tags() -> str:
    return (
        f'<link rel="icon" type="image/png" href="{LOGO_PATH}" />'
        f'<link rel="apple-touch-icon" href="{LOGO_PATH}" />'
    )


def _brand_mark() -> str:
    return f'<div class="brand-mark"><img src="{LOGO_PATH}" alt="BlueBird Alerts logo" /></div>'


@lru_cache(maxsize=1)
def _load_design_tokens() -> Mapping[str, object]:
    token_path = Path(__file__).resolve().parents[3] / "design" / "tokens.json"
    if not token_path.exists():
        return {}
    try:
        parsed = json.loads(token_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def _token_lookup(path: str) -> Optional[str]:
    source = _load_design_tokens()
    current: object = source
    for segment in path.split("."):
        if not isinstance(current, Mapping):
            return None
        key_candidates = (
            segment,
            segment.replace("-", "_"),
            segment.replace("_", "-"),
        )
        next_key = next((candidate for candidate in key_candidates if candidate in current), None)
        if next_key is None:
            return None
        current = current[next_key]
    if isinstance(current, str):
        value = current.strip()
        return value or None
    if isinstance(current, Mapping):
        for key in ("light", "default", "value", "base"):
            value = current.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _theme_vars(theme: Optional[Mapping[str, str]] = None) -> str:
    resolved = {
        "background_light": _token_lookup("colors.background.light") or _token_lookup("color.background.light") or "#eef5ff",
        "background_dark": _token_lookup("colors.background.dark") or _token_lookup("color.background.dark") or "#dce9ff",
        "card": _token_lookup("colors.card") or _token_lookup("color.card") or "#ffffff",
        "input_bg": _token_lookup("colors.input_background") or _token_lookup("color.input_background") or "#39404f",
        "text_primary": _token_lookup("colors.text_primary") or _token_lookup("color.text_primary") or "#10203f",
        "text_secondary": _token_lookup("colors.text_secondary") or _token_lookup("color.text_secondary") or "#5d7398",
        "border": _token_lookup("colors.border") or _token_lookup("color.border") or "rgba(18, 52, 120, 0.10)",
        "accent": _token_lookup("colors.primary") or _token_lookup("color.primary") or "#1b5fe4",
        "accent_strong": _token_lookup("colors.primary_strong") or _token_lookup("color.primary_strong") or "#2f84ff",
        "sidebar_start": _token_lookup("colors.sidebar.start") or _token_lookup("color.sidebar.start") or "#092054",
        "sidebar_end": _token_lookup("colors.sidebar.end") or _token_lookup("color.sidebar.end") or "#071536",
        "status_success": _token_lookup("colors.status.success") or _token_lookup("color.status.success") or "#16a34a",
        "status_warning": _token_lookup("colors.status.warning") or _token_lookup("color.status.warning") or "#b45309",
        "status_info": _token_lookup("colors.status.info") or _token_lookup("color.status.info") or "#1d4ed8",
        "status_quiet": _token_lookup("colors.status.quiet") or _token_lookup("color.status.quiet") or "#8e3beb",
        "status_danger": _token_lookup("colors.button.danger") or _token_lookup("color.button.danger") or _token_lookup("colors.danger") or _token_lookup("color.danger") or "#dc2626",
    }
    if theme:
        for key in ("accent", "accent_strong", "sidebar_start", "sidebar_end"):
            value = str(theme.get(key, "") or "").strip()
            if value:
                resolved[key] = value
    return f"""
    :root {{
      --color-background-light: {resolved["background_light"]};
      --color-background-dark: {resolved["background_dark"]};
      --color-card: {resolved["card"]};
      --color-input-background: {resolved["input_bg"]};
      --color-text-primary: {resolved["text_primary"]};
      --color-text-secondary: {resolved["text_secondary"]};
      --color-border: {resolved["border"]};
      --color-primary: {resolved["accent"]};
      --color-primary-strong: {resolved["accent_strong"]};
      --color-sidebar-start: {resolved["sidebar_start"]};
      --color-sidebar-end: {resolved["sidebar_end"]};
      --bg: var(--color-background-light);
      --bg-deep: var(--color-background-dark);
      --panel: color-mix(in srgb, var(--color-card) 90%, transparent);
      --panel-strong: rgba(255, 255, 255, 0.98);
      --border: var(--color-border);
      --text: var(--color-text-primary);
      --muted: var(--color-text-secondary);
      --accent: var(--color-primary);
      --accent-strong: var(--color-primary-strong);
      --accent-soft: color-mix(in srgb, var(--accent) 14%, transparent);
      --accent-soft-strong: color-mix(in srgb, var(--accent) 22%, transparent);
      --nav-bg: linear-gradient(180deg, var(--color-sidebar-start) 0%, var(--color-sidebar-end) 100%);
      --nav-border: rgba(255, 255, 255, 0.10);
      --nav-text: rgba(248, 250, 252, 0.96);
      --nav-muted: rgba(148, 163, 184, 0.82);
      --brand-glow: color-mix(in srgb, var(--accent-strong) 18%, transparent);
      --brand-glow-soft: color-mix(in srgb, var(--accent) 10%, transparent);
      --success: {resolved["status_success"]};
      --success-soft: color-mix(in srgb, var(--success) 16%, transparent);
      --danger: {resolved["status_danger"]};
      --danger-soft: color-mix(in srgb, var(--danger) 16%, transparent);
      --warning: {resolved["status_warning"]};
      --info: {resolved["status_info"]};
      --quiet: {resolved["status_quiet"]};
      --danger-strong: color-mix(in srgb, var(--danger) 78%, #000 22%);
      --shadow: 0 14px 36px rgba(22, 53, 117, 0.12);
      --radius: 24px;
      --radius-soft: 18px;
      --headline: "Avenir Next", "Segoe UI Variable Display", "SF Pro Display", "Trebuchet MS", sans-serif;
      --body: "Avenir Next", "Segoe UI Variable Text", "SF Pro Text", "Helvetica Neue", sans-serif;
    }}
    """


def _base_styles(theme: Optional[Mapping[str, str]] = None) -> str:
    return _theme_vars(theme) + """
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; color: var(--text); font-family: var(--body); }
    body {
      min-height: 100vh;
      background:
        radial-gradient(circle at top left, var(--brand-glow), transparent 26%),
        radial-gradient(circle at 80% 10%, var(--brand-glow-soft), transparent 20%),
        radial-gradient(circle at 50% 100%, rgba(47, 132, 255, 0.08), transparent 28%),
        linear-gradient(180deg, var(--bg) 0%, var(--bg-deep) 100%);
    }
    a { color: var(--accent); text-decoration: none; }
    .page-shell { max-width: 1480px; margin: 0 auto; padding: 24px; }
    .login-shell {
      min-height: 100vh;
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(360px, 460px);
      gap: 20px;
      align-items: stretch;
      padding: 24px;
    }
    .hero-card, .panel, .login-panel, .brand-block, .signal-card, .command-section {
      border: 1px solid var(--border);
      background: var(--panel);
      backdrop-filter: blur(14px);
      -webkit-backdrop-filter: blur(14px);
      box-shadow: var(--shadow);
      border-radius: var(--radius);
    }
    .hero-card {
      padding: 32px;
      display: grid;
      gap: 18px;
      align-content: space-between;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.98), rgba(245,250,255,0.94)),
        linear-gradient(140deg, rgba(27, 95, 228, 0.08), rgba(47, 132, 255, 0.03));
    }
    .eyebrow {
      margin: 0;
      color: var(--accent);
      font-size: 0.76rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    h1, h2, h3 { margin: 0; font-family: var(--headline); }
    h1 { font-size: 2.4rem; line-height: 1.02; }
    h2 { font-size: 1.25rem; }
    .hero-copy, .muted, .card-copy, .meta { color: var(--muted); line-height: 1.55; }
    .hero-metrics, .status-row { display: flex; flex-wrap: wrap; gap: 12px; }
    .metric-pill, .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 38px;
      padding: 0 14px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.86);
      font-size: 0.95rem;
    }
    .status-pill.ok { color: var(--success); background: var(--success-soft); }
    .status-pill.danger { color: var(--danger); background: var(--danger-soft); }
    .status-pill.warn { color: var(--warning); background: color-mix(in srgb, var(--warning) 15%, white); }
    .login-panel { padding: 28px; display: grid; gap: 18px; align-content: center; }
    .stack { display: grid; gap: 14px; }
    .field { display: grid; gap: 6px; }
    .field label { font-size: 0.92rem; color: var(--muted); }
    .field input, .field select, .field textarea {
      min-height: 46px;
      width: 100%;
      border-radius: 14px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.95);
      padding: 0 14px;
      font: inherit;
      color: var(--text);
    }
    .field textarea { min-height: 110px; padding-top: 12px; padding-bottom: 12px; resize: vertical; }
    .button-row { display: flex; flex-wrap: wrap; gap: 12px; }
    .button, button {
      appearance: none;
      border: 0;
      border-radius: 14px;
      min-height: 46px;
      padding: 0 18px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }
    .button-primary { background: linear-gradient(180deg, var(--accent-strong), var(--accent)); color: #fff; }
    .button-secondary { background: rgba(255,255,255,0.9); color: var(--text); border: 1px solid var(--border); }
    .button-danger { background: linear-gradient(180deg, color-mix(in srgb, var(--danger) 82%, #fff 18%), var(--danger-strong)); color: #fff; }
    .button-danger-outline {
      background: color-mix(in srgb, var(--danger) 10%, #fff 90%);
      color: var(--danger);
      border: 1px solid color-mix(in srgb, var(--danger) 20%, transparent);
    }
    .flash {
      padding: 14px 16px;
      border-radius: 16px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.95);
      color: var(--text);
    }
    .flash.error {
      border-color: color-mix(in srgb, var(--danger) 24%, transparent);
      background: color-mix(in srgb, var(--danger) 10%, #fff 90%);
      color: color-mix(in srgb, var(--danger) 72%, #000 28%);
    }
    .flash.success {
      border-color: color-mix(in srgb, var(--success) 24%, transparent);
      background: color-mix(in srgb, var(--success) 10%, #fff 90%);
      color: color-mix(in srgb, var(--success) 72%, #000 28%);
    }
    .app-shell {
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
      gap: 18px;
      align-items: start;
    }
    .sidebar, .content-stack { display: grid; gap: 18px; }
    .sidebar {
      position: sticky;
      top: 24px;
    }
    .nav-panel {
      padding: 22px;
      border-radius: var(--radius);
      border: 1px solid var(--nav-border);
      background:
        radial-gradient(circle at top left, var(--brand-glow), transparent 22%),
        var(--nav-bg);
      color: var(--nav-text);
      box-shadow: var(--shadow);
    }
    .brand-card, .panel, .command-section { padding: 22px; }
    .brand-block {
      display: flex;
      gap: 16px;
      padding: 18px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.08);
    }
    .brand-mark {
      width: 58px;
      height: 58px;
      border-radius: 16px;
      display: grid;
      place-items: center;
      overflow: hidden;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.20);
      box-shadow: 0 10px 24px rgba(27, 95, 228, 0.18);
      flex: 0 0 auto;
    }
    .brand-mark img {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
    }
    .brand-text h1, .brand-text h2, .brand-text h3, .brand-text p,
    .signal-card h1, .signal-card h2, .signal-card h3, .signal-card p, .signal-card span,
    .nav-panel .nav-label, .nav-panel .eyebrow {
      color: var(--nav-text);
    }
    .nav-panel .hero-copy, .nav-panel .card-copy, .nav-panel .mini-copy, .nav-panel .signal-copy {
      color: var(--nav-muted);
    }
    .nav-label {
      margin: 0 0 8px;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-size: 0.7rem;
      color: var(--accent-strong);
    }
    .nav-group { display: grid; gap: 10px; }
    .nav-list { display: grid; gap: 10px; margin-top: 16px; }
    .nav-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 14px 16px;
      border-radius: 16px;
      color: var(--nav-text);
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.08);
      transition: transform 180ms ease, border-color 180ms ease, background 180ms ease;
    }
    .nav-badge {
      display: inline-flex;
      min-width: 20px;
      min-height: 20px;
      align-items: center;
      justify-content: center;
      padding: 0 6px;
      border-radius: 999px;
      background: var(--danger);
      color: #fff;
      font-size: 0.72rem;
      font-weight: 800;
      line-height: 1;
    }
    .nav-item:hover {
      transform: translateX(4px);
      border-color: rgba(59, 130, 246, 0.42);
      background: var(--accent-soft-strong);
    }
    .nav-item-active {
      border-color: rgba(147, 197, 253, 0.9);
      background: rgba(255,255,255,0.14);
      box-shadow: inset 0 0 0 1px rgba(147, 197, 253, 0.35);
    }
    .signal-card {
      display: grid;
      gap: 14px;
      padding: 18px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.08);
    }
    .signal-card .button-secondary, .signal-card .button {
      background: rgba(255,255,255,0.08);
      color: var(--nav-text);
      border: 1px solid rgba(255,255,255,0.08);
    }
    .workspace { display: grid; gap: 18px; }
    .command-section {
      background:
        linear-gradient(135deg, rgba(27, 95, 228, 0.06), transparent 42%),
        var(--panel);
    }
    .hero-band {
      background:
        linear-gradient(135deg, rgba(27, 95, 228, 0.14), transparent 42%),
        var(--panel-strong);
    }
    .hero-band { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
    .grid {
      display: grid;
      gap: 18px;
      grid-template-columns: repeat(12, minmax(0, 1fr));
    }
    .span-12 { grid-column: span 12; }
    .span-8 { grid-column: span 8; }
    .span-7 { grid-column: span 7; }
    .span-6 { grid-column: span 6; }
    .span-5 { grid-column: span 5; }
    .span-4 { grid-column: span 4; }
    .metrics-grid {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    }
    .metric-card, .user-card {
      border: 1px solid var(--border);
      border-radius: var(--radius-soft);
      background: rgba(255,255,255,0.92);
      padding: 16px;
    }
    .metric-card strong, .user-card strong { color: var(--text); }
    .metric-value { font-size: 2rem; font-weight: 800; margin-top: 8px; }
    .panel-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      margin-bottom: 16px;
    }
    .user-grid {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(310px, 1fr));
    }
    .form-grid {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    }
    .checkbox-row {
      display: flex;
      align-items: center;
      gap: 10px;
      min-height: 46px;
      border-radius: 14px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.9);
      padding: 0 14px;
    }
    .checkbox-row input { width: 18px; height: 18px; }
    table { width: 100%; border-collapse: collapse; }
    th, td {
      padding: 12px 10px;
      text-align: left;
      border-top: 1px solid var(--border);
      vertical-align: top;
      font-size: 0.95rem;
    }
    th { color: var(--muted); border-top: 0; }
    code {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      background: rgba(15, 23, 42, 0.05);
      padding: 2px 6px;
      border-radius: 8px;
    }
    .mini-copy { color: var(--muted); font-size: 0.88rem; line-height: 1.45; }
    .shell-actions { display: grid; gap: 12px; }
    @media (max-width: 1100px) {
      .app-shell, .login-shell { grid-template-columns: 1fr; }
      .sidebar { position: static; }
      .span-8, .span-7, .span-6, .span-5, .span-4 { grid-column: span 12; }
    }
    """


def _render_flash(message: Optional[str], kind: str = "success") -> str:
    if not message:
        return ""
    return f'<div class="flash {escape(kind)}">{escape(message)}</div>'


def _render_report_rows(reports: Sequence[ReportRecord]) -> str:
    if not reports:
        return '<tr><td colspan="4" class="mini-copy">No user reports yet.</td></tr>'
    rows = []
    for report in reports:
        note_text = report.note or (f"User #{report.user_id}" if report.user_id is not None else "No note")
        rows.append(
            f"<tr><td>{report.id}</td><td>{escape(report.created_at)}</td><td>{escape(report.category.replace('_', ' '))}</td><td>{escape(note_text)}</td></tr>"
        )
    return "".join(rows)


def _render_broadcast_rows(broadcasts: Sequence[BroadcastUpdateRecord]) -> str:
    if not broadcasts:
        return '<tr><td colspan="3" class="mini-copy">No admin updates posted yet.</td></tr>'
    rows = []
    for item in broadcasts:
        actor = item.admin_label or (str(item.admin_user_id) if item.admin_user_id is not None else "admin")
        rows.append(
            f"<tr><td>{escape(item.created_at)}</td><td>{escape(actor)}</td><td>{escape(item.message)}</td></tr>"
        )
    return "".join(rows)


def _render_admin_message_rows(messages: Sequence[AdminMessageRecord], school_path_prefix: str) -> str:
    if not messages:
        return '<tr><td colspan="7" class="mini-copy">No user messages yet.</td></tr>'
    prefix = escape(school_path_prefix)
    rows = []
    for item in messages:
        sender = item.sender_label or (f"User #{item.sender_user_id}" if item.sender_user_id is not None else "Unknown")
        response_block = (
            f"<div><strong>{escape(item.response_message or '')}</strong></div>"
            f"<div class=\"mini-copy\">{escape(item.response_created_at or '')} • {escape(item.response_by_label or 'admin')}</div>"
            if item.response_message
            else "<span class=\"mini-copy\">No reply yet.</span>"
        )
        action_html = (
            f"""
            <form method="post" action="{prefix}/admin/messages/{item.id}/reply" class="stack">
              <div class="field">
                <input name="message" placeholder="Reply to this user message..." />
              </div>
              <div class="button-row">
                <button class="button button-secondary" type="submit">Reply</button>
              </div>
            </form>
            """
            if item.status == "open"
            else "<span class=\"mini-copy\">Answered</span>"
        )
        rows.append(
            "<tr>"
            f"<td>{item.id}</td>"
            f"<td>{escape(item.created_at)}</td>"
            f"<td>{escape(sender)}</td>"
            f"<td>{escape(item.message)}</td>"
            f"<td>{escape(item.status)}</td>"
            f"<td>{response_block}</td>"
            f"<td>{action_html}</td>"
            "</tr>"
        )
    return "".join(rows)


def _render_quiet_period_rows(
    records: Sequence[QuietPeriodRecord],
    users: Sequence[UserRecord],
    school_path_prefix: str,
    *,
    tenant_label: Optional[str] = None,
    include_actions: bool = True,
) -> str:
    if not records:
        return '<tr><td colspan="7" class="mini-copy">No matching quiet period requests.</td></tr>'
    user_names = {user.id: user.name for user in users}
    prefix = escape(school_path_prefix)
    rows = []
    for item in records:
        approver = item.approved_by_label or (f"User #{item.approved_by_user_id}" if item.approved_by_user_id is not None else "—")
        action_html = "—"
        if include_actions and item.status == "approved":
            action_html = f"""
            <div class="button-row">
              <form method="post" action="{prefix}/admin/quiet-periods/{item.id}/clear" onsubmit="return confirm('Remove this quiet period?');">
                <button class="button button-danger-outline" type="submit">Remove</button>
              </form>
              <form method="post" action="{prefix}/admin/quiet-periods/{item.id}/hide">
                <button class="button button-secondary" type="submit">Hide from main view</button>
              </form>
            </div>
            """
        elif include_actions and item.status == "pending":
            action_html = f"""
            <div class="button-row">
              <form method="post" action="{prefix}/admin/quiet-periods/{item.id}/approve">
                <button class="button button-secondary" type="submit">Approve</button>
              </form>
              <form method="post" action="{prefix}/admin/quiet-periods/{item.id}/deny" onsubmit="return confirm('Deny this quiet period request?');">
                <button class="button button-danger-outline" type="submit">Deny</button>
              </form>
              <form method="post" action="{prefix}/admin/quiet-periods/{item.id}/hide">
                <button class="button button-secondary" type="submit">Hide from main view</button>
              </form>
            </div>
            """
        elif not include_actions:
            action_html = '<span class="mini-copy">History</span>'
        tenant_note = f'<div class="mini-copy">Tenant: {escape(tenant_label)}</div>' if tenant_label else ""
        rows.append(
            f"<tr><td>{escape(user_names.get(item.user_id, f'User #{item.user_id}'))}{tenant_note}</td><td>{escape(item.status)}</td><td>{escape(item.reason or '—')}</td><td>{escape(approver)}</td><td>{escape(item.requested_at)}</td><td>{escape(item.expires_at or '—')}</td><td>{action_html}</td></tr>"
        )
    return "".join(rows)


def _render_request_help_rows(
    records: Sequence[TeamAssistRecord],
    users: Sequence[UserRecord],
    school_path_prefix: str,
    *,
    tenant_label: Optional[str] = None,
    include_actions: bool = True,
) -> str:
    if not records:
        return '<tr><td colspan="7" class="mini-copy">No active help requests.</td></tr>'
    user_names = {user.id: user.name for user in users}
    prefix = escape(school_path_prefix)
    rows = []
    for item in records:
        created_by = user_names.get(item.created_by, f"User #{item.created_by}")
        handled_by = item.acted_by_label or (f"User #{item.acted_by_user_id}" if item.acted_by_user_id is not None else "—")
        action_html = "—"
        if include_actions:
            action_html = f"""
            <div class="button-row">
              <form method="post" action="{prefix}/admin/request-help/{item.id}/clear" onsubmit="return confirm('Clear this help request now? This does not require requester confirmation.');">
                <button class="button button-danger-outline" type="submit">Clear Request</button>
              </form>
            </div>
            """
        tenant_note = f'<div class="mini-copy">Tenant: {escape(tenant_label)}</div>' if tenant_label else ""
        rows.append(
            "<tr>"
            f"<td>{item.id}</td>"
            f"<td>{escape(item.created_at)}</td>"
            f"<td>{escape(item.type)}</td>"
            f"<td>{escape(created_by)}{tenant_note}</td>"
            f"<td>{escape(item.status)}</td>"
            f"<td>{escape(handled_by)}</td>"
            f"<td>{action_html}</td>"
            "</tr>"
        )
    return "".join(rows)


def render_login_page(
    *,
    message: Optional[str] = None,
    error: Optional[str] = None,
    setup_mode: bool,
    school_name: str = "School",
    school_slug: str = "default",
    school_path_prefix: str = "/default",
    setup_pin_required: bool = False,
    theme: Optional[Mapping[str, str]] = None,
) -> str:
    heading = "Create the first BlueBird admin" if setup_mode else "Sign in to BlueBird Admin"
    button = "Create admin account" if setup_mode else "Sign in"
    action = f"{school_path_prefix}/admin/setup" if setup_mode else f"{school_path_prefix}/admin/login"
    helper = (
        (
            "This first account becomes the dashboard operator account. Enter the setup PIN from the platform admin, then create the first dashboard admin."
            if setup_pin_required
            else "This first account becomes the dashboard operator account. After that, you can create and edit the rest of the school users from inside the portal."
        )
        if setup_mode
        else "Use your admin credentials to manage users, alarms, devices, and the audit trail."
    )
    setup_tip = (
        f'<div class="flash success">First-time setup for <strong>{escape(school_name)}</strong>. Create the first admin for this school at <code>{escape(school_path_prefix)}/admin</code>.{" A school setup PIN is required for this step." if setup_pin_required else ""}</div>'
        if setup_mode
        else ""
    )
    pin_field = """
      <div class="field">
        <label for="setup_pin">School setup PIN</label>
        <input id="setup_pin" name="setup_pin" type="password" autocomplete="one-time-code" />
      </div>
    """ if setup_mode and setup_pin_required else ""
    extra_fields = """
      <div class="field">
        <label for="name">Full name</label>
        <input id="name" name="name" autocomplete="name" />
      </div>
    """ if setup_mode else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BlueBird Admin Login</title>
  {_favicon_tags()}
  <style>{_base_styles(theme)}</style>
</head>
<body>
  <main class="login-shell">
    <section class="hero-card">
      <div class="brand-block">
        {_brand_mark()}
        <div class="stack brand-text">
        <p class="eyebrow">School Safety Command Deck</p>
        <h1>BlueBird Alerts admin portal</h1>
        <p class="hero-copy">
          A calm command surface for alarm activation, account management, recent alert review, and device readiness.
          The visual system is intentionally neutral so it can be tuned later to match a school's mascot, colors, or district identity.
        </p>
        <p class="mini-copy">School: <strong>{escape(school_name)}</strong> ({escape(school_slug)})</p>
        </div>
      </div>
      <div class="hero-metrics">
        <span class="metric-pill"><strong>Admin login</strong> session-based</span>
        <span class="metric-pill"><strong>User roles</strong> admin + standard</span>
        <span class="metric-pill"><strong>Alarm control</strong> tracked + auditable</span>
      </div>
    </section>
    <section class="login-panel">
      <div class="stack">
        <p class="eyebrow">Operator Access</p>
        <h2>{escape(heading)}</h2>
        <p class="card-copy">{escape(helper)}</p>
      </div>
      {setup_tip}
      {_render_flash(message, "success")}
      {_render_flash(error, "error")}
      <form method="post" action="{action}" class="stack">
        {extra_fields}
        {pin_field}
        <div class="field">
          <label for="login_name">Username</label>
          <input id="login_name" name="login_name" autocomplete="username" />
        </div>
        <div class="field">
          <label for="password">Password</label>
          <input id="password" name="password" type="password" autocomplete="current-password" />
        </div>
        <div class="button-row">
          <button class="button button-primary" type="submit">{escape(button)}</button>
        </div>
      </form>
    </section>
  </main>
</body>
</html>"""


def render_super_admin_login_page(*, message: Optional[str] = None, error: Optional[str] = None) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BlueBird Super Admin</title>
  {_favicon_tags()}
  <style>{_base_styles()}</style>
</head>
<body>
  <main class="login-shell">
    <section class="hero-card">
      <div class="brand-block">
        {_brand_mark()}
        <div class="stack brand-text">
        <p class="eyebrow">Platform Control</p>
        <h1>BlueBird super admin</h1>
        <p class="hero-copy">Provision schools, hand out school-specific admin URLs, and keep the multi-school platform organized from one place.</p>
        </div>
      </div>
      <div class="hero-metrics">
        <span class="metric-pill"><strong>School setup</strong> centralized</span>
        <span class="metric-pill"><strong>Tenant routing</strong> path based</span>
        <span class="metric-pill"><strong>Isolation</strong> per-school data</span>
      </div>
    </section>
    <section class="login-panel">
      <div class="stack">
        <p class="eyebrow">Platform Access</p>
        <h2>Sign in to super admin</h2>
        <p class="card-copy">Use the platform credentials from the backend environment to manage school creation and setup.</p>
      </div>
      {_render_flash(message, "success")}
      {_render_flash(error, "error")}
      <form method="post" action="/super-admin/login" class="stack">
        <div class="field">
          <label for="login_name">Username</label>
          <input id="login_name" name="login_name" autocomplete="username" />
        </div>
        <div class="field">
          <label for="password">Password</label>
          <input id="password" name="password" type="password" autocomplete="current-password" />
        </div>
        <div class="button-row">
          <button class="button button-primary" type="submit">Sign in</button>
        </div>
      </form>
    </section>
  </main>
</body>
</html>"""


def render_totp_page(
    *,
    action: str,
    cancel_action: str,
    title: str,
    eyebrow: str,
    heading: str,
    helper: str,
    user_label: str,
    message: Optional[str] = None,
    error: Optional[str] = None,
    theme: Optional[Mapping[str, str]] = None,
    allow_trust_device: bool = False,
) -> str:
    trust_device_html = ""
    if allow_trust_device:
        trust_device_html = """
        <label style="display:flex; align-items:flex-start; gap:10px; font-size:0.96rem; color:var(--muted);">
          <input type="checkbox" name="trust_device" value="1" style="margin-top:3px; min-height:auto; width:auto;" />
          <span>Trust this device for 14 days</span>
        </label>
        """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  {_favicon_tags()}
  <style>{_base_styles(theme)}</style>
</head>
<body>
  <main class="login-shell">
    <section class="hero-card">
      <div class="brand-block">
        {_brand_mark()}
        <div class="stack brand-text">
        <p class="eyebrow">{escape(eyebrow)}</p>
        <h1>{escape(heading)}</h1>
        <p class="hero-copy">{escape(helper)}</p>
        </div>
      </div>
    </section>
    <section class="login-panel">
      <div class="stack">
        <p class="eyebrow">Two-Factor Authentication</p>
        <h2>Enter your 6-digit code</h2>
        <p class="card-copy">Account: <strong>{escape(user_label)}</strong></p>
      </div>
      {_render_flash(message, "success")}
      {_render_flash(error, "error")}
      <form method="post" action="{action}" class="stack">
        <div class="field">
          <label for="code">Authenticator code</label>
          <input id="code" name="code" inputmode="numeric" pattern="[0-9]*" maxlength="6" autocomplete="one-time-code" />
        </div>
        {trust_device_html}
        <div class="button-row">
          <button class="button button-primary" type="submit">Verify code</button>
          <a class="button button-secondary" href="{cancel_action}">Cancel</a>
        </div>
      </form>
    </section>
  </main>
</body>
</html>"""


def render_super_admin_page(
    *,
    base_domain: str,
    school_rows: Sequence[Mapping[str, object]],
    billing_rows: Sequence[Mapping[str, object]],
    platform_activity_rows: Sequence[Mapping[str, str]],
    git_pull_configured: bool,
    server_info: Mapping[str, str],
    super_admin_login_name: str,
    totp_enabled: bool,
    totp_setup_secret: Optional[str] = None,
    totp_setup_uri: Optional[str] = None,
    flash_message: Optional[str] = None,
    flash_error: Optional[str] = None,
    active_section: str = "schools",
) -> str:
    rows = "".join(
        (
            "<tr>"
            f"<td>{escape(str(item['name']))}</td>"
            f"<td><code>{escape(str(item['slug']))}</code></td>"
            f"<td><a href=\"{escape(str(item['admin_url']))}\" target=\"_blank\">{escape(str(item['admin_url_label']))}</a>"
            f"<div class=\"mini-copy\">Mobile/API base: <code>{escape(str(item['api_base_label']))}</code></div></td>"
            f"<td>{escape(str(item['setup_status']))}<div class=\"mini-copy\">{escape(str(item['setup_hint']))}</div>{str(item['access_controls_html'])}{str(item['pin_controls_html'])}{str(item['theme_controls_html'])}</td>"
            f"<td>{'Active' if bool(item['is_active']) else 'Inactive'}</td>"
            "</tr>"
        )
        for item in school_rows
    ) or '<tr><td colspan="5" class="mini-copy">No schools yet.</td></tr>'
    security_feedback = f"{_render_flash(flash_message, 'success')}{_render_flash(flash_error, 'error')}"
    platform_rows = "".join(
        (
            "<tr>"
            f"<td>{escape(str(item.get('created_at', '')))}</td>"
            f"<td>{escape(str(item.get('school', '')))}</td>"
            f"<td>{escape(str(item.get('action', '')))}</td>"
            f"<td>{escape(str(item.get('actor', '')))}</td>"
            f"<td>{escape(str(item.get('details', '')))}</td>"
            "</tr>"
        )
        for item in platform_activity_rows
    ) or '<tr><td colspan="5" class="mini-copy">No platform-super-admin activity recorded yet.</td></tr>'
    billing_table_rows = "".join(
        (
            "<tr>"
            f"<td>{escape(str(item.get('name', '')))}<div class=\"mini-copy\"><code>{escape(str(item.get('slug', '')))}</code></div></td>"
            f"<td>{escape(str(item.get('plan_id', '—')))}</td>"
            f"<td><span class=\"status-pill {escape(str(item.get('billing_status_class', '')))}\">{escape(str(item.get('billing_status', 'unknown')))}</span></td>"
            f"<td>{escape(str(item.get('trial_end', '—')))}</td>"
            f"<td>{escape(str(item.get('renewal_date', '—')))}</td>"
            f"<td><span class=\"status-pill {escape(str(item.get('free_override_class', '')))}\">{escape(str(item.get('free_override_label', 'Disabled')))}</span><div class=\"mini-copy\">{escape(str(item.get('free_reason', '—')))}</div></td>"
            f"<td><code>{escape(str(item.get('stripe_customer_id', '—')))}</code><div class=\"mini-copy\"><code>{escape(str(item.get('stripe_subscription_id', '—')))}</code></div></td>"
            f"<td>"
            f"<form method=\"post\" action=\"{escape(str(item.get('start_trial_action', '#')))}\" class=\"stack\" style=\"margin-bottom:8px;\">"
            f"<div class=\"button-row\" style=\"justify-content:flex-start;\">"
            f"<input name=\"duration_days\" type=\"number\" min=\"1\" max=\"365\" value=\"14\" style=\"max-width:120px;\" />"
            f"<button class=\"button button-secondary\" type=\"submit\">Start Trial</button>"
            f"</div>"
            f"</form>"
            f"<form method=\"post\" action=\"{escape(str(item.get('grant_free_action', '#')))}\" class=\"stack\" style=\"margin-bottom:8px;\">"
            f"<div class=\"field\">"
            f"<input name=\"free_reason\" placeholder=\"Optional free-access reason\" />"
            f"</div>"
            f"<div class=\"button-row\" style=\"justify-content:flex-start;\">"
            f"<button class=\"button button-primary\" type=\"submit\">Grant Free Access</button>"
            f"</div>"
            f"</form>"
            f"<form method=\"post\" action=\"{escape(str(item.get('remove_free_action', '#')))}\" onsubmit=\"return confirm('Remove free access for {escape(str(item.get('name', 'this school')))}?');\">"
            f"<div class=\"button-row\" style=\"justify-content:flex-start;\">"
            f"<button class=\"button button-danger-outline\" type=\"submit\">Remove Free Access</button>"
            f"</div>"
            f"</form>"
            f"</td>"
            "</tr>"
        )
        for item in billing_rows
    ) or '<tr><td colspan="8" class="mini-copy">No tenant billing records yet.</td></tr>'
    section = active_section if active_section in {"schools", "billing", "platform-audit", "create-school", "security", "server-tools"} else "schools"

    def _section_style(name: str) -> str:
        return "" if section == name else ' style="display:none;"'

    def _nav_item(name: str, label: str, badge: Optional[str] = None) -> str:
        active_class = " nav-item-active" if section == name else ""
        badge_html = f'<span class="nav-badge">{escape(str(badge))}</span>' if badge else ""
        return f'<a class="nav-item{active_class}" href="/super-admin?section={name}#{name}">{label}{badge_html}</a>'
    if totp_enabled:
        security_html = f"""
          {security_feedback}
          <div class="flash success">
            Two-factor authentication is active for <strong>{escape(super_admin_login_name)}</strong>.
          </div>
          <form method="post" action="/super-admin/totp/disable-form" class="stack" style="max-width:460px;">
            <div class="field">
              <label for="current_password">Current password</label>
              <input id="current_password" name="current_password" type="password" autocomplete="current-password" />
            </div>
            <div class="button-row">
              <button class="button button-danger-outline" type="submit">Disable 2FA</button>
            </div>
          </form>
        """
    else:
        setup_details = '<p class="mini-copy">Start setup to generate a secret for your authenticator app.</p>'
        if totp_setup_secret:
            safe_uri = escape(totp_setup_uri or "#")
            setup_details = f"""
              <div class="flash">
                <strong>Secret key</strong><br />
                <code style="font-size:1rem; letter-spacing:0.12em;">{escape(totp_setup_secret)}</code>
                <div class="mini-copy" style="margin-top:10px;">Paste this into your authenticator app, or open the setup link if your device supports it.</div>
                <div class="button-row" style="margin-top:12px;">
                  <a class="button button-secondary" href="{safe_uri}">Open in Authenticator App</a>
                </div>
              </div>
              <form method="post" action="/super-admin/totp/enable-form" class="stack">
                <div class="field">
                  <label for="code">Enter the 6-digit code</label>
                  <input id="code" name="code" inputmode="numeric" pattern="[0-9]*" maxlength="6" autocomplete="one-time-code" />
                </div>
                <div class="button-row">
                  <button class="button button-primary" type="submit">Enable 2FA</button>
                </div>
              </form>
            """
        security_html = f"""
          <div class="stack" style="max-width:680px;">
            {security_feedback}
            <form method="post" action="/super-admin/totp/setup-form">
              <div class="button-row">
                <button class="button button-primary" type="submit">Start 2FA Setup</button>
              </div>
            </form>
            {setup_details}
          </div>
        """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BlueBird Super Admin</title>
  {_favicon_tags()}
  <style>{_base_styles()}</style>
</head>
<body>
  <main class="page-shell">
    <div class="app-shell">
      <aside class="sidebar nav-panel">
        <section class="brand-block">
          {_brand_mark()}
          <div class="stack brand-text">
            <p class="eyebrow">BlueBird Platform</p>
            <h2>Super admin</h2>
            <p class="hero-copy">Manage school provisioning across <strong>{escape(base_domain)}</strong>.</p>
          </div>
        </section>
        <section class="signal-card">
          <div class="nav-group">
            <p class="nav-label">Control</p>
          <nav class="nav-list">
            {_nav_item("schools", "Schools", str(len(school_rows)) if school_rows else None)}
            {_nav_item("billing", "Billing", str(len(billing_rows)) if billing_rows else None)}
            {_nav_item("create-school", "Create School")}
            {_nav_item("platform-audit", "Platform Audit")}
            {_nav_item("security", "Security")}
            {_nav_item("server-tools", "Server Tools")}
            <a class="nav-item" href="/super-admin/change-password">Change password</a>
          </nav>
          </div>
          <div class="shell-actions">
            <p class="signal-copy">Provision schools, manage first-admin setup PINs, and keep onboarding clean from one shared platform console.</p>
            <a class="button button-secondary" href="/super-admin/change-password">Change Password</a>
            <form method="post" action="/super-admin/logout">
              <button class="button button-secondary" type="submit">Log out</button>
            </form>
          </div>
        </section>
      </aside>
      <section class="content-stack workspace">
        <section class="panel command-section" id="schools"{_section_style("schools")}>
          <div class="panel-header hero-band">
            <div>
              <p class="eyebrow">Tenant Registry</p>
              <h1>Schools</h1>
              <p class="hero-copy">Each school gets its own path and isolated database. School admins still manage their own users from their tenant dashboard.</p>
            </div>
            <div class="status-row">
              <span class="status-pill ok"><strong>Base domain</strong>{escape(base_domain)}</span>
              <span class="status-pill"><strong>Schools</strong>{len(school_rows)}</span>
              <span class="status-pill {'ok' if git_pull_configured else 'danger'}"><strong>Git pull</strong>{'configured' if git_pull_configured else 'not configured'}</span>
            </div>
          </div>
          <table>
            <thead>
              <tr><th>Name</th><th>Slug</th><th>School URLs</th><th>Setup</th><th>Status</th></tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
        </section>
        <section class="panel command-section" id="billing"{_section_style("billing")}>
          <div class="panel-header hero-band">
            <div>
              <p class="eyebrow">Tenant Billing</p>
              <h1>Billing Controls</h1>
              <p class="hero-copy">Manage tenant billing state, trial windows, and manual free-access overrides without changing checkout or Stripe integration flows.</p>
            </div>
            <div class="status-row">
              <span class="status-pill"><strong>Tenants</strong>{len(billing_rows)}</span>
              <span class="status-pill ok"><strong>Stripe checkout</strong>unchanged</span>
            </div>
          </div>
          <table>
            <thead>
              <tr><th>School</th><th>Plan</th><th>Status</th><th>Trial End</th><th>Renewal</th><th>Free Override</th><th>Stripe IDs</th><th>Controls</th></tr>
            </thead>
            <tbody>{billing_table_rows}</tbody>
          </table>
        </section>
        <section class="panel command-section" id="platform-audit"{_section_style("platform-audit")}>
          <div class="panel-header">
            <div>
              <p class="eyebrow">Audit</p>
              <h2>Platform super-admin activity</h2>
              <p class="card-copy">Cross-school activity feed for actions performed while operating as platform super admin.</p>
            </div>
          </div>
          <table>
            <thead>
              <tr><th>Time (UTC)</th><th>School</th><th>Action</th><th>By</th><th>Details</th></tr>
            </thead>
            <tbody>{platform_rows}</tbody>
          </table>
        </section>
        <section class="panel command-section" id="create-school"{_section_style("create-school")}>
          <div class="panel-header">
            <div>
              <p class="eyebrow">Provisioning</p>
              <h2>Create a new school</h2>
              <p class="card-copy">This creates the school registry entry and path-based tenant. The first school admin is still created from that school's own admin portal.</p>
            </div>
          </div>
          <form method="post" action="/super-admin/schools/create" class="stack">
            <div class="form-grid">
              <div class="field">
                <label>School name</label>
                <input name="name" placeholder="Northeast Nodaway" />
              </div>
              <div class="field">
                <label>School slug</label>
                <input name="slug" placeholder="nen" />
              </div>
              <div class="field">
                <label>First-admin setup PIN</label>
                <input name="setup_pin" type="password" placeholder="Optional shared PIN" />
              </div>
            </div>
            <div class="button-row">
              <button class="button button-primary" type="submit">Create school</button>
            </div>
          </form>
          <p class="mini-copy" style="margin-top:14px;">New school URLs use the same domain with a school path, like <code>https://{escape(base_domain)}/school-slug/admin</code>.</p>
        </section>
        <section class="panel command-section" id="security"{_section_style("security")}>
          <div class="panel-header">
            <div>
              <p class="eyebrow">Security</p>
              <h2>Super admin account protection</h2>
              <p class="card-copy">Use an authenticator app for time-based one-time codes. This protects the platform account without adding SMS or email dependencies.</p>
            </div>
          </div>
          <div class="metrics-grid" style="margin-bottom:20px;">
            <article class="metric-card">
              <div class="meta">Account</div>
              <div class="metric-value" style="font-size:1.2rem;">{escape(super_admin_login_name)}</div>
            </article>
            <article class="metric-card">
              <div class="meta">2FA Status</div>
              <div class="metric-value" style="font-size:1.2rem;">{'Enabled' if totp_enabled else 'Not enabled'}</div>
            </article>
          </div>
          {security_html}
        </section>
        <section class="panel command-section"{_section_style("create-school")}>
          <div class="panel-header">
            <div>
              <p class="eyebrow">Onboarding</p>
              <h2>School setup flow</h2>
              <p class="card-copy">Use the same repeatable handoff for every new school so setup stays predictable.</p>
            </div>
          </div>
          <div class="metrics-grid">
            <article class="metric-card">
              <div class="meta">1. Provision</div>
              <div style="margin-top:8px; font-weight:700;">Create the school here</div>
              <p class="mini-copy">Choose the display name and slug. That immediately reserves the path-based tenant.</p>
            </article>
            <article class="metric-card">
              <div class="meta">2. Open portal</div>
              <div style="margin-top:8px; font-weight:700;">Visit <code>/&lt;slug&gt;/admin</code></div>
              <p class="mini-copy">If the school has no admin yet, the page switches into first-admin setup mode automatically.</p>
            </article>
            <article class="metric-card">
              <div class="meta">3. Hand off</div>
              <div style="margin-top:8px; font-weight:700;">Create first admin and sign in</div>
              <p class="mini-copy">If you set a setup PIN, share it with the school contact. After the initial admin account exists, the same URL becomes the ongoing school dashboard login.</p>
            </article>
            <article class="metric-card">
              <div class="meta">4. Rotate access</div>
              <div style="margin-top:8px; font-weight:700;">Update or clear setup PIN</div>
              <p class="mini-copy">Use the controls in the schools table if you need to reset the first-admin handoff PIN for a school.</p>
            </article>
          </div>
        </section>
        <section class="panel command-section" id="server-tools"{_section_style("server-tools")}>
          <div class="panel-header">
            <div>
              <p class="eyebrow">Server Tools</p>
              <h2>Backend service</h2>
              <p class="card-copy">Pull the latest code or restart the running backend from one platform-only control surface.</p>
            </div>
          </div>
          <div class="metrics-grid" style="margin-bottom:20px;">
            <article class="metric-card">
              <div class="meta">Uptime</div>
              <div class="metric-value" style="font-size:1.3rem;">{escape(server_info.get("uptime", "—"))}</div>
            </article>
            <article class="metric-card">
              <div class="meta">Hostname</div>
              <div class="metric-value" style="font-size:1.3rem;">{escape(server_info.get("hostname", "—"))}</div>
            </article>
            <article class="metric-card">
              <div class="meta">Python</div>
              <div class="metric-value" style="font-size:1.3rem;">{escape(server_info.get("python_version", "—"))}</div>
            </article>
            <article class="metric-card">
              <div class="meta">Process ID</div>
              <div class="metric-value" style="font-size:1.3rem;">{escape(server_info.get("pid", "—"))}</div>
            </article>
          </div>
          <p class="mini-copy" style="margin-bottom:14px;">
            {'Configured and ready to run.' if git_pull_configured else 'Set <code>SERVER_GIT_PULL_COMMAND</code> in the backend environment to enable this action.'}
          </p>
          <div class="button-row">
            <form method="post" action="/super-admin/server/pull-latest"
                  onsubmit="return confirm('Pull the latest main branch on the server now?');">
              <button class="button button-primary" type="submit" {'disabled' if not git_pull_configured else ''}>Pull Latest Main</button>
            </form>
            <form method="post" action="/super-admin/server/restart"
                  onsubmit="return confirm('Restart the backend service now? The dashboard will be unavailable for a few seconds.');">
              <button class="button button-danger" type="submit">Restart service</button>
            </form>
          </div>
          <p class="mini-copy" style="margin-top:14px;">
            {'Uses <code>SERVER_RESTART_COMMAND</code> env var.' if server_info.get("restart_configured") == "yes" else 'No <code>SERVER_RESTART_COMMAND</code> set — restart falls back to a self-restart of the running process.'}
          </p>
        </section>
      </section>
    </div>
  </main>
</body>
</html>"""


def _count_list(items: Mapping[str, int]) -> str:
    if not items:
        return '<span class="mini-copy">None yet</span>'
    return "".join(
        f'<span class="status-pill"><strong>{escape(str(k))}</strong>{int(v)}</span>'
        for k, v in sorted(items.items())
    )


def _tenant_selector(
    *,
    school_path_prefix: str,
    selected_section: str,
    selected_tenant_slug: str,
    tenant_options: Sequence[Mapping[str, str]],
) -> str:
    if len(tenant_options) <= 1:
        return ""
    prefix = escape(school_path_prefix)
    options_html = "".join(
        f"<option value=\"{escape(str(item.get('slug', '')))}\" {'selected' if str(item.get('slug', '')) == selected_tenant_slug else ''}>{escape(str(item.get('name', 'School')))}</option>"
        for item in tenant_options
    )
    return f"""
      <form method="get" action="{prefix}/admin" class="button-row" style="justify-content:flex-start; margin-top:10px;">
        <input type="hidden" name="section" value="{escape(selected_section)}" />
        <label for="tenant_filter" class="mini-copy" style="margin-right:6px;">Tenant</label>
        <select id="tenant_filter" name="tenant" onchange="this.form.submit()">{options_html}</select>
        <noscript><button class="button button-secondary" type="submit">Apply</button></noscript>
      </form>
    """


def _render_alert_rows(alerts: Sequence[AlertRecord]) -> str:
    if not alerts:
        return '<tr><td colspan="5" class="mini-copy">No alerts logged yet.</td></tr>'
    rows = []
    for alert in alerts:
        actor = alert.triggered_by_label or (str(alert.triggered_by_user_id) if alert.triggered_by_user_id is not None else "Unknown")
        type_badge = (
            '<span class="status-pill warn">Training</span>'
            if alert.is_training
            else '<span class="status-pill ok">Live</span>'
        )
        rows.append(
            "<tr>"
            f"<td>{alert.id}</td>"
            f"<td>{type_badge}</td>"
            f"<td>{escape(alert.created_at)}</td>"
            f"<td>{escape(alert.message)}</td>"
            f"<td>{escape(actor)}</td>"
            "</tr>"
        )
    return "".join(rows)


def _render_audit_event_rows(events: Sequence[AuditEventRecord]) -> str:
    if not events:
        return '<tr><td colspan="5" class="mini-copy">No audit events recorded yet.</td></tr>'
    rows = []
    for evt in events:
        actor = escape(evt.actor_label or (f"User #{evt.actor_user_id}" if evt.actor_user_id is not None else "System"))
        target = ""
        if evt.target_type:
            target = escape(evt.target_type)
            if evt.target_id:
                target += f" #{escape(evt.target_id)}"
        ts = evt.timestamp[:16] if len(evt.timestamp) > 16 else evt.timestamp
        meta = evt.metadata or {}
        summary_parts = []
        if "message" in meta:
            summary_parts.append(escape(str(meta["message"])[:60]))
        if "name" in meta:
            summary_parts.append(escape(str(meta["name"])))
        if "role" in meta and "old_role" not in meta:
            summary_parts.append(f"role={escape(str(meta['role']))}")
        if "old_role" in meta and "new_role" in meta:
            old, new = str(meta["old_role"]), str(meta["new_role"])
            if old != new:
                summary_parts.append(f"{escape(old)} → {escape(new)}")
        if "platform" in meta:
            summary_parts.append(escape(str(meta["platform"])))
        if "channel" in meta:
            summary_parts.append(f"via {escape(str(meta['channel']))}")
        summary = ", ".join(summary_parts) if summary_parts else "—"
        rows.append(
            "<tr>"
            f"<td class=\"mini-copy\">{escape(ts)}</td>"
            f"<td><code>{escape(evt.event_type)}</code></td>"
            f"<td>{actor}</td>"
            f"<td>{target}</td>"
            f"<td class=\"mini-copy\">{summary}</td>"
            "</tr>"
        )
    return "".join(rows)


def _render_activity_rows(alerts: Sequence[AlertRecord]) -> str:
    if not alerts:
        return '<tr><td colspan="5" class="mini-copy">No alerts yet.</td></tr>'
    rows = []
    for alert in alerts:
        actor = alert.triggered_by_label or (str(alert.triggered_by_user_id) if alert.triggered_by_user_id is not None else "System")
        type_badge = (
            '<span class="status-pill warn">Training</span>'
            if alert.is_training
            else '<span class="status-pill ok">Live</span>'
        )
        rows.append(
            "<tr>"
            f"<td>{alert.id}</td>"
            f"<td>{type_badge}</td>"
            f"<td class=\"mini-copy\">{escape(alert.created_at[:16] if len(alert.created_at) > 16 else alert.created_at)}</td>"
            f"<td>{escape(alert.message[:60] + ('…' if len(alert.message) > 60 else ''))}</td>"
            f"<td>{escape(actor)}</td>"
            "</tr>"
        )
    return "".join(rows)


def _render_device_rows(devices: Sequence[RegisteredDevice], users: Sequence[UserRecord], school_path_prefix: str) -> str:
    if not devices:
        return '<tr><td colspan="8" class="mini-copy">No devices registered yet.</td></tr>'
    user_lookup = {user.id: user for user in users}
    prefix = escape(school_path_prefix)
    rows = []
    for index, device in enumerate(devices, start=1):
        linked_user = user_lookup.get(device.user_id) if device.user_id is not None else None
        first_user = user_lookup.get(device.first_user_id) if device.first_user_id is not None else None
        device_name = device.device_name or "Unnamed device"
        owner = (
            (linked_user.login_name or linked_user.name)
            if linked_user
            else ("Unassigned" if device.user_id is None else f"User #{device.user_id}")
        )
        first_owner = (
            (first_user.login_name or first_user.name)
            if first_user
            else ("Unknown" if device.first_user_id is None else f"User #{device.first_user_id}")
        )
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{escape(device_name)}</td>"
            f"<td>{escape(device.platform)}</td>"
            f"<td>{escape(device.push_provider)}</td>"
            f"<td>{escape(owner)}</td>"
            f"<td>{escape(first_owner)}</td>"
            f"<td><code>...{escape(device.token[-12:])}</code></td>"
            "<td>"
            f"<form method=\"post\" action=\"{prefix}/admin/devices/delete\" onsubmit=\"return confirm('Delete this registered device token?');\">"
            f"<input type=\"hidden\" name=\"token\" value=\"{escape(device.token)}\" />"
            f"<input type=\"hidden\" name=\"push_provider\" value=\"{escape(device.push_provider)}\" />"
            "<button class=\"button button-danger-outline\" type=\"submit\">Delete</button>"
            "</form>"
            "</td>"
            "</tr>"
        )
    return "".join(rows)


def _render_user_cards(
    users: Sequence[UserRecord],
    school_path_prefix: str,
    *,
    tenant_label: Optional[str] = None,
    tenant_options: Sequence[Mapping[str, str]] = (),
    user_tenant_assignments: Optional[Mapping[int, Sequence[str]]] = None,
    allow_assignment_edit: bool = False,
) -> str:
    if not users:
        return '<div class="mini-copy">No users yet.</div>'
    cards = []
    prefix = escape(school_path_prefix)
    for user in users:
        checked_active = "checked" if user.is_active else ""
        checked_clear_login = ""
        login_name = escape(user.login_name or "")
        phone = escape(user.phone_e164 or "")
        last_login = escape(user.last_login_at or "Never")
        tenant_badge = f'<p class="mini-copy">Tenant: <strong>{escape(tenant_label)}</strong></p>' if tenant_label else ""
        assigned_labels = list((user_tenant_assignments or {}).get(user.id, []))
        assignment_label = ", ".join(escape(item) for item in assigned_labels) if assigned_labels else "None"
        assignment_options = "".join(
            f'<label class="checkbox-row"><input type="checkbox" name="tenant_ids" value="{escape(str(item.get("id", "")))}" {"checked" if str(item.get("name", "")) in assigned_labels else ""} /><span>{escape(str(item.get("name", "")))}</span></label>'
            for item in tenant_options
        )
        assignment_block = ""
        if allow_assignment_edit and user.role in {"district_admin", "law_enforcement"}:
            assignment_block = f"""
              <form method="post" action="{prefix}/admin/users/{user.id}/tenant-assignments" class="stack" style="margin-top:10px;">
                <div class="field">
                  <label>Assigned tenants</label>
                  <div class="stack">{assignment_options or '<span class="mini-copy">No tenants available.</span>'}</div>
                </div>
                <div class="button-row">
                  <button class="button button-secondary" type="submit">Save tenant assignments</button>
                </div>
                <p class="mini-copy">Current assignment: {assignment_label}</p>
              </form>
            """
        elif user.role in {"district_admin", "law_enforcement"}:
            assignment_block = f'<p class="mini-copy">Assigned tenants: {assignment_label}</p>'
        cards.append(
            f"""
            <article class="user-card">
              <form method="post" action="{prefix}/admin/users/{user.id}/update" class="stack">
                <div class="panel-header">
                  <div>
                    <h3>{escape(user.name)}</h3>
                    <p class="mini-copy">User #{user.id} • created {escape(user.created_at)}</p>
                    {tenant_badge}
                  </div>
                  <span class="status-pill {'ok' if user.is_active else 'danger'}">{'Active' if user.is_active else 'Inactive'}</span>
                </div>
                <div class="form-grid">
                  <div class="field">
                    <label>Name</label>
                    <input name="name" value="{escape(user.name)}" />
                  </div>
                  <div class="field">
                    <label>Role</label>
                    <select name="role">
                      <option value="teacher" {'selected' if user.role == 'teacher' else ''}>standard / teacher</option>
                      <option value="law_enforcement" {'selected' if user.role == 'law_enforcement' else ''}>law enforcement</option>
                      <option value="admin" {'selected' if user.role == 'admin' else ''}>admin</option>
                      <option value="district_admin" {'selected' if user.role == 'district_admin' else ''}>district admin</option>
                    </select>
                  </div>
                  <div class="field">
                    <label>Phone</label>
                    <input name="phone_e164" value="{phone}" placeholder="+15551234567" />
                  </div>
                  <div class="field">
                    <label>Username</label>
                    <input name="login_name" value="{login_name}" placeholder="optional login username" />
                  </div>
                  <div class="field">
                    <label>New password</label>
                    <input name="password" type="password" placeholder="leave blank to keep current" />
                  </div>
                  <div class="checkbox-row">
                    <input type="checkbox" name="is_active" value="1" {checked_active} />
                    <span>Account active</span>
                  </div>
                  <div class="checkbox-row">
                    <input type="checkbox" name="clear_login" value="1" {checked_clear_login} />
                    <span>Clear login credentials</span>
                  </div>
                </div>
                <div class="button-row">
                  <button class="button button-primary" type="submit">Save user</button>
                </div>
                <p class="mini-copy">Dashboard login: <strong>{'enabled' if user.can_login else 'disabled'}</strong> • last login: {last_login}</p>
              </form>
              {assignment_block}
              <form method="post" action="{prefix}/admin/users/{user.id}/delete" onsubmit="return confirm('Delete {escape(user.name)}? This cannot be undone.');">
                <div class="button-row">
                  <button class="button button-danger-outline" type="submit">Delete user</button>
                </div>
              </form>
            </article>
            """
        )
    return "".join(cards)


def render_change_password_page(
    *,
    user_name: str,
    message: Optional[str] = None,
    error: Optional[str] = None,
    action: str = "/admin/change-password",
    title: str = "Change Password — BlueBird Admin",
    eyebrow: str = "BlueBird Alerts",
    heading: str = "Password change required",
    helper: str = "Your account was set up with a temporary password. Please choose a new password before continuing.",
    theme: Optional[Mapping[str, str]] = None,
) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  {_favicon_tags()}
  <style>{_base_styles(theme)}</style>
</head>
<body>
  <main class="login-shell">
    <section class="hero-card">
      <div class="brand-block">
        {_brand_mark()}
        <div class="stack brand-text">
        <p class="eyebrow">{escape(eyebrow)}</p>
        <h1>{escape(heading)}</h1>
        <p class="hero-copy">{escape(helper)}</p>
        </div>
      </div>
    </section>
    <section class="login-panel">
      <div class="stack">
        <p class="eyebrow">Welcome, {escape(user_name)}</p>
        <h2>Set a new password</h2>
      </div>
      {_render_flash(message, "success")}
      {_render_flash(error, "error")}
      <form method="post" action="{escape(action)}" class="stack">
        <div class="field">
          <label for="new_password">New password</label>
          <input id="new_password" name="new_password" type="password" autocomplete="new-password" />
        </div>
        <div class="field">
          <label for="confirm_password">Confirm new password</label>
          <input id="confirm_password" name="confirm_password" type="password" autocomplete="new-password" />
        </div>
        <div class="button-row">
          <button class="button button-primary" type="submit">Set password and continue</button>
        </div>
      </form>
    </section>
  </main>
</body>
</html>"""


def render_admin_page(
    *,
    school_name: str,
    school_slug: str,
    school_path_prefix: str,
    selected_tenant_slug: str,
    selected_tenant_name: str,
    tenant_options: Sequence[Mapping[str, str]],
    theme: Optional[Mapping[str, str]],
    current_user: UserRecord,
    users: Sequence[UserRecord],
    user_tenant_assignments: Mapping[int, Sequence[str]],
    alerts: Sequence[AlertRecord],
    devices: Sequence[RegisteredDevice],
    alarm_state: AlarmStateRecord,
    reports: Sequence[ReportRecord],
    broadcasts: Sequence[BroadcastUpdateRecord],
    admin_messages: Sequence[AdminMessageRecord],
    unread_admin_messages: int,
    request_help_active: Sequence[TeamAssistRecord],
    quiet_periods_active: Sequence[QuietPeriodRecord],
    quiet_periods_history: Sequence[QuietPeriodRecord],
    quiet_periods_hidden_count: int,
    apns_configured: bool,
    twilio_configured: bool,
    server_info: Mapping[str, str],
    totp_enabled: bool,
    totp_setup_secret: Optional[str] = None,
    totp_setup_uri: Optional[str] = None,
    flash_message: Optional[str] = None,
    flash_error: Optional[str] = None,
    super_admin_mode: bool = False,
    super_admin_actor_name: Optional[str] = None,
    active_section: str = "dashboard",
    acknowledgement_count: int = 0,
    fcm_configured: bool = False,
    delivery_stats: Optional[Mapping[str, object]] = None,
    audit_events: Sequence[AuditEventRecord] = (),
    audit_event_types: Sequence[str] = (),
    audit_event_type_filter: str = "",
) -> str:
    prefix = escape(school_path_prefix)
    role_counts = Counter(user.role for user in users)
    platform_counts = Counter(device.platform for device in devices)
    provider_counts = Counter(device.push_provider for device in devices)
    active_users = sum(1 for user in users if user.is_active)
    login_enabled = sum(1 for user in users if user.can_login)
    alarm_status_class = "danger" if alarm_state.is_active and not alarm_state.is_training else ("warn" if alarm_state.is_active else "ok")
    alarm_status_label = "TRAINING ACTIVE" if alarm_state.is_active and alarm_state.is_training else ("ALARM ACTIVE" if alarm_state.is_active else "Alarm clear")
    security_feedback = f"{_render_flash(flash_message, 'success')}{_render_flash(flash_error, 'error')}"
    section = active_section if active_section in {"dashboard", "user-management", "quiet-periods", "audit-logs", "settings"} else "dashboard"
    quiet_period_total = len(quiet_periods_active) + len(quiet_periods_history)
    refresh_meta = '<meta http-equiv="refresh" content="30">' if section == "dashboard" else ""
    ack_pill = (
        f'<span class="status-pill ok"><strong>Acknowledged</strong>{acknowledgement_count} user{"s" if acknowledgement_count != 1 else ""}</span>'
        if alarm_state.is_active and acknowledgement_count > 0
        else ""
    )

    # Phase 2 panel computed values
    _ds = delivery_stats or {}
    _ds_total = int(_ds.get("total", 0))
    _ds_ok = int(_ds.get("ok", 0))
    _ds_failed = int(_ds.get("failed", 0))
    _ds_last_error = str(_ds.get("last_error") or "") if _ds.get("last_error") else ""
    _push_configured = apns_configured or fcm_configured
    _ios_count = platform_counts.get("ios", 0)
    _android_count = platform_counts.get("android", 0)
    _apns_token_count = provider_counts.get("apns", 0)
    _fcm_token_count = provider_counts.get("fcm", 0)
    _total_device_count = len(devices)

    def _section_style(name: str) -> str:
        return "" if section == name else ' style="display:none;"'

    def _nav_item(name: str, label: str, badge: Optional[str] = None) -> str:
        active_class = " nav-item-active" if section == name else ""
        badge_html = f'<span class="nav-badge">{escape(str(badge))}</span>' if badge else ""
        return f'<a class="nav-item{active_class}" href="{prefix}/admin?section={name}">{label}{badge_html}</a>'
    tenant_selector_html = _tenant_selector(
        school_path_prefix=school_path_prefix,
        selected_section=section,
        selected_tenant_slug=selected_tenant_slug,
        tenant_options=tenant_options,
    )
    super_admin_shell_action_html = ""
    super_admin_banner_html = ""
    if super_admin_mode:
        super_admin_shell_action_html = f"""
            <form method="post" action="{prefix}/admin/super-admin/exit">
              <button class="button button-secondary" type="submit">Return to Super Admin</button>
            </form>
        """
        super_admin_recorded_badge_html = f"""
          <div class="flash" style="margin-bottom:14px;">
            Recorded as <strong>Platform Super Admin ({escape(super_admin_actor_name or 'superadmin')})</strong>
          </div>
        """
        super_admin_banner_html = f"""
        <section class="panel command-section">
          <div class="flash success">
            <strong>Super Admin Access</strong><br />
            You are operating inside <strong>{escape(school_name)}</strong> as platform super admin <strong>{escape(super_admin_actor_name or 'superadmin')}</strong>. Actions here affect this school directly.
          </div>
        </section>
        """
    else:
        super_admin_recorded_badge_html = ""
    if super_admin_mode:
        admin_security_html = f"""
          <div class="flash success">
            This school console is being accessed through the platform super admin account <strong>{escape(super_admin_actor_name or 'superadmin')}</strong>.
          </div>
          <div class="flash">
            School-admin password, 2FA, and account-rotation controls stay with the real tenant admin accounts. Use the school user list to create or update those accounts as needed.
          </div>
          <form method="post" action="{prefix}/admin/super-admin/exit">
            <div class="button-row">
              <button class="button button-secondary" type="submit">Return to Super Admin</button>
            </div>
          </form>
        """
    elif totp_enabled:
        admin_security_html = """
          {security_feedback}
          <div class="flash success">
            Two-factor authentication is active for this admin account.
          </div>
          <form method="post" action="{prefix}/admin/totp/disable-form" class="stack" style="max-width:460px;">
            <div class="field">
              <label for="current_password">Current password</label>
              <input id="current_password" name="current_password" type="password" autocomplete="current-password" />
            </div>
            <div class="button-row">
              <button class="button button-danger-outline" type="submit">Disable 2FA</button>
              <a class="button button-secondary" href="{prefix}/admin/change-password">Change password</a>
            </div>
          </form>
        """.replace("{prefix}", prefix).replace("{security_feedback}", security_feedback)
    else:
        setup_details = '<p class="mini-copy">Start setup to generate a secret for your authenticator app.</p>'
        if totp_setup_secret:
            safe_uri = escape(totp_setup_uri or "#")
            setup_details = f"""
              <div class="flash">
                <strong>Secret key</strong><br />
                <code style="font-size:1rem; letter-spacing:0.12em;">{escape(totp_setup_secret)}</code>
                <div class="mini-copy" style="margin-top:10px;">Paste this into your authenticator app, or open the setup link if your device supports it.</div>
                <div class="button-row" style="margin-top:12px;">
                  <a class="button button-secondary" href="{safe_uri}">Open in Authenticator App</a>
                </div>
              </div>
              <form method="post" action="{prefix}/admin/totp/enable-form" class="stack">
                <div class="field">
                  <label for="code">Enter the 6-digit code</label>
                  <input id="code" name="code" inputmode="numeric" pattern="[0-9]*" maxlength="6" autocomplete="one-time-code" />
                </div>
                <div class="button-row">
                  <button class="button button-primary" type="submit">Enable 2FA</button>
                  <a class="button button-secondary" href="{prefix}/admin/change-password">Change password</a>
                </div>
              </form>
            """
        admin_security_html = f"""
          <div class="stack" style="max-width:680px;">
            {security_feedback}
            <form method="post" action="{prefix}/admin/totp/setup-form">
              <div class="button-row">
                <button class="button button-primary" type="submit">Start 2FA Setup</button>
                <a class="button button-secondary" href="{prefix}/admin/change-password">Change password</a>
              </div>
            </form>
            {setup_details}
          </div>
        """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BlueBird Admin</title>
  {_favicon_tags()}
  {refresh_meta}
  <style>{_base_styles(theme)}</style>
  <script>
  document.addEventListener('DOMContentLoaded', function() {{
    // Training mode warning — show a red banner when training is unchecked
    var cb = document.getElementById('is_training');
    var warning = document.getElementById('live_alert_warning');
    if (cb && warning) {{
      function syncWarning() {{
        warning.style.display = cb.checked ? 'none' : 'block';
      }}
      cb.addEventListener('change', syncWarning);
      syncWarning();
    }}
    // Alarm activate confirmation
    var activateForm = document.getElementById('alarm_activate_form');
    if (activateForm) {{
      activateForm.addEventListener('submit', function(e) {{
        var isTraining = document.getElementById('is_training') && document.getElementById('is_training').checked;
        var msg = isTraining
          ? 'Start a training drill?\\n\\nDrill alerts will be delivered in training mode (no live SMS delivery).'
          : '\\u26a0 LIVE ALERT\\n\\nThis will send real emergency notifications to all registered devices for this school.\\n\\nContinue?';
        if (!confirm(msg)) {{ e.preventDefault(); }}
      }});
    }}
    // Alarm deactivate confirmation
    document.querySelectorAll('[data-confirm-deactivate]').forEach(function(form) {{
      form.addEventListener('submit', function(e) {{
        if (!confirm('End the active alarm?\\n\\nThis will clear the emergency state for all staff devices.')) {{
          e.preventDefault();
        }}
      }});
    }});
  }});
  </script>
</head>
<body>
  <main class="page-shell">
    <div class="app-shell">
      <aside class="sidebar nav-panel">
        <section class="brand-block">
          {_brand_mark()}
          <div class="stack brand-text">
            <p class="eyebrow">BlueBird Alerts</p>
            <h2>Safety operations</h2>
            <p class="hero-copy">Signed in as <strong>{escape(current_user.name)}</strong> ({escape(current_user.login_name or 'admin')}).</p>
            <p class="mini-copy">School: <strong>{escape(school_name)}</strong> ({escape(school_slug)})</p>
            <p class="mini-copy">Viewing tenant: <strong>{escape(selected_tenant_name)}</strong> ({escape(selected_tenant_slug)})</p>
            {tenant_selector_html}
          </div>
        </section>
        <section class="signal-card">
          <div class="nav-group">
            <p class="nav-label">Command Deck</p>
          <nav class="nav-list">
            {_nav_item("dashboard", "Dashboard")}
            {_nav_item("user-management", "User Management")}
            {_nav_item("quiet-periods", "Quiet Period Requests", str(len(quiet_periods_active)) if quiet_periods_active else None)}
            {_nav_item("audit-logs", "Audit Logs")}
            {_nav_item("settings", "Settings")}
          </nav>
          </div>
          <div class="shell-actions">
            <p class="signal-copy">Manage people, alerts, readiness, and response from one school operations console.</p>
            {super_admin_shell_action_html}
            <form method="post" action="{prefix}/admin/logout">
            <button class="button button-secondary" type="submit">Log out</button>
          </form>
          </div>
        </section>
      </aside>

      <section class="content-stack workspace">
        {_render_flash(flash_message, "success")}
        {_render_flash(flash_error, "error")}
        {super_admin_banner_html}

        <section class="panel command-section" id="overview"{_section_style("dashboard")}>
          <div class="panel-header hero-band">
            <div>
              <p class="eyebrow">Command Deck</p>
              <h1>Admin dashboard</h1>
              <p class="hero-copy">Manage users, see device readiness, review alerts, and control the active alarm state for <strong>{escape(selected_tenant_name)}</strong> from one place.</p>
            </div>
            <div class="status-row">
              <span class="status-pill {alarm_status_class}"><strong>{alarm_status_label}</strong>{escape(alarm_state.message or 'No active alarm')}</span>
              {"<span class='status-pill warn'><strong>TRAINING</strong>" + escape(alarm_state.training_label or "This is a drill") + "</span>" if alarm_state.is_active and alarm_state.is_training else ""}
              {ack_pill}
              <span class="status-pill {'ok' if apns_configured else 'danger'}"><strong>APNs</strong>{'ready' if apns_configured else 'not configured'}</span>
              <span class="status-pill {'ok' if twilio_configured else 'danger'}"><strong>SMS</strong>{'ready' if twilio_configured else 'not configured'}</span>
            </div>
          </div>
          <div class="metrics-grid">
            <article class="metric-card"><div class="meta">Users</div><div class="metric-value">{len(users)}</div></article>
            <article class="metric-card"><div class="meta">Active users</div><div class="metric-value">{active_users}</div></article>
            <article class="metric-card"><div class="meta">Login-enabled</div><div class="metric-value">{login_enabled}</div></article>
            <article class="metric-card"><div class="meta">Devices</div><div class="metric-value">{len(devices)}</div></article>
            <article class="metric-card"><div class="meta">Recent alerts</div><div class="metric-value">{len(alerts)}</div></article>
            <article class="metric-card"><div class="meta">User reports</div><div class="metric-value">{len(reports)}</div></article>
            <article class="metric-card"><div class="meta">Open messages</div><div class="metric-value">{unread_admin_messages}</div></article>
            <article class="metric-card"><div class="meta">Active help requests</div><div class="metric-value">{len(request_help_active)}</div></article>
            <article class="metric-card"><div class="meta">Quiet period requests</div><div class="metric-value">{len(quiet_periods_active)}</div></article>
          </div>
          <div class="status-row" style="margin-top:16px;">
            {_count_list(role_counts)}
            {_count_list(platform_counts)}
            {_count_list(provider_counts)}
          </div>
        </section>

        <section class="panel command-section" id="security"{_section_style("settings")}>
          <div class="panel-header">
            <div>
              <p class="eyebrow">Security</p>
              <h2>Admin account protection</h2>
              <p class="card-copy">Use an authenticator app for time-based one-time codes. This protects your school dashboard account without adding SMS or email dependencies.</p>
            </div>
          </div>
          <div class="metrics-grid" style="margin-bottom:20px;">
            <article class="metric-card">
              <div class="meta">Account</div>
              <div class="metric-value" style="font-size:1.2rem;">{escape(current_user.login_name or current_user.name)}</div>
            </article>
            <article class="metric-card">
              <div class="meta">Role</div>
              <div class="metric-value" style="font-size:1.2rem;">{escape(current_user.role)}</div>
            </article>
            <article class="metric-card">
              <div class="meta">2FA Status</div>
              <div class="metric-value" style="font-size:1.2rem;">{'Enabled' if totp_enabled else 'Not enabled'}</div>
            </article>
          </div>
          {admin_security_html}
        </section>

        <section class="grid">
          <section class="panel command-section span-5" id="alarm"{_section_style("dashboard")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Alarm Control</p>
                <h2>{"End active alarm" if alarm_state.is_active else "Activate alarm"}</h2>
                <p class="card-copy">Dashboard actions are attributed to your logged-in admin account automatically.</p>
              </div>
            </div>
            {f'''
            <div class="flash {'warn' if alarm_state.is_training else 'error'}" style="margin-bottom:14px;">
              <strong>{"TRAINING DRILL ACTIVE" if alarm_state.is_training else "ALARM ACTIVE"}</strong><br />
              {escape(alarm_state.message or "No message")}
              {(" — by " + escape(alarm_state.activated_by_label or (f"User #{alarm_state.activated_by_user_id}" if alarm_state.activated_by_user_id is not None else "system"))) if alarm_state.activated_at else ""}
              {(" at " + escape(alarm_state.activated_at)) if alarm_state.activated_at else ""}
              {(" — Training label: " + escape(alarm_state.training_label or "This is a drill")) if alarm_state.is_training else ""}
            </div>
            <form method="post" action="{prefix}/admin/alarm/deactivate" class="stack" data-confirm-deactivate>
              <div class="button-row">
                <button class="button button-danger" type="submit">End alarm now</button>
              </div>
            </form>
            ''' if alarm_state.is_active else f'''
            {super_admin_recorded_badge_html}
            <div id="live_alert_warning" class="flash error" style="display:none; margin-bottom:12px;">
              <strong>&#9888; Live alert mode.</strong> Training mode is off.
              This will send real emergency notifications to all registered devices for this school.
            </div>
            <form id="alarm_activate_form" method="post" action="{prefix}/admin/alarm/activate" class="stack">
              <div class="checkbox-row" style="background:color-mix(in srgb,var(--warning) 10%,white);border-color:color-mix(in srgb,var(--warning) 25%,transparent);">
                <input type="checkbox" name="is_training" value="1" id="is_training" checked />
                <label for="is_training">Training mode — no real push/SMS delivery</label>
              </div>
              <div class="field">
                <label for="alarm_message">Alarm message</label>
                <textarea id="alarm_message" name="message">Emergency alert. Please follow school procedures.</textarea>
              </div>
              <div class="field">
                <label for="training_label">Training label (optional)</label>
                <input id="training_label" name="training_label" placeholder="This is a drill" />
              </div>
              <div class="button-row">
                <button class="button button-danger" type="submit">Activate alarm</button>
              </div>
            </form>
            <form method="post" action="{prefix}/admin/alarm/deactivate" class="stack" style="margin-top:14px;">
              <div class="button-row">
                <button class="button button-secondary" type="submit" disabled>Deactivate alarm</button>
              </div>
            </form>
            '''}
            <p class="mini-copy">
              Activated at: {escape(alarm_state.activated_at or 'Never')}
              {" • by " + escape(alarm_state.activated_by_label or (f"User #{alarm_state.activated_by_user_id}" if alarm_state.activated_by_user_id is not None else "system")) if alarm_state.activated_at else ""}
              {" • mode: TRAINING (" + escape(alarm_state.training_label or "This is a drill") + ")" if alarm_state.is_active and alarm_state.is_training else " • mode: LIVE" if alarm_state.is_active else ""}
              • Deactivated at: {escape(alarm_state.deactivated_at or 'Not yet')}
              {" • by " + escape(alarm_state.deactivated_by_label or (f"User #{alarm_state.deactivated_by_user_id}" if alarm_state.deactivated_by_user_id is not None else "system")) if alarm_state.deactivated_at else ""}
            </p>
          </section>

          <section class="panel span-7" id="system-health"{_section_style("dashboard")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">System Health</p>
                <h2>Platform status</h2>
              </div>
            </div>
            <table class="data-table" style="margin-bottom:12px;">
              <tbody>
                <tr><td><strong>School</strong></td><td>{escape(school_name)} <span class="mini-copy">({escape(school_slug)})</span></td></tr>
                <tr><td><strong>Alarm state</strong></td><td><span class="status-pill {alarm_status_class}">{escape(alarm_status_label)}</span></td></tr>
                <tr><td><strong>APNs (iOS push)</strong></td><td><span class="status-pill {"ok" if apns_configured else "warn"}">{("Configured" if apns_configured else "Not configured")}</span></td></tr>
                <tr><td><strong>FCM (Android push)</strong></td><td><span class="status-pill {"ok" if fcm_configured else "warn"}">{("Configured" if fcm_configured else "Not configured")}</span></td></tr>
                <tr><td><strong>SMS (Twilio)</strong></td><td><span class="status-pill {"ok" if twilio_configured else "warn"}">{("Configured" if twilio_configured else "Not configured")}</span></td></tr>
                <tr><td><strong>Registered devices</strong></td><td>{_total_device_count}</td></tr>
                <tr><td><strong>Acknowledgements (current)</strong></td><td>{acknowledgement_count if alarm_state.is_active else "—"}</td></tr>
                <tr><td><strong>Last alarm activated</strong></td><td>{escape(alarm_state.activated_at or "Never")}</td></tr>
                <tr><td><strong>Last alarm deactivated</strong></td><td>{escape(alarm_state.deactivated_at or "Never")}</td></tr>
              </tbody>
            </table>
          </section>

          <section class="panel span-5" id="device-status"{_section_style("dashboard")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Device &amp; Notification Status</p>
                <h2>Registered devices</h2>
              </div>
            </div>
            <table class="data-table" style="margin-bottom:12px;">
              <tbody>
                <tr><td><strong>iOS</strong></td><td>{_ios_count}</td></tr>
                <tr><td><strong>Android</strong></td><td>{_android_count}</td></tr>
                <tr><td><strong>APNs tokens</strong></td><td>{_apns_token_count}</td></tr>
                <tr><td><strong>FCM tokens</strong></td><td>{_fcm_token_count}</td></tr>
              </tbody>
            </table>
            <p class="eyebrow" style="margin-bottom:6px;">Most recent alert deliveries</p>
            {f'''
            <table class="data-table">
              <tbody>
                <tr><td><strong>Attempts</strong></td><td>{_ds_total}</td></tr>
                <tr><td><strong>Delivered</strong></td><td><span class="status-pill ok">{_ds_ok}</span></td></tr>
                <tr><td><strong>Failed</strong></td><td><span class="status-pill {"danger" if _ds_failed > 0 else "ok"}">{_ds_failed}</span></td></tr>
                {f'<tr><td><strong>Last error</strong></td><td class="mini-copy">{escape(_ds_last_error[:120])}</td></tr>' if _ds_last_error else ""}
              </tbody>
            </table>
            ''' if _ds_total > 0 else '<p class="mini-copy">No delivery records for the most recent alert.</p>'}
          </section>

          <section class="panel span-7" id="recent-activity"{_section_style("dashboard")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Recent Activity</p>
                <h2>Last 5 alerts</h2>
              </div>
            </div>
            <table class="data-table">
              <thead><tr><th>ID</th><th>Type</th><th>Time</th><th>Message</th><th>By</th></tr></thead>
              <tbody>
                {_render_activity_rows(alerts[:5])}
              </tbody>
            </table>
          </section>

          <section class="panel span-5" id="drill-readiness"{_section_style("dashboard")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Drill Readiness</p>
                <h2>Ready to drill?</h2>
              </div>
            </div>
            <table class="data-table" style="margin-bottom:12px;">
              <tbody>
                <tr><td><strong>Push configured</strong></td><td><span class="status-pill {"ok" if _push_configured else "warn"}">{("Yes" if _push_configured else "No — set up APNs or FCM")}</span></td></tr>
                <tr><td><strong>Devices registered</strong></td><td><span class="status-pill {"ok" if _total_device_count > 0 else "warn"}">{(_total_device_count if _total_device_count > 0 else "None registered")}</span></td></tr>
                <tr><td><strong>Training mode</strong></td><td><span class="status-pill ok">Available</span></td></tr>
                <tr><td><strong>Alarm currently</strong></td><td><span class="status-pill {alarm_status_class}">{escape(alarm_status_label)}</span></td></tr>
              </tbody>
            </table>
            <p class="mini-copy">
              {
                "Ready for a training drill. Use the Alarm Control panel with Training mode on." if _push_configured and _total_device_count > 0 and not alarm_state.is_active
                else "Alarm is currently active — complete or end it before starting a drill." if alarm_state.is_active
                else "Register at least one device and configure push before running a drill."
              }
            </p>
          </section>

          <section class="panel command-section span-12" id="user-management"{_section_style("user-management")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">User Management</p>
                <h2>Manage school user accounts</h2>
                <p class="card-copy">Create, edit, and maintain staff/admin accounts in one dedicated workspace.</p>
              </div>
            </div>
            <div class="metrics-grid">
              <article class="metric-card"><div class="meta">Total users</div><div class="metric-value">{len(users)}</div></article>
              <article class="metric-card"><div class="meta">Active users</div><div class="metric-value">{active_users}</div></article>
              <article class="metric-card"><div class="meta">Login-enabled users</div><div class="metric-value">{login_enabled}</div></article>
              <article class="metric-card"><div class="meta">Admin users</div><div class="metric-value">{role_counts.get("admin", 0)}</div></article>
            </div>
          </section>

          <section class="panel command-section span-7" id="users"{_section_style("user-management")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Accounts</p>
                <h2>Create a user</h2>
                <p class="card-copy">Create standard users or new admins. Add a username and password if the account should be able to sign in.</p>
              </div>
            </div>
            <form method="post" action="{prefix}/admin/users/create" class="stack">
              <div class="form-grid">
                <div class="field">
                  <label>Name</label>
                  <input name="name" />
                </div>
                <div class="field">
                  <label>Role</label>
                  <select name="role">
                    <option value="teacher">standard / teacher</option>
                    <option value="law_enforcement">law enforcement</option>
                    <option value="admin">admin</option>
                    <option value="district_admin">district admin</option>
                  </select>
                </div>
                <div class="field">
                  <label>Phone</label>
                  <input name="phone_e164" placeholder="+15551234567" />
                </div>
                <div class="field">
                  <label>Username</label>
                  <input name="login_name" placeholder="optional login username" />
                </div>
                <div class="field">
                  <label>Password</label>
                  <input name="password" type="password" placeholder="optional login password" />
                </div>
                <div class="checkbox-row">
                  <input type="checkbox" name="must_change_password" value="1" id="must_change_password" />
                  <label for="must_change_password">Require password change on first login</label>
                </div>
              </div>
              <div class="button-row">
                <button class="button button-primary" type="submit">Create user</button>
              </div>
            </form>
          </section>

          <section class="panel command-section span-12"{_section_style("user-management")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Account Editor</p>
                <h2>Edit existing users</h2>
                <p class="card-copy">Update role, phone, active status, and login credentials without leaving the dashboard.</p>
              </div>
            </div>
            <div class="user-grid">
              {_render_user_cards(
                  users,
                  school_path_prefix,
                  tenant_label=selected_tenant_name,
                  tenant_options=[{"id": str(item.get("id", "")), "slug": str(item.get("slug", "")), "name": str(item.get("name", ""))} for item in tenant_options],
                  user_tenant_assignments=user_tenant_assignments,
                  allow_assignment_edit=(current_user.role in {"district_admin", "super_admin"}),
              )}
            </div>
          </section>

          <section class="panel command-section span-5" id="reports"{_section_style("dashboard")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Admin Broadcasts</p>
                <h2>Send official updates</h2>
                <p class="card-copy">Post short verified updates that all signed-in mobile users will see on their app status screen.</p>
              </div>
            </div>
            {super_admin_recorded_badge_html}
            <form method="post" action="{prefix}/admin/broadcasts/create" class="stack">
              <div class="field">
                <label for="broadcast_message">Broadcast message</label>
                <textarea id="broadcast_message" name="message" placeholder="Police on site. Stay barricaded until further notice."></textarea>
              </div>
              <div class="checkbox-row">
                <input type="checkbox" name="send_push" value="1" id="send_push_broadcast" />
                <label for="send_push_broadcast">Send this update as a push notification too</label>
              </div>
              <div class="button-row">
                <button class="button button-primary" type="submit">Post update</button>
              </div>
            </form>
            <table style="margin-top:16px;">
              <thead>
                <tr><th>Created</th><th>By</th><th>Message</th></tr>
              </thead>
              <tbody>
                {_render_broadcast_rows(broadcasts)}
              </tbody>
            </table>
          </section>

          <section class="panel command-section span-12" id="messages"{_section_style("dashboard")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Messaging</p>
                <h2>User messages inbox {'🔔' if unread_admin_messages > 0 else ''}</h2>
                <p class="card-copy">Review incoming mobile messages and reply directly from the admin console.</p>
              </div>
            </div>
            <table>
              <thead>
                <tr><th>ID</th><th>Created</th><th>From</th><th>Message</th><th>Status</th><th>Response</th><th>Action</th></tr>
              </thead>
              <tbody>
                {_render_admin_message_rows(admin_messages, school_path_prefix)}
              </tbody>
            </table>
          </section>

          <section class="panel command-section span-12" id="request-help"{_section_style("dashboard")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Request Help</p>
                <h2>Active help requests</h2>
                <p class="card-copy">Admins can clear help requests directly from the console. This clear action does not require two-person cancellation consent.</p>
              </div>
            </div>
            <table>
              <thead>
                <tr><th>ID</th><th>Created</th><th>Type</th><th>Requested by</th><th>Status</th><th>Handled by</th><th>Action</th></tr>
              </thead>
              <tbody>
                {_render_request_help_rows(request_help_active, users, school_path_prefix, tenant_label=selected_tenant_name)}
              </tbody>
            </table>
          </section>

          <section class="panel command-section span-7"{_section_style("dashboard")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Structured Reports</p>
                <h2>Incoming user reports</h2>
                <p class="card-copy">Users can send structured status updates without creating an open chat stream.</p>
              </div>
            </div>
            <table>
              <thead>
                <tr><th>ID</th><th>Created</th><th>Category</th><th>Note</th></tr>
              </thead>
              <tbody>
                {_render_report_rows(reports)}
              </tbody>
            </table>
          </section>

          <section class="panel command-section span-12" id="quiet-periods"{_section_style("quiet-periods")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Quiet Periods</p>
                <h2>Grant a 24-hour notification pause</h2>
                <p class="card-copy">This main view only shows active or pending requests. Resolved requests stay retained in audit history.</p>
              </div>
            </div>
            {super_admin_recorded_badge_html}
            <div class="status-row" style="margin-bottom:14px;">
              <span class="status-pill"><strong>Current queue</strong>{len(quiet_periods_active)}</span>
              <span class="status-pill"><strong>Hidden from main view</strong>{quiet_periods_hidden_count}</span>
              <span class="status-pill"><strong>Total stored</strong>{quiet_period_total}</span>
            </div>
            <form method="post" action="{prefix}/admin/quiet-periods/grant" class="stack">
              <div class="form-grid">
                <div class="field">
                  <label>User</label>
                  <select name="user_id">
                    {''.join(f'<option value="{user.id}">{escape(user.name)} ({escape(user.role)})</option>' for user in users if user.is_active)}
                  </select>
                </div>
                <div class="field">
                  <label>Reason</label>
                  <input name="reason" placeholder="Optional reason for the temporary pause" />
                </div>
              </div>
              <div class="button-row">
                <button class="button button-secondary" type="submit">Grant 24-hour quiet period</button>
              </div>
            </form>
            <table style="margin-top:16px;">
              <thead>
                <tr><th>User</th><th>Status</th><th>Reason</th><th>Approved By</th><th>Requested</th><th>Expires</th><th>Action</th></tr>
              </thead>
              <tbody>
                {_render_quiet_period_rows(quiet_periods_active, users, school_path_prefix, tenant_label=selected_tenant_name, include_actions=True)}
              </tbody>
            </table>
            <div class="button-row" style="margin-top:12px;">
              <form method="post" action="{prefix}/admin/quiet-periods/show-all">
                <button class="button button-secondary" type="submit">Show hidden requests again</button>
              </form>
              <a class="button button-secondary" href="{prefix}/admin?section=audit-logs#audit-quiet-periods">View logs/history</a>
            </div>
          </section>

          <section class="panel span-7" id="alerts"{_section_style("audit-logs")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Alert Log</p>
                <h2>Recent alerts</h2>
              </div>
            </div>
            <table>
              <thead>
                <tr><th>ID</th><th>Type</th><th>Created</th><th>Message</th><th>Triggered by</th></tr>
              </thead>
              <tbody>
                {_render_alert_rows(alerts)}
              </tbody>
            </table>
          </section>

          <section class="panel span-5" id="devices"{_section_style("dashboard")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Devices</p>
                <h2>Registered devices</h2>
              </div>
            </div>
            <table>
              <thead>
                <tr><th>#</th><th>Device</th><th>Platform</th><th>Provider</th><th>Current user</th><th>First user</th><th>Token</th><th>Action</th></tr>
              </thead>
              <tbody>
                {_render_device_rows(devices, users, school_path_prefix)}
              </tbody>
            </table>
          </section>

          <section class="panel span-12" id="audit-events"{_section_style("audit-logs")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Audit Log</p>
                <h2>System event trail</h2>
                <p class="card-copy">Complete record of critical actions for accountability and incident review. Showing last 100 entries.</p>
              </div>
            </div>
            <form method="get" action="{prefix}/admin" style="display:flex;gap:10px;align-items:flex-end;margin-bottom:14px;flex-wrap:wrap;">
              <input type="hidden" name="section" value="audit-logs" />
              <div class="field" style="margin:0;flex:1;min-width:160px;">
                <label style="font-size:11px;">Filter by event type</label>
                <select name="audit_event_type" style="width:100%;">
                  <option value="">— All events —</option>
                  {''.join(f'<option value="{escape(et)}"{" selected" if et == audit_event_type_filter else ""}>{escape(et)}</option>' for et in audit_event_types)}
                </select>
              </div>
              <div class="button-row" style="margin:0;">
                <button class="button button-secondary" type="submit">Filter</button>
                {"" if not audit_event_type_filter else f'<a class="button button-secondary" href="{prefix}/admin?section=audit-logs">Clear</a>'}
              </div>
            </form>
            <table class="data-table">
              <thead>
                <tr><th>Timestamp</th><th>Event</th><th>Actor</th><th>Target</th><th>Summary</th></tr>
              </thead>
              <tbody>
                {_render_audit_event_rows(audit_events)}
              </tbody>
            </table>
          </section>

          <section class="panel command-section span-12" id="audit-quiet-periods"{_section_style("audit-logs")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Quiet Period Audit</p>
                <h2>Resolved request history</h2>
                <p class="card-copy">Historical requests are retained for audit review and excluded from the active queue.</p>
              </div>
            </div>
            <table>
              <thead>
                <tr><th>User</th><th>Status</th><th>Reason</th><th>Approved By</th><th>Requested</th><th>Expires</th><th>Action</th></tr>
              </thead>
              <tbody>
                {_render_quiet_period_rows(quiet_periods_history, users, school_path_prefix, tenant_label=selected_tenant_name, include_actions=False)}
              </tbody>
            </table>
          </section>

        </section>
      </section>
    </div>
  </main>
</body>
</html>"""
