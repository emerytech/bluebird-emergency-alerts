from __future__ import annotations

from collections import Counter
from html import escape
import json
from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional, Sequence

from app.services.alert_log import AlertRecord
from app.services.audit_log_service import AuditEventRecord
from app.services.alarm_store import AlarmStateRecord
from app.services.email_service import EmailLogRecord, GmailSettings, SMTPConfig, TEMPLATE_KEYS as EMAIL_TEMPLATE_KEYS
from app.services.health_monitor import HeartbeatRecord, HealthStatus, UptimeStats
from app.services.device_registry import RegisteredDevice
from app.services.incident_store import TeamAssistRecord
from app.services.quiet_period_store import QuietPeriodRecord
from app.services.report_store import AdminMessageRecord, BroadcastUpdateRecord, ReportRecord
from app.services.school_registry import SchoolRecord
from app.services.tenant_settings import TenantSettings
from app.services.tenant_settings_store import SettingsChangeRecord
from app.services.user_store import UserRecord
from app.services.permissions import can_archive_user, can_generate_codes, is_district_admin_or_higher
from app.services.suggestion_engine import Suggestion, SuggestionContext, SuggestionEngine


LOGO_PATH = "/static/bluebird-alert-logo.png"


def _favicon_tags() -> str:
    return (
        '<link rel="icon" href="/favicon.ico?v=1" />'
        '<link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png?v=1" />'
        '<link rel="icon" type="image/png" sizes="16x16" href="/static/favicon-16x16.png?v=1" />'
        '<link rel="apple-touch-icon" href="/static/apple-touch-icon.png?v=1" />'
    )


def _brand_mark() -> str:
    return (
        f'<div class="brand-mark"><img src="{LOGO_PATH}" alt="BlueBird Alerts logo"'
        f' onerror="this.onerror=null;" /></div>'
    )


def _brand_mark_sm() -> str:
    return (
        f'<div style="width:36px;height:36px;border-radius:10px;display:grid;'
        f'place-items:center;overflow:hidden;background:rgba(255,255,255,0.14);'
        f'border:1px solid rgba(255,255,255,0.22);flex:0 0 auto;">'
        f'<img src="{LOGO_PATH}" alt="BlueBird Alerts" style="width:100%;height:100%;'
        f'object-fit:contain;padding:4px;" /></div>'
    )


def _help_tip(text: str, right: bool = False) -> str:
    """Inline '?' help tooltip badge. Hover reveals the tip text."""
    cls = "tip-text tip-text--right" if right else "tip-text"
    return f'<span class="help-tip" tabindex="0" role="note" aria-label="{escape(text)}">?<span class="{cls}">{escape(text)}</span></span>'


def _render_next_steps_panel(
    *,
    role: str,
    user_count: int,
    device_count: int,
    apns_configured: bool,
    fcm_configured: bool,
    totp_enabled: bool,
    access_code_count: int,
    unread_messages: int,
    help_requests_active: int,
    prefix: str,
) -> str:
    """Context-aware 'next steps' card for the admin dashboard.

    Returns empty string when nothing actionable — panel never shows if all clear.
    Rendered hidden; inline JS checks localStorage and shows if not recently dismissed.
    """
    items: list[tuple[str, str, str, str]] = []  # (icon, title, desc, href)

    if user_count <= 1:
        items.append(("👤", "Add staff accounts",
                       "Create accounts for teachers and staff so they receive alerts.",
                       f"{prefix}/admin?section=user-management"))

    if access_code_count == 0:
        items.append(("🔑", "Generate access codes",
                       "Create one-time codes so staff can self-register on the BlueBird app.",
                       f"{prefix}/admin?section=user-management&tab=codes"))

    if device_count == 0 and user_count > 1:
        items.append(("📱", "Register devices",
                       "No phones registered yet. Share access codes so staff can install the app.",
                       f"{prefix}/admin?section=user-management&tab=codes"))

    if not apns_configured and not fcm_configured:
        items.append(("🔔", "Configure push notifications",
                       "Push alerts require APNs (iOS) or FCM (Android) credentials in Settings.",
                       f"{prefix}/admin?section=settings"))

    if not totp_enabled and role in {"building_admin", "district_admin"}:
        items.append(("🔒", "Enable two-factor authentication",
                       "Protect this admin account from unauthorized access.",
                       f"{prefix}/admin?section=settings"))

    if unread_messages > 0:
        plural = "s" if unread_messages != 1 else ""
        items.append(("✉", f"{unread_messages} unread message{plural}",
                       "Staff have sent messages to the admin dashboard.",
                       f"{prefix}/admin?section=dashboard#messages"))

    if help_requests_active > 0:
        plural = "s" if help_requests_active != 1 else ""
        items.append(("🙋", f"{help_requests_active} active help request{plural}",
                       "Staff are requesting assistance or backup.",
                       f"{prefix}/admin?section=dashboard#request-help"))

    items = items[:5]
    if not items:
        return ""

    rows = ""
    for icon, title, desc, href in items:
        rows += (
            f'<div class="bb-nsp-item">'
            f'<div class="bb-nsp-icon">{icon}</div>'
            f'<div class="bb-nsp-body">'
            f'<div class="bb-nsp-item-title">{escape(title)}</div>'
            f'<div class="bb-nsp-item-desc">{escape(desc)}</div>'
            f'</div>'
            f'<div class="bb-nsp-cta">'
            f'<a class="button button-secondary" href="{escape(href)}" '
            f'style="font-size:0.78rem;padding:5px 12px;min-height:30px;">Go &rarr;</a>'
            f'</div>'
            f'</div>'
        )

    item_count = str(len(items))
    return (
        f'<div class="bb-nsp" id="bb-next-steps" data-item-count="{item_count}">'
        f'<div class="bb-nsp-header">'
        f'<span class="bb-nsp-title">&#9654; Suggested next steps ({item_count})</span>'
        f'<button class="bb-nsp-dismiss" onclick="bbNspDismiss()" type="button">Got it &times;</button>'
        f'</div>'
        f'<div class="bb-nsp-items">{rows}</div>'
        f'</div>'
    )


def _render_suggestion_panel(suggestions: list[Suggestion], prefix: str) -> str:
    """Renders the AI-style smart suggestions card.

    Each item has an icon, title, description, optional action button, and dismiss X.
    The panel is rendered hidden; JS filters already-dismissed items and shows the panel
    if any remain visible. Items write dismiss TTLs to localStorage on click.
    """
    if not suggestions:
        return ""

    rows = ""
    for sg in suggestions:
        action_btn = ""
        if sg.action_label and sg.action_url:
            action_btn = (
                f'<a class="button button-secondary" href="{escape(sg.action_url)}" '
                f'style="font-size:0.78rem;padding:5px 12px;min-height:30px;white-space:nowrap;">'
                f'{escape(sg.action_label)}</a>'
            )
        dismiss_btn = ""
        if sg.dismissible:
            dismiss_btn = (
                f'<button class="bb-sg-dismiss" type="button" '
                f'onclick="bbSgDismiss(this)" '
                f'data-sid="{escape(sg.id)}" data-ttl="{sg.dismiss_ttl_hours}" '
                f'title="Dismiss" aria-label="Dismiss suggestion">&times;</button>'
            )
        rows += (
            f'<div class="bb-sg-item" data-prio="{escape(sg.priority)}" data-sid="{escape(sg.id)}">'
            f'<div class="bb-sg-icon">{sg.icon}</div>'
            f'<div class="bb-sg-body">'
            f'<div class="bb-sg-item-title">{escape(sg.title)}</div>'
            f'<div class="bb-sg-item-desc">{escape(sg.description)}</div>'
            f'</div>'
            f'<div class="bb-sg-actions">{action_btn}{dismiss_btn}</div>'
            f'</div>'
        )

    return (
        f'<div class="bb-sg" id="bb-suggestions" style="display:none;">'
        f'<div class="bb-sg-header">'
        f'<span class="bb-sg-title">&#128161; Suggestions</span>'
        f'</div>'
        f'<div class="bb-sg-items" id="bb-sg-items">{rows}</div>'
        f'</div>'
    )


def _render_da_checklist(
    *,
    user_count: int,
    device_count: int,
    apns_configured: bool,
    fcm_configured: bool,
    alert_count_7d: int,
    totp_enabled: bool,
    prefix: str,
) -> str:
    """Setup checklist for district_admin users — shown on dashboard until dismissed or all done."""
    items: list[tuple[bool, str, str, str, str]] = [
        (user_count > 0, "👤", "Add at least one staff account",
         "Add Users", f"{prefix}/admin?section=user-management"),
        (device_count > 0, "📱", "Register at least one device",
         "Manage Devices", f"{prefix}/admin?section=devices"),
        (apns_configured or fcm_configured, "🔔", "Configure push notifications",
         "Open Settings", f"{prefix}/admin?section=settings"),
        (alert_count_7d > 0, "🚨", "Run a training drill",
         "Dashboard", f"{prefix}/admin?section=dashboard"),
        (totp_enabled, "🔒", "Enable two-factor authentication",
         "Security", f"{prefix}/admin?section=settings"),
    ]
    done_count = sum(1 for done, *_ in items if done)
    rows = ""
    for done, icon, label, action, href in items:
        done_cls = " done" if done else ""
        check_mark = "✓" if done else ""
        action_btn = "" if done else (
            f'<a class="button button-secondary" href="{escape(href)}" '
            f'style="font-size:0.75rem;padding:4px 10px;min-height:28px;white-space:nowrap;">'
            f'{escape(action)}</a>'
        )
        rows += (
            f'<div class="bb-da-cl-item{done_cls}">'
            f'<div class="bb-da-cl-check">{check_mark}</div>'
            f'<span class="bb-da-cl-item-label">{icon} {escape(label)}</span>'
            f'{action_btn}'
            f'</div>'
        )
    done_count_str = str(done_count)
    total_str = str(len(items))
    return (
        f'<div class="bb-da-cl" id="bb-da-checklist" style="display:none;" '
        f'data-done="{done_count_str}" data-total="{total_str}">'
        f'<div class="bb-da-cl-header">'
        f'<span class="bb-da-cl-title">&#9989; District Setup Checklist</span>'
        f'<button class="bb-da-cl-dismiss" type="button" onclick="bbDaClDismiss()"'
        f' title="Dismiss">Hide &times;</button>'
        f'</div>'
        f'<div class="bb-da-cl-items">{rows}</div>'
        f'<p class="bb-da-cl-progress">{done_count_str} of {total_str} complete — '
        f'checklist hides automatically once all items are done.</p>'
        f'</div>'
    )


def _render_da_welcome_modal(school_name: str) -> str:
    """First-login welcome overlay for district_admin users. Hidden by default; JS reveals it."""
    return (
        f'<div id="bb-da-wb-ov" class="bb-da-wb-ov" role="dialog" '
        f'aria-modal="true" aria-labelledby="bb-da-wb-title">'
        f'<div class="bb-da-wb">'
        f'<div class="bb-da-wb-bird">🦋</div>'
        f'<h2 id="bb-da-wb-title">Welcome to BlueBird Alerts</h2>'
        f'<p class="bb-da-wb-sub">'
        f"You're set up as a <strong>District Admin</strong> for "
        f'<strong>{escape(school_name)}</strong>. '
        f"This console gives you real-time control over emergency alerts and full visibility "
        f"across all buildings in your district."
        f'</p>'
        f'<div class="bb-da-wb-actions">'
        f'<button class="button" type="button" onclick="bbDaStartOnboarding()">'
        f'&#9654; Start Tour</button>'
        f'<button class="button button-secondary" type="button" onclick="bbDaSkipOnboarding()">'
        f'Skip for now</button>'
        f'</div>'
        f'</div>'
        f'</div>'
    )


def _super_admin_header_html(
    logout_url: str = "/super-admin/logout",
    license_summary: Optional[Mapping[str, object]] = None,
) -> str:
    lic_badge = ""
    if license_summary:
        total = int(license_summary.get("total", 0))
        active = int(license_summary.get("active", 0))
        expired = int(license_summary.get("expired", 0))
        archived = int(license_summary.get("archived", 0))
        if expired > 0:
            badge_cls = "danger"
            badge_text = str(expired) + " expired"
            badge_icon = "⚠ "
        elif total == 0:
            badge_cls = ""
            badge_text = "No licenses"
            badge_icon = ""
        else:
            badge_cls = "ok"
            badge_text = str(active) + "/" + str(total) + " active"
            badge_icon = ""
        archived_hint = (" · " + str(archived) + " archived") if archived > 0 else ""
        title_attr = "Licenses: " + str(active) + " active, " + str(expired) + " expired, " + str(archived) + " archived"
        lic_badge = (
            f'<a href="/super-admin?section=billing#billing" title="{escape(title_attr)}" '
            f'style="text-decoration:none;display:flex;align-items:center;gap:4px;">'
            f'<span class="status-pill {badge_cls}" style="font-size:0.72rem;white-space:nowrap;">'
            f'{badge_icon}Licenses: {escape(badge_text)}{escape(archived_hint)}'
            f'</span></a>'
        )
    return f"""
    <header class="app-header">
      <div class="hdr-logo">
        {_brand_mark_sm()}
        <div class="hdr-wordmark">
          <span class="hdr-app">BlueBird Platform</span>
          <span class="hdr-sub">Super Admin Console</span>
        </div>
      </div>
      <div class="hdr-actions">
        {lic_badge}
        <button class="hdr-btn" onclick="bbOpenSaCmdBar()" type="button" title="Search pages and districts (/ or Ctrl+K)" style="display:none;" id="bb-sa-cmdbar-btn">&#128269; Search</button>
        <button class="hdr-btn" onclick="bbToggleTheme()" id="bb-theme-btn" type="button">&#9790; Dark</button>
        <form method="post" action="{logout_url}" style="margin:0;">
          <button class="hdr-btn" type="submit">Log out</button>
        </form>
      </div>
    </header>"""


def _admin_header_html(
    user_display: str,
    school_name: str,
    tenant_selector_html: str,
    logout_url: str,
    extra_action_html: str = "",
    selected_tenant_name: str = "",
) -> str:
    viewing_indicator = (
        f'<span class="hdr-user" style="font-size:0.75rem;">Viewing tenant: <strong>{escape(selected_tenant_name)}</strong></span>'
        if selected_tenant_name and selected_tenant_name != school_name
        else f'<span class="hdr-user" style="font-size:0.75rem;">Viewing tenant: <strong>{escape(school_name)}</strong></span>'
    )
    return f"""
    <header class="app-header">
      <div class="hdr-logo">
        {_brand_mark_sm()}
        <div class="hdr-wordmark">
          <span class="hdr-app">BlueBird Alerts</span>
          <span class="hdr-sub">{escape(school_name)}</span>
        </div>
      </div>
      {tenant_selector_html}
      <div class="hdr-actions">
        {viewing_indicator}
        <span class="hdr-user">&#128100; {escape(user_display)}</span>
        {extra_action_html}
        <button class="hdr-btn" onclick="bbOpenCmdBar()" type="button" title="Search pages and actions (/ or Ctrl+K)" style="display:none;" id="bb-cmdbar-btn">&#128269; Search</button>
        <button class="hdr-btn" onclick="startBluebirdTour()" type="button" title="Take a guided tour of the admin console" style="display:none;" id="bb-tour-btn">&#9654; Tour</button>
        <button class="hdr-btn" onclick="bbToggleTheme()" id="bb-theme-btn" type="button">&#9790; Dark</button>
        <form method="post" action="{logout_url}">
          <button class="hdr-btn" type="submit">Log out</button>
        </form>
      </div>
    </header>"""


def _base_styles() -> str:
    return """
    :root {
      --bg: #eef5ff;
      --bg-deep: #dce9ff;
      --card: #ffffff;
      --panel: rgba(255, 255, 255, 0.90);
      --panel-strong: rgba(255, 255, 255, 0.98);
      --surface: rgba(255, 255, 255, 0.98);
      --border: rgba(18, 52, 120, 0.10);
      --text: #10203f;
      --muted: #5d7398;
      --accent: #1b5fe4;
      --accent-strong: #2f84ff;
      --accent-soft: rgba(27, 95, 228, 0.14);
      --accent-soft-strong: rgba(27, 95, 228, 0.22);
      --nav-bg: linear-gradient(180deg, #092054 0%, #071536 100%);
      --nav-border: rgba(255, 255, 255, 0.10);
      --nav-text: rgba(248, 250, 252, 0.96);
      --nav-muted: rgba(148, 163, 184, 0.82);
      --brand-glow: rgba(47, 132, 255, 0.18);
      --brand-glow-soft: rgba(27, 95, 228, 0.10);
      --success: #16a34a;
      --success-soft: rgba(22, 163, 74, 0.16);
      --danger: #dc2626;
      --danger-soft: rgba(220, 38, 38, 0.16);
      --danger-strong: #b01c1c;
      --warning: #b45309;
      --info: #1d4ed8;
      --quiet: #8e3beb;
      --offline: #6B7280;
      --trial: #D97706;
      /* alert type colors */
      --alert-lockdown: #dc2626;
      --alert-secure:   #1d4ed8;
      --alert-evacuate: #166534;
      --alert-shelter:  #b45309;
      --alert-hold:     #8e3beb;
      --shadow: 0 14px 36px rgba(22, 53, 117, 0.12);
      --radius: 24px;
      --radius-soft: 18px;
      --input-bg: #ffffff;
      /* ── Design-system tokens (aligned with login portal) ── */
      --blue:          #1b5fe4;
      --blue-dark:     #1048c0;
      --blue-soft:     #eff6ff;
      --input-radius:  12px;
      --btn-radius:    12px;
      --card-radius:   20px;
      --shadow-card:   0 32px 80px rgba(0,0,0,.35);
      --shadow-btn:    0 4px 14px rgba(27,95,228,.3);
      --btn-secondary-bg: rgba(255, 255, 255, 0.80);
      --btn-secondary-hover: #ffffff;
      --headline: "Avenir Next", "Segoe UI Variable Display", "SF Pro Display", "Trebuchet MS", sans-serif;
      --body: "Avenir Next", "Segoe UI Variable Text", "SF Pro Text", "Helvetica Neue", sans-serif;
    }
    """ + """
    * { box-sizing: border-box; }
    html[data-theme="dark"] {
      --bg: #0d1829;
      --bg-deep: #0a1020;
      --card: #131f35;
      --panel: rgba(19, 31, 53, 0.92);
      --panel-strong: rgba(19, 31, 53, 0.99);
      --surface: rgba(19, 31, 53, 0.99);
      --border: rgba(99, 140, 210, 0.15);
      --text: #e8f0fe;
      --muted: #8baad4;
      --input-bg: #1e2e4a;
      --btn-secondary-bg: rgba(255,255,255,0.07);
      --btn-secondary-hover: rgba(255,255,255,0.12);
      --card-bg: rgba(25, 40, 66, 0.88);
    }
    html[data-theme="dark"] .field input,
    html[data-theme="dark"] .field select,
    html[data-theme="dark"] .field textarea {
      background: var(--input-bg, #1e2e4a);
      border-color: rgba(99, 140, 210, 0.22);
      color: var(--text);
    }
    html[data-theme="dark"] .field input:focus,
    html[data-theme="dark"] .field select:focus,
    html[data-theme="dark"] .field textarea:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(77, 139, 255, 0.20);
    }
    html[data-theme="dark"] .table-search input {
      background: var(--input-bg, #1e2e4a);
      border-color: rgba(99, 140, 210, 0.22);
      color: var(--text);
    }
    html[data-theme="dark"] .button-secondary {
      background: var(--btn-secondary-bg);
      color: var(--text);
      border-color: rgba(99, 140, 210, 0.28);
    }
    html[data-theme="dark"] .button-secondary:hover:not(:disabled) {
      background: var(--btn-secondary-hover);
      border-color: var(--accent);
    }
    html[data-theme="dark"] .metric-card,
    html[data-theme="dark"] .user-card {
      background: var(--card-bg);
      border-color: rgba(99, 140, 210, 0.14);
    }
    html[data-theme="dark"] .data-table tbody tr:hover {
      background: rgba(77, 139, 255, 0.10);
    }
    html[data-theme="dark"] .data-table th {
      background: rgba(77, 139, 255, 0.06);
    }
    html[data-theme="dark"] code {
      background: rgba(255, 255, 255, 0.07);
      color: #93c5fd;
    }
    html[data-theme="dark"] .status-pill.ok   { background: rgba(22,101,52,0.28); }
    html[data-theme="dark"] .status-pill.danger { background: rgba(220,38,38,0.22); }
    html[data-theme="dark"] .status-pill.warn  { background: rgba(180,83,9,0.24); }
    html[data-theme="dark"] .status-pill.info  { background: rgba(29,78,216,0.24); }
    html[data-theme="dark"] .status-pill.quiet { background: rgba(142,59,235,0.22); }
    html[data-theme="dark"] .flash {
      background: rgba(19,31,53,0.96);
      border-color: rgba(99, 140, 210, 0.22);
      color: var(--text);
    }
    html[data-theme="dark"] .flash.error { background: rgba(220,38,38,0.14); }
    html[data-theme="dark"] .flash.success { background: rgba(22,101,52,0.16); }
    html[data-theme="dark"] .hero-card {
      background: linear-gradient(180deg, rgba(19,31,53,0.98), rgba(15,25,48,0.96));
    }
    html { scroll-padding-top: 80px; scroll-behavior: smooth; }
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
    .theme-toggle-btn {
      display: flex; align-items: center; gap: 6px;
      background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.14);
      color: var(--nav-text); border-radius: 8px;
      padding: 6px 12px; font-size: 0.78rem; font-weight: 600;
      cursor: pointer; width: 100%; margin-top: 8px;
      transition: background 0.15s;
    }
    .theme-toggle-btn:hover { background: rgba(255,255,255,0.15); }
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
    .status-pill.ok      { color: var(--success); background: var(--success-soft); border-color: color-mix(in srgb, var(--success) 22%, transparent); }
    .status-pill.danger  { color: var(--danger);  background: var(--danger-soft);  border-color: color-mix(in srgb, var(--danger)  22%, transparent); }
    .status-pill.warn    { color: var(--warning); background: color-mix(in srgb, var(--warning) 15%, white); border-color: color-mix(in srgb, var(--warning) 22%, transparent); }
    .status-pill.muted   { color: var(--muted);   background: rgba(0,0,0,0.05); border-color: rgba(0,0,0,0.08); }
    .status-pill.offline { color: #64748b; background: rgba(100,116,139,0.09); border-color: rgba(100,116,139,0.18); }
    .status-pill.info    { color: var(--info); background: color-mix(in srgb, var(--info) 11%, white); border-color: color-mix(in srgb, var(--info) 22%, transparent); }
    .status-pill.quiet   { color: var(--quiet); background: color-mix(in srgb, var(--quiet) 11%, white); border-color: color-mix(in srgb, var(--quiet) 22%, transparent); }
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
      transition: border-color 120ms ease, box-shadow 120ms ease;
    }
    .field input:focus, .field select:focus, .field textarea:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(27,95,228,0.14);
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
      transition: filter 130ms ease, transform 120ms ease, background 130ms ease,
                  border-color 130ms ease, box-shadow 130ms ease, opacity 130ms ease;
    }
    .button-primary {
      background: linear-gradient(180deg, var(--accent-strong), var(--accent));
      color: #fff;
      box-shadow: 0 2px 8px rgba(27,95,228,0.22);
    }
    .button-primary:hover:not(:disabled) {
      filter: brightness(1.09);
      transform: translateY(-1px);
      box-shadow: 0 4px 14px rgba(27,95,228,0.30);
    }
    .button-primary:active:not(:disabled) { transform: translateY(0); filter: brightness(0.96); }
    .button-secondary {
      background: rgba(255,255,255,0.9);
      color: var(--text);
      border: 1px solid var(--border);
    }
    .button-secondary:hover:not(:disabled) {
      background: var(--card, #fff);
      border-color: var(--accent);
      transform: translateY(-1px);
      box-shadow: 0 2px 8px rgba(27,95,228,0.10);
    }
    .button-secondary:active:not(:disabled) { transform: translateY(0); }
    .button-danger {
      background: linear-gradient(180deg, color-mix(in srgb, var(--danger) 82%, #fff 18%), var(--danger-strong));
      color: #fff;
      box-shadow: 0 2px 8px rgba(220,38,38,0.18);
    }
    .button-danger:hover:not(:disabled) {
      filter: brightness(1.07);
      transform: translateY(-1px);
      box-shadow: 0 4px 12px rgba(220,38,38,0.26);
    }
    .button-danger:active:not(:disabled) { transform: translateY(0); filter: brightness(0.96); }
    .button-danger-outline {
      background: color-mix(in srgb, var(--danger) 10%, #fff 90%);
      color: var(--danger);
      border: 1px solid color-mix(in srgb, var(--danger) 20%, transparent);
    }
    .button-danger-outline:hover:not(:disabled) {
      background: color-mix(in srgb, var(--danger) 16%, #fff 84%);
      border-color: color-mix(in srgb, var(--danger) 38%, transparent);
      transform: translateY(-1px);
    }
    .button:disabled, button:disabled, .button[disabled], button[disabled] {
      opacity: 0.46;
      cursor: not-allowed;
      transform: none !important;
      box-shadow: none !important;
      filter: none !important;
    }
    .button:focus-visible, button:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }
    .flash {
      padding: 14px 16px;
      border-radius: 16px;
      border: 1px solid var(--border);
      border-left: 4px solid var(--accent);
      background: rgba(255,255,255,0.95);
      color: var(--text);
    }
    .flash.error {
      border-color: color-mix(in srgb, var(--danger) 24%, transparent);
      border-left-color: var(--danger);
      background: color-mix(in srgb, var(--danger) 8%, #fff 92%);
      color: color-mix(in srgb, var(--danger) 72%, #000 28%);
    }
    .flash.success {
      border-color: color-mix(in srgb, var(--success) 24%, transparent);
      border-left-color: var(--success);
      background: color-mix(in srgb, var(--success) 8%, #fff 92%);
      color: color-mix(in srgb, var(--success) 72%, #000 28%);
    }
    .bb-911-notice {
      display: flex; align-items: center; justify-content: space-between;
      gap: 12px;
      padding: 11px 16px;
      border-radius: 10px;
      border: 1px solid rgba(180,83,9,.22);
      border-left: 4px solid #d97706;
      background: rgba(254,243,199,.7);
      color: #78350f;
      font-size: 0.82rem; line-height: 1.45;
      margin-bottom: 16px;
    }}
    .bb-911-notice strong {{ color: #92400e; }}
    .bb-911-notice-close {{
      background: none; border: none; cursor: pointer;
      color: #92400e; font-size: 1.1rem; line-height: 1;
      padding: 0 2px; flex-shrink: 0; opacity: .7;
    }}
    .bb-911-notice-close:hover {{ opacity: 1; }}
    html[data-theme="dark"] .bb-911-notice {{
      background: rgba(120,53,15,.18);
      border-color: rgba(217,119,6,.25);
      border-left-color: #d97706;
      color: #fcd34d;
    }}
    html[data-theme="dark"] .bb-911-notice strong {{ color: #fde68a; }}
    html[data-theme="dark"] .bb-911-notice-close {{ color: #fcd34d; }}
    .app-shell {
      display: grid;
      grid-template-areas: "header header" "sidebar workspace";
      grid-template-rows: 64px 1fr;
      grid-template-columns: 300px 1fr;
      height: 100vh;
      overflow: hidden;
    }
    .app-header {
      grid-area: header;
      display: flex;
      align-items: center;
      gap: 14px;
      padding: 0 20px;
      background: linear-gradient(90deg, #092054, #071536);
      border-bottom: 1px solid var(--nav-border);
      box-shadow: 0 2px 12px rgba(27,95,228,0.18);
      z-index: 10;
    }
    .app-header .hdr-logo { flex: 0 0 auto; display: flex; align-items: center; gap: 10px; }
    .app-header .hdr-wordmark { display: grid; gap: 0; }
    .app-header .hdr-app { font-size: 0.82rem; font-weight: 800; color: var(--nav-text); letter-spacing: 0.01em; }
    .app-header .hdr-sub { font-size: 0.7rem; color: var(--nav-muted); }
    .app-header .hdr-actions { margin-left: auto; display: flex; align-items: center; gap: 10px; }
    .app-header .hdr-user { font-size: 0.8rem; color: var(--nav-muted); white-space: nowrap; }
    .app-header form { margin: 0; display: flex; align-items: center; gap: 6px; }
    .app-header select {
      appearance: none; border: 1px solid rgba(255,255,255,0.16); border-radius: 8px;
      background: rgba(255,255,255,0.08); color: var(--nav-text); font: inherit;
      font-size: 0.78rem; padding: 5px 10px; cursor: pointer;
    }
    .app-header label { font-size: 0.75rem; color: var(--nav-muted); }
    .hdr-btn {
      appearance: none; border: 1px solid rgba(255,255,255,0.16); border-radius: 8px;
      background: rgba(255,255,255,0.08); color: var(--nav-text); font: inherit;
      font-size: 0.78rem; font-weight: 600; padding: 5px 11px; cursor: pointer;
      transition: background 0.15s;
    }
    .hdr-btn:hover { background: rgba(255,255,255,0.16); }
    .hdr-select {
      appearance: none; border: 1px solid rgba(255,255,255,0.16); border-radius: 8px;
      background: rgba(255,255,255,0.08); color: var(--nav-text); font: inherit;
      font-size: 0.78rem; padding: 5px 28px 5px 10px; cursor: pointer;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='rgba(255,255,255,0.6)' stroke-width='2.5'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 8px center;
    }
    .sidebar {
      grid-area: sidebar;
      overflow-y: auto;
      min-height: 0;
      display: grid;
      gap: 14px;
      align-content: start;
      padding: 16px;
    }
    .content-stack { display: grid; gap: 18px; align-content: start; }
    .nav-panel {
      border-right: 1px solid var(--nav-border);
      background:
        radial-gradient(circle at top left, var(--brand-glow), transparent 22%),
        var(--nav-bg);
      color: var(--nav-text);
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
      object-fit: contain;
      padding: 6px;
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
    .workspace {
      grid-area: workspace;
      overflow-y: auto;
      min-height: 0;
      padding: 22px 24px;
      min-width: 0;
      display: grid;
      gap: 18px;
      align-content: start;
    }
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
      cursor: pointer;
      transition: border-color 120ms ease, background 120ms ease;
    }
    .checkbox-row:hover { border-color: var(--accent); background: rgba(255,255,255,0.98); }
    .checkbox-row input { width: 18px; height: 18px; cursor: pointer; flex: 0 0 auto; }
    .checkbox-row span, .checkbox-row label { font-size: 0.92rem; color: var(--text); }
    html[data-theme="dark"] .checkbox-row { background: rgba(255,255,255,0.05); border-color: rgba(99,140,210,0.22); }
    html[data-theme="dark"] .checkbox-row:hover { border-color: var(--accent); background: rgba(255,255,255,0.09); }
    .field select {
      appearance: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2.5'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 12px center;
      padding-right: 32px;
    }
    html[data-theme="dark"] .field select {
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%238baad4' stroke-width='2.5'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
    }
    table { width: 100%; border-collapse: collapse; }
    th, td {
      padding: 12px 10px;
      text-align: left;
      border-top: 1px solid var(--border);
      vertical-align: top;
      font-size: 0.95rem;
    }
    th { color: var(--muted); border-top: 0; }
    .table-wrapper { overflow-x: auto; border-radius: 12px; }
    code {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      background: rgba(15, 23, 42, 0.05);
      padding: 2px 6px;
      border-radius: 8px;
    }
    .mini-copy { color: var(--muted); font-size: 0.88rem; line-height: 1.45; }
    .shell-actions { display: grid; gap: 12px; }
    @media (max-width: 1100px) {
      .app-shell {
        grid-template-areas: "header" "sidebar" "workspace";
        grid-template-rows: 64px auto 1fr;
        grid-template-columns: 1fr;
        height: auto;
        overflow: visible;
      }
      .sidebar { overflow-y: visible; padding: 12px 16px; }
      .workspace { overflow-y: visible; padding: 16px; }
      .login-shell { grid-template-columns: 1fr; }
      .span-8, .span-7, .span-6, .span-5, .span-4 { grid-column: span 12; }
    }
    .data-table th {
      background: rgba(27, 95, 228, 0.04);
      border-bottom: 2px solid var(--border);
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--muted);
      white-space: nowrap;
    }
    .data-table tbody tr { transition: background 100ms ease; }
    .data-table tbody tr:hover { background: rgba(27, 95, 228, 0.08); }
    .table-wrap { overflow-x: auto; border-radius: 12px; }
    .table-search { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }
    .table-search input {
      flex: 1;
      min-height: 38px;
      max-width: 360px;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.95);
      padding: 0 12px;
      font: inherit;
      font-size: 0.92rem;
      color: var(--text);
    }
    .school-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 16px;
    }
    .school-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 18px 20px;
      cursor: pointer;
      user-select: none;
      transition: transform 150ms ease, box-shadow 150ms ease, border-color 150ms ease;
      box-shadow: 0 2px 8px rgba(0,0,0,0.06);
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .school-card:hover {
      transform: translateY(-2px);
      box-shadow: 0 6px 20px rgba(0,0,0,0.12);
    }
    .school-card.drag-over { outline: 2px solid var(--accent); }
    .school-card--alarm  { border-color: rgba(220,38,38,0.45); background: rgba(220,38,38,0.04); }
    .school-card--training { border-color: rgba(180,83,9,0.45); background: rgba(180,83,9,0.04); }
    .school-card--alarm:hover  { border-color: rgba(220,38,38,0.7); }
    .school-card--training:hover { border-color: rgba(180,83,9,0.7); }
    .school-card-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 10px;
    }
    .school-card-name {
      font-size: 15px;
      font-weight: 600;
      line-height: 1.35;
      color: var(--text);
      flex: 1;
      min-width: 0;
      overflow-wrap: break-word;
    }
    .school-card-message {
      color: var(--muted);
      font-size: 0.78rem;
      line-height: 1.4;
      margin: 0;
    }
    .school-card-footer {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: auto;
    }
    .school-card-last { color: var(--muted); font-size: 0.75rem; }
    .school-card-drag {
      color: var(--muted);
      font-size: 16px;
      cursor: grab;
      padding: 2px 4px;
      flex-shrink: 0;
      opacity: 0.5;
    }
    @media (max-width: 700px) {
      .school-grid { grid-template-columns: 1fr; }
    }
    @media (min-width: 701px) and (max-width: 1023px) {
      .school-grid { grid-template-columns: repeat(2, 1fr); }
    }
    /* ── MSP Dashboard ─────────────────────────────────────────────────── */
    .msp-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 16px;
      margin-bottom: 28px;
    }
    .msp-card {
      background: var(--card, #fff);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 16px 18px 14px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      transition: box-shadow 0.15s, transform 0.15s;
    }
    .msp-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.09); transform: translateY(-1px); }
    .msp-card-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
    .msp-card-type { font-size: 0.68rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
    .msp-card-name { font-size: 1rem; font-weight: 700; margin: 2px 0 0; }
    .msp-card-meta { display: flex; gap: 12px; font-size: 0.78rem; color: var(--muted); flex-wrap: wrap; }
    .msp-card-badges { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; min-height: 16px; }
    .msp-card-actions { margin-top: 4px; }
    .msp-detail-drawer {
      grid-column: 1 / -1;
      background: var(--bg-offset, #f8fafc);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 20px 24px;
      margin-bottom: 4px;
    }
    .msp-detail-drawer h4 { font-size: 0.85rem; font-weight: 600; margin: 0 0 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
    .msp-school-list { list-style: none; margin: 0 0 12px; padding: 0; display: flex; flex-direction: column; gap: 6px; }
    .msp-school-row { display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; background: var(--card); border: 1px solid var(--border); border-radius: 6px; font-size: 0.83rem; }
    .msp-note-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px; }
    .msp-note-item { background: var(--card); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; font-size: 0.82rem; display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
    .msp-note-meta { font-size: 0.72rem; color: var(--muted); margin-top: 2px; }
    .msp-search-bar { display: flex; gap: 10px; align-items: center; margin-bottom: 16px; }
    .msp-search-bar input { flex: 1; }
    @media (max-width: 700px) { .msp-grid { grid-template-columns: 1fr; } }

    /* ── Tenant Registry Cards ─────────────────────────────────────────── */
    .tenant-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 16px;
      margin-bottom: 8px;
    }
    .tenant-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 18px 20px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      transition: box-shadow 0.15s, transform 0.15s;
    }
    .tenant-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.09); transform: translateY(-1px); }
    .tenant-card--archived { opacity: 0.7; border-style: dashed; }
    .tenant-card-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
    .tenant-card-name { font-size: 1rem; font-weight: 700; color: var(--text); line-height: 1.3; }
    .tenant-card-badges { display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; flex-shrink: 0; }
    .tenant-card-meta { font-size: 0.82rem; color: var(--muted); line-height: 1.7; }
    .tenant-card-actions { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-top: auto; }
    .tenant-search { margin-bottom: 16px; }
    .tenant-archived-section { margin-top: 28px; border-top: 1px solid var(--border); padding-top: 20px; }
    .tenant-archived-toggle { display: flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; background: none; border: none; padding: 0; color: var(--muted); font-size: 0.88rem; font-weight: 600; }
    .tenant-archived-toggle:hover { color: var(--text); }
    @media (max-width: 700px) { .tenant-grid { grid-template-columns: 1fr; } }

    td.empty-state {
      text-align: center;
      padding: 36px 16px;
      color: var(--muted);
      font-size: 0.9rem;
      border-top: none;
    }
    td.empty-state::before {
      display: block;
      font-size: 1.6rem;
      margin-bottom: 8px;
      opacity: 0.35;
      content: "—";
    }
    .count-badge {
      display: inline-flex;
      min-width: 22px;
      height: 22px;
      align-items: center;
      justify-content: center;
      padding: 0 7px;
      border-radius: 999px;
      background: var(--danger);
      color: #fff;
      font-size: 0.75rem;
      font-weight: 800;
      vertical-align: middle;
      margin-left: 6px;
    }
    /* ── Enterprise User Management ─────────────────────────────────────── */
    .role-badge {
      display: inline-flex; align-items: center; padding: 3px 10px;
      border-radius: 999px; font-size: 0.73rem; font-weight: 700;
      letter-spacing: 0.03em; white-space: nowrap; vertical-align: middle;
    }
    .rb-district_admin { background: linear-gradient(135deg,#5b21b6,#4338ca); color:#fff; }
    .rb-admin, .rb-building_admin { background: rgba(27,95,228,.13); color:#1e40af; border:1px solid rgba(27,95,228,.22); }
    .rb-teacher, .rb-staff { background: rgba(71,85,105,.09); color:#475569; border:1px solid rgba(71,85,105,.18); }
    .rb-law_enforcement { background: rgba(180,83,9,.12); color:#92400e; border:1px solid rgba(180,83,9,.22); }
    .rb-super_admin { background: linear-gradient(135deg,#0f172a,#1e293b); color:#e2e8f0; }
    .um-avatar {
      width:36px; height:36px; border-radius:50%; display:inline-flex;
      align-items:center; justify-content:center; font-size:0.73rem;
      font-weight:800; flex-shrink:0; letter-spacing:0.02em;
    }
    .ua-district_admin { background:linear-gradient(135deg,#5b21b6,#4338ca); color:#fff; }
    .ua-admin, .ua-building_admin { background:rgba(27,95,228,.16); color:#1e40af; }
    .ua-teacher, .ua-staff { background:rgba(71,85,105,.12); color:#475569; }
    .ua-law_enforcement { background:rgba(180,83,9,.14); color:#92400e; }
    .ua-super_admin { background:linear-gradient(135deg,#0f172a,#1e293b); color:#e2e8f0; }
    .um-name-cell { display:flex; align-items:center; gap:12px; }
    .um-name-stack { display:flex; flex-direction:column; gap:1px; }
    .um-name { font-weight:600; font-size:0.92rem; color:var(--text); }
    .um-sub { font-size:0.76rem; color:var(--muted); }
    .um-table { border-collapse: collapse; width: 100%; }
    .um-table thead th {
      background:rgba(27,95,228,.04); border-bottom:2px solid var(--border);
      font-size:0.72rem; font-weight:700; letter-spacing:0.05em;
      text-transform:uppercase; color:var(--muted); padding:10px 12px; white-space:nowrap;
    }
    .um-table tbody tr {
      cursor:pointer; border-bottom:1px solid rgba(0,0,0,.045);
      transition:background 110ms ease;
    }
    .um-table tbody tr:hover { background:rgba(27,95,228,.055); }
    .um-table tbody tr.um-row-active { background:rgba(27,95,228,.10); box-shadow:inset 3px 0 0 var(--accent); }
    .um-table td { padding:12px 12px; vertical-align:middle; font-size:0.9rem; border:0; }
    /* Slide panel */
    .um-detail-panel {
      position:fixed; top:0; right:-440px; width:420px; height:100vh;
      background:var(--card, #fff); border-left:1px solid var(--border);
      box-shadow:-8px 0 40px rgba(0,0,0,.13); z-index:1000;
      transition:right 260ms cubic-bezier(0.22,0.61,0.36,1);
      overflow-y:auto; display:flex; flex-direction:column;
    }
    .um-detail-panel.open { right:0; }
    .um-panel-overlay {
      display:none; position:fixed; inset:0;
      background:rgba(0,0,0,.18); z-index:999; backdrop-filter:blur(2px);
    }
    .um-panel-overlay.open { display:block; }
    .um-panel-hd {
      padding:22px 22px 16px; border-bottom:1px solid var(--border);
      background:linear-gradient(180deg,rgba(27,95,228,.04),transparent);
      position:relative; flex-shrink:0;
    }
    .um-panel-avatar {
      width:52px; height:52px; border-radius:50%; display:flex;
      align-items:center; justify-content:center; font-size:1.1rem;
      font-weight:800; margin-bottom:12px;
    }
    .um-panel-close {
      position:absolute; top:14px; right:14px; width:30px; height:30px;
      border-radius:50%; border:1px solid var(--border); background:#fff;
      cursor:pointer; display:flex; align-items:center; justify-content:center;
      font-size:1rem; color:var(--muted); transition:background 120ms;
      line-height:1;
    }
    .um-panel-close:hover { background:rgba(220,38,38,.1); color:var(--danger); }
    .um-panel-name { font-size:1.05rem; font-weight:700; margin:0 0 3px; color:var(--text); }
    .um-panel-meta { color:var(--muted); font-size:0.8rem; line-height:1.5; }
    .um-panel-body { padding:18px 22px; display:flex; flex-direction:column; gap:18px; }
    .um-panel-sect-label {
      font-size:0.7rem; font-weight:700; text-transform:uppercase;
      letter-spacing:0.08em; color:var(--muted); margin:0 0 8px;
    }
    .um-perm-list { display:flex; flex-direction:column; gap:4px; }
    .um-perm-item {
      display:flex; align-items:center; gap:8px; font-size:0.8rem;
      padding:5px 10px; border-radius:8px; background:rgba(0,0,0,.025); color:var(--text);
    }
    .um-perm-dot { width:6px; height:6px; border-radius:50%; background:var(--success); flex-shrink:0; }
    .um-panel-actions { display:flex; flex-direction:column; gap:8px; }
    /* Security health bar */
    .um-health-bar {
      display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr));
      gap:10px; margin-bottom:18px;
    }
    .um-hcard {
      background:rgba(255,255,255,.92); border:1px solid var(--border);
      border-radius:12px; padding:13px 16px; position:relative; overflow:hidden;
    }
    .um-hcard::before {
      content:""; position:absolute; top:0; left:0; right:0;
      height:3px; border-radius:3px 3px 0 0;
    }
    .um-hcard.hc-ok::before { background:var(--success); }
    .um-hcard.hc-warn::before { background:var(--warning); }
    .um-hcard.hc-danger::before { background:var(--danger); }
    .um-hcard-label { font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.05em; color:var(--muted); margin-bottom:4px; }
    .um-hcard-value { font-size:1.55rem; font-weight:800; line-height:1; color:var(--text); }
    .um-hcard-sub { font-size:0.7rem; color:var(--muted); margin-top:3px; }
    /* Role change modal */
    .um-modal-wrap {
      display:none; position:fixed; inset:0;
      background:rgba(0,0,0,.4); z-index:1100;
      backdrop-filter:blur(4px); align-items:center; justify-content:center;
    }
    .um-modal-wrap.open { display:flex; }
    .um-modal {
      background:var(--card, #fff); border-radius:20px; padding:28px 30px;
      max-width:420px; width:90%;
      box-shadow:0 24px 64px rgba(0,0,0,.22);
    }
    .um-modal h3 { margin:0 0 8px; font-size:1.05rem; color:var(--text); }
    .um-modal-desc { color:var(--muted); font-size:0.88rem; margin:0 0 14px; line-height:1.55; }
    .um-modal-warning {
      background:rgba(220,38,38,.08); border:1px solid rgba(220,38,38,.22);
      border-radius:10px; padding:10px 14px; color:#b91c1c;
      font-size:0.8rem; margin-bottom:18px; line-height:1.45;
    }
    .um-modal-actions { display:flex; gap:10px; justify-content:flex-end; }
    /* Collapsible edit forms */
    .um-edit-wrap { display:none; }
    .um-edit-wrap.open { display:block; }
    /* Toast */
    .bb-toast {
      position:fixed; bottom:26px; right:26px;
      background:#1e293b; color:#fff;
      padding:11px 18px; border-radius:14px; font-size:0.86rem; font-weight:500;
      z-index:2000; opacity:0; transform:translateY(6px);
      transition:opacity 220ms ease,transform 220ms ease;
      box-shadow:0 8px 24px rgba(0,0,0,.22); pointer-events:none;
    }
    .bb-toast.show { opacity:1; transform:translateY(0); }
    .bb-toast.ok { background:linear-gradient(135deg,#065f46,#047857); }
    .bb-toast.err { background:linear-gradient(135deg,#991b1b,#dc2626); }

    /* ── Help Tooltip System ────────────────────────────────────────────── */
    .help-tip {
      display: inline-flex; align-items: center; justify-content: center;
      width: 16px; height: 16px; border-radius: 50%;
      background: var(--accent-soft); color: var(--accent);
      font-size: 9px; font-weight: 800; font-style: normal;
      cursor: default; position: relative; vertical-align: middle;
      margin-left: 5px; flex-shrink: 0;
      border: 1px solid var(--accent-soft-strong);
      user-select: none; line-height: 1;
    }
    .help-tip:hover .tip-text, .help-tip:focus-within .tip-text { display: block; }
    .tip-text {
      display: none; position: absolute;
      left: 50%; bottom: calc(100% + 8px);
      transform: translateX(-50%);
      background: var(--text); color: var(--panel);
      font-size: 0.74rem; font-weight: 400; line-height: 1.45;
      padding: 8px 12px; border-radius: 8px;
      white-space: normal; width: 220px; min-width: 160px;
      z-index: 2000; pointer-events: none;
      text-align: left; box-shadow: 0 6px 20px rgba(0,0,0,0.22);
    }
    .tip-text::after {
      content: ''; position: absolute; top: 100%; left: 50%;
      transform: translateX(-50%);
      border: 5px solid transparent; border-top-color: var(--text);
    }
    .tip-text--right { left: auto; right: 0; transform: none; }
    .tip-text--right::after { left: auto; right: 12px; transform: none; }
    html[data-theme="dark"] .help-tip { background: rgba(77,139,255,0.18); border-color: rgba(77,139,255,0.35); }
    html[data-theme="dark"] .tip-text { background: #e8f0fe; color: #10203f; }
    html[data-theme="dark"] .tip-text::after { border-top-color: #e8f0fe; }
    html[data-theme="dark"] .tip-text--right::after { border-top-color: #e8f0fe; }

    /* ── Next Steps Panel ───────────────────────────────────────────────── */
    .bb-nsp {
      background: linear-gradient(135deg, rgba(27,95,228,0.05), rgba(47,132,255,0.02));
      border: 1px solid var(--accent-soft-strong);
      border-radius: 18px; padding: 16px 20px; margin-bottom: 20px; display: none;
    }
    .bb-nsp-header {
      display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;
    }
    .bb-nsp-title { font-size: 0.78rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.08em; color: var(--accent); }
    .bb-nsp-dismiss { background: none; border: none; cursor: pointer;
      font-size: 0.75rem; color: var(--muted); padding: 2px 6px; border-radius: 4px; }
    .bb-nsp-dismiss:hover { background: var(--accent-soft); color: var(--accent); }
    .bb-nsp-items { display: flex; flex-direction: column; gap: 8px; }
    .bb-nsp-item {
      display: flex; align-items: center; gap: 12px; padding: 10px 14px;
      border-radius: 10px; background: var(--panel-strong); border: 1px solid var(--border);
    }
    .bb-nsp-icon { font-size: 1.1rem; flex-shrink: 0; width: 26px; text-align: center; }
    .bb-nsp-body { flex: 1; min-width: 0; }
    .bb-nsp-item-title { font-size: 0.86rem; font-weight: 600; color: var(--text); }
    .bb-nsp-item-desc { font-size: 0.75rem; color: var(--muted); margin-top: 1px; }
    .bb-nsp-cta { flex-shrink: 0; }
    html[data-theme="dark"] .bb-nsp {
      background: linear-gradient(135deg, rgba(77,139,255,0.08), rgba(27,95,228,0.04));
    }

    /* ── Command Bar ────────────────────────────────────────────────────── */
    .bb-cmdbar-overlay {
      position: fixed; inset: 0; background: rgba(0,0,0,0.52);
      backdrop-filter: blur(3px); -webkit-backdrop-filter: blur(3px);
      z-index: 9100; display: none; align-items: flex-start;
      justify-content: center; padding-top: 11vh;
    }
    .bb-cmdbar-overlay.open { display: flex; }
    .bb-cmdbar {
      background: var(--panel-strong); border: 1px solid var(--border);
      border-radius: 18px; width: 100%; max-width: 580px;
      box-shadow: 0 28px 72px rgba(0,0,0,0.30); overflow: hidden;
      animation: bb-cmd-in 0.14s ease;
    }
    @keyframes bb-cmd-in {
      from { opacity: 0; transform: translateY(-12px) scale(0.98); }
      to   { opacity: 1; transform: translateY(0) scale(1); }
    }
    .bb-cmdbar-top {
      display: flex; align-items: center; gap: 10px;
      padding: 14px 18px; border-bottom: 1px solid var(--border);
    }
    .bb-cmdbar-search-icon { color: var(--muted); font-size: 1rem; flex-shrink: 0; }
    .bb-cmdbar-input {
      flex: 1; border: none; outline: none; background: transparent;
      font-size: 1rem; color: var(--text); font-family: var(--body);
    }
    .bb-cmdbar-input::placeholder { color: var(--muted); }
    .bb-cmdbar-kbd {
      font-size: 0.68rem; color: var(--muted); border: 1px solid var(--border);
      border-radius: 4px; padding: 2px 6px; flex-shrink: 0; background: var(--surface);
    }
    .bb-cmdbar-results { max-height: 380px; overflow-y: auto; padding: 6px 6px 4px; }
    .bb-cmdbar-item {
      display: flex; align-items: center; gap: 10px;
      padding: 9px 12px; border-radius: 9px; cursor: pointer;
      transition: background 0.08s;
    }
    .bb-cmdbar-item:hover, .bb-cmdbar-item.bb-cmd-sel { background: var(--accent-soft); }
    .bb-cmdbar-item-icon {
      font-size: 0.9rem; flex-shrink: 0; width: 26px; text-align: center;
      color: var(--muted);
    }
    .bb-cmdbar-item-info { flex: 1; min-width: 0; }
    .bb-cmdbar-item-label { font-size: 0.88rem; font-weight: 600; color: var(--text); }
    .bb-cmdbar-item-desc { font-size: 0.74rem; color: var(--muted); }
    .bb-cmdbar-item-badge {
      font-size: 0.63rem; color: var(--muted); border: 1px solid var(--border);
      border-radius: 4px; padding: 1px 5px; flex-shrink: 0; text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .bb-cmdbar-empty { text-align: center; padding: 28px; color: var(--muted);
      font-size: 0.88rem; }
    .bb-cmdbar-footer {
      padding: 8px 16px; border-top: 1px solid var(--border);
      display: flex; gap: 16px; font-size: 0.7rem; color: var(--muted);
    }
    .bb-cmdbar-footer kbd {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 3px; padding: 1px 5px; font-family: monospace;
    }
    .bb-cmdbar-section-label {
      font-size: 0.67rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.08em; color: var(--muted); padding: 10px 12px 4px;
    }

    /* ── Smart Confirm Dialog ───────────────────────────────────────────── */
    .bb-sconfirm-overlay {
      position: fixed; inset: 0; background: rgba(0,0,0,0.55);
      backdrop-filter: blur(2px); -webkit-backdrop-filter: blur(2px);
      z-index: 9200; display: none; align-items: center; justify-content: center;
    }
    .bb-sconfirm-overlay.open { display: flex; }
    .bb-sconfirm {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 20px; padding: 28px 30px;
      max-width: 440px; width: calc(100% - 48px);
      box-shadow: 0 20px 64px rgba(0,0,0,0.30);
      animation: bb-sconfirm-in 0.16s ease;
    }
    @keyframes bb-sconfirm-in {
      from { opacity: 0; transform: scale(0.95); }
      to   { opacity: 1; transform: scale(1); }
    }
    .bb-sconfirm-icon { font-size: 2rem; margin-bottom: 10px; }
    .bb-sconfirm h3 { margin: 0 0 8px; font-size: 1.1rem; color: var(--text); }
    .bb-sconfirm-body {
      font-size: 0.9rem; color: var(--muted); line-height: 1.55; margin-bottom: 20px;
    }
    .bb-sconfirm-consequence {
      background: rgba(220,38,38,0.07); border: 1px solid rgba(220,38,38,0.18);
      border-radius: 8px; padding: 10px 14px; font-size: 0.82rem; color: #b91c1c;
      margin-bottom: 18px; line-height: 1.45;
    }
    html[data-theme="dark"] .bb-sconfirm-consequence {
      background: rgba(220,38,38,0.12); color: #fca5a5;
    }
    .bb-sconfirm-type-label { font-size: 0.78rem; color: var(--muted); margin-bottom: 6px; }
    .bb-sconfirm-type-input {
      width: 100%; padding: 9px 12px; border-radius: 8px;
      border: 1px solid var(--border); font-size: 0.9rem; font-family: monospace;
      outline: none; background: var(--input-bg); color: var(--text); margin-bottom: 16px;
    }
    .bb-sconfirm-type-input:focus { border-color: var(--accent); }
    .bb-sconfirm-actions { display: flex; gap: 10px; justify-content: flex-end; }

    /* ── Guided Tour ────────────────────────────────────────────────────── */
    @keyframes bb-tour-pulse {
      0%,100% { box-shadow: 0 0 0 0 rgba(27,95,228,0.5); }
      50% { box-shadow: 0 0 0 8px rgba(27,95,228,0); }
    }
    .bb-tour-highlight {
      outline: 3px solid var(--accent) !important;
      outline-offset: 5px !important;
      border-radius: var(--radius) !important;
      animation: bb-tour-pulse 1.6s ease-in-out 2;
      position: relative; z-index: 9002 !important;
    }
    .bb-sg {
      background: var(--card); border: 1px solid var(--border);
      border-left: 4px solid var(--accent); border-radius: var(--radius);
      padding: 14px 16px; margin-bottom: 16px;
    }
    .bb-sg-header {
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 10px;
    }
    .bb-sg-title { font-size: 0.78rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.04em; color: var(--accent); }
    .bb-sg-items { display: flex; flex-direction: column; gap: 10px; }
    .bb-sg-item {
      display: flex; align-items: flex-start; gap: 10px;
      padding: 10px 12px; border-radius: calc(var(--radius) - 2px);
      background: var(--bg); border: 1px solid var(--border);
      transition: opacity 0.3s;
    }
    .bb-sg-item[data-prio="high"] { border-left: 3px solid #ef4444; }
    .bb-sg-item[data-prio="medium"] { border-left: 3px solid #f59e0b; }
    .bb-sg-item[data-prio="low"] { border-left: 3px solid var(--accent); }
    .bb-sg-icon { font-size: 1.2rem; flex-shrink: 0; width: 26px; text-align: center; margin-top: 1px; }
    .bb-sg-body { flex: 1; min-width: 0; }
    .bb-sg-item-title { font-size: 0.86rem; font-weight: 600; color: var(--text); margin-bottom: 2px; }
    .bb-sg-item-desc { font-size: 0.75rem; color: var(--muted); }
    .bb-sg-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
    .bb-sg-dismiss {
      background: none; border: none; cursor: pointer; color: var(--muted);
      font-size: 0.9rem; padding: 2px 6px; border-radius: 4px; line-height: 1;
    }
    .bb-sg-dismiss:hover { background: var(--accent-soft); color: var(--accent); }
    html[data-theme="dark"] .bb-sg { border-color: rgba(255,255,255,0.08); border-left-color: var(--accent); }
    html[data-theme="dark"] .bb-sg-item { background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.08); }
    /* ── District Admin Welcome Modal ───────────────────────────────────────── */
    .bb-da-wb-ov {
      position: fixed; inset: 0; background: rgba(0,0,0,0.62);
      z-index: 9500; display: none;
      align-items: center; justify-content: center;
    }
    .bb-da-wb-ov.open { display: flex; }
    .bb-da-wb {
      background: var(--surface, #fff); border-radius: 22px;
      padding: 36px 40px; max-width: 520px; width: calc(100% - 40px);
      box-shadow: 0 28px 80px rgba(0,0,0,0.32); text-align: center;
      animation: bb-sconfirm-in 0.18s ease;
    }
    .bb-da-wb-bird { font-size: 3rem; margin-bottom: 12px; }
    .bb-da-wb h2 { margin: 0 0 10px; font-size: 1.35rem; color: var(--text); }
    .bb-da-wb-sub { color: var(--muted); font-size: 0.9rem; line-height: 1.6; margin: 0 0 24px; }
    .bb-da-wb-actions { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }
    /* ── District Admin Setup Checklist ─────────────────────────────────────── */
    .bb-da-cl {
      background: var(--card); border: 1px solid var(--border);
      border-left: 4px solid #10b981; border-radius: var(--radius);
      padding: 14px 16px; margin-bottom: 16px;
    }
    .bb-da-cl-header {
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 10px;
    }
    .bb-da-cl-title { font-size: 0.78rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.04em; color: #10b981; }
    .bb-da-cl-dismiss { background: none; border: none; cursor: pointer;
      color: var(--muted); font-size: 0.9rem; padding: 2px 6px; border-radius: 4px; }
    .bb-da-cl-dismiss:hover { background: var(--accent-soft); color: var(--accent); }
    .bb-da-cl-items { display: flex; flex-direction: column; gap: 8px; }
    .bb-da-cl-item {
      display: flex; align-items: center; gap: 10px;
      padding: 8px 10px; border-radius: calc(var(--radius) - 2px);
      background: var(--bg); border: 1px solid var(--border);
    }
    .bb-da-cl-item.done { opacity: 0.5; }
    .bb-da-cl-check {
      width: 20px; height: 20px; border-radius: 50%; flex-shrink: 0;
      display: grid; place-items: center; font-size: 0.8rem;
      border: 2px solid var(--border); color: transparent;
    }
    .bb-da-cl-item.done .bb-da-cl-check {
      background: #10b981; border-color: #10b981; color: #fff;
    }
    .bb-da-cl-item-label { flex: 1; font-size: 0.86rem; color: var(--text); }
    .bb-da-cl-item.done .bb-da-cl-item-label { text-decoration: line-through; color: var(--muted); }
    .bb-da-cl-progress { font-size: 0.75rem; color: var(--muted); margin-top: 10px; margin-bottom: 0; }
    html[data-theme="dark"] .bb-da-cl { border-color: rgba(255,255,255,0.08); border-left-color: #10b981; }
    html[data-theme="dark"] .bb-da-cl-item { background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.08); }
    """


def _render_flash(message: Optional[str], kind: str = "success") -> str:
    if not message:
        return ""
    return f'<div class="flash {escape(kind)}">{escape(message)}</div>'


def _render_billing_banner(banner: dict) -> str:
    """Render the license/billing status banner for the tenant admin console."""
    if not banner.get("show"):
        return ""
    level = str(banner.get("level", "info"))
    message = str(banner.get("message", ""))
    css_class = str(banner.get("css_class", "billing-banner-info"))
    _colors = {
        "ok":     ("background:#d1fae5;border-color:#10b981;color:#065f46;", "✓"),
        "info":   ("background:#eff6ff;border-color:#3b82f6;color:#1e40af;", "ℹ"),
        "warn":   ("background:#fffbeb;border-color:#f59e0b;color:#92400e;", "⚠"),
        "danger": ("background:#fef2f2;border-color:#ef4444;color:#991b1b;", "⚠"),
    }
    style_str, icon = _colors.get(level, _colors["info"])
    return (
        f'<div class="{escape(css_class)}" style="'
        f'{style_str}'
        f'border-left:4px solid;padding:8px 16px;margin-bottom:12px;'
        f'font-size:0.85rem;border-radius:4px;display:flex;align-items:center;gap:8px;">'
        f'<span>{icon}</span><span>{escape(message)}</span>'
        f'</div>'
    )


def _render_report_rows(reports: Sequence[ReportRecord]) -> str:
    if not reports:
        return '<tr><td colspan="4" class="empty-state">No user reports yet.</td></tr>'
    rows = []
    for report in reports:
        note_text = report.note or (f"User #{report.user_id}" if report.user_id is not None else "No note")
        rows.append(
            f"<tr><td>{report.id}</td><td>{escape(report.created_at)}</td><td>{escape(report.category.replace('_', ' '))}</td><td>{escape(note_text)}</td></tr>"
        )
    return "".join(rows)


def _render_broadcast_rows(broadcasts: Sequence[BroadcastUpdateRecord]) -> str:
    if not broadcasts:
        return '<tr><td colspan="3" class="empty-state">No admin updates posted yet.</td></tr>'
    rows = []
    for item in broadcasts:
        actor = item.admin_label or (str(item.admin_user_id) if item.admin_user_id is not None else "admin")
        rows.append(
            f"<tr><td>{escape(item.created_at)}</td><td>{escape(actor)}</td><td>{escape(item.message)}</td></tr>"
        )
    return "".join(rows)


def _render_admin_message_rows(messages: Sequence[AdminMessageRecord], school_path_prefix: str) -> str:
    if not messages:
        return '<tr><td colspan="7" class="empty-state">No user messages yet.</td></tr>'
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
        return '<tr><td colspan="7" class="empty-state">No matching quiet period requests.</td></tr>'
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
                <button class="button button-secondary" type="submit">Hide</button>
              </form>
            </div>
            """
        elif include_actions and item.status == "scheduled":
            action_html = f"""
            <div class="button-row">
              <form method="post" action="{prefix}/admin/quiet-periods/{item.id}/clear" onsubmit="return confirm('Cancel this scheduled quiet period?');">
                <button class="button button-danger-outline" type="submit">Cancel</button>
              </form>
              <form method="post" action="{prefix}/admin/quiet-periods/{item.id}/hide">
                <button class="button button-secondary" type="submit">Hide</button>
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
                <button class="button button-secondary" type="submit">Hide</button>
              </form>
            </div>
            """
        elif not include_actions:
            action_html = '<span class="mini-copy">History</span>'
        tenant_note = f'<div class="mini-copy">Tenant: {escape(tenant_label)}</div>' if tenant_label else ""
        sched_note = f'<div class="mini-copy">Starts: {escape(str(item.scheduled_start_at))}</div>' if getattr(item, "scheduled_start_at", None) else ""
        rows.append(
            f"<tr><td>{escape(user_names.get(item.user_id, f'User #{item.user_id}'))}{tenant_note}</td><td>{escape(item.status)}{sched_note}</td><td>{escape(item.reason or '—')}</td><td>{escape(approver)}</td><td>{escape(item.requested_at)}</td><td>{escape(item.expires_at or '—')}</td><td>{action_html}</td></tr>"
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
        return '<tr><td colspan="7" class="empty-state">No active help requests.</td></tr>'
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
    school_slug: str = "nen",
    school_path_prefix: str = "/nen",
    setup_pin_required: bool = False,
) -> str:
    heading = "Create the first admin account" if setup_mode else "Sign in to continue"
    button = "Create admin account" if setup_mode else "Sign in"
    action = f"{school_path_prefix}/admin/setup" if setup_mode else f"{school_path_prefix}/admin/login"
    helper = (
        (
            "Enter the setup PIN from the platform admin, then create the first dashboard admin account."
            if setup_pin_required
            else "This becomes the operator account. You can add more users from inside the portal."
        )
        if setup_mode
        else "Use your admin credentials to manage users, alarms, devices, and the audit trail."
    )
    _school_ctx_html = (
        '<div class="school-context">'
        '<div class="school-context-inner">'
        '<div class="school-context-label">Signing in to</div>'
        f'<div class="school-context-name">{escape(school_name)}</div>'
        '</div>'
        '<a class="school-context-change" href="/login?switch=true">← Change school</a>'
        '</div>'
    ) if not setup_mode else (
        '<div class="school-context setup">'
        '<div class="school-context-inner">'
        '<div class="school-context-label">First-time setup</div>'
        f'<div class="school-context-name">{escape(school_name)}</div>'
        '</div>'
        '</div>'
    )
    _setup_notice_html = (
        f'<div class="notice-box">'
        f'Setting up <strong>{escape(school_name)}</strong>.'
        f'{" A setup PIN is required." if setup_pin_required else ""}'
        f' After this, add more users from inside the portal.'
        f'</div>'
    ) if setup_mode else ""
    _msg_html = f'<div class="flash-msg success">{escape(message)}</div>' if message else ""
    _err_html = f'<div class="flash-msg error">{escape(error)}</div>' if error else ""
    _pin_field_html = (
        '<div class="field">'
        '<label for="setup_pin">School setup PIN</label>'
        '<input id="setup_pin" name="setup_pin" type="password" autocomplete="one-time-code" placeholder="Enter setup PIN" />'
        '</div>'
    ) if setup_mode and setup_pin_required else ""
    _extra_fields_html = (
        '<div class="field">'
        '<label for="name">Full name</label>'
        '<input id="name" name="name" autocomplete="name" placeholder="Your full name" />'
        '</div>'
    ) if setup_mode else ""
    _slug_js = escape(school_slug)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Sign in &mdash; {escape(school_name)}</title>
  {_favicon_tags()}
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --blue:        #1b5fe4;
      --blue-dark:   #1048c0;
      --blue-soft:   #eff6ff;
      --text:        #10203f;
      --muted:       #5d7398;
      --border:      rgba(18,52,120,.12);
      --input-radius: 12px;
      --btn-radius:  12px;
      --card-radius: 20px;
      --shadow-card: 0 32px 80px rgba(0,0,0,.35);
      --shadow-btn:  0 4px 14px rgba(27,95,228,.3);
    }}
    html {{ height: 100%; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
      color: var(--text);
      background: linear-gradient(150deg, #0f172a 0%, #1b3a7a 55%, #1b5fe4 100%);
      min-height: 100vh;
      display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      padding: 24px;
    }}

    /* ── Card ──────────────────────────────────────────────────────── */
    .portal-card {{
      background: #fff;
      border-radius: var(--card-radius);
      padding: 40px 44px;
      max-width: 460px; width: 100%;
      box-shadow: var(--shadow-card);
      animation: bbFadeUp .35s cubic-bezier(.22,.61,.36,1) both;
    }}
    @keyframes bbFadeUp {{
      from {{ opacity: 0; transform: translateY(16px); }}
      to   {{ opacity: 1; transform: translateY(0); }}
    }}

    /* ── Logo ──────────────────────────────────────────────────────── */
    .portal-logo {{
      display: flex; align-items: center; gap: 10px;
      margin-bottom: 24px;
    }}
    .portal-logo img {{
      width: 36px; height: 36px; object-fit: contain; border-radius: 8px;
      animation: bbLogoEntry .55s cubic-bezier(.34,1.56,.64,1) both;
      animation-delay: .05s;
    }}
    @keyframes bbLogoEntry {{
      from {{ opacity: 0; transform: scale(.72) rotate(-10deg); }}
      to   {{ opacity: 1; transform: scale(1)  rotate(0deg); }}
    }}
    .portal-logo span {{
      font-weight: 800; font-size: 1.1rem; color: var(--text);
      animation: bbFadeUp .35s ease both;
      animation-delay: .12s;
    }}

    /* ── School context ────────────────────────────────────────────── */
    .school-context {{
      display: flex; align-items: center; justify-content: space-between;
      gap: 12px;
      background: var(--blue-soft); border: 1px solid rgba(27,95,228,.18);
      border-radius: var(--input-radius); padding: 12px 16px;
      margin-bottom: 22px;
    }}
    .school-context.setup {{
      background: rgba(27,95,228,.06); border-color: rgba(27,95,228,.15);
    }}
    .school-context-inner {{ display: flex; flex-direction: column; gap: 2px; min-width: 0; }}
    .school-context-label {{
      font-size: 0.68rem; font-weight: 700; color: var(--blue);
      text-transform: uppercase; letter-spacing: .07em;
    }}
    .school-context-name {{
      font-size: 0.95rem; font-weight: 700; color: var(--text);
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    .school-context-change {{
      font-size: 0.78rem; color: var(--muted); font-weight: 600;
      text-decoration: none; white-space: nowrap; flex-shrink: 0;
    }}
    .school-context-change:hover {{ color: var(--blue); text-decoration: underline; }}

    /* ── Heading ───────────────────────────────────────────────────── */
    .portal-heading {{
      font-size: 1.28rem; font-weight: 800; color: var(--text); margin-bottom: 5px;
    }}
    .portal-sub {{
      font-size: 0.87rem; color: var(--muted); margin-bottom: 22px; line-height: 1.5;
    }}

    /* ── Notice / Flash ────────────────────────────────────────────── */
    .notice-box {{
      background: rgba(27,95,228,.07); border: 1px solid rgba(27,95,228,.18);
      border-radius: 10px; padding: 10px 14px;
      font-size: 0.84rem; color: #1e3a6e; line-height: 1.5;
      margin-bottom: 16px;
    }}
    .flash-msg {{
      padding: 10px 14px; border-radius: 10px;
      font-size: 0.84rem; line-height: 1.5; margin-bottom: 16px;
    }}
    .flash-msg.error {{
      background: rgba(220,38,38,.07); border: 1px solid rgba(220,38,38,.18);
      color: #991b1b;
    }}
    .flash-msg.success {{
      background: rgba(22,163,74,.07); border: 1px solid rgba(22,163,74,.18);
      color: #166534;
    }}

    /* ── Fields ────────────────────────────────────────────────────── */
    .field {{ display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }}
    .field label {{ font-size: 0.82rem; font-weight: 600; color: var(--text); }}
    .field input {{
      width: 100%; padding: 12px 14px;
      border: 1.5px solid var(--border);
      border-radius: var(--input-radius);
      font-size: 0.95rem; color: var(--text);
      background: #fff; outline: none;
      transition: border-color .15s, box-shadow .15s;
      font-family: inherit;
    }}
    .field input::placeholder {{ color: var(--muted); opacity: 1; }}
    .field input:focus {{
      border-color: var(--blue);
      box-shadow: 0 0 0 3px rgba(27,95,228,.12);
    }}
    .field-label-row {{
      display: flex; align-items: center; justify-content: space-between;
    }}
    .field-label-row label {{ margin: 0; }}

    /* ── Password wrapper ──────────────────────────────────────────── */
    .pwd-wrap {{ position: relative; }}
    .pwd-wrap input {{ padding-right: 44px; }}
    .pwd-toggle {{
      position: absolute; right: 12px; top: 50%;
      transform: translateY(-50%);
      background: none; border: none; cursor: pointer; padding: 4px;
      color: var(--muted); font-size: 1rem; line-height: 1;
      transition: color .15s;
    }}
    .pwd-toggle:hover {{ color: var(--blue); }}

    /* ── Forgot password ───────────────────────────────────────────── */
    .forgot-link {{
      font-size: 0.78rem; color: var(--muted); font-weight: 600;
      background: none; border: none; cursor: pointer; padding: 0;
      text-decoration: none;
    }}
    .forgot-link:hover {{ color: var(--blue); text-decoration: underline; }}
    .forgot-panel {{
      overflow: hidden;
      max-height: 0;
      opacity: 0;
      transition: max-height .3s cubic-bezier(.22,.61,.36,1), opacity .25s ease, margin .3s ease;
      margin-bottom: 0;
    }}
    .forgot-panel.open {{
      max-height: 220px;
      opacity: 1;
      margin-bottom: 14px;
    }}
    .forgot-inner {{
      background: rgba(27,95,228,.06); border: 1px solid rgba(27,95,228,.16);
      border-radius: 10px; padding: 14px 16px;
      font-size: 0.84rem; color: #1e3a6e; line-height: 1.55;
    }}
    .forgot-inner p {{ margin-bottom: 8px; }}
    .forgot-inner p:last-child {{ margin-bottom: 0; }}
    .forgot-back {{
      background: none; border: none; cursor: pointer; padding: 0;
      color: var(--blue); font-size: 0.8rem; font-weight: 600;
      text-decoration: underline;
    }}

    /* ── Submit ────────────────────────────────────────────────────── */
    .btn-signin {{
      display: flex; align-items: center; justify-content: center; gap: 8px;
      width: 100%; padding: 13px 20px; margin-top: 6px;
      background: var(--blue); color: #fff;
      font-size: 0.97rem; font-weight: 700;
      border-radius: var(--btn-radius);
      border: none; cursor: pointer; font-family: inherit;
      transition: background .15s, transform .1s, box-shadow .15s;
      box-shadow: var(--shadow-btn);
    }}
    .btn-signin:hover {{
      background: var(--blue-dark);
      transform: translateY(-1px);
      box-shadow: 0 6px 20px rgba(27,95,228,.42);
    }}
    .btn-signin:active {{ transform: translateY(0); box-shadow: 0 2px 8px rgba(27,95,228,.22); }}
    .btn-signin:focus-visible {{ outline: 3px solid rgba(27,95,228,.4); outline-offset: 2px; }}
    .btn-spinner {{
      width: 16px; height: 16px; border-radius: 50%;
      border: 2px solid rgba(255,255,255,.35);
      border-top-color: #fff;
      animation: bbSpin .6s linear infinite;
      display: none;
    }}
    @keyframes bbSpin {{ to {{ transform: rotate(360deg); }} }}

    /* ── Footer ────────────────────────────────────────────────────── */
    .portal-footer {{
      text-align: center; margin-top: 20px;
      font-size: 0.8rem; color: rgba(255,255,255,.5);
    }}
    .portal-footer a {{ color: rgba(255,255,255,.7); text-decoration: none; }}
    .portal-footer a:hover {{ color: #fff; text-decoration: underline; }}
    .portal-disclaimer {{
      margin-top: 10px; font-size: 0.71rem; color: rgba(255,255,255,.32);
      line-height: 1.5; max-width: 380px; margin-left: auto; margin-right: auto;
    }}

    /* ── Responsive ────────────────────────────────────────────────── */
    @media (max-width: 520px) {{
      .portal-card {{ padding: 28px 22px; border-radius: 16px; }}
    }}

    /* ── Dark mode ─────────────────────────────────────────────────── */
    @media (prefers-color-scheme: dark) {{
      .portal-card {{ background: #1e293b; }}
      .portal-logo span, .portal-heading {{ color: #e2e8f0; }}
      .portal-sub {{ color: #94a3b8; }}
      .school-context {{ background: rgba(27,95,228,.15); border-color: rgba(27,95,228,.28); }}
      .school-context-name {{ color: #e2e8f0; }}
      .school-context-change {{ color: #94a3b8; }}
      .field label {{ color: #cbd5e1; }}
      .field input {{
        background: #0f172a; color: #e2e8f0;
        border-color: rgba(255,255,255,.1);
      }}
      .field input:focus {{
        border-color: #60a5fa;
        box-shadow: 0 0 0 3px rgba(96,165,250,.12);
      }}
      .forgot-inner {{ background: rgba(27,95,228,.12); border-color: rgba(96,165,250,.2); color: #93c5fd; }}
    }}
  </style>
</head>
<body>

<div class="portal-card" role="main">
  <div class="portal-logo">
    <img src="{LOGO_PATH}" alt="BlueBird Alerts logo" />
    <span>BlueBird Alerts</span>
  </div>

  {_school_ctx_html}

  <h1 class="portal-heading">{escape(heading)}</h1>
  <p class="portal-sub">{escape(helper)}</p>

  {_setup_notice_html}
  {"" if not _err_html else f'<div role="alert">{_err_html}</div>'}
  {_msg_html}

  <form method="post" action="{action}" id="login-form" novalidate>
    {_extra_fields_html}
    {_pin_field_html}
    <div class="field">
      <label for="login_name">Username</label>
      <input id="login_name" name="login_name" autocomplete="username"
             placeholder="Enter your username" spellcheck="false"
             autocapitalize="off" autocorrect="off" />
    </div>
    <div class="field">
      <div class="field-label-row">
        <label for="password">Password</label>
        {"" if setup_mode else '<button type="button" class="forgot-link" id="forgot-btn" aria-expanded="false" aria-controls="forgot-panel">Forgot password?</button>'}
      </div>
      <div class="pwd-wrap">
        <input id="password" name="password" type="password"
               autocomplete="current-password" placeholder="Enter your password" />
        <button type="button" class="pwd-toggle" id="pwd-toggle"
                aria-label="Show password" tabindex="-1">&#128065;</button>
      </div>
    </div>

    {"" if setup_mode else '''
    <div class="forgot-panel" id="forgot-panel" aria-hidden="true">
      <div class="forgot-inner">
        <p><strong>Password resets are managed by your school admin.</strong></p>
        <p>Contact your building administrator or IT department to have your password reset. They can update your credentials from the admin console.</p>
        <button type="button" class="forgot-back" onclick="bbForgot(false)">&#8592; Back to sign in</button>
      </div>
    </div>
    '''}

    <button class="btn-signin" type="submit" id="signin-btn">
      <span id="signin-label">{escape(button)}</span>
      <span class="btn-spinner" id="signin-spinner" aria-hidden="true"></span>
    </button>
  </form>
</div>

<div class="portal-footer">
  <a href="/">&larr; Back to home</a>
  <p class="portal-disclaimer">
    This system does not replace emergency services.
    Always call 911 in a real emergency.
  </p>
</div>

<script>
(function() {{
  var SLUG = '{_slug_js}';
  var UKEY = 'bb_username_' + SLUG;

  /* ── Remember username ───────────────────────────────────────── */
  var _nameInp = document.getElementById('login_name');
  var _pwdInp  = document.getElementById('password');
  var _form    = document.getElementById('login-form');
  var _btn     = document.getElementById('signin-btn');
  var _spinner = document.getElementById('signin-spinner');
  var _label   = document.getElementById('signin-label');

  if (_nameInp) {{
    var _saved = '';
    try {{ _saved = localStorage.getItem(UKEY) || ''; }} catch(e) {{}}
    if (_saved && !_nameInp.value) {{
      _nameInp.value = _saved;
    }}
    /* autofocus: jump to password if username already filled */
    if (_saved && _pwdInp) {{
      _pwdInp.focus();
    }} else if (_nameInp) {{
      _nameInp.focus();
    }}
  }}

  if (_form) {{
    _form.addEventListener('submit', function() {{
      /* Save username */
      var uval = _nameInp ? _nameInp.value.trim() : '';
      if (uval) {{ try {{ localStorage.setItem(UKEY, uval); }} catch(e) {{}} }}
      /* Loading state */
      if (_btn) {{ _btn.disabled = true; }}
      if (_spinner) {{ _spinner.style.display = ''; }}
      if (_label)   {{ _label.style.opacity = '.7'; }}
    }});
  }}

  /* ── Enter key: username → password ─────────────────────────── */
  if (_nameInp && _pwdInp) {{
    _nameInp.addEventListener('keydown', function(e) {{
      if (e.key === 'Enter') {{ e.preventDefault(); _pwdInp.focus(); }}
    }});
  }}

  /* ── Password show/hide ──────────────────────────────────────── */
  var _pwdToggle = document.getElementById('pwd-toggle');
  if (_pwdToggle && _pwdInp) {{
    _pwdToggle.addEventListener('click', function() {{
      var show = _pwdInp.type === 'password';
      _pwdInp.type = show ? 'text' : 'password';
      _pwdToggle.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
      _pwdToggle.innerHTML = show ? '&#128683;' : '&#128065;';
    }});
  }}

  /* ── Forgot password panel ───────────────────────────────────── */
  window.bbForgot = function(open) {{
    var panel = document.getElementById('forgot-panel');
    var btn   = document.getElementById('forgot-btn');
    if (!panel) return;
    if (open) {{
      panel.classList.add('open');
      panel.setAttribute('aria-hidden', 'false');
      if (btn) btn.setAttribute('aria-expanded', 'true');
    }} else {{
      panel.classList.remove('open');
      panel.setAttribute('aria-hidden', 'true');
      if (btn) {{ btn.setAttribute('aria-expanded', 'false'); btn.focus(); }}
    }}
  }};
  var _forgotBtn = document.getElementById('forgot-btn');
  if (_forgotBtn) {{
    _forgotBtn.addEventListener('click', function() {{
      var open = this.getAttribute('aria-expanded') === 'true';
      bbForgot(!open);
    }});
  }}
}})();
</script>

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
  <script>(function(){{var t=localStorage.getItem('bb_theme')||(window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');if(t==='dark')document.documentElement.setAttribute('data-theme','dark');}})();</script>
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
  <style>{_base_styles()}</style>
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
  <script>(function(){{var t=localStorage.getItem('bb_theme')||(window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');if(t==='dark')document.documentElement.setAttribute('data-theme','dark');}})();</script>
</body>
</html>"""


def _sandbox_district_options(prod_districts: Sequence[object]) -> str:
    parts = []
    for d in prod_districts:
        did = escape(str(getattr(d, "id", "")))
        name = escape(str(getattr(d, "name", "")))
        slug = escape(str(getattr(d, "slug", "")))
        parts.append(f'<option value="{did}">{name} ({slug})</option>')
    return "".join(parts)


def _sandbox_school_row(s: Mapping[str, object]) -> str:
    slug = escape(str(s.get("slug", "")))
    name = escape(str(s.get("name", "")))
    sim_on = bool(s.get("simulation_mode_enabled"))
    audio_on = bool(s.get("suppress_alarm_audio"))
    live_demo_on = bool(s.get("live_demo_active"))
    sim_class = "success" if sim_on else "neutral"
    sim_label = "SIM ON" if sim_on else "SIM OFF"
    audio_class = "warning" if audio_on else "neutral"
    audio_label = "AUDIO MUTED" if audio_on else "AUDIO ON"
    demo_class = "success" if live_demo_on else "neutral"
    demo_label = "🟢 LIVE DEMO" if live_demo_on else "DEMO OFF"
    confirm_msg = "Reset simulation data for " + str(s.get("slug", "")) + "?"
    _demo_enable_action = f"/super-admin/sandbox/{slug}/live-demo/enable"
    _demo_disable_action = f"/super-admin/sandbox/{slug}/live-demo/disable"
    _demo_btn = (
        f'<form method="post" action="{_demo_disable_action}">'
        '<button class="button button-warning-outline" type="submit">Disable Live Demo</button>'
        '</form>'
        if live_demo_on else
        f'<form method="post" action="{_demo_enable_action}">'
        '<button class="button button-secondary" type="submit">Enable Live Demo</button>'
        '</form>'
    )
    return (
        '<div style="border-top:1px solid #e5e7eb;padding:10px 0;display:flex;align-items:center;gap:12px;flex-wrap:wrap;">'
        f'<code style="flex:1;min-width:120px;">{slug}</code>'
        f'<span style="flex:2;">{name}</span>'
        f'<span class="status-pill {sim_class}">{sim_label}</span>'
        f'<span class="status-pill {audio_class}">{audio_label}</span>'
        f'<span class="status-pill {demo_class}">{demo_label}</span>'
        f'<form method="post" action="/super-admin/test-tenants/{slug}/toggle-simulation">'
        '<button class="button button-secondary" type="submit">Toggle Sim</button>'
        '</form>'
        f'<form method="post" action="/super-admin/test-tenants/{slug}/toggle-audio-suppression">'
        '<button class="button button-secondary" type="submit">Toggle Audio</button>'
        '</form>'
        f'<form method="post" action="/super-admin/test-tenants/{slug}/simulate-alert">'
        '<input type="hidden" name="alert_type" value="lockdown" />'
        '<button class="button button-warning-outline" type="submit">Simulate Alert</button>'
        '</form>'
        + _demo_btn +
        f'<form method="post" action="/super-admin/sandbox/{slug}/seed">'
        '<button class="button button-secondary" type="submit" title="Seed 50+ users, incidents, alerts, and access codes">Seed Demo Data</button>'
        '</form>'
        f'<form method="post" action="/super-admin/test-tenants/{slug}/reset"'
        f' onsubmit="return confirm({repr(confirm_msg)});">'
        '<button class="button button-secondary" type="submit">Reset</button>'
        '</form>'
        '</div>'
    )


def _sandbox_district_cards(sandbox_data: Sequence[Mapping[str, object]]) -> str:
    if not sandbox_data:
        return '<p class="card-copy">No test environments created yet.</p>'
    parts = []
    for td in sandbox_data:
        did = escape(str(td.get("district_id", "")))
        dname = escape(str(td.get("district_name", "")))
        dslug = escape(str(td.get("district_slug", "")))
        schools_html = "".join(
            _sandbox_school_row(s)  # type: ignore[arg-type]
            for s in td.get("schools", [])
        )
        confirm_msg = "Permanently delete test district and all its schools?"
        parts.append(
            '<div class="signal-card" style="margin-bottom:20px;">'
            '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">'
            f'<div><strong>{dname}</strong><code style="margin-left:8px;">{dslug}</code></div>'
            f'<form method="post" action="/super-admin/test-districts/{did}/delete"'
            f' onsubmit="return confirm({repr(confirm_msg)});">'
            '<button class="button button-danger-outline" type="submit">Delete Sandbox</button>'
            '</form>'
            '</div>'
            f'{schools_html}'
            '</div>'
        )
    return "".join(parts)


def _tenant_registry_card(item: Mapping[str, object]) -> str:
    name = escape(str(item.get("name", "")))
    slug_raw = str(item.get("slug", ""))
    slug = escape(slug_raw)
    admin_url = escape(str(item.get("admin_url", "#")))
    admin_url_label = escape(str(item.get("admin_url_label", "")))
    is_active = bool(item.get("is_active", True))
    billing_status = str(item.get("billing_status", "trial") or "trial")
    user_count = int(item.get("user_count", 0) or 0)
    setup_status = escape(str(item.get("setup_status", "")))
    setup_hint = escape(str(item.get("setup_hint", "")))
    status_class = "ok" if is_active else "danger"
    status_label = "Active" if is_active else "Inactive"
    billing_class = "ok" if billing_status in {"active", "trial", "free"} else "danger"
    admins_label = f"{user_count} admin{'s' if user_count != 1 else ''}"
    confirm_archive = escape(f"Archive {str(item.get('name', slug_raw))}? This will deactivate the school and move it to the archive.")
    return (
        f'<div class="tenant-card" data-slug="{slug}">'
        f'<div class="tenant-card-header">'
        f'<div class="tenant-card-name">{name}</div>'
        f'<div class="tenant-card-badges">'
        f'<span class="status-pill {status_class}">{status_label}</span>'
        f'<span class="status-pill {billing_class}">{escape(billing_status)}</span>'
        f'</div></div>'
        f'<div class="tenant-card-meta">'
        f'<code>{slug}</code> &middot; {admins_label}<br>'
        f'<a href="{admin_url}" target="_blank" style="color:var(--accent);font-size:0.8rem;">{admin_url_label}</a><br>'
        f'<span>{setup_status}</span>'
        f'{"<br><span>" + setup_hint + "</span>" if setup_hint else ""}'
        f'</div>'
        f'<div class="tenant-card-actions">'
        f'<form method="post" action="/super-admin/schools/{slug}/enter" style="margin:0;">'
        f'<button class="button button-primary" style="font-size:0.8rem;padding:5px 12px;">Open Admin</button>'
        f'</form>'
        f'<a class="button button-secondary" href="/super-admin?section=billing#billing" style="font-size:0.8rem;padding:5px 12px;">Billing</a>'
        f'<form method="post" action="/super-admin/schools/{slug}/archive" style="margin:0;"'
        f' onsubmit="return confirm(\'{confirm_archive}\');">'
        f'<button class="button button-danger-outline" style="font-size:0.8rem;padding:5px 12px;">Archive</button>'
        f'</form>'
        f'</div>'
        f'</div>'
    )


def _tenant_registry_archived_card(item: Mapping[str, object]) -> str:
    name = escape(str(item.get("name", "")))
    slug_raw = str(item.get("slug", ""))
    slug = escape(slug_raw)
    archived_at = str(item.get("archived_at", "") or "")[:10]
    confirm_delete = escape(f"Permanently delete {str(item.get('name', slug_raw))} and purge all registry data? This cannot be undone.")
    return (
        f'<div class="tenant-card tenant-card--archived" data-slug="{slug}">'
        f'<div class="tenant-card-header">'
        f'<div class="tenant-card-name" style="color:var(--muted);">{name}</div>'
        f'<span class="status-pill danger">Archived</span>'
        f'</div>'
        f'<div class="tenant-card-meta">'
        f'<code>{slug}</code>'
        f'{"<br><span>Archived " + archived_at + "</span>" if archived_at else ""}'
        f'</div>'
        f'<div class="tenant-card-actions">'
        f'<form method="post" action="/super-admin/schools/{slug}/restore" style="margin:0;">'
        f'<button class="button button-secondary" style="font-size:0.8rem;padding:5px 12px;">Restore</button>'
        f'</form>'
        f'<form method="post" action="/super-admin/schools/{slug}/delete" style="margin:0;"'
        f' onsubmit="return confirm(\'{confirm_delete}\');">'
        f'<button class="button button-danger-outline" style="font-size:0.8rem;padding:5px 12px;">Delete</button>'
        f'</form>'
        f'</div>'
        f'</div>'
    )


def _billing_status_badge(status: str) -> str:
    _cls = {
        "active": "ok", "manual_override": "ok",
        "trial": "warn", "past_due": "warn",
        "expired": "danger", "suspended": "danger", "cancelled": "danger",
    }.get(status.lower(), "")
    return f'<span class="status-pill {_cls}">{escape(status)}</span>'


def _render_billing_cards(billing_rows: Sequence[Mapping[str, object]]) -> str:
    if not billing_rows:
        return '<p class="mini-copy" style="color:var(--muted);padding:24px 0;">No tenant billing records yet.</p>'

    plan_opts = "".join(f'<option value="{p}">{p.title()}</option>' for p in ("trial", "basic", "pro", "enterprise"))
    status_opts = "".join(
        f'<option value="{s}">{s.replace("_", " ").title()}</option>'
        for s in ("trial", "active", "past_due", "expired", "suspended", "cancelled", "manual_override")
    )
    method_opts = "".join(f'<option value="{m}">{m}</option>' for m in ("check", "cash", "card", "ACH", "manual", "stripe_future"))

    cards = []
    for item in billing_rows:
        name = escape(str(item.get("name", "")))
        slug = escape(str(item.get("slug", "")))
        slug_raw = str(item.get("slug", ""))
        eff = str(item.get("effective_status", item.get("billing_status", "trial")))
        plan = escape(str(item.get("plan_type", item.get("plan_id", "trial"))))
        days = item.get("days_remaining")
        renewal = escape(str(item.get("renewal_date", "") or ""))
        override_on = bool(item.get("override_enabled"))
        override_reason = escape(str(item.get("override_reason", "") or ""))
        license_suffix = escape(str(item.get("license_key_suffix", "") or ""))
        customer_email = escape(str(item.get("customer_email", "") or ""))
        internal_notes = escape(str(item.get("internal_notes", "") or ""))

        days_pill = ""
        if days is not None:
            days_color = "#dc2626" if days < 0 else ("#d97706" if days <= 7 else "#059669")
            days_label = f"{days}d remaining" if days >= 0 else f"Expired {abs(days)}d ago"
            days_pill = f'<span style="font-size:0.72rem;color:{days_color};font-weight:600;">{escape(days_label)}</span>'

        override_badge = (
            f'<span class="status-pill ok" style="font-size:0.7rem;">Override Active</span>'
        ) if override_on else ""

        # Action URLs
        gen_lic = escape(str(item.get("generate_license_action", f"/super-admin/schools/{slug_raw}/billing/generate-license")))
        set_status = escape(str(item.get("set_status_action", f"/super-admin/schools/{slug_raw}/billing/set-status")))
        set_plan = escape(str(item.get("set_plan_action", f"/super-admin/schools/{slug_raw}/billing/set-plan")))
        upd_det = escape(str(item.get("update_details_action", f"/super-admin/schools/{slug_raw}/billing/update-details")))
        tog_ov = escape(str(item.get("toggle_override_action", f"/super-admin/schools/{slug_raw}/billing/toggle-override")))
        add_pay = escape(str(item.get("add_payment_action", f"/super-admin/schools/{slug_raw}/billing/add-payment")))
        cre_inv = escape(str(item.get("create_invoice_action", f"/super-admin/schools/{slug_raw}/billing/create-invoice")))

        today = ""
        try:
            from datetime import date as _date
            today = str(_date.today())
        except Exception:
            pass

        card = (
            f'<div class="tenant-card" data-slug="{slug}" style="margin-bottom:16px;">'
            # Header
            f'<div class="tenant-card-header" style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px;">'
            f'<div>'
            f'<div class="tenant-card-name">{name}</div>'
            f'<div class="mini-copy"><code>{slug}</code>{(" · " + escape(customer_email)) if customer_email else ""}</div>'
            f'</div>'
            f'<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">'
            f'{_billing_status_badge(eff)}'
            f'<span class="status-pill">{plan}</span>'
            f'{override_badge}'
            f'{days_pill}'
            f'</div>'
            f'</div>'
            # Details row
            f'<div style="padding:8px 12px;font-size:0.8rem;color:var(--muted);display:flex;gap:16px;flex-wrap:wrap;">'
            f'{"<span>Renewal: " + renewal + "</span>" if renewal else ""}'
            f'{"<span>License: ···" + license_suffix + "</span>" if license_suffix else "<span>No license key</span>"}'
            f'{"<span>Notes: " + internal_notes + "</span>" if internal_notes else ""}'
            f'</div>'
            # Actions (collapsible)
            f'<details style="padding:0 12px 12px;">'
            f'<summary style="cursor:pointer;font-size:0.8rem;color:var(--accent);user-select:none;">Actions</summary>'
            f'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin-top:12px;">'
            # Generate license
            f'<div class="card" style="padding:12px;">'
            f'<p style="font-size:0.75rem;font-weight:600;margin-bottom:8px;">Generate / Renew License</p>'
            f'<form method="post" action="{gen_lic}" class="stack" style="gap:6px;">'
            f'<select name="plan_type" style="width:100%;">{plan_opts}</select>'
            f'<input name="starts_at" type="date" value="{today}" />'
            f'<input name="current_period_end" type="date" placeholder="Period end date" />'
            f'<input name="customer_name" placeholder="Customer name" />'
            f'<input name="customer_email" type="email" placeholder="Customer email" />'
            f'<input name="internal_notes" placeholder="Internal notes" />'
            f'<button class="button button-primary" type="submit">Generate License</button>'
            f'</form></div>'
            # Set status
            f'<div class="card" style="padding:12px;">'
            f'<p style="font-size:0.75rem;font-weight:600;margin-bottom:8px;">Set Billing Status</p>'
            f'<form method="post" action="{set_status}" class="stack" style="gap:6px;">'
            f'<select name="new_status" style="width:100%;">{status_opts}</select>'
            f'<button class="button button-secondary" type="submit">Set Status</button>'
            f'</form>'
            f'<p style="font-size:0.75rem;font-weight:600;margin:12px 0 8px;">Set Plan</p>'
            f'<form method="post" action="{set_plan}" class="stack" style="gap:6px;">'
            f'<select name="plan_type" style="width:100%;">{plan_opts}</select>'
            f'<button class="button button-secondary" type="submit">Set Plan</button>'
            f'</form></div>'
            # Toggle override
            f'<div class="card" style="padding:12px;">'
            f'<p style="font-size:0.75rem;font-weight:600;margin-bottom:8px;">Manual Override</p>'
            f'<form method="post" action="{tog_ov}" class="stack" style="gap:6px;">'
            f'<input name="override_reason" placeholder="Override reason" value="{override_reason}" />'
            f'<button class="button {"button-danger-outline" if override_on else "button-primary"}" type="submit">'
            f'{"Disable Override" if override_on else "Enable Override"}</button>'
            f'</form></div>'
            # Update details
            f'<div class="card" style="padding:12px;">'
            f'<p style="font-size:0.75rem;font-weight:600;margin-bottom:8px;">Update Period / Details</p>'
            f'<form method="post" action="{upd_det}" class="stack" style="gap:6px;">'
            f'<input name="current_period_start" type="date" placeholder="Period start" />'
            f'<input name="current_period_end" type="date" placeholder="Period end / renewal" />'
            f'<input name="customer_name" placeholder="Customer name" />'
            f'<input name="customer_email" type="email" placeholder="Customer email" />'
            f'<input name="internal_notes" placeholder="Internal notes" />'
            f'<button class="button button-secondary" type="submit">Save Details</button>'
            f'</form></div>'
            # Record payment
            f'<div class="card" style="padding:12px;">'
            f'<p style="font-size:0.75rem;font-weight:600;margin-bottom:8px;">Record Payment</p>'
            f'<form method="post" action="{add_pay}" class="stack" style="gap:6px;">'
            f'<input name="amount" type="number" step="0.01" min="0" placeholder="Amount" />'
            f'<input name="currency" value="USD" style="max-width:80px;" />'
            f'<input name="payment_date" type="date" value="{today}" />'
            f'<select name="payment_method" style="width:100%;">{method_opts}</select>'
            f'<input name="reference_number" placeholder="Reference / check #" />'
            f'<input name="notes" placeholder="Notes" />'
            f'<input name="extend_days" type="number" min="0" placeholder="Extend period by N days (0=no)" value="0" />'
            f'<button class="button button-primary" type="submit">Record Payment</button>'
            f'</form></div>'
            # Create invoice
            f'<div class="card" style="padding:12px;">'
            f'<p style="font-size:0.75rem;font-weight:600;margin-bottom:8px;">Create Invoice</p>'
            f'<form method="post" action="{cre_inv}" class="stack" style="gap:6px;">'
            f'<input name="amount_due" type="number" step="0.01" min="0" placeholder="Amount due" />'
            f'<input name="due_date" type="date" />'
            f'<input name="notes" placeholder="Notes" />'
            f'<button class="button button-secondary" type="submit">Create Invoice</button>'
            f'</form></div>'
            # Legacy: start trial / grant free
            f'<div class="card" style="padding:12px;">'
            f'<p style="font-size:0.75rem;font-weight:600;margin-bottom:8px;">Legacy Controls</p>'
            f'<form method="post" action="{escape(str(item.get("start_trial_action", "#")))}" class="stack" style="gap:6px;margin-bottom:8px;">'
            f'<div style="display:flex;gap:6px;">'
            f'<input name="duration_days" type="number" min="1" max="365" value="14" style="max-width:80px;" />'
            f'<button class="button button-secondary" type="submit">Start Trial</button>'
            f'</div></form>'
            f'<form method="post" action="{escape(str(item.get("grant_free_action", "#")))}" class="stack" style="gap:6px;margin-bottom:8px;">'
            f'<input name="free_reason" placeholder="Free access reason" />'
            f'<button class="button button-secondary" type="submit">Grant Free Access</button>'
            f'</form>'
            f'<form method="post" action="{escape(str(item.get("remove_free_action", "#")))}" onsubmit="return confirm(\'Remove free access for {name}?\');">'
            f'<button class="button button-danger-outline" type="submit">Remove Free Access</button>'
            f'</form></div>'
            f'</div>'  # grid
            f'</details>'
            f'</div>'  # card
        )
        cards.append(card)
    return '<div class="tenant-grid" style="display:block;">' + "".join(cards) + "</div>"


def _render_district_billing_audit_trail(audit_rows: Sequence[Mapping[str, object]]) -> str:
    if not audit_rows:
        return ""
    event_labels = {
        "license_created": "License Generated",
        "license_archived": "License Archived",
        "license_restored": "License Restored",
        "license_deleted": "License Deleted",
        "status_changed": "Status Changed",
        "plan_changed": "Plan Changed",
        "override_enabled": "Override Enabled",
        "override_disabled": "Override Disabled",
        "trial_started": "Trial Started",
        "details_updated": "Details Updated",
    }
    rows_html = ""
    for row in audit_rows:
        evt = str(row.get("event_type", ""))
        label = event_labels.get(evt, evt.replace("_", " ").title())
        actor = escape(str(row.get("actor", "")))
        detail = escape(str(row.get("detail", "") or ""))
        created = escape(str(row.get("created_at", "")))
        did = int(row.get("district_id", 0))
        icon = {"license_archived": "📦", "license_deleted": "🗑", "license_restored": "♻", "license_created": "🔑"}.get(evt, "📋")
        rows_html += (
            f'<tr>'
            f'<td style="white-space:nowrap;font-size:0.75rem;color:var(--muted);">{created}</td>'
            f'<td style="font-size:0.78rem;">{icon} {escape(label)}</td>'
            f'<td style="font-size:0.75rem;color:var(--muted);">{actor}</td>'
            f'<td style="font-size:0.75rem;color:var(--muted);">{detail}</td>'
            f'<td style="font-size:0.75rem;color:var(--muted);">District #{did}</td>'
            f'</tr>'
        )
    return (
        '<div style="margin-top:32px;">'
        '<p class="eyebrow" style="margin-bottom:12px;">License Audit Trail</p>'
        '<div style="overflow-x:auto;">'
        '<table class="data-table" style="font-size:0.82rem;">'
        '<thead><tr><th>Time (UTC)</th><th>Event</th><th>Actor</th><th>Detail</th><th>District</th></tr></thead>'
        '<tbody>' + rows_html + '</tbody>'
        '</table>'
        '</div></div>'
    )


def _render_district_billing_card(item: Mapping[str, object], plan_opts: str, status_opts: str, *, archived: bool = False) -> str:
    name = escape(str(item.get("name", "")))
    slug = escape(str(item.get("slug", "")))
    school_count = int(item.get("school_count", 0))
    eff = str(item.get("effective_status", item.get("billing_status", "trial")))
    plan = escape(str(item.get("plan_type", "trial")))
    days = item.get("days_remaining")
    renewal = escape(str(item.get("renewal_date", "") or ""))
    override_on = bool(item.get("override_enabled"))
    override_reason = escape(str(item.get("override_reason", "") or ""))
    license_suffix = escape(str(item.get("license_key_suffix", "") or ""))
    customer_email = escape(str(item.get("customer_email", "") or ""))
    internal_notes = escape(str(item.get("internal_notes", "") or ""))
    analytics_url = escape(str(item.get("analytics_url", "#")))
    archive_action = escape(str(item.get("archive_action", "#")))
    restore_action = escape(str(item.get("restore_action", "#")))
    delete_action = escape(str(item.get("delete_action", "#")))
    archived_at = escape(str(item.get("archived_at", "") or ""))
    archived_by = escape(str(item.get("archived_by", "") or ""))

    if archived:
        # Archived card — compact, shows restore + delete only
        can_delete = eff in {"expired", "cancelled", "suspended"} or archived
        delete_btn = (
            f'<span style="display:inline-flex;align-items:center;gap:4px;">'
            + _help_tip('Permanently removes this license record. Cannot be undone. Only allowed after archiving.')
            + f'<form method="post" action="{delete_action}" style="display:inline;margin:0;" '
            f'onsubmit="bbConfirmSubmit(this,{{title:\'Delete district license?\','
            f'body:\'Permanently removes the license record for <strong>{name}</strong>.\','
            f'consequence:\'This cannot be undone. The district will need a new license to regain access.\','
            f'requireType:\'DELETE\',confirmLabel:\'Delete permanently\',danger:true}});return false;">'
            f'<button class="button button-danger-outline" type="submit" style="font-size:0.73rem;padding:4px 10px;">Delete</button>'
            f'</form>'
            f'</span>'
        )
        restore_btn = (
            f'<span style="display:inline-flex;align-items:center;gap:4px;">'
            + _help_tip('Moves this license back to active status. Enforcement resumes immediately.')
            + f'<form method="post" action="{restore_action}" style="display:inline;margin:0;">'
            f'<button class="button button-primary" type="submit" style="font-size:0.73rem;padding:4px 10px;">Restore</button>'
            f'</form>'
            f'</span>'
        )
        return (
            f'<div style="background:rgba(100,116,139,0.06);border:1px solid var(--border);border-radius:12px;'
            f'padding:14px 16px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:10px;">'
            f'<div>'
            f'<span style="font-size:0.95rem;font-weight:600;color:var(--text);">{name}</span>'
            f'<span style="font-size:0.72rem;color:var(--muted);margin-left:8px;font-family:monospace;">{slug}</span>'
            f'<span class="status-pill" style="font-size:0.68rem;margin-left:8px;background:rgba(100,116,139,0.15);color:var(--muted);">Archived</span>'
            f'<p style="font-size:0.75rem;color:var(--muted);margin-top:4px;">'
            f'Archived {archived_at}'
            f'{(" by " + archived_by) if archived_by else ""}'
            f' · {plan} plan · {escape(eff)}'
            f'</p>'
            f'</div>'
            f'<div style="display:flex;gap:8px;align-items:center;">'
            f'{restore_btn}'
            f'{delete_btn}'
            f'</div>'
            f'</div>'
        )

    # Active card — full details + actions
    days_pill = ""
    if days is not None:
        days_color = "#dc2626" if days < 0 else ("#d97706" if days <= 7 else "#059669")
        days_label = str(days) + "d remaining" if days >= 0 else "Expired " + str(abs(int(days))) + "d ago"
        days_pill = f'<span style="font-size:0.72rem;color:{days_color};font-weight:600;">{escape(days_label)}</span>'

    override_badge_html = (
        '<span class="status-pill ok" style="font-size:0.7rem;">Override</span>'
        if override_on else ""
    )

    gen_lic = escape(str(item.get("generate_license_action", "#")))
    set_status = escape(str(item.get("set_status_action", "#")))
    set_plan = escape(str(item.get("set_plan_action", "#")))
    upd_det = escape(str(item.get("update_details_action", "#")))
    tog_ov = escape(str(item.get("toggle_override_action", "#")))
    start_trial = escape(str(item.get("start_trial_action", "#")))

    try:
        from datetime import date as _date
        today = str(_date.today())
    except Exception:
        today = ""

    override_btn_cls = "button-danger-outline" if override_on else "button-primary"
    override_btn_lbl = "Disable Override" if override_on else "Enable Override"

    return (
        f'<div class="tenant-card" data-slug="{slug}" style="margin-bottom:16px;border-left:4px solid var(--accent);">'
        f'<div class="tenant-card-header" style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px;">'
        f'<div>'
        f'<div class="tenant-card-name">{name} <span style="font-size:0.75rem;color:var(--muted);font-weight:400;">District</span></div>'
        f'<div class="mini-copy"><code>{slug}</code> · {school_count} school{"s" if school_count != 1 else ""}'
        f'{(" · " + escape(customer_email)) if customer_email else ""}</div>'
        f'</div>'
        f'<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">'
        f'{_billing_status_badge(eff)}'
        f'<span class="status-pill">{plan}</span>'
        f'{days_pill}'
        f'{override_badge_html}'
        f'<a href="{analytics_url}" class="button button-secondary" style="font-size:0.72rem;padding:3px 10px;" target="_blank">Analytics</a>'
        f'</div>'
        f'</div>'
        f'<div style="padding:8px 12px;font-size:0.8rem;color:var(--muted);display:flex;gap:16px;flex-wrap:wrap;">'
        f'{"<span>Renewal: " + renewal + "</span>" if renewal else ""}'
        f'{"<span>License: ···" + license_suffix + "</span>" if license_suffix else "<span>No district license</span>"}'
        f'{"<span>Notes: " + internal_notes + "</span>" if internal_notes else ""}'
        f'</div>'
        f'<details style="padding:0 12px 12px;">'
        f'<summary style="cursor:pointer;font-size:0.8rem;color:var(--accent);user-select:none;">District Billing Actions</summary>'
        f'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;margin-top:12px;">'
        f'<div class="card" style="padding:12px;">'
        f'<p style="font-size:0.75rem;font-weight:600;margin-bottom:8px;">Generate / Renew District License</p>'
        f'<form method="post" action="{gen_lic}" class="stack" style="gap:6px;">'
        f'<select name="plan_type" style="width:100%;">{plan_opts}</select>'
        f'<input name="starts_at" type="date" value="{today}" />'
        f'<input name="current_period_end" type="date" placeholder="Period end date" />'
        f'<input name="customer_name" placeholder="Customer name" />'
        f'<input name="customer_email" type="email" placeholder="Customer email" />'
        f'<input name="internal_notes" placeholder="Internal notes" />'
        f'<button class="button button-primary" type="submit">Generate District License</button>'
        f'</form></div>'
        f'<div class="card" style="padding:12px;">'
        f'<p style="font-size:0.75rem;font-weight:600;margin-bottom:8px;">Set Status</p>'
        f'<form method="post" action="{set_status}" class="stack" style="gap:6px;">'
        f'<select name="new_status" style="width:100%;">{status_opts}</select>'
        f'<button class="button button-secondary" type="submit">Set Status</button>'
        f'</form>'
        f'<p style="font-size:0.75rem;font-weight:600;margin:12px 0 8px;">Set Plan</p>'
        f'<form method="post" action="{set_plan}" class="stack" style="gap:6px;">'
        f'<select name="plan_type" style="width:100%;">{plan_opts}</select>'
        f'<button class="button button-secondary" type="submit">Set Plan</button>'
        f'</form></div>'
        f'<div class="card" style="padding:12px;">'
        f'<p style="font-size:0.75rem;font-weight:600;margin-bottom:8px;">Manual Override'
        + _help_tip('Grants full access regardless of license status. Use for nonprofits, pilots, or contract exceptions. Always record a reason.')
        + f'</p>'
        f'<form method="post" action="{tog_ov}" class="stack" style="gap:6px;">'
        f'<input name="override_reason" placeholder="Override reason" value="{override_reason}" />'
        f'<button class="button {override_btn_cls}" type="submit">'
        f'{override_btn_lbl}</button>'
        f'</form></div>'
        f'<div class="card" style="padding:12px;">'
        f'<p style="font-size:0.75rem;font-weight:600;margin-bottom:8px;">Update Period / Details</p>'
        f'<form method="post" action="{upd_det}" class="stack" style="gap:6px;">'
        f'<input name="current_period_start" type="date" placeholder="Period start" />'
        f'<input name="current_period_end" type="date" placeholder="Period end / renewal" />'
        f'<input name="customer_name" placeholder="Customer name" />'
        f'<input name="customer_email" type="email" placeholder="Customer email" />'
        f'<input name="internal_notes" placeholder="Internal notes" />'
        f'<button class="button button-secondary" type="submit">Save Details</button>'
        f'</form></div>'
        f'<div class="card" style="padding:12px;">'
        f'<p style="font-size:0.75rem;font-weight:600;margin-bottom:8px;">Start District Trial</p>'
        f'<form method="post" action="{start_trial}" class="stack" style="gap:6px;">'
        f'<input name="duration_days" type="number" min="1" max="365" value="14" />'
        f'<button class="button button-secondary" type="submit">Start Trial</button>'
        f'</form></div>'
        f'<div class="card" style="padding:12px;border-top:2px solid var(--border);">'
        f'<p style="font-size:0.75rem;font-weight:600;margin-bottom:8px;color:var(--muted);">Archive License</p>'
        f'<p style="font-size:0.72rem;color:var(--muted);margin-bottom:8px;">Archived licenses are hidden from active enforcement. Restoring re-activates them. Active licenses cannot be deleted.</p>'
        f'<form method="post" action="{archive_action}" '
        f'onsubmit="bbConfirmSubmit(this,{{title:\'Archive district license?\','
        f'body:\'The license for <strong>{name}</strong> will be archived and removed from enforcement.\','
        f'consequence:\'School access falls back to tenant-level billing until the license is restored.\','
        f'confirmLabel:\'Archive license\',danger:true}});return false;">'
        f'<button class="button button-danger-outline" type="submit" style="width:100%;">Archive License</button>'
        f'</form></div>'
        f'</div></details>'
        f'</div>'
    )


def _render_district_billing_section(district_billing_rows: Sequence[Mapping[str, object]], archived_district_billing_rows: Sequence[Mapping[str, object]] = ()) -> str:
    if not district_billing_rows and not archived_district_billing_rows:
        return ""
    plan_opts = "".join(f'<option value="{p}">{p.title()}</option>' for p in ("trial", "basic", "pro", "enterprise"))
    status_opts = "".join(
        f'<option value="{s}">{s.replace("_", " ").title()}</option>'
        for s in ("trial", "active", "past_due", "expired", "suspended", "cancelled", "manual_override")
    )
    active_cards = [_render_district_billing_card(item, plan_opts, status_opts) for item in district_billing_rows]
    archived_cards = [_render_district_billing_card(item, plan_opts, status_opts, archived=True) for item in archived_district_billing_rows]

    archived_section = ""
    if archived_cards:
        archived_count_label = str(len(archived_cards)) + " archived license" + ("s" if len(archived_cards) != 1 else "")
        archived_section = (
            '<details style="margin-top:20px;">'
            '<summary style="cursor:pointer;font-size:0.8rem;font-weight:600;color:var(--muted);user-select:none;padding:8px 0;">'
            + escape(archived_count_label) +
            ' — click to expand</summary>'
            '<div style="margin-top:12px;">' + "".join(archived_cards) + "</div>"
            '</details>'
        )

    active_html = '<div class="tenant-grid" style="display:block;">' + "".join(active_cards) + "</div>" if active_cards else \
        '<p class="mini-copy" style="color:var(--muted);padding:12px 0;">No active district licenses.</p>'

    return (
        '<div style="margin-bottom:24px;">'
        '<p class="eyebrow" style="margin-bottom:12px;">District Licenses</p>'
        + active_html
        + archived_section
        + '</div>'
    )


def _render_sales_inbox_section(messages: object, section: str, unread_count: int = 0) -> str:
    _style = "" if section == "sales-inbox" else ' style="display:none;"'
    status_icon = {"new": "🔵", "read": "⚪", "replied": "✅"}
    rows_html = ""
    for msg in (messages or []):
        msg_id = int(getattr(msg, "id", 0))
        from_name = escape(str(getattr(msg, "from_name", "") or ""))
        from_email = escape(str(getattr(msg, "from_email", "") or ""))
        subject = escape(str(getattr(msg, "subject", "") or "(no subject)"))
        status = str(getattr(msg, "status", "new"))
        is_read = bool(getattr(msg, "is_read", False))
        received = str(getattr(msg, "received_at", "") or getattr(msg, "created_at", ""))[:16].replace("T", " ")
        linked_customer_id = getattr(msg, "linked_customer_id", None)
        linked_district_id = getattr(msg, "linked_district_id", None)
        icon = status_icon.get(status, "⚪")
        weight = "600" if not is_read else "400"
        link_badges = ""
        if linked_customer_id:
            link_badges += (f'<span style="font-size:0.67rem;background:#dbeafe;color:#1d4ed8;'
                            f'border-radius:4px;padding:1px 5px;margin-right:3px;">C#{linked_customer_id}</span>')
        if linked_district_id:
            link_badges += (f'<span style="font-size:0.67rem;background:#d1fae5;color:#065f46;'
                            f'border-radius:4px;padding:1px 5px;">D#{linked_district_id}</span>')
        rows_html += (
            f'<tr style="cursor:pointer;" onclick="bbInboxOpen({msg_id});">'
            f'<td style="text-align:center;font-size:1rem;">{icon}</td>'
            f'<td style="font-weight:{weight};white-space:nowrap;">'
            f'{from_name or from_email}<br><span style="font-size:0.72rem;color:var(--muted);">{from_email}</span></td>'
            f'<td style="font-weight:{weight};">{subject}'
            f'{"<br>" + link_badges if link_badges else ""}</td>'
            f'<td style="font-size:0.75rem;color:var(--muted);white-space:nowrap;">{received}</td>'
            f'<td style="text-align:center;">'
            f'<button class="button button-outline" style="font-size:0.72rem;padding:2px 8px;" '
            f'onclick="event.stopPropagation();bbInboxOpen({msg_id});">View</button>'
            f'</td>'
            f'</tr>'
        )
    if not rows_html:
        rows_html = ('<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:24px;">'
                     'No messages yet. Configure IMAP settings in Configuration to start syncing.</td></tr>')

    unread_badge = (f'<span style="display:inline-block;background:#2563eb;color:#fff;border-radius:999px;'
                    f'font-size:0.75rem;font-weight:700;padding:1px 8px;margin-left:8px;">'
                    f'{unread_count} unread</span>') if unread_count else ""

    reply_modal = (
        '<div id="bb-inbox-modal" style="display:none;position:fixed;inset:0;z-index:9999;'
        'background:rgba(0,0,0,0.55);align-items:center;justify-content:center;">'
        '<div style="background:var(--surface);border-radius:12px;max-width:640px;width:90%;'
        'max-height:85vh;overflow-y:auto;box-shadow:0 8px 40px rgba(0,0,0,.25);padding:32px;">'
        '<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px;">'
        '<h2 id="bb-inbox-subject" style="margin:0;font-size:1.1rem;flex:1;"></h2>'
        '<button onclick="document.getElementById(\'bb-inbox-modal\').style.display=\'none\';" '
        'style="background:none;border:none;font-size:1.5rem;cursor:pointer;color:var(--muted);">✕</button>'
        '</div>'
        '<p style="margin:0 0 4px;font-size:0.8rem;color:var(--muted);">From: <span id="bb-inbox-from"></span></p>'
        '<p style="margin:0 0 16px;font-size:0.8rem;color:var(--muted);">Received: <span id="bb-inbox-date"></span></p>'
        '<div id="bb-inbox-link-bar" style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">'
        '<div style="display:flex;gap:6px;align-items:center;">'
        '<input id="bb-link-customer-id" type="number" placeholder="Customer ID" min="1" '
        'style="width:100px;font-size:0.8rem;padding:4px 6px;border:1px solid var(--border);'
        'border-radius:4px;background:var(--bg);color:var(--text);" />'
        '<button type="button" class="button button-outline" style="font-size:0.75rem;padding:3px 10px;" '
        'onclick="bbInboxLinkCustomer();">Link Customer</button>'
        '</div>'
        '<span id="bb-inbox-linked-customer" style="font-size:0.75rem;color:var(--muted);align-self:center;"></span>'
        '</div>'
        '<pre id="bb-inbox-body" style="white-space:pre-wrap;word-break:break-word;font-family:inherit;'
        'font-size:0.85rem;background:var(--bg);border-radius:8px;padding:16px;max-height:240px;overflow-y:auto;'
        'border:1px solid var(--border);margin:0 0 16px;"></pre>'
        '<form id="bb-inbox-reply-form" onsubmit="event.preventDefault();bbInboxSendReply();">'
        '<textarea id="bb-inbox-reply-body" rows="5" style="width:100%;box-sizing:border-box;'
        'font-family:inherit;font-size:0.85rem;border:1px solid var(--border);border-radius:6px;'
        'padding:10px;background:var(--bg);color:var(--text);resize:vertical;margin-bottom:8px;" '
        'placeholder="Write your reply…"></textarea>'
        '<div style="display:flex;gap:8px;">'
        '<button type="submit" class="button button-primary" id="bb-inbox-send-btn">Send Reply</button>'
        '<button type="button" class="button button-outline" '
        'onclick="document.getElementById(\'bb-inbox-modal\').style.display=\'none\';">Cancel</button>'
        '</div>'
        '</form>'
        '</div></div>'
    )

    inbox_js = (
        '<script>'
        'var _bbInboxMsgId=null;'
        'function bbInboxOpen(id){'
        '  _bbInboxMsgId=id;'
        '  var m=document.getElementById("bb-inbox-modal");'
        '  m.style.display="flex";'
        '  document.getElementById("bb-inbox-subject").textContent="Loading…";'
        '  document.getElementById("bb-inbox-body").textContent="";'
        '  document.getElementById("bb-inbox-reply-body").value="";'
        '  fetch("/super-admin/inbox/"+id,{headers:{"X-Requested-With":"XMLHttpRequest"}})'
        '  .then(r=>r.json()).then(d=>{'
        '    if(!d.ok){alert("Error loading message.");return;}'
        '    var msg=d.message;'
        '    document.getElementById("bb-inbox-subject").textContent=msg.subject||"(no subject)";'
        '    document.getElementById("bb-inbox-from").textContent=(msg.from_name?msg.from_name+" ":"")+"<"+msg.from_email+">";'
        '    var dt=(msg.received_at||msg.created_at||"").replace("T"," ").slice(0,16);'
        '    document.getElementById("bb-inbox-date").textContent=dt;'
        '    document.getElementById("bb-inbox-body").textContent=msg.body_text||"(no text content)";'
        '    var lc=document.getElementById("bb-inbox-linked-customer");'
        '    if(msg.linked_customer_id) lc.textContent="Linked: Customer #"+msg.linked_customer_id;'
        '    else lc.textContent="";'
        '    document.getElementById("bb-link-customer-id").value=msg.linked_customer_id||"";'
        '  }).catch(()=>alert("Failed to load message."));'
        '}'
        'function bbInboxLinkCustomer(){'
        '  var cid=document.getElementById("bb-link-customer-id").value.trim();'
        '  if(!cid&&!confirm("Remove customer link?"))return;'
        '  var fd=new FormData();if(cid)fd.append("customer_id",cid);'
        '  fetch("/super-admin/inbox/"+_bbInboxMsgId+"/link-customer",{method:"POST",body:fd,'
        '  headers:{"X-Requested-With":"XMLHttpRequest"}})'
        '  .then(r=>r.json()).then(d=>{'
        '    if(d.ok){var lc=document.getElementById("bb-inbox-linked-customer");'
        '    lc.textContent=cid?"Linked: Customer #"+cid:"";location.reload();}'
        '    else alert("Link failed: "+(d.error||"unknown"));'
        '  }).catch(()=>alert("Network error."));'
        '}'
        'function bbInboxSendReply(){'
        '  var body=document.getElementById("bb-inbox-reply-body").value.trim();'
        '  if(!body){alert("Reply cannot be empty.");return;}'
        '  var btn=document.getElementById("bb-inbox-send-btn");'
        '  btn.disabled=true;btn.textContent="Sending…";'
        '  var fd=new FormData();fd.append("reply_body",body);'
        '  fetch("/super-admin/inbox/"+_bbInboxMsgId+"/reply",{method:"POST",body:fd,'
        '  headers:{"X-Requested-With":"XMLHttpRequest"}})'
        '  .then(r=>r.json()).then(d=>{'
        '    btn.disabled=false;btn.textContent="Send Reply";'
        '    if(d.ok){document.getElementById("bb-inbox-modal").style.display="none";location.reload();}'
        '    else alert("Send failed: "+(d.error||"unknown error"));'
        '  }).catch(()=>{btn.disabled=false;btn.textContent="Send Reply";alert("Network error.");});'
        '}'
        'function bbInboxSync(){'
        '  var btn=document.getElementById("bb-inbox-sync-btn");'
        '  if(btn){btn.disabled=true;btn.textContent="Syncing…";}'
        '  fetch("/super-admin/inbox/sync",{method:"POST",headers:{"X-Requested-With":"XMLHttpRequest"}})'
        '  .then(r=>r.json()).then(d=>{'
        '    if(d.ok){location.reload();}'
        '    else alert("Sync failed: "+(d.error||"unknown"));'
        '  }).catch(()=>alert("Network error during sync."));'
        '}'
        '</script>'
    )

    return (
        f'<section class="panel command-section" id="sales-inbox"{_style}>'
        f'{reply_modal}'
        f'<div class="panel-header hero-band">'
        f'<div><p class="eyebrow">CRM</p><h1>Sales Inbox{unread_badge}</h1>'
        f'<p class="hero-copy">Incoming emails received via IMAP. Sync every 3 minutes automatically.</p></div>'
        f'<div style="display:flex;gap:8px;align-items:center;">'
        f'<button id="bb-inbox-sync-btn" class="button button-outline" onclick="bbInboxSync();" type="button">'
        f'↻ Sync Now</button>'
        f'</div>'
        f'</div>'
        f'<div style="overflow-x:auto;margin-top:16px;">'
        f'<table class="data-table" style="width:100%;font-size:0.82rem;">'
        f'<thead><tr><th style="width:32px;"></th><th>From</th><th>Subject</th>'
        f'<th>Received</th><th></th></tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table></div>'
        f'{inbox_js}'
        f'</section>'
    )


def _render_demo_requests_section(demo_requests: object, section: str) -> str:
    _style = "" if section == "demo-requests" else ' style="display:none;"'
    status_colors = {
        "new": "#2563eb",
        "contacted": "#d97706",
        "converted": "#059669",
        "closed": "#6b7280",
    }
    rows_html = ""
    for dr in (demo_requests or []):
        rid = int(getattr(dr, "id", 0))
        name = escape(str(getattr(dr, "name", "")))
        email = escape(str(getattr(dr, "email", "")))
        org = escape(str(getattr(dr, "organization", "")))
        role = escape(str(getattr(dr, "role", "") or ""))
        school_count = getattr(dr, "school_count", None)
        sc_disp = escape(str(school_count)) if school_count is not None else "—"
        message = escape(str(getattr(dr, "message", "") or ""))
        phone = escape(str(getattr(dr, "phone", "") or ""))
        preferred_time = escape(str(getattr(dr, "preferred_time", "") or ""))
        status = escape(str(getattr(dr, "status", "new")))
        created_at = escape(str(getattr(dr, "created_at", ""))[:10])
        notes = escape(str(getattr(dr, "notes", "") or ""))
        sc = status_colors.get(status, "#6b7280")
        status_badge = (
            f'<span style="display:inline-block;padding:2px 8px;border-radius:20px;'
            f'background:{sc}15;color:{sc};font-size:.72rem;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:.04em;">{status}</span>'
        )
        convert_btn = (
            f'<button class="bb-btn-xs bb-btn-success" onclick="bbDemoConvert({rid},\'{escape(org)}\')">→ District</button>'
            if status not in ("converted", "closed") else ""
        )
        rows_html += (
            f'<tr>'
            f'<td><strong>{org}</strong><br/><small style="color:var(--muted);">{role}</small></td>'
            f'<td>{name}<br/><a href="mailto:{email}" style="font-size:.8rem;color:var(--blue);">{email}</a></td>'
            f'<td style="font-size:.85rem;">{sc_disp} schools</td>'
            f'<td style="max-width:200px;font-size:.82rem;color:var(--muted);">'
            f'<div style="white-space:pre-wrap;overflow:hidden;max-height:3em;" title="{message}">'
            f'{message[:120]}{"…" if len(message) > 120 else ""}</div>'
            f'{"<br/><small>Phone: " + phone + "</small>" if phone else ""}'
            f'{"<br/><small>Prefers: " + preferred_time + "</small>" if preferred_time else ""}'
            f'</td>'
            f'<td>{status_badge}</td>'
            f'<td style="font-size:.82rem;">{created_at}</td>'
            f'<td style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">'
            f'<select onchange="bbDemoStatus({rid},this.value)" style="font-size:.8rem;padding:3px 6px;border-radius:6px;">'
            f'<option value="">— Status —</option>'
            f'<option value="new">New</option>'
            f'<option value="contacted">Contacted</option>'
            f'<option value="converted">Converted</option>'
            f'<option value="closed">Closed</option>'
            f'</select>'
            f'{convert_btn}'
            f'<button class="bb-btn-xs" style="background:#fee2e2;color:#dc2626;" onclick="bbDemoDelete({rid})">Delete</button>'
            f'</td>'
            f'</tr>'
            f'<tr><td colspan="7" style="padding:4px 12px 12px;">'
            f'<textarea id="dr-notes-{rid}" style="width:100%;font-size:.8rem;border:1px solid var(--border);border-radius:6px;padding:6px;resize:vertical;min-height:48px;"'
            f' placeholder="Internal notes…" onblur="bbDemoNotes({rid},this.value)">{notes}</textarea>'
            f'</td></tr>'
        )

    if not rows_html:
        rows_html = '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:32px 0;">No demo requests yet.</td></tr>'

    new_count = sum(1 for dr in (demo_requests or []) if getattr(dr, "status", "") == "new")
    badge = f'<span style="background:#2563eb;color:#fff;border-radius:20px;padding:2px 8px;font-size:.75rem;margin-left:8px;">{new_count} new</span>' if new_count else ""

    demo_js = """
<script>
async function bbDemoStatus(id, status) {
  if (!status) return;
  var fd = new FormData(); fd.append('new_status', status);
  var r = await fetch('/super-admin/demo-requests/' + id + '/status', {method:'POST', body: fd});
  var d = await r.json();
  if (d.ok) bbShowBanner('Status updated.');
  else bbShowBanner('Error: ' + (d.error || 'unknown'), true);
}
async function bbDemoNotes(id, notes) {
  var fd = new FormData(); fd.append('notes', notes);
  await fetch('/super-admin/demo-requests/' + id + '/notes', {method:'POST', body: fd});
}
async function bbDemoDelete(id) {
  if (!confirm('Delete this demo request? This cannot be undone.')) return;
  var r = await fetch('/super-admin/demo-requests/' + id, {method:'DELETE'});
  var d = await r.json();
  if (d.ok) { location.reload(); }
  else bbShowBanner('Error: ' + (d.error || 'unknown'), true);
}
function bbDemoConvert(id, org) {
  var dname = prompt('District name:', org);
  if (!dname) return;
  var dslug = dname.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
  var confirmed = confirm('Create district "' + dname + '" (slug: ' + dslug + ')?');
  if (!confirmed) return;
  var fd = new FormData();
  fd.append('district_name', dname);
  fd.append('district_slug', dslug);
  fetch('/super-admin/demo-requests/' + id + '/convert', {method:'POST', body: fd})
    .then(r => r.json())
    .then(d => {
      if (d.ok) { bbShowBanner('District "' + d.district_name + '" created. Demo request marked converted.'); setTimeout(() => location.reload(), 1200); }
      else bbShowBanner('Error: ' + (d.error || 'unknown'), true);
    });
}
</script>
"""

    return (
        f'<section class="panel command-section" id="demo-requests"{_style}>'
        f'<h2 style="margin-bottom:4px;">Demo Requests {badge}</h2>'
        f'<p style="color:var(--muted);font-size:.875rem;margin-bottom:20px;">'
        f'Submissions from the /request-demo form. Convert promising leads directly to districts.</p>'
        f'<div class="table-wrap" style="overflow-x:auto;">'
        f'<table class="data-table" style="min-width:860px;">'
        f'<thead><tr>'
        f'<th>Organization</th><th>Contact</th><th>Size</th>'
        f'<th>Message</th><th>Status</th><th>Date</th><th>Actions</th>'
        f'</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table></div>'
        f'{demo_js}'
        f'</section>'
    )


def _render_inquiries_section(inquiries: object, section: str) -> str:
    _style = "" if section == "inquiries" else ' style="display:none;"'
    status_colors = {
        "new": "#2563eb",
        "contacted": "#d97706",
        "quoted": "#7c3aed",
        "closed": "#059669",
    }
    size_colors = {"small": "#6b7280", "medium": "#d97706", "large": "#dc2626", "unknown": "#6b7280"}
    rows_html = ""
    for inq in (inquiries or []):
        inq_id = int(getattr(inq, "id", 0))
        name = escape(str(getattr(inq, "name", "")))
        email = escape(str(getattr(inq, "email", "")))
        school = escape(str(getattr(inq, "school_or_district", "")))
        students = str(getattr(inq, "estimated_students", "") or "—")
        tag = str(getattr(inq, "size_tag", "unknown"))
        st = str(getattr(inq, "status", "new"))
        created = str(getattr(inq, "created_at", ""))[:10]
        notes = escape(str(getattr(inq, "notes", "") or ""))
        st_color = status_colors.get(st, "#6b7280")
        sz_color = size_colors.get(tag, "#6b7280")
        rows_html += (
            f'<tr>'
            f'<td style="font-weight:600;">{name}</td>'
            f'<td><a href="mailto:{email}" style="color:var(--accent);">{email}</a></td>'
            f'<td>{school}</td>'
            f'<td style="text-align:center;">{students}</td>'
            f'<td style="text-align:center;"><span style="font-size:0.72rem;font-weight:700;color:{sz_color};">{tag.upper()}</span></td>'
            f'<td style="text-align:center;"><span style="font-size:0.72rem;font-weight:700;color:{st_color};">{st.upper()}</span></td>'
            f'<td style="font-size:0.75rem;color:var(--muted);">{created}</td>'
            f'<td style="min-width:160px;">'
            f'<form method="post" action="/super-admin/inquiries/{inq_id}/status" '
            f'style="display:inline;" onsubmit="event.preventDefault();bbUpdateInquiryStatus(this,{inq_id});">'
            f'<select name="new_status" style="font-size:0.72rem;padding:2px 6px;border-radius:4px;" onchange="this.form.requestSubmit();">'
            + "".join(
                f'<option value="{s}"{" selected" if s == st else ""}>{s.title()}</option>'
                for s in ("new", "contacted", "quoted", "closed")
            )
            + f'</select></form>'
            f' <button class="button button-outline" style="font-size:0.72rem;padding:2px 8px;" '
            f'onclick="bbInquiryConvert({inq_id},\'{escape(school)}\');" type="button">→ District</button>'
            f' <button class="button button-outline" style="font-size:0.72rem;padding:2px 8px;" '
            f'onclick="bbInquiryToCustomer({inq_id},\'{escape(name)}\',\'{escape(email)}\',\'{escape(school)}\');" '
            f'type="button">→ Customer</button>'
            f'</td>'
            f'<td style="min-width:180px;">'
            f'<form onsubmit="event.preventDefault();bbSaveInquiryNotes(this,{inq_id});" style="display:flex;gap:4px;align-items:flex-start;">'
            f'<textarea name="notes" rows="2" style="flex:1;font-size:0.72rem;border:1px solid var(--border);'
            f'border-radius:4px;padding:4px;background:var(--bg);color:var(--text);resize:vertical;"'
            f' placeholder="Internal notes…">{notes}</textarea>'
            f'<button class="button button-outline" style="font-size:0.72rem;padding:2px 8px;" type="submit">Save</button>'
            f'</form>'
            f'</td>'
            f'</tr>'
        )
    if not rows_html:
        rows_html = '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:24px;">No inquiries yet. Submit the contact form on the marketing site to test.</td></tr>'

    convert_modal = (
        '<div id="bb-convert-modal" style="display:none;position:fixed;inset:0;z-index:9998;'
        'background:rgba(0,0,0,0.55);align-items:center;justify-content:center;">'
        '<div style="background:var(--surface);border-radius:12px;max-width:480px;width:90%;'
        'padding:32px;box-shadow:0 8px 40px rgba(0,0,0,.25);">'
        '<h2 style="margin:0 0 16px;">Convert to District</h2>'
        '<p style="font-size:0.85rem;color:var(--muted);margin:0 0 20px;">'
        'Create a new district record and trial billing for this inquiry.</p>'
        '<form onsubmit="event.preventDefault();bbDoConvert();">'
        '<input type="hidden" id="bb-convert-inq-id" value="">'
        '<label style="font-size:0.82rem;font-weight:600;display:block;margin-bottom:4px;">District Name</label>'
        '<input id="bb-convert-name" type="text" style="width:100%;box-sizing:border-box;'
        'font-size:0.85rem;padding:8px;border:1px solid var(--border);border-radius:6px;'
        'background:var(--bg);color:var(--text);margin-bottom:12px;" required>'
        '<label style="font-size:0.82rem;font-weight:600;display:block;margin-bottom:4px;">District Slug <span style="font-weight:400;color:var(--muted);">(auto-generated)</span></label>'
        '<input id="bb-convert-slug" type="text" style="width:100%;box-sizing:border-box;'
        'font-size:0.85rem;padding:8px;border:1px solid var(--border);border-radius:6px;'
        'background:var(--bg);color:var(--text);margin-bottom:20px;">'
        '<div style="display:flex;gap:8px;">'
        '<button type="submit" class="button button-primary" id="bb-convert-btn">Create District</button>'
        '<button type="button" class="button button-outline" '
        'onclick="document.getElementById(\'bb-convert-modal\').style.display=\'none\';">Cancel</button>'
        '</div>'
        '</form>'
        '</div></div>'
    )

    convert_customer_modal = (
        '<div id="bb-convert-customer-modal" style="display:none;position:fixed;inset:0;z-index:9998;'
        'background:rgba(0,0,0,0.55);align-items:center;justify-content:center;">'
        '<div style="background:var(--surface);border-radius:12px;max-width:440px;width:90%;'
        'padding:32px;box-shadow:0 8px 40px rgba(0,0,0,.25);">'
        '<h2 style="margin:0 0 12px;">Create Customer Lead</h2>'
        '<p style="font-size:0.85rem;color:var(--muted);margin:0 0 16px;">'
        'Save this inquiry as a CRM customer record without creating a district.</p>'
        '<input type="hidden" id="bcc-inq-id" value="">'
        '<p id="bcc-summary" style="font-size:0.82rem;margin-bottom:16px;"></p>'
        '<div style="display:flex;gap:8px;">'
        '<button type="button" class="button button-primary" id="bcc-btn" onclick="bbDoInquiryToCustomer();">Create Customer</button>'
        '<button type="button" class="button button-outline" '
        'onclick="document.getElementById(\'bb-convert-customer-modal\').style.display=\'none\';">Cancel</button>'
        '</div></div></div>'
    )

    inquiry_js = (
        '<script>'
        'function bbSaveInquiryNotes(form,id){'
        '  var fd=new FormData(form);'
        '  fetch("/super-admin/inquiries/"+id+"/notes",{method:"POST",body:fd,'
        '  headers:{"X-Requested-With":"XMLHttpRequest"}})'
        '  .then(r=>r.json()).then(d=>{'
        '    if(!d.ok)alert("Save failed: "+(d.error||"unknown"));'
        '  }).catch(()=>alert("Network error."));'
        '}'
        'function bbInquiryConvert(id,schoolName){'
        '  document.getElementById("bb-convert-inq-id").value=id;'
        '  document.getElementById("bb-convert-name").value=schoolName;'
        '  var slug=schoolName.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"");'
        '  document.getElementById("bb-convert-slug").value=slug;'
        '  document.getElementById("bb-convert-modal").style.display="flex";'
        '}'
        'function bbDoConvert(){'
        '  var id=document.getElementById("bb-convert-inq-id").value;'
        '  var btn=document.getElementById("bb-convert-btn");'
        '  btn.disabled=true;btn.textContent="Creating…";'
        '  var fd=new FormData();'
        '  fd.append("district_name",document.getElementById("bb-convert-name").value);'
        '  fd.append("district_slug",document.getElementById("bb-convert-slug").value);'
        '  fetch("/super-admin/inquiries/"+id+"/convert",{method:"POST",body:fd,'
        '  headers:{"X-Requested-With":"XMLHttpRequest"}})'
        '  .then(r=>r.json()).then(d=>{'
        '    btn.disabled=false;btn.textContent="Create District";'
        '    if(d.ok){document.getElementById("bb-convert-modal").style.display="none";'
        '    alert("District created: "+d.district_name+" ("+d.district_slug+")");location.reload();}'
        '    else alert("Error: "+(d.error||"unknown"));'
        '  }).catch(()=>{btn.disabled=false;btn.textContent="Create District";alert("Network error.");});'
        '}'
        'function bbInquiryToCustomer(id,name,email,org){'
        '  document.getElementById("bcc-inq-id").value=id;'
        '  document.getElementById("bcc-summary").textContent=name+" ("+email+") — "+org;'
        '  document.getElementById("bb-convert-customer-modal").style.display="flex";'
        '}'
        'function bbDoInquiryToCustomer(){'
        '  var id=document.getElementById("bcc-inq-id").value;'
        '  var btn=document.getElementById("bcc-btn");'
        '  btn.disabled=true;btn.textContent="Creating…";'
        '  fetch("/super-admin/inquiries/"+id+"/convert-to-customer",{method:"POST",'
        '  headers:{"X-Requested-With":"XMLHttpRequest"}})'
        '  .then(r=>r.json()).then(d=>{'
        '    btn.disabled=false;btn.textContent="Create Customer";'
        '    if(d.ok){document.getElementById("bb-convert-customer-modal").style.display="none";'
        '    alert("Customer created: "+d.customer_name);location.reload();}'
        '    else alert("Error: "+(d.error||"unknown"));'
        '  }).catch(()=>{btn.disabled=false;btn.textContent="Create Customer";alert("Network error.");});'
        '}'
        '</script>'
    )

    return (
        f'<section class="panel command-section" id="inquiries"{_style}>'
        f'{convert_modal}'
        f'{convert_customer_modal}'
        f'<div class="panel-header hero-band">'
        f'<div><p class="eyebrow">Marketing</p><h1>Website Inquiries</h1>'
        f'<p class="hero-copy">Leads submitted through the BlueBird Alerts marketing contact form.</p></div>'
        f'</div>'
        f'<div style="overflow-x:auto;margin-top:16px;">'
        f'<table class="data-table" style="width:100%;font-size:0.82rem;">'
        f'<thead><tr><th>Name</th><th>Email</th><th>School / District</th><th>Students</th>'
        f'<th>Size</th><th>Status</th><th>Date</th><th>Actions</th><th>Notes</th></tr></thead>'
        f'<tbody id="inquiry-table-body">{rows_html}</tbody>'
        f'</table></div>'
        f'{inquiry_js}'
        f'</section>'
    )


def _render_customers_section(customers: object, section: str) -> str:
    _style = "" if section == "customers" else ' style="display:none;"'
    status_colors = {
        "lead": "#2563eb",
        "active": "#059669",
        "closed": "#6b7280",
        "archived": "#9ca3af",
    }
    source_labels = {"website": "Web", "email": "Email", "manual": "Manual"}
    rows_html = ""
    for c in (customers or []):
        cid = int(getattr(c, "id", 0))
        name = escape(str(getattr(c, "name", "")))
        email = escape(str(getattr(c, "email", "")))
        org = escape(str(getattr(c, "organization", "") or ""))
        status = str(getattr(c, "status", "lead"))
        source = str(getattr(c, "source", "manual"))
        district_id = getattr(c, "district_id", None)
        created = str(getattr(c, "created_at", ""))[:10]
        st_color = status_colors.get(status, "#6b7280")
        src_label = source_labels.get(source, source.title())
        district_badge = (
            f'<a href="/super-admin?section=districts#districts" '
            f'style="font-size:0.7rem;color:var(--accent);text-decoration:none;" '
            f'title="Linked district #{district_id}">District #{district_id}</a>'
            if district_id else
            '<span style="font-size:0.72rem;color:var(--muted);">—</span>'
        )
        rows_html += (
            f'<tr style="cursor:pointer;" onclick="bbCustomerOpen({cid});">'
            f'<td style="font-weight:600;">{name}</td>'
            f'<td><a href="mailto:{email}" onclick="event.stopPropagation();" '
            f'style="color:var(--accent);">{email}</a></td>'
            f'<td>{org or "<span style=\"color:var(--muted);\">—</span>"}</td>'
            f'<td style="text-align:center;"><span style="font-size:0.7rem;font-weight:700;'
            f'color:{st_color};">{status.upper()}</span></td>'
            f'<td style="text-align:center;font-size:0.72rem;color:var(--muted);">{src_label}</td>'
            f'<td style="text-align:center;">{district_badge}</td>'
            f'<td style="font-size:0.75rem;color:var(--muted);">{created}</td>'
            f'<td onclick="event.stopPropagation();">'
            f'<form method="post" action="/super-admin/customers/{cid}/update" '
            f'style="display:inline;" onsubmit="event.preventDefault();bbUpdateCustomerStatus(this,{cid});">'
            f'<select name="status" style="font-size:0.72rem;padding:2px 6px;border-radius:4px;" '
            f'onchange="this.form.requestSubmit();">'
            + "".join(
                f'<option value="{s}"{" selected" if s == status else ""}>{s.title()}</option>'
                for s in ("lead", "active", "closed", "archived")
            )
            + f'</select></form>'
            f' <button class="button button-outline" style="font-size:0.72rem;padding:2px 8px;" '
            f'onclick="event.stopPropagation();bbCustomerOpen({cid});" type="button">View</button>'
            f'</td>'
            f'</tr>'
        )
    if not rows_html:
        rows_html = ('<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:24px;">'
                     'No customers yet. Convert an inquiry or create one manually.</td></tr>')

    create_modal = (
        '<div id="bb-customer-create-modal" style="display:none;position:fixed;inset:0;z-index:9998;'
        'background:rgba(0,0,0,0.55);align-items:center;justify-content:center;">'
        '<div style="background:var(--surface);border-radius:12px;max-width:480px;width:90%;'
        'padding:32px;box-shadow:0 8px 40px rgba(0,0,0,.25);max-height:90vh;overflow-y:auto;">'
        '<h2 style="margin:0 0 16px;">Create Customer</h2>'
        '<form onsubmit="event.preventDefault();bbDoCreateCustomer();" class="stack" style="gap:8px;">'
        '<input id="bc-name" name="name" type="text" placeholder="Full name" required '
        'style="font-size:0.85rem;padding:8px;border:1px solid var(--border);border-radius:6px;'
        'background:var(--bg);color:var(--text);" />'
        '<input id="bc-email" name="email" type="email" placeholder="Email address" required '
        'style="font-size:0.85rem;padding:8px;border:1px solid var(--border);border-radius:6px;'
        'background:var(--bg);color:var(--text);" />'
        '<input id="bc-org" name="organization" type="text" placeholder="School / District name" '
        'style="font-size:0.85rem;padding:8px;border:1px solid var(--border);border-radius:6px;'
        'background:var(--bg);color:var(--text);" />'
        '<input id="bc-phone" name="phone" type="tel" placeholder="Phone (optional)" '
        'style="font-size:0.85rem;padding:8px;border:1px solid var(--border);border-radius:6px;'
        'background:var(--bg);color:var(--text);" />'
        '<select id="bc-source" name="source" style="font-size:0.83rem;padding:8px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);">'
        '<option value="manual">Source: Manual</option>'
        '<option value="website">Source: Website</option>'
        '<option value="email">Source: Email</option>'
        '</select>'
        '<textarea id="bc-notes" name="notes" rows="3" placeholder="Internal notes…" '
        'style="font-size:0.83rem;padding:8px;border:1px solid var(--border);border-radius:6px;'
        'background:var(--bg);color:var(--text);resize:vertical;"></textarea>'
        '<div style="display:flex;gap:8px;margin-top:8px;">'
        '<button type="submit" class="button button-primary" id="bc-submit-btn">Create Customer</button>'
        '<button type="button" class="button button-outline" '
        'onclick="document.getElementById(\'bb-customer-create-modal\').style.display=\'none\';">Cancel</button>'
        '</div></form></div></div>'
    )

    detail_modal = (
        '<div id="bb-customer-modal" style="display:none;position:fixed;inset:0;z-index:9999;'
        'background:rgba(0,0,0,0.55);align-items:center;justify-content:center;">'
        '<div style="background:var(--surface);border-radius:12px;max-width:680px;width:90%;'
        'max-height:85vh;overflow-y:auto;box-shadow:0 8px 40px rgba(0,0,0,.25);padding:32px;">'
        '<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px;">'
        '<h2 id="bc-detail-name" style="margin:0;font-size:1.1rem;"></h2>'
        '<button onclick="document.getElementById(\'bb-customer-modal\').style.display=\'none\';" '
        'style="background:none;border:none;font-size:1.5rem;cursor:pointer;color:var(--muted);">✕</button>'
        '</div>'
        '<div id="bc-detail-meta" style="font-size:0.82rem;color:var(--muted);margin-bottom:16px;line-height:1.8;"></div>'
        '<div id="bc-detail-billing" style="margin-bottom:16px;display:none;">'
        '<h4 style="margin:0 0 6px;font-size:0.85rem;">Licensing</h4>'
        '<div id="bc-detail-billing-body" style="font-size:0.82rem;color:var(--muted);"></div>'
        '</div>'
        '<div id="bc-detail-emails-wrap" style="margin-bottom:16px;display:none;">'
        '<h4 style="margin:0 0 6px;font-size:0.85rem;">Linked Emails</h4>'
        '<div id="bc-detail-emails" style="font-size:0.82rem;max-height:180px;overflow-y:auto;'
        'border:1px solid var(--border);border-radius:8px;padding:8px;background:var(--bg);"></div>'
        '</div>'
        '<div>'
        '<h4 style="margin:0 0 6px;font-size:0.85rem;">Notes</h4>'
        '<form onsubmit="event.preventDefault();bbSaveCustomerNotes();" style="display:flex;gap:8px;">'
        '<textarea id="bc-detail-notes" rows="3" style="flex:1;font-size:0.82rem;padding:8px;'
        'border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);resize:vertical;">'
        '</textarea>'
        '<button type="submit" class="button button-outline" style="align-self:flex-start;">Save</button>'
        '</form></div></div></div>'
    )

    customers_js = (
        '<script>'
        'var _bbCustId=null;'
        'function bbCustomerOpen(id){'
        '  _bbCustId=id;'
        '  var m=document.getElementById("bb-customer-modal");'
        '  m.style.display="flex";'
        '  document.getElementById("bc-detail-name").textContent="Loading…";'
        '  document.getElementById("bc-detail-meta").innerHTML="";'
        '  document.getElementById("bc-detail-billing").style.display="none";'
        '  document.getElementById("bc-detail-emails-wrap").style.display="none";'
        '  fetch("/super-admin/customers/"+id,{headers:{"X-Requested-With":"XMLHttpRequest"}})'
        '  .then(r=>r.json()).then(d=>{'
        '    if(!d.ok){alert("Error loading customer.");return;}'
        '    var c=d.customer;'
        '    document.getElementById("bc-detail-name").textContent=c.name;'
        '    var meta=c.email+"  •  "+(c.organization||"—")+"  •  Status: "+c.status+"  •  Source: "+c.source;'
        '    if(c.phone) meta+="  •  "+c.phone;'
        '    if(c.district_id) meta+="<br>District #"+c.district_id;'
        '    if(c.inquiry_id) meta+="  •  Inquiry #"+c.inquiry_id;'
        '    document.getElementById("bc-detail-meta").innerHTML=meta;'
        '    document.getElementById("bc-detail-notes").value=c.notes||"";'
        '    if(c.billing){'
        '      document.getElementById("bc-detail-billing").style.display="block";'
        '      var b=c.billing;'
        '      document.getElementById("bc-detail-billing-body").textContent='
        '        "Plan: "+(b.plan_type||"—")+"  |  Status: "+(b.status||"—")'
        '        +"  |  Renewal: "+(b.renewal_date||"—");'
        '    }'
        '    if(c.emails&&c.emails.length){'
        '      document.getElementById("bc-detail-emails-wrap").style.display="block";'
        '      document.getElementById("bc-detail-emails").innerHTML='
        '        c.emails.map(function(e){'
        '          return "<div style=\'padding:4px 0;border-bottom:1px solid var(--border);font-size:0.78rem;\'>"'
        '            +"<strong>"+(e.direction==="inbound"?"←":"→")+"</strong> "+(e.subject||"(no subject)")'
        '            +" — <span style=\'color:var(--muted);\'>"+(e.received_at||e.created_at||"").slice(0,10)+"</span></div>";'
        '        }).join("");'
        '    }'
        '  }).catch(()=>alert("Failed to load customer."));'
        '}'
        'function bbSaveCustomerNotes(){'
        '  var fd=new FormData();fd.append("notes",document.getElementById("bc-detail-notes").value);'
        '  fetch("/super-admin/customers/"+_bbCustId+"/update",{method:"POST",body:fd,'
        '  headers:{"X-Requested-With":"XMLHttpRequest"}})'
        '  .then(r=>r.json()).then(d=>{'
        '    if(!d.ok)alert("Save failed: "+(d.error||"unknown"));'
        '  }).catch(()=>alert("Network error."));'
        '}'
        'function bbUpdateCustomerStatus(form,id){'
        '  var fd=new FormData(form);'
        '  fetch("/super-admin/customers/"+id+"/update",{method:"POST",body:fd,'
        '  headers:{"X-Requested-With":"XMLHttpRequest"}})'
        '  .then(r=>r.json()).then(d=>{'
        '    if(!d.ok)alert("Update failed: "+(d.error||"unknown"));'
        '    else location.reload();'
        '  }).catch(()=>alert("Network error."));'
        '}'
        'function bbCreateCustomer(){'
        '  document.getElementById("bb-customer-create-modal").style.display="flex";'
        '}'
        'function bbDoCreateCustomer(){'
        '  var btn=document.getElementById("bc-submit-btn");'
        '  btn.disabled=true;btn.textContent="Creating…";'
        '  var fd=new FormData();'
        '  fd.append("name",document.getElementById("bc-name").value);'
        '  fd.append("email",document.getElementById("bc-email").value);'
        '  fd.append("organization",document.getElementById("bc-org").value);'
        '  fd.append("phone",document.getElementById("bc-phone").value);'
        '  fd.append("source",document.getElementById("bc-source").value);'
        '  fd.append("notes",document.getElementById("bc-notes").value);'
        '  fetch("/super-admin/customers",{method:"POST",body:fd,'
        '  headers:{"X-Requested-With":"XMLHttpRequest"}})'
        '  .then(r=>r.json()).then(d=>{'
        '    btn.disabled=false;btn.textContent="Create Customer";'
        '    if(d.ok){document.getElementById("bb-customer-create-modal").style.display="none";location.reload();}'
        '    else alert("Error: "+(d.error||"unknown"));'
        '  }).catch(()=>{btn.disabled=false;btn.textContent="Create Customer";alert("Network error.");});'
        '}'
        '</script>'
    )

    return (
        f'<section class="panel command-section" id="customers"{_style}>'
        f'{create_modal}'
        f'{detail_modal}'
        f'<div class="panel-header hero-band">'
        f'<div><p class="eyebrow">CRM</p><h1>Customers</h1>'
        f'<p class="hero-copy">Sales leads, active customers, and their licensing status.</p></div>'
        f'<div style="display:flex;gap:8px;align-items:center;">'
        f'<button class="button button-primary" type="button" onclick="bbCreateCustomer();">+ New Customer</button>'
        f'</div>'
        f'</div>'
        f'<div style="overflow-x:auto;margin-top:16px;">'
        f'<table class="data-table" style="width:100%;font-size:0.82rem;">'
        f'<thead><tr><th>Name</th><th>Email</th><th>Organization</th>'
        f'<th>Status</th><th>Source</th><th>District</th><th>Created</th><th>Actions</th></tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table></div>'
        f'{customers_js}'
        f'</section>'
    )


def _render_email_delivery_section(
    settings: object, auto_reply: object, section: str = "configuration"
) -> str:
    def _v(key: str, default: str = "") -> str:
        if isinstance(settings, dict):
            return escape(str(settings.get(key, default) or default))
        return escape(default)

    def _ar(key: str, default: str = "") -> str:
        if isinstance(auto_reply, dict):
            return str(auto_reply.get(key, default) or default)
        return default

    provider = _v("PROVIDER", "smtp")
    from_email = _v("FROM_EMAIL") or _v("SMTP_FROM")
    from_name = _v("FROM_NAME") or _v("SMTP_FROM_NAME", "BlueBird Alerts")
    reply_to = _v("REPLY_TO_EMAIL")
    notify_email = _v("INQUIRY_NOTIFY_EMAIL", "taylor@emerytechsolutions.com")
    inbox_filter_to = _v("INBOX_FILTER_TO")
    sg_set = _v("SENDGRID_API_KEY_ENCRYPTED")
    ar_enabled = _ar("enabled", "0") == "1"
    ar_subject = escape(_ar("subject", "Thanks for your interest in BlueBird Alerts"))
    ar_body = escape(_ar("body", "Hi {{name}},\n\nThanks for reaching out..."))

    prov_opts = "".join(
        f'<option value="{p}"{" selected" if p == provider else ""}>{p.title()}</option>'
        for p in ("smtp", "sendgrid", "disabled")
    )

    sendgrid_hint = (
        '<span class="status-pill ok" style="font-size:0.68rem;">API key stored</span>'
        if sg_set else
        '<span style="font-size:0.72rem;color:var(--muted);">No API key stored</span>'
    )

    return (
        f'<div id="email-delivery-panel">'
        f'<h2 style="margin-bottom:8px;">Email Delivery</h2>'
        f'<p class="card-copy" style="margin-bottom:16px;">Provider for inquiry notifications and auto-replies. '
        f'Separate from the Gmail/SMTP settings above — used for outbound marketing emails.</p>'
        f'<div class="form-grid" style="gap:24px;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));margin-top:16px;">'
        f'<div style="border:1px solid var(--border);border-radius:10px;padding:20px;">'
        f'<h3 style="margin-bottom:12px;">Provider &amp; Identity</h3>'
        f'<form id="email-delivery-form" method="post" action="/super-admin/email-delivery-settings" class="stack" style="gap:8px;">'
        f'<label style="font-size:0.78rem;">Provider</label>'
        f'<select name="provider" style="margin-bottom:6px;">{prov_opts}</select>'
        f'<input name="from_email" type="email" value="{from_email}" placeholder="From email" style="font-size:0.83rem;" />'
        f'<input name="from_name" value="{from_name}" placeholder="From name" style="font-size:0.83rem;" />'
        f'<input name="reply_to_email" value="{reply_to}" placeholder="Reply-to (optional)" style="font-size:0.83rem;" />'
        f'<input name="inquiry_notify_email" type="email" value="{notify_email}" placeholder="Inquiry notification email" style="font-size:0.83rem;" />'
        f'<p style="font-size:0.72rem;color:var(--muted);margin:0;">Inquiry notifications are sent here.</p>'
        f'<input name="inbox_filter_to" type="email" value="{inbox_filter_to}" placeholder="Sales inbox filter — e.g. sales@bluebird-alerts.com" style="font-size:0.83rem;margin-top:4px;" />'
        f'<p style="font-size:0.72rem;color:var(--muted);margin:0;">Only sync emails addressed to this address. Leave blank to sync all.</p>'
        f'<hr style="margin:8px 0;border-color:var(--border);" />'
        f'<label style="font-size:0.78rem;">SendGrid API Key {sendgrid_hint}</label>'
        f'<input name="sendgrid_api_key" type="password" placeholder="Leave blank to keep existing" style="font-size:0.83rem;" />'
        f'<p style="font-size:0.72rem;color:var(--muted);margin:0;">Only needed if provider = SendGrid.</p>'
        f'<div class="button-row" style="margin-top:8px;">'
        f'<button class="button button-primary" type="submit" id="email-delivery-save-btn">Save Settings</button>'
        f'</div></form>'
        f'<div style="margin-top:12px;border-top:1px solid var(--border);padding-top:12px;">'
        f'<p style="font-size:0.78rem;font-weight:600;margin-bottom:8px;">Send Test Email</p>'
        f'<div style="display:flex;gap:8px;">'
        f'<input id="email-test-to" type="email" placeholder="Recipient address" style="flex:1;font-size:0.83rem;" />'
        f'<button class="button button-secondary" type="button" onclick="bbSendTestEmail()">Send Test</button>'
        f'</div>'
        f'<span id="email-test-result" style="font-size:0.75rem;margin-top:4px;display:block;"></span>'
        f'</div></div>'
        f'<div style="border:1px solid var(--border);border-radius:10px;padding:20px;margin-top:0;">'
        f'<h3 style="margin-bottom:12px;">Auto-Reply Template</h3>'
        f'<form id="auto-reply-form" method="post" action="/super-admin/email-delivery-settings/auto-reply" class="stack" style="gap:8px;">'
        f'<label style="display:flex;align-items:center;gap:8px;font-size:0.82rem;">'
        f'<input type="checkbox" name="auto_reply_enabled" value="1"{"  checked" if ar_enabled else ""} />'
        f'Enable auto-reply to submitters</label>'
        f'<input name="auto_reply_subject" value="{ar_subject}" placeholder="Subject" style="font-size:0.83rem;" />'
        f'<textarea name="auto_reply_body" rows="10" style="font-size:0.8rem;font-family:monospace;resize:vertical;"'
        f' placeholder="Body (use {{{{name}}}}, {{{{school_or_district}}}}, etc.)">{ar_body}</textarea>'
        f'<p style="font-size:0.72rem;color:var(--muted);">Variables: {{{{name}}}}, {{{{email}}}}, {{{{school_or_district}}}}, '
        f'{{{{estimated_students}}}}, {{{{number_of_schools}}}}</p>'
        f'<div class="button-row" style="margin-top:4px;">'
        f'<button class="button button-primary" type="submit">Save Auto-Reply</button>'
        f'<button class="button button-secondary" type="button" onclick="bbPreviewAutoReply()">Preview</button>'
        f'</div></form>'
        f'<div id="auto-reply-preview" style="display:none;margin-top:12px;padding:12px;'
        f'background:var(--card-bg, #f8faff);border:1px solid var(--border);border-radius:8px;">'
        f'<p style="font-size:0.78rem;font-weight:600;margin-bottom:4px;">Subject: <span id="preview-subject"></span></p>'
        f'<pre id="preview-body" style="font-size:0.78rem;white-space:pre-wrap;margin:0;"></pre>'
        f'</div></div></div></div>'
    )


def _render_stripe_section(
    stripe: object, plans: object, section: str = "configuration"
) -> str:
    def _sv(key: str, default: str = "") -> str:
        if isinstance(stripe, dict):
            return escape(str(stripe.get(key, default) or default))
        return escape(default)

    mode = _sv("mode", "test")
    pub_key = _sv("publishable_key")
    sk_set = _sv("secret_key_set") == "1"
    wh_set = _sv("webhook_secret_set") == "1"
    updated = _sv("updated_at")

    mode_opts = "".join(
        f'<option value="{m}"{" selected" if m == mode else ""}>{m.title()}</option>'
        for m in ("test", "live")
    )
    mode_badge = (
        f'<span class="status-pill {"ok" if mode == "live" else ""}" '
        f'style="font-size:0.68rem;">{mode.upper()}</span>'
    )

    plans_rows = ""
    for p in (plans or []):
        if not isinstance(p, dict):
            continue
        pt = escape(str(p.get("plan_type", "")))
        dn = escape(str(p.get("display_name", "")))
        pid_t = escape(str(p.get("stripe_price_id_test") or ""))
        pid_l = escape(str(p.get("stripe_price_id_live") or ""))
        ms = str(p.get("max_schools") or "")
        mu = str(p.get("max_users") or "")
        notes = escape(str(p.get("internal_notes") or ""))
        plans_rows += (
            f'<tr>'
            f'<td style="font-weight:600;">{pt}</td>'
            f'<td>{dn}</td>'
            f'<td style="font-family:monospace;font-size:0.72rem;">{pid_t or "—"}</td>'
            f'<td style="font-family:monospace;font-size:0.72rem;">{pid_l or "—"}</td>'
            f'<td style="text-align:center;">{ms or "—"}</td>'
            f'<td style="text-align:center;">{mu or "—"}</td>'
            f'<td style="font-size:0.72rem;color:var(--muted);">{notes}</td>'
            f'<td><button class="button button-secondary" type="button" style="font-size:0.72rem;padding:3px 8px;" '
            f'onclick="bbEditPlan({json.dumps(pt)},{json.dumps(dn)},{json.dumps(pid_t)},{json.dumps(pid_l)},{json.dumps(ms)},{json.dumps(mu)},{json.dumps(notes)})">Edit</button></td>'
            f'</tr>'
        )
    if not plans_rows:
        plans_rows = '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:12px;">No plans configured.</td></tr>'

    _sk_cls = "ok" if sk_set else "danger"
    _sk_lbl = "set" if sk_set else "missing"
    _wh_cls = "ok" if wh_set else ""
    _wh_lbl = "set" if wh_set else "not set"
    _updated_html = f'<p style="font-size:0.72rem;color:var(--muted);">Last updated: {updated[:10]}</p>' if updated else ''
    _sk_ph = "Secret key (stored — change to replace)" if sk_set else "Secret key (sk_...)"
    _wh_ph = "Webhook secret (stored — change to replace)" if wh_set else "Webhook signing secret (whsec_...)"

    return (
        f'<div id="stripe-billing-panel">'
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">'
        f'<h2 style="margin:0;">Stripe Billing</h2> {mode_badge}'
        f'<span class="status-pill {_sk_cls}" style="font-size:0.68rem;">Secret {_sk_lbl}</span>'
        f'<span class="status-pill {_wh_cls}" style="font-size:0.68rem;">Webhook {_wh_lbl}</span>'
        f'</div>'
        f'<p class="card-copy" style="margin-bottom:16px;">Stripe API credentials and subscription plan configuration. Secrets are encrypted at rest and never exposed.</p>'
        f'<div class="form-grid" style="gap:24px;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));margin-top:16px;">'
        f'<div style="border:1px solid var(--border);border-radius:10px;padding:20px;">'
        f'<h3 style="margin-bottom:12px;">API Credentials</h3>'
        f'<form id="stripe-settings-form" method="post" action="/super-admin/stripe-settings" class="stack" style="gap:8px;">'
        f'<label style="font-size:0.78rem;">Mode</label>'
        f'<select name="stripe_mode" style="margin-bottom:6px;">{mode_opts}</select>'
        f'<input name="publishable_key" value="{pub_key}" placeholder="Publishable key (pk_...)" style="font-size:0.83rem;" />'
        f'<input name="secret_key" type="password" placeholder="{_sk_ph}" style="font-size:0.83rem;" />'
        f'<input name="webhook_secret" type="password" placeholder="{_wh_ph}" style="font-size:0.83rem;" />'
        f'<p style="font-size:0.72rem;color:var(--muted);">Webhook URL: <code>/stripe/webhook</code></p>'
        f'{_updated_html}'
        f'<div class="button-row" style="margin-top:8px;">'
        f'<button class="button button-primary" type="submit">Save Settings</button>'
        f'<button class="button button-secondary" type="button" onclick="bbTestStripe()">Test Connection</button>'
        f'</div></form>'
        f'<span id="stripe-test-result" style="font-size:0.75rem;margin-top:8px;display:block;"></span>'
        f'</div>'
        f'<div style="border:1px solid var(--border);border-radius:10px;padding:20px;">'
        f'<h3 style="margin-bottom:12px;">Billing Plans</h3>'
        f'<p style="font-size:0.78rem;color:var(--muted);margin-bottom:12px;">Map plan types to Stripe price IDs. Never exposed publicly.</p>'
        f'<div style="overflow-x:auto;">'
        f'<table class="data-table" style="font-size:0.78rem;width:100%;">'
        f'<thead><tr><th>Plan</th><th>Label</th><th>Test Price ID</th><th>Live Price ID</th>'
        f'<th>Max Schools</th><th>Max Users</th><th>Notes</th><th></th></tr></thead>'
        f'<tbody id="billing-plans-tbody">{plans_rows}</tbody>'
        f'</table></div>'
        f'<div id="edit-plan-form-wrap" style="display:none;margin-top:12px;padding:12px;border:1px solid var(--border);border-radius:8px;">'
        f'<form id="edit-plan-form" method="post" action="/super-admin/stripe-settings/plans" class="stack" style="gap:6px;" onsubmit="event.preventDefault();bbSavePlan();">'
        f'<input id="ep-plan_type" name="plan_type" placeholder="plan_type (e.g. basic)" style="font-size:0.82rem;" />'
        f'<input id="ep-display_name" name="display_name" placeholder="Display name" style="font-size:0.82rem;" />'
        f'<input id="ep-test" name="stripe_price_id_test" placeholder="Test price ID" style="font-size:0.82rem;" />'
        f'<input id="ep-live" name="stripe_price_id_live" placeholder="Live price ID" style="font-size:0.82rem;" />'
        f'<input id="ep-ms" name="max_schools" type="number" placeholder="Max schools" style="font-size:0.82rem;" />'
        f'<input id="ep-mu" name="max_users" type="number" placeholder="Max users" style="font-size:0.82rem;" />'
        f'<input id="ep-notes" name="internal_notes" placeholder="Internal notes" style="font-size:0.82rem;" />'
        f'<div class="button-row">'
        f'<button class="button button-primary" type="submit">Save Plan</button>'
        f'<button class="button button-secondary" type="button" onclick="document.getElementById(\'edit-plan-form-wrap\').style.display=\'none\'">Cancel</button>'
        f'</div></form></div>'
        f'<button class="button button-secondary" type="button" style="margin-top:12px;font-size:0.78rem;" '
        f'onclick="bbEditPlan(\'\',\'\',\'\',\'\',\'\',\'\',\'\')">+ Add / Edit Plan</button>'
        f'</div></div>'
        f'</div>'
    )


def render_super_admin_page(
    *,
    base_domain: str,
    school_rows: Sequence[Mapping[str, object]],
    billing_rows: Sequence[Mapping[str, object]],
    district_billing_rows: Sequence[Mapping[str, object]] = (),
    archived_district_billing_rows: Sequence[Mapping[str, object]] = (),
    billing_audit_rows: Sequence[Mapping[str, object]] = (),
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
    health_status: Optional[HealthStatus] = None,
    health_heartbeats: Sequence[HeartbeatRecord] = (),
    email_log: Sequence[EmailLogRecord] = (),
    email_configured: bool = False,
    smtp_config: Optional[SMTPConfig] = None,
    gmail_settings: Optional[GmailSettings] = None,
    platform_admin_emails: Sequence[str] = (),
    email_template_keys: Sequence[str] = (),
    setup_codes: Sequence[Mapping[str, object]] = (),
    schools_by_slug: Mapping[str, object] = {},
    noc_tenant_data: Sequence[Mapping[str, object]] = (),
    noc_uptime_seconds: int = 0,
    msp_districts: Sequence[Mapping[str, object]] = (),
    platform_stats: Optional[Mapping[str, object]] = None,
    sandbox_data: Sequence[Mapping[str, object]] = (),
    prod_districts: Sequence[object] = (),
    inquiries: Sequence[object] = (),
    demo_requests: Sequence[object] = (),
    inbox_messages: Sequence[object] = (),
    inbox_unread_count: int = 0,
    customers: Sequence[object] = (),
    email_delivery_settings: Mapping[str, str] = {},
    auto_reply_settings: Mapping[str, str] = {},
    stripe_settings: Mapping[str, str] = {},
    billing_plans: Sequence[Mapping[str, object]] = (),
) -> str:
    _active_school_rows = [r for r in school_rows if not r.get("is_archived")]
    _archived_school_rows = [r for r in school_rows if r.get("is_archived")]
    active_school_cards_html = "".join(_tenant_registry_card(r) for r in _active_school_rows) or \
        '<p class="mini-copy" style="color:var(--muted);padding:24px 0;">No schools yet.</p>'
    archived_school_cards_html = "".join(_tenant_registry_archived_card(r) for r in _archived_school_rows)
    # Pre-compute archived section to avoid backslash-in-f-string-expression (Python <3.12 restriction)
    if _archived_school_rows:
        _n_arch = len(_archived_school_rows)
        _arch_onclick = (
            "var g=document.getElementById('schools-archived-grid');"
            "g.style.display=g.style.display==='none'?'grid':'none';"
            "this.textContent=g.style.display==='none'"
            "?'▶ Show archived (" + str(_n_arch) + ")'"
            ":'▼ Hide archived (" + str(_n_arch) + ")';"
        )
        _archived_schools_section_html = (
            '<div class="tenant-archived-section" id="archived-schools-section">'
            '<button class="tenant-archived-toggle" onclick="' + _arch_onclick + '" type="button">'
            "▶ Show archived (" + str(_n_arch) + ")"
            '</button>'
            '<div class="tenant-grid" id="schools-archived-grid" style="display:none;margin-top:16px;">'
            + archived_school_cards_html
            + '</div></div>'
        )
    else:
        _archived_schools_section_html = ""
    security_feedback = f"{_render_flash(flash_message, 'success')}{_render_flash(flash_error, 'error')}"

    def _ai_insights_row(r: Mapping[str, object]) -> str:
        s = escape(str(r.get("slug", "")))
        n = escape(str(r.get("name", "")))
        onclick_enabled = "bbAiToggle('" + s + "','enabled')"
        onclick_debug = "bbAiToggle('" + s + "','debug')"
        onclick_view = "bbAiViewInsights('" + s + "')"
        onclick_health = "bbAiViewHealth('" + s + "')"
        onclick_reports = "bbAiViewReports('" + s + "')"
        return (
            '<tr id="ai-row-' + s + '">'
            '<td>' + n + '</td>'
            '<td><code>' + s + '</code></td>'
            '<td>'
            '<button class="button button-secondary" style="font-size:0.8rem;padding:4px 10px;" '
            'onclick="' + onclick_enabled + '">Toggle ON/OFF</button>'
            '<span id="ai-enabled-' + s + '" style="margin-left:8px;font-size:0.8rem;color:var(--muted);">&mdash;</span>'
            '</td>'
            '<td id="ai-health-cell-' + s + '" style="white-space:nowrap;">'
            '<button class="button button-secondary" style="font-size:0.8rem;padding:4px 10px;" '
            'onclick="' + onclick_health + '">Load</button>'
            '</td>'
            '<td>'
            '<button class="button button-secondary" style="font-size:0.8rem;padding:4px 10px;" '
            'onclick="' + onclick_view + '">Insights</button>'
            ' <button class="button button-secondary" style="font-size:0.8rem;padding:4px 10px;" '
            'onclick="' + onclick_reports + '">Reports</button>'
            '</td>'
            '</tr>'
        )

    _ai_insights_tenant_rows_html = "".join(_ai_insights_row(r) for r in _active_school_rows) or \
        '<tr><td colspan="5" class="empty-state">No active schools.</td></tr>'

    def _ai_insights_debug_btn(r: Mapping[str, object]) -> str:
        s = escape(str(r.get("slug", "")))
        return (
            '<button class="button button-secondary" style="font-size:0.8rem;padding:4px 10px;" '
            'onclick="bbAiViewDebug(\'' + s + '\')">' + s + '</button>'
        )

    _ai_insights_debug_btns_html = "".join(_ai_insights_debug_btn(r) for r in _active_school_rows)
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
    ) or '<tr><td colspan="5" class="empty-state">No platform-super-admin activity recorded yet.</td></tr>'
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
    ) or '<tr><td colspan="8" class="empty-state">No tenant billing records yet.</td></tr>'

    _status_class_map = {"active": "ok", "used": "warn", "expired": "warn", "revoked": "danger"}
    setup_code_rows = "".join(
        (
            "<tr>"
            f"<td><code>{escape(str(getattr(c, 'code', '')))}</code></td>"
            f"<td>{escape(str(getattr(schools_by_slug.get(str(getattr(c, 'tenant_slug', '')), None), 'name', getattr(c, 'tenant_slug', ''))))}</td>"
            f"<td><code>{escape(str(getattr(c, 'tenant_slug', '')))}</code></td>"
            f"<td><span class=\"status-pill {_status_class_map.get(str(getattr(c, 'status', '')), 'warn')}\">{escape(str(getattr(c, 'status', '')))}</span></td>"
            f"<td>{escape(str(getattr(c, 'expires_at', ''))[:16])}</td>"
            f"<td>{int(getattr(c, 'use_count', 0))}/{int(getattr(c, 'max_uses', 1))}</td>"
            f"<td><form method=\"post\" action=\"/super-admin/setup-codes/{int(getattr(c, 'id', 0))}/revoke\""
            f" onsubmit=\"return confirm('Revoke setup code {escape(str(getattr(c, 'code', '')))}?');\"><button class=\"button button-danger-outline\" type=\"submit\">Revoke</button></form></td>"
            "</tr>"
        )
        for c in setup_codes
    ) or '<tr><td colspan="7" class="empty-state">No setup codes generated yet.</td></tr>'

    section = active_section if active_section in {"districts", "schools", "billing", "platform-audit", "create-school", "security", "configuration", "server-tools", "health", "email-tool", "setup-codes", "noc", "msp", "platform-control", "sandbox", "ai-insights", "inquiries", "demo-requests", "sales-inbox", "customers"} else "districts"

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
    # ── Health section computed vars ────────────────────────────────────────────
    _hs = health_status
    _hs_overall = _hs.overall if _hs else "unknown"
    _hs_pill_cls = {"ok": "ok", "degraded": "warn", "error": "danger"}.get(_hs_overall, "")
    _hs_uptime_24 = f"{_hs.uptime_24h:.1f}%" if (_hs and _hs.uptime_24h is not None) else "—"
    _hs_uptime_7d = f"{_hs.uptime_7d:.1f}%" if (_hs and _hs.uptime_7d is not None) else "—"
    _hs_last = escape(_hs.last_heartbeat_at[:19].replace("T", " ")) if (_hs and _hs.last_heartbeat_at) else "—"
    _hs_since_raw = _hs.seconds_since_heartbeat if _hs else None
    if _hs_since_raw is None:
        _hs_since = "—"
    elif _hs_since_raw < 120:
        _hs_since = f"{int(_hs_since_raw)}s ago"
    elif _hs_since_raw < 3600:
        _hs_since = f"{int(_hs_since_raw) // 60}m ago"
    else:
        _hs_since = f"{int(_hs_since_raw) // 3600}h ago"
    _hs_rtt = f"{_hs.response_time_ms:.0f} ms" if _hs else "—"
    _hs_db_cls = "ok" if (_hs and _hs.db_ok) else "danger"
    _hs_db_text = "OK" if (_hs and _hs.db_ok) else "Error"
    _hs_ws = str(_hs.ws_connections) if _hs else "0"
    _hs_apns = "Configured" if (_hs and _hs.apns_configured) else "Not set"
    _hs_fcm = "Configured" if (_hs and _hs.fcm_configured) else "Not set"
    _hs_error_html = (
        f'<div class="flash error" style="margin-bottom:16px;">{escape(_hs.error_note)}</div>'
        if (_hs and _hs.error_note) else ""
    )

    def _hb_pill(s: str) -> str:
        cls = {"ok": "ok", "degraded": "warn", "error": "danger"}.get(s, "")
        return f'<span class="status-pill {cls}">{escape(s)}</span>' if cls else f'<span class="status-pill">{escape(s)}</span>'

    _hb_rows_html = "".join(
        f"<tr>"
        f"<td class='mini-copy'>{escape(hb.timestamp[:19].replace('T', ' '))}</td>"
        f"<td>{_hb_pill(hb.status)}</td>"
        f"<td>{hb.response_time_ms:.0f} ms</td>"
        f"<td>{'✓' if hb.db_ok else '✗'}</td>"
        f"<td>{hb.ws_connections}</td>"
        f"<td>{'✓' if hb.apns_configured else '—'}</td>"
        f"<td>{'✓' if hb.fcm_configured else '—'}</td>"
        f"<td class='mini-copy'>{escape(hb.error_note or '')}</td>"
        f"</tr>"
        for hb in health_heartbeats
    ) or '<tr><td colspan="8" class="empty-state">No heartbeats recorded yet — monitor starts with the next background tick.</td></tr>'

    # ── Email tool computed vars ─────────────────────────────────────────────────
    _et_pill_cls = "ok" if email_configured else "danger"
    _et_status_text = "Configured" if email_configured else "Not configured"
    _et_admin_emails_html = (
        "".join(f'<span class="status-pill">{escape(e)}</span>' for e in platform_admin_emails)
        or '<span class="mini-copy">None — set <code>PLATFORM_ADMIN_EMAILS</code> (comma-separated)</span>'
    )
    _et_not_configured_html = (
        '<div class="flash error" style="margin-bottom:16px;">'
        'SMTP is not configured. Set <code>SMTP_HOST</code>, <code>SMTP_PORT</code>, '
        '<code>SMTP_FROM</code>, and optionally <code>SMTP_USERNAME</code> / '
        '<code>SMTP_PASSWORD</code> in the backend environment.</div>'
    ) if not email_configured else ""
    _et_template_options = "".join(
        f'<option value="{escape(k)}">{escape(k.replace("_", " ").title())}</option>'
        for k in email_template_keys
    )

    def _et_ok_pill(ok: bool) -> str:
        return '<span class="status-pill ok">Sent</span>' if ok else '<span class="status-pill danger">Failed</span>'

    _et_log_rows = "".join(
        f"<tr>"
        f"<td class='mini-copy'>{escape(rec.timestamp[:19].replace('T', ' '))}</td>"
        f"<td>{escape(rec.event_type)}</td>"
        f"<td>{escape(rec.to_address)}</td>"
        f"<td>{escape(rec.subject[:60])}</td>"
        f"<td>{_et_ok_pill(rec.ok)}</td>"
        f"<td class='mini-copy'>{escape(rec.error or '')}</td>"
        f"</tr>"
        for rec in email_log
    ) or '<tr><td colspan="6" class="empty-state">No emails sent yet.</td></tr>'
    _et_disabled = "disabled" if not email_configured else ""
    _smtp = smtp_config or SMTPConfig(host="", port=587, username="", from_address="", use_tls=True, password_set=False)
    _smtp_tls_checked = "checked" if _smtp.use_tls else ""
    _smtp_password_status = "Saved" if _smtp.password_set else "Not saved"
    _smtp_password_cls = "ok" if _smtp.password_set else "warn"
    _gmail = gmail_settings
    _gmail_address = escape(_gmail.gmail_address if _gmail else "")
    _gmail_from_name = escape(_gmail.from_name if _gmail else "BlueBird Alerts")
    _gmail_pw_status = "Saved" if (_gmail and _gmail.password_set) else "Not saved"
    _gmail_pw_cls = "ok" if (_gmail and _gmail.password_set) else "warn"
    _gmail_configured_pill = '<span class="status-pill ok">Configured</span>' if (_gmail and _gmail.configured) else '<span class="status-pill warn">Not configured</span>'
    _gmail_updated = escape(_gmail.updated_at[:16].replace("T", " ") + " UTC" if (_gmail and _gmail.updated_at) else "Never")
    _gmail_updated_by = escape(_gmail.updated_by or "—" if _gmail else "—")

    # ── NOC computed vars ────────────────────────────────────────────────────────
    _noc_hs = health_status
    _noc_overall = _noc_hs.overall if _noc_hs else "unknown"
    _noc_pill_cls = {"ok": "ok", "degraded": "warn", "error": "danger"}.get(_noc_overall, "")
    _noc_label = {"ok": "Healthy", "degraded": "Degraded", "error": "Down"}.get(_noc_overall, "Unknown")
    _noc_api_cls = "ok" if _noc_hs and _noc_hs.overall != "error" else "danger"
    _noc_db_cls = "ok" if (_noc_hs and _noc_hs.db_ok) else "danger"
    _noc_db_text = "OK" if (_noc_hs and _noc_hs.db_ok) else "Error"
    _noc_ws = str(_noc_hs.ws_connections if _noc_hs else 0)
    _noc_tenant_count = str(len(noc_tenant_data))
    _noc_has_alarm = any(bool(t.get("alarm_active")) for t in noc_tenant_data)

    def _fmt_uptime(sec: int) -> str:
        if sec <= 0:
            return "—"
        d, rem = divmod(sec, 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        if d > 0:
            return f"{d}d {h}h"
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m"

    _noc_uptime_str = _fmt_uptime(noc_uptime_seconds)

    def _noc_tenant_card(t: Mapping[str, object]) -> str:
        slug = escape(str(t.get("slug", "")))
        name = escape(str(t.get("name", slug)))
        is_alarm = bool(t.get("alarm_active"))
        card_mod = "school-card--alarm" if is_alarm else "school-card--ok"
        status_pill = "danger" if is_alarm else "ok"
        status_text = "Alarm Active" if is_alarm else "Normal"
        ws = int(t.get("ws_connections") or 0)
        last_at_raw = str(t.get("last_alert_at") or "")
        last_at = last_at_raw[:16].replace("T", " ") + " UTC" if last_at_raw else "No alerts"
        ack_count = int(t.get("ack_count") or 0)
        user_count = int(t.get("user_count") or 0)
        ack_html = f'<div class="school-card-message">{ack_count}/{user_count} acknowledged</div>' if is_alarm and user_count > 0 else ""
        alarm_msg_raw = str(t.get("alarm_message") or "")
        alarm_msg_html = f'<p class="school-card-message">{escape(alarm_msg_raw[:60])}</p>' if alarm_msg_raw else ""
        return (
            f'<div class="school-card {card_mod}" onclick="window.location=\'/super-admin?section=schools\'">'
            f'<div class="school-card-header">'
            f'<span class="school-card-name">{name}</span>'
            f'<span class="status-pill {status_pill}" style="font-size:0.7rem;padding:2px 8px;">{status_text}</span>'
            f'</div>'
            f'{alarm_msg_html}'
            f'<div class="school-card-footer">'
            f'<span class="school-card-last">WS: {ws} &nbsp;·&nbsp; {escape(last_at)}</span>'
            f'</div>'
            f'{ack_html}'
            f'</div>'
        )

    _noc_tenant_cards_html = "".join(_noc_tenant_card(t) for t in noc_tenant_data) or \
        '<p class="mini-copy" style="padding:16px 0;">No tenants provisioned yet.</p>'

    _noc_alarm_banner_html = (
        f'<div class="flash error" id="noc-alarm-banner" style="margin-bottom:16px;">'
        f'🔴 ALARM ACTIVE in: {escape(", ".join(str(t.get("name","")) for t in noc_tenant_data if t.get("alarm_active")))}'
        f'</div>'
    ) if _noc_has_alarm else '<div id="noc-alarm-banner" style="display:none;"></div>'

    _noc_sys_banner_html = (
        f'<div class="flash error" id="noc-sys-banner" style="margin-bottom:16px;">'
        f'⚠ System status: {escape(_noc_label)}'
        + (f' — {escape(_noc_hs.error_note)}' if _noc_hs and _noc_hs.error_note else "")
        + '</div>'
    ) if _noc_hs and _noc_overall in ("error", "degraded") else \
        '<div id="noc-sys-banner" style="display:none;"></div>'

    # ── MSP computed vars ─────────────────────────────────────────────────────
    _msp_alarm_districts = [d for d in msp_districts if str(d.get("status", "")) == "alarm"]
    _msp_has_alarm = bool(_msp_alarm_districts)

    _MSP_STATUS_COLORS = {"alarm": "#ef4444", "healthy": "#22c55e", "empty": "#94a3b8", "offline": "#64748b"}
    _MSP_STATUS_LABELS = {"alarm": "Alarm Active", "healthy": "Healthy", "empty": "No Schools", "offline": "Offline"}
    _MSP_STATUS_PILL   = {"alarm": "danger", "healthy": "ok", "empty": "", "offline": ""}

    def _msp_customer_card(d: Mapping[str, object]) -> str:
        slug = escape(str(d.get("slug", "")))
        name = escape(str(d.get("name", slug)))
        status = str(d.get("status", "healthy"))
        pill_cls = _MSP_STATUS_PILL.get(status, "")
        pill_label = _MSP_STATUS_LABELS.get(status, status.title())
        school_count = int(d.get("school_count") or 0)
        alarm_count = int(d.get("alarm_count") or 0)
        ws = int(d.get("ws_total") or 0)
        last_raw = str(d.get("last_activity") or "")
        last_fmt = last_raw[:16].replace("T", " ") + " UTC" if last_raw else "No alerts"
        is_district = bool(d.get("is_district"))
        billing_ok = bool(d.get("billing_ok", True))
        type_tag = "District" if is_district else "School"
        border_color = _MSP_STATUS_COLORS.get(status, "#94a3b8")
        push_failed = int(d.get("push_failed_total") or 0)
        alarm_badge = f'<span style="color:#ef4444;font-size:0.75rem;font-weight:600;">⚠ {alarm_count} alarm</span>' if alarm_count > 0 else ""
        push_fail_badge = f'<span class="msp-push-fail" data-count="{push_failed}" style="color:#f97316;font-size:0.75rem;font-weight:600;margin-left:6px;">✗ {push_failed} push</span>' if push_failed > 0 else f'<span class="msp-push-fail" data-count="0" style="display:none;"></span>'
        billing_badge = "" if billing_ok else '<span style="color:#f59e0b;font-size:0.75rem;font-weight:600;margin-left:6px;">Billing</span>'
        return (
            f'<div class="msp-card" data-slug="{slug}" data-status="{escape(status)}" data-name="{name}" data-push-failed="{push_failed}" '
            f'style="border-left:4px solid {border_color};">'
            f'<div class="msp-card-header">'
            f'<div>'
            f'<span class="msp-card-type">{type_tag}</span>'
            f'<h3 class="msp-card-name">{name}</h3>'
            f'</div>'
            f'<span class="status-pill {pill_cls}" style="font-size:0.7rem;padding:2px 10px;white-space:nowrap;">{pill_label}</span>'
            f'</div>'
            f'<div class="msp-card-meta">'
            f'<span>{school_count} school{"s" if school_count != 1 else ""}</span>'
            f'<span>WS: {ws}</span>'
            f'<span style="color:var(--text-muted);font-size:0.75rem;">{escape(last_fmt)}</span>'
            f'</div>'
            f'<div class="msp-card-badges">{alarm_badge}{push_fail_badge}{billing_badge}</div>'
            f'<div class="msp-card-actions">'
            f'<button class="button button-secondary" style="font-size:0.78rem;padding:4px 12px;" '
            f'onclick="mspOpenDetail(\'{slug}\')" type="button">Details</button>'
            f'</div>'
            f'</div>'
        )

    _msp_cards_html = "".join(_msp_customer_card(d) for d in msp_districts) or \
        '<p class="mini-copy" style="padding:24px 0;">No districts or schools configured yet.</p>'

    def _msp_severity_level(d: Mapping[str, object]) -> int:
        if str(d.get("status", "")) == "alarm":
            return 0
        if int(d.get("push_failed_total") or 0) > 0:
            return 1
        if not bool(d.get("billing_ok", True)):
            return 2
        return 99

    _msp_priority_items = [d for d in msp_districts if _msp_severity_level(d) < 99]
    _msp_priority_items = sorted(_msp_priority_items, key=lambda d: (_msp_severity_level(d), str(d.get("name", ""))))

    _msp_global_alerts_html = ""
    if _msp_priority_items:
        def _priority_row(d: Mapping[str, object]) -> str:
            level = _msp_severity_level(d)
            _slug = escape(str(d.get("slug", "")))
            _name = escape(str(d.get("name", "")))
            if level == 0:
                sev_html = '<span class="status-pill danger" style="font-size:0.7rem;white-space:nowrap;">🔴 Alarm</span>'
                detail = f'{int(d.get("alarm_count") or 0)} school{"s" if int(d.get("alarm_count") or 0) != 1 else ""} in alarm'
            elif level == 1:
                sev_html = '<span class="status-pill warn" style="font-size:0.7rem;white-space:nowrap;">⚠ Push Failures</span>'
                detail = f'{int(d.get("push_failed_total") or 0)} failed deliveries on last alert'
            else:
                sev_html = '<span class="status-pill warn" style="font-size:0.7rem;white-space:nowrap;">Billing</span>'
                detail = 'Billing issue — verify subscription'
            return (
                f'<tr>'
                f'<td style="padding:6px 8px;">{sev_html}</td>'
                f'<td style="padding:6px 8px;font-weight:600;">{_name}</td>'
                f'<td style="padding:6px 8px;font-size:0.8rem;color:var(--muted);">{escape(detail)}</td>'
                f'<td style="padding:6px 8px;">'
                f'<button class="button button-secondary" style="font-size:0.73rem;padding:3px 10px;" '
                f'onclick="mspOpenDetail(\'{_slug}\')" type="button">View</button>'
                f'</td>'
                f'</tr>'
            )
        _priority_rows_html = "".join(_priority_row(d) for d in _msp_priority_items)
        _has_alarm_str = "🔴 ALARM: " + ", ".join(str(d.get("name","")) for d in _msp_alarm_districts) if _msp_has_alarm else ""
        _alarm_strip_html = (
            f'<div class="flash error" id="msp-alarm-strip" style="margin-bottom:8px;">{escape(_has_alarm_str)}</div>'
            if _msp_has_alarm else
            '<div id="msp-alarm-strip" style="display:none;"></div>'
        )
        _msp_global_alerts_html = (
            _alarm_strip_html +
            f'<div style="background:rgba(239,68,68,0.04);border:1px solid rgba(239,68,68,0.18);'
            f'border-radius:10px;overflow:hidden;margin-bottom:16px;" id="msp-priority-table">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;'
            f'border-bottom:1px solid rgba(239,68,68,0.15);background:rgba(239,68,68,0.06);">'
            f'<span style="font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.07em;color:#b91c1c;">Alert Queue</span>'
            f'<span style="font-size:0.7rem;color:var(--muted);">{len(_msp_priority_items)} issue{"s" if len(_msp_priority_items) != 1 else ""}</span>'
            f'</div>'
            f'<table style="width:100%;border-collapse:collapse;"><tbody>{_priority_rows_html}</tbody></table>'
            f'</div>'
        )
    else:
        _msp_global_alerts_html = '<div id="msp-alarm-strip" style="display:none;"></div>'

    _pctrl_styles = """
          .pctrl-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:18px;margin-bottom:28px;}
          .pctrl-card{background:var(--card,#fff);border:1px solid var(--border);border-radius:14px;padding:22px 20px;position:relative;overflow:hidden;}
          .pctrl-card-hdr{font-size:.72rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:12px;}
          .pctrl-kpi{font-size:2.4rem;font-weight:800;line-height:1;margin:0 0 4px;}
          .pctrl-sub{font-size:.78rem;color:var(--muted);}
          .pctrl-pill{display:inline-block;padding:2px 8px;border-radius:99px;font-size:.72rem;font-weight:700;background:var(--border);}
          .pctrl-pill.ok{background:#dcfce7;color:#15803d;}
          .pctrl-pill.warn{background:#fef9c3;color:#854d0e;}
          .pctrl-pill.danger{background:#fee2e2;color:#b91c1c;}
          """

    # ── Districts dashboard card helpers ─────────────────────────────────────

    def _billing_status_pill(bstatus: str) -> str:
        cls = "ok" if bstatus in {"active", "trial", "free"} else "danger"
        return f'<span class="status-pill {cls}" style="font-size:0.7rem;padding:2px 8px;">{escape(bstatus)}</span>'

    def _district_card(d: Mapping[str, object], bills: Sequence[Mapping[str, object]]) -> str:
        did = int(d.get("id") or 0)
        raw_name = str(d.get("name", ""))
        name = escape(raw_name)
        slug_raw = str(d.get("slug", ""))
        slug = escape(slug_raw)
        school_count = int(d.get("school_count") or 0)
        is_district = bool(d.get("is_district"))
        dstatus = str(d.get("status", "healthy"))
        status_pill_cls = {"alarm": "danger", "healthy": "ok", "empty": "", "offline": ""}.get(dstatus, "")
        status_label = {"alarm": "Alarm Active", "healthy": "Healthy", "empty": "No Schools", "offline": "Offline"}.get(dstatus, dstatus.title())
        schools_list = d.get("schools", [])

        # Look up district-level license from district_billing_rows (closure)
        d_lic = next((b for b in district_billing_rows if str(b.get("slug", "")) == slug_raw), None)

        # District license status metadata + manage license expand
        lic_meta_html = ""
        manage_license_details = ""
        if d_lic:
            lic_eff = str(d_lic.get("effective_status", d_lic.get("billing_status", "trial")))
            lic_plan = escape(str(d_lic.get("plan_type", "trial")))
            lic_days = d_lic.get("days_remaining")
            lic_override = bool(d_lic.get("override_enabled"))
            lic_pill_cls = "ok" if lic_eff in {"active", "trial", "free", "manual_override"} else "danger"

            days_str = ""
            if lic_days is not None:
                if int(lic_days) < 0:
                    days_str = "Exp " + str(abs(int(lic_days))) + "d ago"
                else:
                    days_str = str(int(lic_days)) + "d left"
            days_color = "#dc2626" if (lic_days is not None and int(lic_days) < 0) else ("#d97706" if (lic_days is not None and int(lic_days) <= 7) else "#059669")
            days_html = f'<span style="font-size:0.72rem;color:{days_color};font-weight:600;">{escape(days_str)}</span>' if days_str else ""
            override_html = '<span class="status-pill ok" style="font-size:0.68rem;">Override</span>' if lic_override else ""

            lic_meta_html = (
                f'<span><span class="status-pill {lic_pill_cls}" style="font-size:0.68rem;">{escape(lic_eff)}</span></span>'
                f'<span style="font-size:0.78rem;color:var(--muted);">{lic_plan} plan</span>'
                f'{days_html}'
                f'{override_html}'
            )

            plan_opts = "".join(f'<option value="{p}">{p.title()}</option>' for p in ("trial", "basic", "pro", "enterprise"))
            status_opts = "".join(
                f'<option value="{s}">{s.replace("_", " ").title()}</option>'
                for s in ("trial", "active", "past_due", "expired", "suspended", "cancelled", "manual_override")
            )
            gen_lic = escape(str(d_lic.get("generate_license_action", "/super-admin/districts/" + slug_raw + "/billing/generate-license")))
            set_status_url = escape(str(d_lic.get("set_status_action", "/super-admin/districts/" + slug_raw + "/billing/set-status")))
            set_plan_url = escape(str(d_lic.get("set_plan_action", "/super-admin/districts/" + slug_raw + "/billing/set-plan")))
            tog_ov = escape(str(d_lic.get("toggle_override_action", "/super-admin/districts/" + slug_raw + "/billing/toggle-override")))
            start_trial_url = escape(str(d_lic.get("start_trial_action", "/super-admin/districts/" + slug_raw + "/billing/start-trial")))
            override_reason = escape(str(d_lic.get("override_reason", "") or ""))
            try:
                from datetime import date as _date
                today = str(_date.today())
            except Exception:
                today = ""
            override_btn_cls = "button-danger-outline" if lic_override else "button-primary"
            override_btn_lbl = "Disable Override" if lic_override else "Enable Override"
            manage_license_details = (
                f'<details class="district-billing-expand" data-district-slug="{slug}">'
                f'<summary>Manage District License</summary>'
                f'<div class="district-billing-form" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px;">'
                f'<div style="padding:10px;background:var(--card);border:1px solid var(--border);border-radius:8px;">'
                f'<p style="font-size:0.73rem;font-weight:600;margin-bottom:6px;">Generate / Renew</p>'
                f'<form method="post" action="{gen_lic}" class="stack" style="gap:5px;">'
                f'<select name="plan_type" style="width:100%;font-size:0.78rem;">{plan_opts}</select>'
                f'<input name="starts_at" type="date" value="{today}" style="font-size:0.78rem;" />'
                f'<input name="current_period_end" type="date" placeholder="Period end" style="font-size:0.78rem;" />'
                f'<input name="customer_name" placeholder="Customer name" style="font-size:0.78rem;" />'
                f'<input name="customer_email" type="email" placeholder="Email" style="font-size:0.78rem;" />'
                f'<button class="button button-primary" type="submit" style="font-size:0.73rem;">Generate License</button>'
                f'</form></div>'
                f'<div style="padding:10px;background:var(--card);border:1px solid var(--border);border-radius:8px;">'
                f'<p style="font-size:0.73rem;font-weight:600;margin-bottom:6px;">Status / Plan</p>'
                f'<form method="post" action="{set_status_url}" style="display:flex;gap:4px;margin-bottom:8px;">'
                f'<select name="new_status" style="flex:1;font-size:0.78rem;">{status_opts}</select>'
                f'<button class="button button-secondary" type="submit" style="font-size:0.73rem;">Set</button>'
                f'</form>'
                f'<form method="post" action="{set_plan_url}" style="display:flex;gap:4px;">'
                f'<select name="plan_type" style="flex:1;font-size:0.78rem;">{plan_opts}</select>'
                f'<button class="button button-secondary" type="submit" style="font-size:0.73rem;">Set</button>'
                f'</form>'
                f'<p style="font-size:0.73rem;font-weight:600;margin:10px 0 6px;">Trial</p>'
                f'<form method="post" action="{start_trial_url}" style="display:flex;gap:4px;">'
                f'<input name="duration_days" type="number" min="1" max="365" value="14" style="max-width:70px;font-size:0.78rem;" />'
                f'<button class="button button-secondary" type="submit" style="font-size:0.73rem;">Start Trial</button>'
                f'</form></div>'
                f'<div style="padding:10px;background:var(--card);border:1px solid var(--border);border-radius:8px;">'
                f'<p style="font-size:0.73rem;font-weight:600;margin-bottom:6px;">Override</p>'
                f'<form method="post" action="{tog_ov}" class="stack" style="gap:5px;">'
                f'<input name="override_reason" placeholder="Reason" value="{override_reason}" style="font-size:0.78rem;" />'
                f'<button class="button {override_btn_cls}" type="submit" style="font-size:0.73rem;" data-override-btn>{override_btn_lbl}</button>'
                f'</form></div>'
                f'</div></details>'
            )
        elif is_district:
            gen_lic_url = escape(f"/super-admin/districts/{slug_raw}/billing/generate-license")
            plan_opts_nl = "".join(f'<option value="{p}">{p.title()}</option>' for p in ("trial", "basic", "pro", "enterprise"))
            try:
                from datetime import date as _date2
                today_nl = str(_date2.today())
            except Exception:
                today_nl = ""
            manage_license_details = (
                f'<details class="district-billing-expand" data-district-slug="{slug}">'
                f'<summary>Manage District License</summary>'
                f'<div class="district-billing-form" style="padding:8px 0;">'
                f'<p style="font-size:0.78rem;color:var(--muted);margin-bottom:10px;">No license yet. Generate one to activate district billing.</p>'
                f'<form method="post" action="{gen_lic_url}" class="stack" style="gap:5px;max-width:280px;">'
                f'<select name="plan_type" style="font-size:0.78rem;">{plan_opts_nl}</select>'
                f'<input name="starts_at" type="date" value="{today_nl}" style="font-size:0.78rem;" />'
                f'<input name="current_period_end" type="date" placeholder="Period end (optional)" style="font-size:0.78rem;" />'
                f'<input name="customer_name" placeholder="Customer name" style="font-size:0.78rem;" />'
                f'<input name="customer_email" type="email" placeholder="Email" style="font-size:0.78rem;" />'
                f'<button class="button button-primary" type="submit" style="font-size:0.73rem;">Generate License</button>'
                f'</form>'
                f'</div></details>'
            )

        # School enter buttons
        enter_buttons = ""
        for s in (schools_list if isinstance(schools_list, list) else [])[:3]:
            s_slug = escape(str(s.get("slug", "")))
            s_name = escape(str(s.get("name", "")))
            enter_buttons += (
                f'<form method="post" action="/super-admin/schools/{s_slug}/enter" style="margin:0;">'
                f'<button class="button button-primary" type="submit" style="font-size:0.75rem;padding:5px 12px;">Enter {s_name}</button>'
                f'</form>'
            )

        # Edit + Manage Schools buttons (districts only)
        edit_btn = ""
        manage_schools_btn = ""
        if did and is_district:
            js_slug = json.dumps(slug_raw)
            js_name = json.dumps(raw_name)
            js_did  = str(did)
            edit_btn = (
                f'<button class="button button-secondary" type="button"'
                f' style="font-size:0.75rem;padding:5px 12px;"'
                f' onclick="bbOpenEditDistrictModal({js_slug},{js_name})">'
                f'Edit</button>'
            )
            manage_schools_btn = (
                f'<button class="button button-secondary" type="button"'
                f' style="font-size:0.75rem;padding:5px 12px;"'
                f' onclick="bbOpenManageSchoolsModal({js_slug},{js_name},{js_did})">'
                f'Manage Schools</button>'
            )

        # Archive button (only for real districts with an id)
        archive_btn = ""
        if did and is_district:
            archive_cfg = (
                "{{title:'Archive district?',"
                "body:'Archiving <strong>" + str(name) + "</strong> disables all its schools and moves it to the archived list. Schools and data are preserved.',"
                "consequence:'Staff at member schools will lose admin console access until this district is restored.',"
                "confirmLabel:'Archive district',danger:true}}"
            )
            archive_btn = (
                f'<form method="post" action="/super-admin/districts/{did}/archive"'
                f' onsubmit="bbConfirmSubmit(this,{archive_cfg});return false;" style="margin:0;">'
                f'<button class="button button-danger-outline" type="submit" style="font-size:0.75rem;padding:5px 12px;">Archive</button>'
                f'</form>'
            )

        # License action button — "Generate License" if no license, inline "Licensing ↓" expand otherwise
        license_btn = ""
        if did and is_district:
            if not d_lic:
                js_slug2 = json.dumps(slug_raw)
                js_name2 = json.dumps(raw_name)
                license_btn = (
                    f'<button class="button button-primary" type="button"'
                    f' style="font-size:0.75rem;padding:5px 12px;"'
                    f' onclick="bbOpenGenLicenseModal({js_slug2},{js_name2})">+ Generate License</button>'
                )

        school_label = "schools" if school_count != 1 else "school"
        district_or_school = "District" if is_district else "School"
        return (
            f'<div class="district-card" data-district-slug="{slug}">'
            f'<div class="district-card-header">'
            f'<div>'
            f'<p class="district-card-name">{name}</p>'
            f'<p class="district-card-slug">{slug} &nbsp;·&nbsp; {district_or_school}</p>'
            f'</div>'
            f'<span class="status-pill {status_pill_cls}" style="font-size:0.7rem;padding:2px 10px;white-space:nowrap;">{status_label}</span>'
            f'</div>'
            f'<div class="district-card-meta">'
            f'<span><strong>{school_count}</strong> {school_label}</span>'
            f'<span data-billing-meta style="display:contents;">{lic_meta_html}</span>'
            f'</div>'
            f'<div class="district-card-actions">'
            f'{edit_btn}'
            f'{manage_schools_btn}'
            f'{license_btn}'
            f'{enter_buttons}'
            f'{archive_btn}'
            f'</div>'
            f'{manage_license_details}'
            f'</div>'
        )

    # Build cards for active (non-archived) districts only
    _active_msp = [d for d in msp_districts if not bool(d.get("is_archived"))]
    _district_cards_html = "".join(_district_card(d, billing_rows) for d in _active_msp) or \
        '<p class="card-copy">No districts or schools provisioned yet. Use <strong>Create School</strong> to get started.</p>'

    # School data for manage-schools JS modal (slug, name, district_id from msp_districts)
    _bb_schools_js: str = json.dumps(
        [
            {"slug": str(s.get("slug", "")), "name": str(s.get("name", "")), "district_id": int(d.get("id") or 0)}
            for d in msp_districts if d.get("is_district") and not d.get("is_archived")
            for s in (d.get("schools") or [])
        ] + [
            {"slug": str(d.get("slug", "")), "name": str(d.get("name", "")), "district_id": None}
            for d in msp_districts if not d.get("is_district") and not d.get("is_archived")
        ]
    )

    # Build archived section
    _archived_districts = [d for d in msp_districts if bool(d.get("is_archived")) and bool(d.get("is_district"))]

    def _archived_card(d: Mapping[str, object]) -> str:
        did = int(d.get("id") or 0)
        name = escape(str(d.get("name", "")))
        slug = escape(str(d.get("slug", "")))
        school_count = int(d.get("school_count") or 0)
        archived_at_raw = str(d.get("archived_at", "") or "")
        archived_at_fmt = archived_at_raw[:10] if archived_at_raw else "unknown date"
        raw_name_js = str(d.get("name", ""))
        return (
            f'<div class="archived-card">'
            f'<p class="archived-card-name">{name}</p>'
            f'<p class="archived-card-meta">{slug} &nbsp;·&nbsp; {school_count} school{"s" if school_count != 1 else ""} &nbsp;·&nbsp; Archived {escape(archived_at_fmt)}</p>'
            f'<form method="post" action="/super-admin/districts/{did}/purge"'
            f' onsubmit="return bbConfirmPurge(this, {json.dumps(raw_name_js)});">'
            f'<div class="purge-confirm-row">'
            f'<input class="purge-confirm-input" name="confirm_name" placeholder="Type \'{name}\' to confirm" />'
            f'<button class="button button-danger" type="submit" style="font-size:0.75rem;padding:5px 14px;">Purge Forever</button>'
            f'</div>'
            f'<p class="mini-copy" style="margin-top:4px;color:#dc2626;">This permanently deletes all schools, users, alerts, and data.</p>'
            f'</form>'
            f'</div>'
        )

    if _archived_districts:
        _archived_section_html = (
            f'<div class="archived-section">'
            f'<p class="archived-section-title">Archived Districts</p>'
            f'<div class="archived-grid">'
            + "".join(_archived_card(d) for d in _archived_districts)
            + f'</div></div>'
        )
    else:
        _archived_section_html = ""

    # License summary for global header badge
    _all_billing = list(district_billing_rows) + list(archived_district_billing_rows)
    _lic_active = sum(1 for r in district_billing_rows if str(r.get("effective_status", "trial")) in {"active", "manual_override"})
    _lic_expired = sum(1 for r in district_billing_rows if str(r.get("effective_status", "trial")) in {"expired", "cancelled", "suspended"})
    _lic_archived = len(archived_district_billing_rows)
    _license_summary: dict[str, object] = {
        "total": len(district_billing_rows),
        "active": _lic_active,
        "expired": _lic_expired,
        "archived": _lic_archived,
    }

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
  <div class="app-shell">
    {_super_admin_header_html(license_summary=_license_summary)}
    <aside class="sidebar nav-panel">
      <section class="signal-card">
        <div class="nav-group">
          <p class="nav-label">Control</p>
          <nav class="nav-list">
            {_nav_item("platform-control", "Platform Control")}
            {_nav_item("msp", "MSP Dashboard", "!" if any(str(d.get("status","")) == "alarm" for d in msp_districts) else (str(len(msp_districts)) if msp_districts else None))}
            {_nav_item("noc", "Operations", "!" if (health_status and health_status.overall != "ok") or any(bool(t.get("alarm_active")) for t in noc_tenant_data) else None)}
            {_nav_item("districts", "Districts", str(len(msp_districts)) if msp_districts else None)}
            {_nav_item("billing", "Licensing")}
            {_nav_item("create-school", "Create School")}
            {_nav_item("platform-audit", "Platform Audit")}
            {_nav_item("health", "System Health", None if (not health_status or health_status.overall == 'ok') else "!")}
            {_nav_item("email-tool", "Email Tool")}
            {_nav_item("sales-inbox", "Sales Inbox", str(inbox_unread_count) if inbox_unread_count else None)}
            {_nav_item("inquiries", "Inquiries")}
            {_nav_item("demo-requests", "Demo Requests", str(sum(1 for dr in demo_requests if getattr(dr, "status", "") == "new")) if any(getattr(dr, "status", "") == "new" for dr in demo_requests) else None)}
            {_nav_item("customers", "Customers")}
            {_nav_item("configuration", "Configuration", None if email_configured else "!")}
            {_nav_item("setup-codes", "Setup Codes")}
            {_nav_item("security", "Security")}
            {_nav_item("server-tools", "Server Tools")}
            {_nav_item("sandbox", "Sandbox")}
            {_nav_item("ai-insights", "🧠 AI Insights")}
            <a class="nav-item" href="/super-admin/change-password">Change password</a>
          </nav>
        </div>
      </section>
    </aside>
      <section class="content-stack workspace">
        <section class="panel command-section" id="platform-control"{_section_style("platform-control")}>
          <style>{_pctrl_styles}</style>
          <div class="panel-header hero-band">
            <div>
              <p class="eyebrow">Super Admin</p>
              <h1>Platform Control</h1>
              <p class="hero-copy">SaaS-level visibility across all tenants — system status and coverage metrics.</p>
            </div>
          </div>

          <div class="pctrl-grid">
            <div class="pctrl-card">
              <p class="pctrl-card-hdr">Active Schools</p>
              <p class="pctrl-kpi">{int((platform_stats or {}).get("active_schools", 0))}</p>
              <p class="pctrl-sub">{int((platform_stats or {}).get("total_schools", 0))} total provisioned tenants</p>
            </div>
            <div class="pctrl-card">
              <p class="pctrl-card-hdr">Live Connections</p>
              <p class="pctrl-kpi">{int((platform_stats or {}).get("ws_connections", 0))}</p>
              <p class="pctrl-sub">{int((platform_stats or {}).get("alarm_schools", 0))} school{'s' if int((platform_stats or {}).get("alarm_schools", 0)) != 1 else ''} with active alarm</p>
            </div>
          </div>

          <p class="eyebrow" style="margin-bottom:12px;margin-top:4px;">System Health</p>
          <div class="pctrl-grid">
            <div class="pctrl-card">
              <p class="pctrl-card-hdr">API Status</p>
              <p class="pctrl-kpi" style="font-size:1.6rem;">{"OK" if health_status and health_status.overall == "ok" else "Degraded"}</p>
              <p class="pctrl-sub"><span class="pctrl-pill {"ok" if health_status and health_status.overall == "ok" else "danger"}">{"healthy" if health_status and health_status.overall == "ok" else health_status.overall if health_status else "unknown"}</span></p>
            </div>
            <div class="pctrl-card">
              <p class="pctrl-card-hdr">Email Service</p>
              <p class="pctrl-kpi" style="font-size:1.6rem;">{"Active" if email_configured else "Off"}</p>
              <p class="pctrl-sub"><span class="pctrl-pill {"ok" if email_configured else "warn"}">{"configured" if email_configured else "not configured"}</span></p>
            </div>
          </div>

          <p class="eyebrow" style="margin-bottom:12px;margin-top:20px;">Quick Actions</p>
          <div class="pctrl-grid">
            <div class="pctrl-card">
              <p class="pctrl-card-hdr">Manage Licenses</p>
              <p class="pctrl-sub">District &amp; school license management, plan changes, and override controls.</p>
              <p style="margin-top:10px;"><a class="button button-secondary" href="/super-admin?section=billing#billing" style="font-size:0.78rem;padding:5px 14px;">Open Licensing &rarr;</a></p>
            </div>
            <div class="pctrl-card">
              <p class="pctrl-card-hdr">Districts &amp; Schools</p>
              <p class="pctrl-sub">View all districts, school health, and enrollment counts.</p>
              <p style="margin-top:10px;"><a class="button button-secondary" href="/super-admin?section=districts#districts" style="font-size:0.78rem;padding:5px 14px;">Open Districts &rarr;</a></p>
            </div>
          </div>

        </section>

        <section class="panel command-section" id="msp"{_section_style("msp")}>
          <div class="panel-header hero-band">
            <div>
              <p class="eyebrow">Service Provider</p>
              <h1>MSP Dashboard</h1>
              <p class="hero-copy">Customer operations: district &amp; school health, active incidents, push delivery, and operator notes — all in one view.</p>
            </div>
            <div class="status-row">
              <span class="status-pill {'danger' if _msp_has_alarm else 'ok'}" id="msp-overall-pill">{'⚠ Alarm Active' if _msp_has_alarm else 'All Healthy'}</span>
              <span class="status-pill" style="font-size:0.75rem;" id="msp-last-refresh">Live</span>
            </div>
          </div>
          {_msp_global_alerts_html}
          <div class="msp-search-bar">
            <input type="search" id="msp-search" placeholder="Search customers, districts, schools…" oninput="mspFilter(this.value)" />
            <select id="msp-status-filter" onchange="mspFilter(document.getElementById('msp-search').value)" style="max-width:160px;">
              <option value="">All statuses</option>
              <option value="alarm">Alarm Active</option>
              <option value="healthy">Healthy</option>
              <option value="empty">No Schools</option>
              <option value="offline">Offline</option>
            </select>
          </div>
          <div class="msp-grid" id="msp-customer-grid">
            {_msp_cards_html}
          </div>
          <!-- Detail drawer rendered here by JS -->
          <div id="msp-detail-drawer" style="display:none;"></div>

          <script>
          (function() {{
            var _openSlug = null;

            function mspIsVisible() {{
              var el = document.getElementById('msp');
              return el && el.style.display !== 'none';
            }}
            window.mspFilter = function(q) {{
              var statusF = (document.getElementById('msp-status-filter') || {{}}).value || '';
              var term = (q || '').trim().toLowerCase();
              var cards = document.querySelectorAll('#msp-customer-grid .msp-card');
              cards.forEach(function(c) {{
                var name = (c.dataset.name || '').toLowerCase();
                var slug = (c.dataset.slug || '').toLowerCase();
                var status = (c.dataset.status || '');
                var matchQ = !term || name.indexOf(term) >= 0 || slug.indexOf(term) >= 0;
                var matchS = !statusF || status === statusF;
                c.style.display = (matchQ && matchS) ? '' : 'none';
              }});
            }};

            window.mspOpenDetail = function(slug) {{
              if (_openSlug === slug) {{
                _openSlug = null;
                document.getElementById('msp-detail-drawer').style.display = 'none';
                return;
              }}
              _openSlug = slug;
              var drawer = document.getElementById('msp-detail-drawer');
              drawer.style.display = '';
              drawer.innerHTML = '<div style="padding:20px;color:var(--muted);">Loading…</div>';
              Promise.all([
                fetch('/super-admin/msp/district/' + encodeURIComponent(slug)).then(function(r) {{ return r.ok ? r.json() : null; }}),
              ]).then(function(results) {{
                var d = results[0];
                if (!d) {{ drawer.innerHTML = '<p style="color:#ef4444;padding:16px;">Failed to load detail.</p>'; return; }}
                drawer.innerHTML = _renderDetail(d);
                _setupNoteForm(drawer, slug);
              }}).catch(function(e) {{
                drawer.innerHTML = '<p style="color:#ef4444;padding:16px;">Error: ' + e + '</p>';
              }});
            }};

            function _fmt(iso) {{
              if (!iso) return '—';
              try {{ return iso.substring(0,16).replace('T',' ') + ' UTC'; }} catch(e) {{ return iso; }}
            }}

            function _renderDetail(d) {{
              var schoolsHtml = (d.schools || []).map(function(s) {{
                var noc = (d.noc || []).find(function(n) {{ return n.slug === s.slug; }}) || {{}};
                var push = (d.push || []).find(function(p) {{ return p.slug === s.slug; }}) || {{}};
                var alarm = !!noc.alarm_active;
                var pillCls = alarm ? 'danger' : 'ok';
                var pillLabel = alarm ? 'Alarm' : 'Normal';
                var failed = push.failed || 0;
                var pushOk = push.ok || 0;
                var pushTotal = push.total || 0;
                return '<li class="msp-school-row">'
                  + '<div>'
                  + '<strong>' + _esc(s.name) + '</strong>'
                  + '<span style="font-size:0.72rem;color:var(--muted);margin-left:6px;">/' + _esc(s.slug) + '</span>'
                  + (pushTotal > 0 ? '<div style="font-size:0.72rem;color:var(--muted);margin-top:2px;">Push: ' + pushOk + '/' + pushTotal + ' ok' + (failed > 0 ? ' <span style="color:#ef4444;">' + failed + ' failed</span>' : '') + '</div>' : '')
                  + '</div>'
                  + '<div style="display:flex;align-items:center;gap:6px;">'
                  + '<span class="status-pill ' + pillCls + '" style="font-size:0.68rem;padding:2px 8px;">' + pillLabel + '</span>'
                  + '<form method="post" action="/super-admin/schools/' + _esc(s.slug) + '/enter" style="margin:0;">'
                  + '<button class="button button-secondary" type="submit" style="font-size:0.72rem;padding:2px 10px;">Open</button>'
                  + '</form>'
                  + '</div>'
                  + '</li>';
              }}).join('') || '<li style="color:var(--muted);font-size:0.83rem;padding:6px 0;">No schools.</li>';

              var notesHtml = (d.notes || []).map(function(n) {{
                return '<div class="msp-note-item" id="msp-note-' + n.id + '">'
                  + '<div><div>' + _esc(n.note_text) + '</div><div class="msp-note-meta">' + _esc(n.created_by) + ' · ' + _fmt(n.created_at) + '</div></div>'
                  + '<button class="button button-danger-outline" style="font-size:0.72rem;padding:2px 8px;flex-shrink:0;" onclick="mspDeleteNote(' + n.id + ',\'' + _esc(d.slug) + '\')" type="button">Remove</button>'
                  + '</div>';
              }}).join('') || '<p style="color:var(--muted);font-size:0.82rem;margin:0 0 8px;">No notes yet.</p>';

              var activeAlarms = (d.noc || []).filter(function(n) {{ return n.alarm_active; }});
              var alarmHtml = activeAlarms.length ? activeAlarms.map(function(n) {{
                return '<div style="background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.3);border-radius:6px;padding:8px 12px;margin-bottom:6px;font-size:0.82rem;">'
                  + '<strong style="color:#ef4444;">' + _esc(n.name) + '</strong>'
                  + (n.alarm_message ? '<p style="margin:4px 0 0;">' + _esc(n.alarm_message) + '</p>' : '')
                  + '<div style="font-size:0.72rem;color:var(--muted);margin-top:4px;">' + (n.ack_count||0) + '/' + (n.user_count||0) + ' acknowledged</div>'
                  + '</div>';
              }}).join('') : '<p style="color:var(--muted);font-size:0.82rem;margin:0;">No active alarms.</p>';

              var incCount = d.incident_count || 0;
              var qpCount = d.pending_quiet || 0;
              var statsBar = '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px;padding:10px 14px;'
                + 'background:var(--card);border:1px solid var(--border);border-radius:8px;">'
                + '<span style="font-size:0.78rem;"><strong>' + incCount + '</strong> active incident' + (incCount !== 1 ? 's' : '') + '</span>'
                + '<span style="color:var(--border);">|</span>'
                + '<span style="font-size:0.78rem;' + (qpCount > 0 ? 'color:#f59e0b;font-weight:600;' : '') + '">'
                + '<strong>' + qpCount + '</strong> pending quiet request' + (qpCount !== 1 ? 's' : '') + '</span>'
                + '<span style="color:var(--border);">|</span>'
                + '<span style="font-size:0.78rem;">' + (d.schools || []).length + ' school' + ((d.schools||[]).length !== 1 ? 's' : '') + '</span>'
                + '</div>';

              var auditRows = (d.recent_audit || []).map(function(e) {{
                return '<tr style="border-bottom:1px solid var(--border);">'
                  + '<td style="padding:5px 8px;font-size:0.72rem;color:var(--muted);white-space:nowrap;">' + _esc((e.created_at||'').substring(0,16).replace('T',' ')) + '</td>'
                  + '<td style="padding:5px 8px;font-size:0.75rem;">' + _esc(e.event_type||'') + '</td>'
                  + '<td style="padding:5px 8px;font-size:0.75rem;color:var(--muted);">' + _esc(e.actor||'system') + '</td>'
                  + '</tr>';
              }}).join('');
              var auditHtml = auditRows
                ? '<table style="width:100%;border-collapse:collapse;">'
                  + '<thead><tr><th style="text-align:left;padding:5px 8px;font-size:0.7rem;color:var(--muted);border-bottom:1px solid var(--border);">Time</th>'
                  + '<th style="text-align:left;padding:5px 8px;font-size:0.7rem;color:var(--muted);border-bottom:1px solid var(--border);">Event</th>'
                  + '<th style="text-align:left;padding:5px 8px;font-size:0.7rem;color:var(--muted);border-bottom:1px solid var(--border);">By</th></tr></thead>'
                  + '<tbody>' + auditRows + '</tbody></table>'
                : '<p style="color:var(--muted);font-size:0.82rem;margin:0;">No recent activity.</p>';

              var safeActionsHtml = '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:4px;">'
                + (d.schools && d.schools[0]
                  ? '<form method="post" action="/super-admin/schools/' + _esc(d.schools[0].slug) + '/enter" style="margin:0;">'
                    + '<button class="button button-primary" type="submit" style="font-size:0.78rem;padding:5px 14px;">Open Console</button>'
                    + '</form>'
                  : '')
                + '<a class="button button-secondary" href="/super-admin?section=email-tool" style="font-size:0.78rem;padding:5px 14px;text-decoration:none;">Send Email</a>'
                + '<a class="button button-secondary" href="/super-admin?section=health" style="font-size:0.78rem;padding:5px 14px;text-decoration:none;">Health Check</a>'
                + '</div>';

              return '<div class="msp-detail-drawer">'
                + '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">'
                + '<h2 style="margin:0;font-size:1.1rem;">' + _esc(d.name) + '</h2>'
                + '<button class="button button-secondary" style="font-size:0.75rem;" onclick="mspOpenDetail(\'' + _esc(d.slug) + '\')" type="button">Close</button>'
                + '</div>'
                + statsBar
                + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">'
                + '<div>'
                  + '<h4>Schools / Buildings</h4>'
                  + '<ul class="msp-school-list">' + schoolsHtml + '</ul>'
                  + '<h4 style="margin-top:14px;">Active Alarms</h4>' + alarmHtml
                + '</div>'
                + '<div>'
                  + '<h4>Operator Notes</h4>'
                  + '<div class="msp-note-list" id="msp-notes-' + _esc(d.slug) + '">' + notesHtml + '</div>'
                  + '<form class="msp-note-form" data-slug="' + _esc(d.slug) + '" style="display:flex;gap:8px;align-items:flex-end;margin-bottom:14px;">'
                  + '<div class="field" style="flex:1;margin:0;">'
                  + '<textarea name="note_text" rows="2" placeholder="Add internal note…" style="width:100%;resize:vertical;"></textarea>'
                  + '</div>'
                  + '<button class="button button-primary" type="submit" style="font-size:0.8rem;padding:6px 14px;align-self:flex-end;">Add</button>'
                  + '</form>'
                  + '<h4>Recent Audit Activity</h4>' + auditHtml
                + '</div>'
                + '</div>'
                + '<div style="margin-top:16px;padding-top:14px;border-top:1px solid var(--border);">'
                + '<h4 style="margin-bottom:8px;">Safe Actions</h4>'
                + safeActionsHtml
                + '</div>'
                + '</div>';
            }}

            function _esc(s) {{
              return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
            }}

            function _setupNoteForm(drawer, slug) {{
              var form = drawer.querySelector('.msp-note-form');
              if (!form) return;
              form.addEventListener('submit', function(e) {{
                e.preventDefault();
                var text = (form.querySelector('[name=note_text]') || {{}}).value || '';
                if (!text.trim()) return;
                fetch('/super-admin/msp/notes', {{
                  method: 'POST',
                  headers: {{'Content-Type': 'application/json'}},
                  body: JSON.stringify({{tenant_slug: slug, note_text: text.trim()}})
                }}).then(function(r) {{ return r.ok ? r.json() : null; }}).then(function(d) {{
                  if (!d || !d.note) return;
                  var n = d.note;
                  var list = document.getElementById('msp-notes-' + slug);
                  if (list) {{
                    var p = list.querySelector('p');
                    if (p) p.remove();
                    var item = document.createElement('div');
                    item.className = 'msp-note-item';
                    item.id = 'msp-note-' + n.id;
                    item.innerHTML = '<div><div>' + _esc(n.note_text) + '</div><div class="msp-note-meta">' + _esc(n.created_by) + ' · ' + _fmt(n.created_at) + '</div></div>'
                      + '<button class="button button-danger-outline" style="font-size:0.72rem;padding:2px 8px;flex-shrink:0;" onclick="mspDeleteNote(' + n.id + ',\'' + _esc(slug) + '\')" type="button">Remove</button>';
                    list.prepend(item);
                    form.querySelector('[name=note_text]').value = '';
                  }}
                }}).catch(function() {{}});
              }});
            }}

            window.mspDeleteNote = function(noteId, slug) {{
              if (!confirm('Remove this note?')) return;
              fetch('/super-admin/msp/notes/' + noteId, {{method: 'DELETE'}}).then(function(r) {{ return r.ok; }}).then(function(ok) {{
                if (ok) {{ var el = document.getElementById('msp-note-' + noteId); if (el) el.remove(); }}
              }}).catch(function() {{}});
            }};

            function mspRefreshCards() {{
              if (!mspIsVisible()) return;
              fetch('/super-admin/tenant-health').then(function(r) {{ return r.ok ? r.json() : null; }}).then(function(d) {{
                if (!d || !d.tenants) return;
                var bySlug = {{}};
                d.tenants.forEach(function(t) {{ bySlug[t.slug] = t; }});
                var alarmNames = [];
                var hasIssue = false;
                var cards = document.querySelectorAll('#msp-customer-grid .msp-card');
                cards.forEach(function(card) {{
                  var slug = card.dataset.slug;
                  var t = bySlug[slug];
                  if (!t) return;
                  var alarm = !!t.alarm_active;
                  var pushFailed = parseInt(t.push_failed || 0, 10);
                  if (alarm) alarmNames.push(card.dataset.name || slug);
                  if (alarm || pushFailed > 0) hasIssue = true;
                  var newStatus = alarm ? 'alarm' : 'healthy';
                  card.dataset.status = newStatus;
                  card.dataset.pushFailed = pushFailed;
                  card.style.borderLeftColor = alarm ? '#ef4444' : '#22c55e';
                  var pill = card.querySelector('.status-pill');
                  if (pill) {{
                    pill.className = 'status-pill ' + (alarm ? 'danger' : 'ok');
                    pill.textContent = alarm ? 'Alarm Active' : 'Healthy';
                  }}
                  var badges = card.querySelector('.msp-card-badges');
                  if (badges) {{
                    var existing = badges.querySelector('.msp-alarm-badge');
                    if (alarm && !existing) {{
                      var b = document.createElement('span');
                      b.className = 'msp-alarm-badge';
                      b.style.cssText = 'color:#ef4444;font-size:0.75rem;font-weight:600;';
                      b.textContent = '⚠ 1 alarm';
                      badges.prepend(b);
                    }} else if (!alarm && existing) {{
                      existing.remove();
                    }}
                    var pfBadge = badges.querySelector('.msp-push-fail');
                    if (pfBadge) {{
                      if (pushFailed > 0) {{
                        pfBadge.dataset.count = pushFailed;
                        pfBadge.textContent = '✗ ' + pushFailed + ' push';
                        pfBadge.style.display = '';
                      }} else {{
                        pfBadge.style.display = 'none';
                      }}
                    }}
                  }}
                }});
                var strip = document.getElementById('msp-alarm-strip');
                if (strip) {{
                  if (alarmNames.length) {{
                    strip.style.display = '';
                    strip.textContent = '🔴 ALARM: ' + alarmNames.join(', ');
                  }} else {{
                    strip.style.display = 'none';
                  }}
                }}
                var pill = document.getElementById('msp-overall-pill');
                if (pill) {{
                  pill.className = 'status-pill ' + (alarmNames.length ? 'danger' : 'ok');
                  pill.textContent = alarmNames.length ? '⚠ Alarm Active' : 'All Healthy';
                }}
                var ts = document.getElementById('msp-last-refresh');
                if (ts) ts.textContent = 'Updated ' + new Date().toISOString().substring(11,16) + ' UTC';
              }}).catch(function() {{}});
            }}

            mspRefreshCards();
            setInterval(mspRefreshCards, 15000);
          }})();
          </script>
        </section>
        <section class="panel command-section" id="noc"{_section_style("noc")}>
          <div class="panel-header hero-band">
            <div>
              <p class="eyebrow">Live Operations</p>
              <h1>Operations Center</h1>
              <p class="hero-copy">Real-time system health, active alarms, push delivery, and cross-tenant activity. Refreshes automatically.</p>
            </div>
            <div class="status-row">
              <span class="status-pill {_noc_pill_cls}" id="noc-overall-pill"><strong>System</strong>{_noc_label}</span>
              <span class="status-pill" id="noc-last-update" style="font-size:0.75rem;font-weight:400;">Live</span>
            </div>
          </div>
          {_noc_sys_banner_html}
          {_noc_alarm_banner_html}
          <div class="kpi-grid" style="grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:24px;">
            <div class="kpi-card">
              <p class="kpi-label">API</p>
              <p class="kpi-value" id="noc-api-status" style="font-size:1.25rem;color:{'#22c55e' if _noc_api_cls == 'ok' else '#ef4444'};">{"OK" if _noc_api_cls == "ok" else "Error"}</p>
            </div>
            <div class="kpi-card">
              <p class="kpi-label">Database</p>
              <p class="kpi-value" id="noc-db-status" style="font-size:1.25rem;color:{'#22c55e' if _noc_db_cls == 'ok' else '#ef4444'};">{_noc_db_text}</p>
            </div>
            <div class="kpi-card">
              <p class="kpi-label">WS Connections</p>
              <p class="kpi-value" id="noc-ws-count" style="font-size:1.25rem;">{_noc_ws}</p>
            </div>
            <div class="kpi-card">
              <p class="kpi-label">Active Tenants</p>
              <p class="kpi-value" id="noc-tenant-count" style="font-size:1.25rem;">{_noc_tenant_count}</p>
            </div>
            <div class="kpi-card">
              <p class="kpi-label">Uptime</p>
              <p class="kpi-value" id="noc-uptime" style="font-size:1.25rem;">{_noc_uptime_str}</p>
            </div>
          </div>
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid var(--border);">
            <h3 style="font-size:1rem;font-weight:600;margin:0;">Tenant Health</h3>
            <span style="font-size:0.75rem;color:var(--text-muted);" id="noc-grid-ts"></span>
          </div>
          <div class="school-grid" id="noc-tenant-grid" style="margin-bottom:28px;">
            {_noc_tenant_cards_html}
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:8px;">
            <div>
              <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid var(--border);">
                <h3 style="font-size:1rem;font-weight:600;margin:0;">Live Activity</h3>
                <span style="font-size:0.75rem;color:var(--text-muted);" id="noc-activity-ts"></span>
              </div>
              <div class="table-wrap" style="max-height:300px;overflow-y:auto;">
                <table class="data-table" style="font-size:0.8rem;">
                  <thead><tr><th>Time (UTC)</th><th>School</th><th>Event</th><th>By</th></tr></thead>
                  <tbody id="noc-activity-body"><tr><td colspan="4" style="color:var(--text-muted);padding:12px 0;">Loading&hellip;</td></tr></tbody>
                </table>
              </div>
            </div>
            <div>
              <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid var(--border);">
                <h3 style="font-size:1rem;font-weight:600;margin:0;">Push Delivery</h3>
                <span style="font-size:0.75rem;color:var(--text-muted);" id="noc-push-ts"></span>
              </div>
              <div class="table-wrap" style="max-height:300px;overflow-y:auto;">
                <table class="data-table" style="font-size:0.8rem;">
                  <thead><tr><th>School</th><th>Sent</th><th>OK</th><th>Failed</th><th>Last Alert</th></tr></thead>
                  <tbody id="noc-push-body"><tr><td colspan="5" style="color:var(--text-muted);padding:12px 0;">Loading&hellip;</td></tr></tbody>
                </table>
              </div>
            </div>
          </div>
          <script>
          (function() {{
            function _nocVisible() {{
              var el = document.getElementById('noc');
              return el && el.style.display !== 'none';
            }}
            function _fmtIso(iso) {{
              if (!iso) return '—';
              try {{ return iso.substring(0, 16).replace('T', ' ') + ' UTC'; }} catch(e) {{ return String(iso); }}
            }}
            function _fmtUptime(s) {{
              s = s || 0;
              var d = Math.floor(s / 86400), r = s % 86400, h = Math.floor(r / 3600), m = Math.floor((r % 3600) / 60);
              if (d > 0) return d + 'd ' + h + 'h';
              if (h > 0) return h + 'h ' + m + 'm';
              return m + 'm';
            }}
            function _setHtml(id, html) {{ var el = document.getElementById(id); if (el) el.innerHTML = html; }}
            function _setText(id, txt) {{ var el = document.getElementById(id); if (el) el.textContent = txt; }}
            function _nowUtc() {{ return new Date().toISOString().substring(11, 16) + ' UTC'; }}

            function fetchMetrics() {{
              if (!_nocVisible()) return;
              fetch('/super-admin/metrics').then(function(r) {{ return r.ok ? r.json() : null; }}).then(function(d) {{
                if (!d) return;
                var pillMap = {{ok: 'ok', degraded: 'warn', error: 'danger'}};
                var labelMap = {{ok: 'Healthy', degraded: 'Degraded', error: 'Down'}};
                var pillEl = document.getElementById('noc-overall-pill');
                if (pillEl) {{
                  pillEl.className = 'status-pill' + (pillMap[d.status] ? ' ' + pillMap[d.status] : '');
                  pillEl.innerHTML = '<strong>System</strong>' + (labelMap[d.status] || d.status);
                }}
                var apiEl = document.getElementById('noc-api-status');
                if (apiEl) {{
                  var apiOk = d.status !== 'error';
                  apiEl.textContent = apiOk ? 'OK' : 'Error';
                  apiEl.style.color = apiOk ? '#22c55e' : '#ef4444';
                }}
                var dbEl = document.getElementById('noc-db-status');
                if (dbEl) {{
                  dbEl.textContent = d.db ? 'OK' : 'Error';
                  dbEl.style.color = d.db ? '#22c55e' : '#ef4444';
                }}
                _setText('noc-ws-count', d.ws_connections != null ? String(d.ws_connections) : '—');
                _setText('noc-tenant-count', d.active_tenants != null ? String(d.active_tenants) : '—');
                _setText('noc-uptime', _fmtUptime(d.uptime_seconds));
                _setText('noc-last-update', 'Updated ' + _nowUtc());
                var sb = document.getElementById('noc-sys-banner');
                if (sb) {{
                  if (d.status === 'ok') {{
                    sb.style.display = 'none';
                  }} else {{
                    sb.style.display = '';
                    sb.textContent = '⚠ System status: ' + (labelMap[d.status] || d.status);
                  }}
                }}
              }}).catch(function() {{}});
            }}

            function fetchTenantHealth() {{
              if (!_nocVisible()) return;
              fetch('/super-admin/tenant-health').then(function(r) {{ return r.ok ? r.json() : null; }}).then(function(d) {{
                if (!d || !d.tenants) return;
                var alarmNames = [];
                var html = d.tenants.map(function(t) {{
                  var alarm = !!t.alarm_active;
                  if (alarm) alarmNames.push(t.name || t.slug);
                  var msg = alarm && t.alarm_message ? '<p class="school-card-message">' + String(t.alarm_message).substring(0, 60) + '</p>' : '';
                  var ack = alarm && t.user_count > 0 ? '<div class="school-card-message">' + t.ack_count + '/' + t.user_count + ' acknowledged</div>' : '';
                  return '<div class="school-card ' + (alarm ? 'school-card--alarm' : 'school-card--ok') + '" onclick="window.location=\'/super-admin?section=schools\'">'
                    + '<div class="school-card-header">'
                    + '<span class="school-card-name">' + (t.name || t.slug) + '</span>'
                    + '<span class="status-pill ' + (alarm ? 'danger' : 'ok') + '" style="font-size:0.7rem;padding:2px 8px;">' + (alarm ? 'Alarm Active' : 'Normal') + '</span>'
                    + '</div>' + msg
                    + '<div class="school-card-footer"><span class="school-card-last">WS: ' + (t.ws_connections || 0) + ' &nbsp;&middot;&nbsp; ' + _fmtIso(t.last_alert_at) + '</span></div>'
                    + ack + '</div>';
                }}).join('') || '<p class="mini-copy" style="padding:16px 0;">No tenants provisioned yet.</p>';
                _setHtml('noc-tenant-grid', html);
                _setText('noc-grid-ts', _nowUtc());
                var ab = document.getElementById('noc-alarm-banner');
                if (ab) {{
                  if (alarmNames.length) {{
                    ab.style.display = '';
                    ab.textContent = '🔴 ALARM ACTIVE in: ' + alarmNames.join(', ');
                  }} else {{
                    ab.style.display = 'none';
                  }}
                }}
              }}).catch(function() {{}});
            }}

            function fetchActivity() {{
              if (!_nocVisible()) return;
              fetch('/super-admin/system-activity?limit=40').then(function(r) {{ return r.ok ? r.json() : null; }}).then(function(d) {{
                if (!d || !d.events) return;
                var tbody = document.getElementById('noc-activity-body');
                if (!tbody) return;
                if (!d.events.length) {{
                  tbody.innerHTML = '<tr><td colspan="4" style="color:var(--text-muted);padding:12px 0;">No recent activity.</td></tr>';
                  return;
                }}
                tbody.innerHTML = d.events.slice(0, 30).map(function(e) {{
                  return '<tr>'
                    + '<td style="white-space:nowrap;">' + _fmtIso(e.created_at || e.timestamp) + '</td>'
                    + '<td>' + (e.school || e.tenant || '—') + '</td>'
                    + '<td>' + (e.action || e.event || '—') + '</td>'
                    + '<td>' + (e.by || e.user || '—') + '</td>'
                    + '</tr>';
                }}).join('');
                _setText('noc-activity-ts', '— ' + _nowUtc());
              }}).catch(function() {{}});
            }}

            function fetchPushStats() {{
              if (!_nocVisible()) return;
              fetch('/super-admin/push-stats').then(function(r) {{ return r.ok ? r.json() : null; }}).then(function(d) {{
                if (!d || !d.tenants) return;
                var tbody = document.getElementById('noc-push-body');
                if (!tbody) return;
                if (!d.tenants.length) {{
                  tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted);padding:12px 0;">No push data yet.</td></tr>';
                  return;
                }}
                tbody.innerHTML = d.tenants.map(function(t) {{
                  var failStyle = t.failed > 0 ? ' style="color:#ef4444;"' : '';
                  return '<tr>'
                    + '<td>' + (t.name || t.slug) + '</td>'
                    + '<td>' + (t.total || 0) + '</td>'
                    + '<td>' + (t.ok || 0) + '</td>'
                    + '<td' + failStyle + '>' + (t.failed || 0) + '</td>'
                    + '<td style="white-space:nowrap;">' + _fmtIso(t.last_alert_at) + '</td>'
                    + '</tr>';
                }}).join('');
                _setText('noc-push-ts', '— ' + _nowUtc());
              }}).catch(function() {{}});
            }}

            fetchMetrics(); fetchTenantHealth(); fetchActivity(); fetchPushStats();
            setInterval(fetchMetrics, 10000);
            setInterval(fetchTenantHealth, 10000);
            setInterval(fetchActivity, 15000);
            setInterval(fetchPushStats, 30000);
          }})();
          </script>
        </section>
        <section class="panel command-section" id="districts"{_section_style("districts")}>
          <style>
          .district-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:20px;margin-bottom:32px;}}
          .district-card{{background:var(--card);border:1px solid var(--border);border-radius:18px;padding:0;overflow:hidden;box-shadow:0 2px 12px rgba(22,53,117,0.06);transition:box-shadow 0.15s;}}
          .district-card:hover{{box-shadow:0 6px 24px rgba(22,53,117,0.12);}}
          .district-card-header{{padding:20px 20px 0;display:flex;align-items:flex-start;justify-content:space-between;gap:12px;}}
          .district-card-name{{font-size:1.1rem;font-weight:700;color:var(--text);margin:0 0 2px;line-height:1.3;}}
          .district-card-slug{{font-size:0.75rem;color:var(--muted);font-family:monospace;}}
          .district-card-meta{{padding:10px 20px;display:flex;gap:16px;flex-wrap:wrap;border-bottom:1px solid var(--border);}}
          .district-card-meta span{{font-size:0.79rem;color:var(--muted);}}
          .district-card-meta strong{{color:var(--text);}}
          .district-card-actions{{padding:14px 20px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;}}
          .district-billing-expand{{padding:0 20px 16px;}}
          .district-billing-expand summary{{font-size:0.78rem;font-weight:600;color:var(--accent);cursor:pointer;padding:6px 0;}}
          .district-billing-form{{margin-top:10px;}}
          .archived-section{{margin-top:40px;padding-top:28px;border-top:2px solid var(--border);}}
          .archived-section-title{{font-size:0.72rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:var(--muted);margin-bottom:16px;}}
          .archived-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;}}
          .archived-card{{background:rgba(100,116,139,0.06);border:1px solid var(--border);border-radius:14px;padding:16px 18px;}}
          .archived-card-name{{font-size:1rem;font-weight:600;color:var(--text);margin:0 0 4px;}}
          .archived-card-meta{{font-size:0.76rem;color:var(--muted);margin-bottom:12px;}}
          .purge-confirm-row{{display:flex;gap:8px;align-items:center;margin-top:8px;}}
          .purge-confirm-input{{flex:1;font-size:0.82rem;padding:6px 10px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text);}}
          </style>
          <div class="panel-header hero-band">
            <div>
              <p class="eyebrow">Tenant Registry</p>
              <h1>Districts &amp; Schools</h1>
              <p class="hero-copy">Manage all districts, schools, and billing from one place. Active districts are shown as cards. Archive a district to stop its activity; purge to permanently delete all data.</p>
            </div>
            <div class="status-row">
              <span class="status-pill ok"><strong>Domain</strong>{escape(base_domain)}</span>
              <span class="status-pill"><strong>Districts</strong>{len([d for d in msp_districts if d.get("is_district")])}</span>
              <span class="status-pill"><strong>Schools</strong>{len(_active_school_rows)}</span>
              <button class="button button-primary" type="button" onclick="bbOpenCreateDistrictModal()" style="font-size:0.8rem;padding:6px 16px;margin-left:8px;">+ Create District</button>
            </div>
          </div>
          {security_feedback}
          <div class="district-grid">
            {_district_cards_html}
          </div>
          {_archived_section_html}
          <script>
          window._bbAllSchools = {_bb_schools_js};
          window.bbConfirmPurge = function(form, name) {{
            var input = form.querySelector('input[name="confirm_name"]');
            if (!input || input.value.trim().toLowerCase() !== name.trim().toLowerCase()) {{
              alert('Type the district name exactly to confirm purge.');
              return false;
            }}
            return confirm('PERMANENTLY DELETE ' + name + '? This cannot be undone.');
          }};
          </script>

          <!-- ── District Management Modals ──────────────────────────────── -->
          <style>
          .bb-modal-overlay{{position:fixed;inset:0;background:rgba(10,18,40,0.55);z-index:9000;display:flex;align-items:center;justify-content:center;padding:16px;}}
          .bb-modal{{background:var(--card);border:1px solid var(--border);border-radius:20px;padding:28px 28px 24px;max-width:520px;width:100%;box-shadow:0 8px 40px rgba(10,18,40,0.18);position:relative;max-height:90vh;overflow-y:auto;}}
          .bb-modal-wide{{max-width:760px;}}
          .bb-modal-title{{font-size:1.1rem;font-weight:700;color:var(--text);margin:0 0 18px;}}
          .bb-modal-close{{position:absolute;top:16px;right:18px;background:none;border:none;font-size:1.3rem;cursor:pointer;color:var(--muted);line-height:1;}}
          .bb-modal-close:hover{{color:var(--text);}}
          .bb-field{{display:flex;flex-direction:column;gap:4px;margin-bottom:14px;}}
          .bb-field label{{font-size:0.78rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.06em;}}
          .bb-field input,.bb-field select{{padding:8px 12px;border-radius:10px;border:1.5px solid var(--border);background:var(--card);color:var(--text);font-size:0.9rem;width:100%;box-sizing:border-box;}}
          .bb-field input:focus,.bb-field select:focus{{outline:none;border-color:var(--accent);}}
          .bb-banner{{padding:9px 14px;border-radius:10px;font-size:0.82rem;font-weight:500;margin-bottom:14px;display:none;}}
          .bb-banner.ok{{background:#f0fdf4;color:#166534;border:1px solid #bbf7d0;}}
          .bb-banner.err{{background:#fef2f2;color:#dc2626;border:1px solid #fecaca;}}
          .bb-dual-list{{display:grid;grid-template-columns:1fr 1fr;gap:16px;}}
          .bb-dual-col{{display:flex;flex-direction:column;gap:0;}}
          .bb-dual-col-title{{font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.07em;color:var(--muted);margin-bottom:8px;}}
          .bb-school-list{{border:1.5px solid var(--border);border-radius:12px;min-height:180px;max-height:280px;overflow-y:auto;background:var(--card);}}
          .bb-school-item{{display:flex;align-items:center;justify-content:space-between;padding:9px 12px;border-bottom:1px solid var(--border);font-size:0.84rem;gap:8px;}}
          .bb-school-item:last-child{{border-bottom:none;}}
          .bb-school-item-name{{flex:1;color:var(--text);font-weight:500;}}
          .bb-school-item-slug{{font-size:0.72rem;color:var(--muted);font-family:monospace;}}
          .bb-school-btn{{border:none;border-radius:8px;padding:4px 10px;font-size:0.75rem;font-weight:600;cursor:pointer;transition:opacity 0.15s;}}
          .bb-school-btn:disabled{{opacity:0.45;cursor:default;}}
          .bb-school-btn.remove{{background:#fee2e2;color:#dc2626;}}
          .bb-school-btn.add{{background:#dbeafe;color:#1d4ed8;}}
          .bb-empty-state{{padding:24px;text-align:center;color:var(--muted);font-size:0.83rem;}}
          </style>

          <script>
          /* ── District management JS ─────────────────────────────────────────── */
          var _bbEditDistrictSlug = null;

          function bbCloseModal(id) {{
            var m = document.getElementById(id);
            if (m) m.style.display = 'none';
          }}

          function bbShowBanner(id, msg, isErr) {{
            var b = document.getElementById(id);
            if (!b) return;
            b.textContent = msg;
            b.className = 'bb-banner ' + (isErr ? 'err' : 'ok');
            b.style.display = 'block';
          }}

          function bbClearBanner(id) {{
            var b = document.getElementById(id);
            if (b) {{ b.style.display = 'none'; b.textContent = ''; }}
          }}

          /* Create District */
          function bbOpenCreateDistrictModal() {{
            bbClearBanner('bb-create-district-banner');
            document.getElementById('bb-create-district-name').value = '';
            document.getElementById('bb-create-district-slug').value = '';
            document.getElementById('bb-create-district-btn').disabled = false;
            document.getElementById('bb-create-district-btn').textContent = 'Create District';
            document.getElementById('bb-create-district-modal').style.display = 'flex';
            /* Load orgs and pre-select the only one if possible */
            var sel = document.getElementById('bb-create-district-org');
            sel.innerHTML = '<option value="">Loading…</option>';
            document.getElementById('bb-create-org-field').style.display = '';
            fetch('/super-admin/organizations', {{headers:{{'X-Requested-With':'XMLHttpRequest'}}}})
              .then(function(r){{return r.json();}})
              .then(function(d){{
                var orgs = d.organizations || [];
                if (orgs.length === 1) {{
                  /* Only one org — auto-select and hide the field */
                  sel.innerHTML = '<option value="' + orgs[0].id + '">' + orgs[0].name + '</option>';
                  document.getElementById('bb-create-org-field').style.display = 'none';
                }} else {{
                  sel.innerHTML = '<option value="">Select organization…</option>' +
                    orgs.map(function(o){{return '<option value="'+o.id+'">'+o.name+'</option>';}}).join('');
                }}
              }})
              .catch(function(){{
                /* Fallback: default org_id=1 */
                sel.innerHTML = '<option value="1">Default Organization</option>';
                document.getElementById('bb-create-org-field').style.display = 'none';
              }});
            document.getElementById('bb-create-district-name').focus();
          }}

          /* Auto-generate slug from name (wired after DOM ready) */
          document.addEventListener('DOMContentLoaded', function() {{
            var nameEl = document.getElementById('bb-create-district-name');
            var slugEl = document.getElementById('bb-create-district-slug');
            if (nameEl && slugEl) {{
              nameEl.addEventListener('input', function() {{
                if (!slugEl._userEdited) {{
                  slugEl.value = nameEl.value.toLowerCase()
                    .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
                }}
              }});
              slugEl.addEventListener('input', function() {{ slugEl._userEdited = true; }});
            }}
          }});

          function bbSubmitCreateDistrict() {{
            var name = document.getElementById('bb-create-district-name').value.trim();
            var slug = document.getElementById('bb-create-district-slug').value.trim();
            var orgId = document.getElementById('bb-create-district-org').value;
            if (!name) {{ bbShowBanner('bb-create-district-banner', 'District name is required.', true); return; }}
            if (!slug) {{ bbShowBanner('bb-create-district-banner', 'Slug is required.', true); return; }}
            if (!orgId) {{ bbShowBanner('bb-create-district-banner', 'Select an organization.', true); return; }}
            var btn = document.getElementById('bb-create-district-btn');
            btn.disabled = true; btn.textContent = 'Creating…';
            var fd = new FormData();
            fd.append('name', name); fd.append('slug', slug); fd.append('organization_id', orgId);
            fetch('/super-admin/districts/create', {{method:'POST', body:fd,
              headers:{{'X-Requested-With':'XMLHttpRequest'}}}})
              .then(function(r){{return r.json();}})
              .then(function(d){{
                btn.disabled = false; btn.textContent = 'Create District';
                if (d.ok) {{
                  bbShowBanner('bb-create-district-banner', 'District "' + d.name + '" created!', false);
                  /* Inject a minimal card so UI updates without reload */
                  var grid = document.querySelector('.district-grid');
                  if (grid) {{
                    var card = document.createElement('div');
                    card.className = 'district-card';
                    card.dataset.districtSlug = d.slug;
                    card.innerHTML = '<div class="district-card-header"><div>'
                      + '<p class="district-card-name">' + d.name + '</p>'
                      + '<p class="district-card-slug">' + d.slug + ' &nbsp;·&nbsp; District</p>'
                      + '</div><span class="status-pill" style="font-size:0.7rem;padding:2px 10px;">No license</span></div>'
                      + '<div class="district-card-meta"><span><strong>0</strong> schools</span></div>'
                      + '<div class="district-card-actions">'
                      + '<button class="button button-secondary" type="button" style="font-size:0.75rem;padding:5px 12px;"'
                      + ' onclick="bbOpenEditDistrictModal(' + JSON.stringify(d.slug) + ',' + JSON.stringify(d.name) + ')">Edit</button>'
                      + '<button class="button button-secondary" type="button" style="font-size:0.75rem;padding:5px 12px;"'
                      + ' onclick="bbOpenManageSchoolsModal(' + JSON.stringify(d.slug) + ',' + JSON.stringify(d.name) + ',0)">Manage Schools</button>'
                      + '</div>';
                    grid.insertBefore(card, grid.firstChild);
                  }}
                  setTimeout(function(){{ bbCloseModal('bb-create-district-modal'); }}, 1200);
                }} else {{
                  bbShowBanner('bb-create-district-banner', d.detail || d.error || 'Creation failed.', true);
                }}
              }})
              .catch(function(){{
                btn.disabled = false; btn.textContent = 'Create District';
                bbShowBanner('bb-create-district-banner', 'Network error — please try again.', true);
              }});
          }}

          /* Edit District */
          function bbOpenEditDistrictModal(slug, name) {{
            _bbEditDistrictSlug = slug;
            bbClearBanner('bb-edit-district-banner');
            document.getElementById('bb-edit-district-name').value = name || '';
            document.getElementById('bb-edit-district-slug').value = slug || '';
            document.getElementById('bb-edit-district-btn').disabled = false;
            document.getElementById('bb-edit-district-btn').textContent = 'Save Changes';
            document.getElementById('bb-edit-district-modal').style.display = 'flex';
            document.getElementById('bb-edit-district-name').focus();
          }}

          function bbSubmitEditDistrict() {{
            if (!_bbEditDistrictSlug) return;
            var name = document.getElementById('bb-edit-district-name').value.trim();
            var slug = document.getElementById('bb-edit-district-slug').value.trim();
            if (!name) {{ bbShowBanner('bb-edit-district-banner', 'Name is required.', true); return; }}
            var btn = document.getElementById('bb-edit-district-btn');
            btn.disabled = true; btn.textContent = 'Saving…';
            var fd = new FormData();
            fd.append('name', name); fd.append('new_slug', slug);
            fetch('/super-admin/districts/' + _bbEditDistrictSlug + '/update',
              {{method:'POST', body:fd, headers:{{'X-Requested-With':'XMLHttpRequest'}}}})
              .then(function(r){{return r.json();}})
              .then(function(d){{
                btn.disabled = false; btn.textContent = 'Save Changes';
                if (d.ok !== false && !d.detail) {{
                  bbShowBanner('bb-edit-district-banner', 'District updated.', false);
                  /* Update card name/slug in the grid */
                  var card = document.querySelector('[data-district-slug="' + _bbEditDistrictSlug + '"]');
                  if (card) {{
                    var nameEl = card.querySelector('.district-card-name');
                    var slugEl = card.querySelector('.district-card-slug');
                    if (nameEl) nameEl.textContent = name;
                    if (slugEl) slugEl.textContent = slug + ' · District';
                    card.dataset.districtSlug = slug;
                  }}
                  _bbEditDistrictSlug = slug;
                  setTimeout(function(){{ bbCloseModal('bb-edit-district-modal'); }}, 900);
                }} else {{
                  bbShowBanner('bb-edit-district-banner', d.detail || d.error || 'Update failed.', true);
                }}
              }})
              .catch(function(){{
                btn.disabled = false; btn.textContent = 'Save Changes';
                bbShowBanner('bb-edit-district-banner', 'Network error.', true);
              }});
          }}

          /* Manage Schools */
          var _bbManageSlug = null, _bbManageDistrictId = null;

          function bbOpenManageSchoolsModal(slug, name, districtId) {{
            _bbManageSlug = slug;
            _bbManageDistrictId = districtId;
            bbClearBanner('bb-manage-schools-banner');
            document.getElementById('bb-manage-schools-title').textContent = 'Manage Schools — ' + name;
            document.getElementById('bb-manage-schools-modal').style.display = 'flex';
            bbRefreshSchoolLists(districtId);
          }}

          function bbRefreshSchoolLists(districtId) {{
            var all = window._bbAllSchools || [];
            var assigned = all.filter(function(s){{ return s.district_id && s.district_id == districtId; }});
            var available = all.filter(function(s){{ return !s.district_id; }});

            function schoolItem(s, btnClass, btnLabel, onclick) {{
              return '<div class="bb-school-item">'
                + '<div><span class="bb-school-item-name">' + s.name + '</span>'
                + '<br><span class="bb-school-item-slug">' + s.slug + '</span></div>'
                + '<button class="bb-school-btn ' + btnClass + '" onclick="' + onclick + '">' + btnLabel + '</button>'
                + '</div>';
            }}

            var assignedList = document.getElementById('bb-assigned-list');
            var availableList = document.getElementById('bb-available-list');
            assignedList.innerHTML = assigned.length
              ? assigned.map(function(s){{ return schoolItem(s,'remove','Remove',
                  'bbSchoolAction(' + JSON.stringify(s.slug) + ',null,' + districtId + ')'); }}).join('')
              : '<div class="bb-empty-state">No schools assigned yet.</div>';
            availableList.innerHTML = available.length
              ? available.map(function(s){{ return schoolItem(s,'add','Add',
                  'bbSchoolAction(' + JSON.stringify(s.slug) + ',' + districtId + ',null)'); }}).join('')
              : '<div class="bb-empty-state">All schools are assigned.</div>';
          }}

          function bbSchoolAction(schoolSlug, assignToDistrictId, removeFromDistrictId) {{
            var fd = new FormData();
            var url, newDistrictId;
            if (assignToDistrictId) {{
              fd.append('district_id', assignToDistrictId);
              url = '/super-admin/schools/' + schoolSlug + '/assign-district';
              newDistrictId = assignToDistrictId;
            }} else {{
              url = '/super-admin/schools/' + schoolSlug + '/remove-district';
              newDistrictId = null;
            }}
            fetch(url, {{method:'POST', body:fd, headers:{{'X-Requested-With':'XMLHttpRequest'}}}})
              .then(function(r){{return r.json();}})
              .then(function(d){{
                if (d.ok) {{
                  /* Update local school list */
                  var all = window._bbAllSchools || [];
                  all.forEach(function(s){{ if (s.slug === schoolSlug) s.district_id = newDistrictId; }});
                  bbRefreshSchoolLists(_bbManageDistrictId);
                  /* Update school count badge on card */
                  var card = document.querySelector('[data-district-slug="' + _bbManageSlug + '"]');
                  if (card) {{
                    var metaEl = card.querySelector('.district-card-meta strong');
                    if (metaEl) {{
                      var count = parseInt(metaEl.textContent) || 0;
                      metaEl.textContent = assignToDistrictId ? count + 1 : Math.max(0, count - 1);
                    }}
                  }}
                }} else {{
                  bbShowBanner('bb-manage-schools-banner', d.detail || d.error || 'Action failed.', true);
                }}
              }})
              .catch(function(){{ bbShowBanner('bb-manage-schools-banner', 'Network error.', true); }});
          }}
          </script>

          <!-- Create District Modal -->
          <div id="bb-create-district-modal" class="bb-modal-overlay" style="display:none;" onclick="if(event.target===this)bbCloseModal('bb-create-district-modal')">
            <div class="bb-modal">
              <button class="bb-modal-close" onclick="bbCloseModal('bb-create-district-modal')">&times;</button>
              <p class="bb-modal-title">Create District</p>
              <div id="bb-create-district-banner" class="bb-banner"></div>
              <div class="bb-field">
                <label>District Name</label>
                <input id="bb-create-district-name" type="text" placeholder="e.g. Maryville R-II School District" />
              </div>
              <div class="bb-field">
                <label>Slug <span style="font-weight:400;text-transform:none;letter-spacing:0;">(auto-generated, can edit)</span></label>
                <input id="bb-create-district-slug" type="text" placeholder="maryville-r-ii" />
              </div>
              <div class="bb-field" id="bb-create-org-field">
                <label>Organization</label>
                <select id="bb-create-district-org"><option value="">Loading…</option></select>
              </div>
              <div style="display:flex;gap:10px;margin-top:6px;">
                <button class="button button-primary" onclick="bbSubmitCreateDistrict()" id="bb-create-district-btn">Create District</button>
                <button class="button button-secondary" onclick="bbCloseModal('bb-create-district-modal')">Cancel</button>
              </div>
            </div>
          </div>

          <!-- Edit District Modal -->
          <div id="bb-edit-district-modal" class="bb-modal-overlay" style="display:none;" onclick="if(event.target===this)bbCloseModal('bb-edit-district-modal')">
            <div class="bb-modal">
              <button class="bb-modal-close" onclick="bbCloseModal('bb-edit-district-modal')">&times;</button>
              <p class="bb-modal-title">Edit District</p>
              <div id="bb-edit-district-banner" class="bb-banner"></div>
              <div class="bb-field">
                <label>District Name</label>
                <input id="bb-edit-district-name" type="text" />
              </div>
              <div class="bb-field">
                <label>Slug</label>
                <input id="bb-edit-district-slug" type="text" />
              </div>
              <div style="display:flex;gap:10px;margin-top:6px;">
                <button class="button button-primary" onclick="bbSubmitEditDistrict()" id="bb-edit-district-btn">Save Changes</button>
                <button class="button button-secondary" onclick="bbCloseModal('bb-edit-district-modal')">Cancel</button>
              </div>
            </div>
          </div>

          <!-- Manage Schools Modal -->
          <div id="bb-manage-schools-modal" class="bb-modal-overlay" style="display:none;" onclick="if(event.target===this)bbCloseModal('bb-manage-schools-modal')">
            <div class="bb-modal bb-modal-wide">
              <button class="bb-modal-close" onclick="bbCloseModal('bb-manage-schools-modal')">&times;</button>
              <p class="bb-modal-title" id="bb-manage-schools-title">Manage Schools</p>
              <div id="bb-manage-schools-banner" class="bb-banner"></div>
              <div class="bb-dual-list">
                <div class="bb-dual-col">
                  <p class="bb-dual-col-title">Assigned to this district</p>
                  <div class="bb-school-list" id="bb-assigned-list"><div class="bb-empty-state">Loading…</div></div>
                </div>
                <div class="bb-dual-col">
                  <p class="bb-dual-col-title">Available (unassigned)</p>
                  <div class="bb-school-list" id="bb-available-list"><div class="bb-empty-state">Loading…</div></div>
                </div>
              </div>
              <p style="font-size:0.75rem;color:var(--muted);margin-top:12px;">Changes apply immediately. Refresh the page to see updated school counts on district cards.</p>
            </div>
          </div>

          <!-- Generate License Modal -->
          <div id="bb-gen-license-modal" class="bb-modal-overlay" style="display:none;" onclick="if(event.target===this)bbCloseModal('bb-gen-license-modal')">
            <div class="bb-modal">
              <button class="bb-modal-close" onclick="bbCloseModal('bb-gen-license-modal')">&times;</button>
              <p class="bb-modal-title" id="bb-gen-license-title">Generate License</p>
              <div id="bb-gen-license-banner" class="bb-banner"></div>
              <div id="bb-gen-license-key-result" style="display:none;margin-bottom:14px;padding:12px 14px;background:var(--bg);border:1.5px solid var(--accent);border-radius:10px;">
                <p style="font-size:0.75rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.06em;margin:0 0 6px;">License Key</p>
                <p id="bb-gen-license-key-text" style="font-family:monospace;font-size:1rem;font-weight:700;color:var(--text);letter-spacing:0.08em;margin:0 0 8px;word-break:break-all;"></p>
                <button class="button button-secondary" style="font-size:0.75rem;padding:4px 12px;" onclick="bbCopyLicenseKey()">Copy Key</button>
              </div>
              <div id="bb-gen-license-form">
                <div class="bb-field">
                  <label>Plan Type</label>
                  <select id="bb-gen-plan">
                    <option value="trial">Trial</option>
                    <option value="basic">Basic</option>
                    <option value="pro" selected>Pro</option>
                    <option value="enterprise">Enterprise</option>
                  </select>
                </div>
                <div class="bb-field">
                  <label>Start Date</label>
                  <input id="bb-gen-starts" type="date" />
                </div>
                <div class="bb-field">
                  <label>Expiration Date <span style="font-weight:400;text-transform:none;">(optional)</span></label>
                  <input id="bb-gen-expires" type="date" />
                </div>
                <div class="bb-field">
                  <label>Customer Name <span style="font-weight:400;text-transform:none;">(optional)</span></label>
                  <input id="bb-gen-cname" type="text" placeholder="e.g. Maryville R-II" />
                </div>
                <div class="bb-field">
                  <label>Customer Email <span style="font-weight:400;text-transform:none;">(optional)</span></label>
                  <input id="bb-gen-cemail" type="email" placeholder="admin@district.edu" />
                </div>
                <div style="display:flex;gap:10px;margin-top:6px;">
                  <button class="button button-primary" onclick="bbSubmitGenLicense()" id="bb-gen-license-btn">Generate License</button>
                  <button class="button button-secondary" onclick="bbCloseModal('bb-gen-license-modal')">Cancel</button>
                </div>
              </div>
            </div>
          </div>
          <script>
          var _bbGenLicenseSlug = null;
          var _bbGenLicenseKey = null;

          function bbOpenGenLicenseModal(slug, name) {{
            _bbGenLicenseSlug = slug;
            _bbGenLicenseKey = null;
            bbClearBanner('bb-gen-license-banner');
            document.getElementById('bb-gen-license-title').textContent = 'Generate License — ' + name;
            document.getElementById('bb-gen-license-key-result').style.display = 'none';
            document.getElementById('bb-gen-license-form').style.display = '';
            document.getElementById('bb-gen-license-btn').disabled = false;
            document.getElementById('bb-gen-license-btn').textContent = 'Generate License';
            /* Set today as default start */
            var today = new Date().toISOString().slice(0,10);
            document.getElementById('bb-gen-starts').value = today;
            document.getElementById('bb-gen-expires').value = '';
            document.getElementById('bb-gen-cname').value = name || '';
            document.getElementById('bb-gen-cemail').value = '';
            document.getElementById('bb-gen-license-modal').style.display = 'flex';
          }}

          function bbSubmitGenLicense() {{
            if (!_bbGenLicenseSlug) return;
            var btn = document.getElementById('bb-gen-license-btn');
            btn.disabled = true; btn.textContent = 'Generating…';
            var fd = new FormData();
            fd.append('plan_type', document.getElementById('bb-gen-plan').value);
            fd.append('starts_at', document.getElementById('bb-gen-starts').value);
            var exp = document.getElementById('bb-gen-expires').value;
            if (exp) fd.append('current_period_end', exp);
            var cn = document.getElementById('bb-gen-cname').value.trim();
            var ce = document.getElementById('bb-gen-cemail').value.trim();
            if (cn) fd.append('customer_name', cn);
            if (ce) fd.append('customer_email', ce);
            fetch('/super-admin/districts/' + _bbGenLicenseSlug + '/billing/generate-license',
              {{method:'POST', body:fd, headers:{{'X-Requested-With':'XMLHttpRequest'}}}})
              .then(function(r){{return r.json();}})
              .then(function(d){{
                btn.disabled = false; btn.textContent = 'Generate License';
                if (d.ok || d.license_key) {{
                  var key = d.license_key || '';
                  _bbGenLicenseKey = key;
                  document.getElementById('bb-gen-license-key-text').textContent = key;
                  document.getElementById('bb-gen-license-key-result').style.display = 'block';
                  document.getElementById('bb-gen-license-form').style.display = 'none';
                  bbShowBanner('bb-gen-license-banner', 'License generated and assigned to ' + _bbGenLicenseSlug + '.', false);
                  /* Update billing meta on card */
                  var card = document.querySelector('[data-district-slug="' + _bbGenLicenseSlug + '"]');
                  if (card) {{
                    var metaSpan = card.querySelector('[data-billing-meta]');
                    if (metaSpan) {{
                      metaSpan.innerHTML = '<span style="font-size:0.7rem;font-weight:700;color:#059669;">ACTIVE</span>'
                        + ' <span style="font-size:0.72rem;color:var(--muted);">·</span>'
                        + ' <span style="font-size:0.72rem;color:var(--muted);">'
                        + document.getElementById('bb-gen-plan').value.charAt(0).toUpperCase()
                        + document.getElementById('bb-gen-plan').value.slice(1) + '</span>';
                    }}
                  }}
                }} else {{
                  bbShowBanner('bb-gen-license-banner', d.detail || d.error || 'Generation failed.', true);
                }}
              }})
              .catch(function(){{
                btn.disabled = false; btn.textContent = 'Generate License';
                bbShowBanner('bb-gen-license-banner', 'Network error.', true);
              }});
          }}

          function bbCopyLicenseKey() {{
            if (!_bbGenLicenseKey) return;
            navigator.clipboard.writeText(_bbGenLicenseKey)
              .then(function(){{ bbShowBanner('bb-gen-license-banner', 'License key copied to clipboard.', false); }})
              .catch(function(){{
                prompt('Copy this license key:', _bbGenLicenseKey);
              }});
          }}
          </script>

        </section>
        <section class="panel command-section" id="schools"{_section_style("schools")}>
          <div class="panel-header hero-band">
            <div>
              <p class="eyebrow">Tenant Registry</p>
              <h1>Schools</h1>
              <p class="hero-copy">Each school gets its own path and isolated database. School admins still manage their own users from their tenant dashboard.</p>
            </div>
            <div class="status-row">
              <span class="status-pill ok"><strong>Base domain</strong>{escape(base_domain)}</span>
              <span class="status-pill"><strong>Active</strong>{len(_active_school_rows)}</span>
              {f'<span class="status-pill warn"><strong>Archived</strong>{len(_archived_school_rows)}</span>' if _archived_school_rows else ''}
              <span class="status-pill {'ok' if git_pull_configured else 'danger'}"><strong>Git pull</strong>{'configured' if git_pull_configured else 'not configured'}</span>
            </div>
          </div>
          <div class="tenant-search">
            <input type="search" id="school-search" placeholder="Filter schools by name or slug..." style="max-width:340px;" />
          </div>
          <div class="tenant-grid" id="schools-grid">
            {active_school_cards_html}
          </div>
          {_archived_schools_section_html}
        </section>
        <section class="panel command-section" id="billing"{_section_style("billing")}>
          <div class="panel-header hero-band">
            <div>
              <p class="eyebrow">Licensing</p>
              <h1>Licensing</h1>
              <p class="hero-copy">Manage district and school licenses. District licenses cover all schools in the district. School licenses apply to unassigned schools.</p>
            </div>
            <div class="status-row">
              <span class="status-pill {'ok' if _lic_active > 0 else ''}"><strong>Active</strong>{_lic_active}</span>
              <span class="status-pill {'danger' if _lic_expired > 0 else ''}"><strong>Expired</strong>{_lic_expired}</span>
              {f'<span class="status-pill warn"><strong>Archived</strong>{_lic_archived}</span>' if _lic_archived > 0 else ''}
              <span class="status-pill"><strong>Schools</strong>{len(billing_rows)}</span>
            </div>
          </div>
          {_render_district_billing_section(district_billing_rows, archived_district_billing_rows)}
          {_render_billing_cards(billing_rows)}
          {_render_district_billing_audit_trail(billing_audit_rows)}
        </section>
        <section class="panel command-section" id="platform-audit"{_section_style("platform-audit")}>
          <div class="panel-header">
            <div>
              <p class="eyebrow">Audit</p>
              <h2>Platform super-admin activity</h2>
              <p class="card-copy">Cross-school activity feed for actions performed while operating as platform super admin.</p>
            </div>
          </div>
          <table class="data-table">
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
        <section class="panel command-section" id="health"{_section_style("health")}>
          <div class="panel-header hero-band">
            <div>
              <p class="eyebrow">Platform</p>
              <h1>System Health</h1>
              <p class="hero-copy">Background heartbeat monitor checks DB, WebSocket connections, and push provider config every 60 seconds.</p>
            </div>
            <div class="status-row">
              <span class="status-pill {_hs_pill_cls}"><strong>Status</strong>{escape(_hs_overall)}</span>
              <span class="status-pill"><strong>24h uptime</strong>{_hs_uptime_24}</span>
              <span class="status-pill"><strong>7d uptime</strong>{_hs_uptime_7d}</span>
            </div>
          </div>
          {_hs_error_html}
          <div class="metrics-grid" style="margin-bottom:20px;">
            <article class="metric-card">
              <div class="meta">Last heartbeat</div>
              <div class="metric-value" style="font-size:1.1rem;">{_hs_last}</div>
              <p class="mini-copy">{_hs_since}</p>
            </article>
            <article class="metric-card">
              <div class="meta">DB ping</div>
              <div class="metric-value" style="font-size:1.1rem;">{_hs_rtt}</div>
              <p class="mini-copy"><span class="status-pill {_hs_db_cls}">{_hs_db_text}</span></p>
            </article>
            <article class="metric-card">
              <div class="meta">WebSocket connections</div>
              <div class="metric-value" style="font-size:1.3rem;">{_hs_ws}</div>
            </article>
            <article class="metric-card">
              <div class="meta">APNs</div>
              <div class="metric-value" style="font-size:1.1rem;">{_hs_apns}</div>
            </article>
            <article class="metric-card">
              <div class="meta">FCM</div>
              <div class="metric-value" style="font-size:1.1rem;">{_hs_fcm}</div>
            </article>
          </div>
          <div class="panel-header" style="margin-top:10px; margin-bottom:10px;">
            <div>
              <h2>Recent heartbeats</h2>
              <p class="card-copy">Last 20 background checks, newest first.</p>
            </div>
          </div>
          <div class="table-wrap"><table class="data-table">
            <thead>
              <tr><th>Time (UTC)</th><th>Status</th><th>DB latency</th><th>DB</th><th>WS</th><th>APNs</th><th>FCM</th><th>Note</th></tr>
            </thead>
            <tbody>{_hb_rows_html}</tbody>
          </table></div>
        </section>
        {_render_sales_inbox_section(inbox_messages, section, inbox_unread_count)}
        {_render_inquiries_section(inquiries, section)}
        {_render_demo_requests_section(demo_requests, section)}
        {_render_customers_section(customers, section)}
        <section class="panel command-section" id="email-tool"{_section_style("email-tool")}>
          <div class="panel-header hero-band">
            <div>
              <p class="eyebrow">Communications</p>
              <h1>Email Tool</h1>
              <p class="hero-copy">Send platform admin notifications and test SMTP configuration. Entirely separate from emergency alert delivery — never affects APNs, FCM, or Twilio.</p>
            </div>
            <div class="status-row">
              <span class="status-pill {_et_pill_cls}"><strong>SMTP</strong>{_et_status_text}</span>
            </div>
          </div>
          {_et_not_configured_html}
          <div class="metrics-grid" style="margin-bottom:20px;">
            <article class="metric-card" style="grid-column:span 2;">
              <div class="meta">Platform admin emails</div>
              <div style="margin-top:8px;">{_et_admin_emails_html}</div>
            </article>
          </div>
          <div class="form-grid" style="gap:24px; align-items:start; grid-template-columns:1fr 1fr; margin-bottom:24px;">
            <div class="stack">
              <h3 style="margin-bottom:8px;">Test SMTP</h3>
              <p class="mini-copy" style="margin-bottom:12px;">Send a test email to verify SMTP settings are working.</p>
              <form method="post" action="/super-admin/health/email/test" class="stack">
                <div class="field">
                  <label for="test_email">Recipient address</label>
                  <input id="test_email" name="test_email" type="email" placeholder="you@example.com" {_et_disabled} />
                </div>
                <div class="button-row">
                  <button class="button button-secondary" type="submit" {_et_disabled}>Send test</button>
                </div>
              </form>
            </div>
            <div class="stack">
              <h3 style="margin-bottom:8px;">Send template</h3>
              <p class="mini-copy" style="margin-bottom:12px;">Send a platform notification to one or more addresses.</p>
              <form method="post" action="/super-admin/health/email/send" class="stack">
                <div class="field">
                  <label for="et_template">Template</label>
                  <select id="et_template" name="template_key" {_et_disabled}>{_et_template_options}</select>
                </div>
                <div class="field">
                  <label for="et_subject">Subject override <span class="mini-copy">(optional)</span></label>
                  <input id="et_subject" name="custom_subject" placeholder="Leave blank to use template" {_et_disabled} />
                </div>
                <div class="field">
                  <label for="et_body">Body override <span class="mini-copy">(optional)</span></label>
                  <textarea id="et_body" name="custom_body" rows="4" placeholder="Leave blank to use template" {_et_disabled}></textarea>
                </div>
                <div class="field">
                  <label for="et_addresses">Recipients <span class="mini-copy">(comma or newline-separated)</span></label>
                  <textarea id="et_addresses" name="to_addresses" rows="3" placeholder="admin@school.org, it@district.edu" {_et_disabled}></textarea>
                </div>
                <div class="button-row">
                  <button class="button button-primary" type="submit" {_et_disabled}>Send</button>
                </div>
              </form>
            </div>
          </div>
          <div class="panel-header" style="margin-top:10px; margin-bottom:10px;">
            <div>
              <h2>Email log</h2>
              <p class="card-copy">Last 50 platform emails, newest first. Automatically pruned to 500 records.</p>
            </div>
          </div>
          <div class="table-wrap"><table class="data-table">
            <thead>
              <tr><th>Time (UTC)</th><th>Type</th><th>To</th><th>Subject</th><th>Result</th><th>Error</th></tr>
            </thead>
            <tbody>{_et_log_rows}</tbody>
          </table></div>
        </section>
        <section class="panel command-section" id="configuration"{_section_style("configuration")}>
          <div class="panel-header hero-band">
            <div>
              <p class="eyebrow">Configuration</p>
              <h1>Platform Settings</h1>
              <p class="hero-copy">Manage runtime communication settings for the super admin console without editing the server environment.</p>
            </div>
            <div class="status-row">
              <span class="status-pill {_et_pill_cls}"><strong>SMTP</strong>{_et_status_text}</span>
              <span class="status-pill {_smtp_password_cls}"><strong>App password</strong>{_smtp_password_status}</span>
            </div>
          </div>
          <div class="form-grid" style="gap:24px; align-items:start; grid-template-columns:minmax(0,1.2fr) minmax(280px,.8fr);">
            <div class="stack" style="margin-bottom:28px;border:1px solid var(--border);border-radius:10px;padding:20px;">
              <div class="panel-header" style="margin-bottom:12px;">
                <div>
                  <h2>Gmail Settings {_gmail_configured_pill}</h2>
                  <p class="card-copy">Simple Gmail + App Password setup. Covers 99% of cases — use the SMTP form below for non-Gmail senders.</p>
                </div>
              </div>
              <div class="metrics-grid" style="margin-bottom:16px;">
                <article class="metric-card">
                  <div class="meta">Gmail address</div>
                  <div style="font-weight:700;">{_gmail_address or "—"}</div>
                </article>
                <article class="metric-card">
                  <div class="meta">App password</div>
                  <div class="metric-value"><span class="status-pill {_gmail_pw_cls}">{_gmail_pw_status}</span></div>
                </article>
                <article class="metric-card">
                  <div class="meta">Last updated</div>
                  <div style="font-size:0.85rem;">{_gmail_updated}</div>
                  <div class="mini-copy">by {_gmail_updated_by}</div>
                </article>
              </div>
              <form method="post" action="/super-admin/email-settings" class="stack">
                <div class="form-grid">
                  <div class="field">
                    <label for="gmail_address">Gmail address</label>
                    <input id="gmail_address" name="gmail_address" type="email" value="{_gmail_address}" placeholder="yourname@gmail.com" autocomplete="username" />
                  </div>
                  <div class="field">
                    <label for="from_name">From name</label>
                    <input id="from_name" name="from_name" value="{_gmail_from_name}" placeholder="BlueBird Alerts" />
                  </div>
                </div>
                <div class="field">
                  <label for="app_password">Google app password</label>
                  <input id="app_password" name="app_password" type="password" placeholder="Leave blank to keep existing password" autocomplete="new-password" />
                </div>
                <div class="button-row">
                  <button class="button button-primary" type="submit">Save Gmail Settings</button>
                </div>
              </form>
              <form method="post" action="/super-admin/email-settings/test" class="stack" style="margin-top:12px;">
                <div class="field">
                  <label for="gmail_test_email">Send test email to</label>
                  <input id="gmail_test_email" name="test_email" type="email" placeholder="you@example.com" autocomplete="off" />
                </div>
                <div class="button-row">
                  <button class="button button-secondary" type="submit">Send Test Email</button>
                </div>
              </form>
            </div>
            <form method="post" action="/super-admin/configuration/smtp" class="stack">
              <div class="panel-header" style="margin-bottom:4px;">
                <div>
                  <h2>Google Workspace SMTP</h2>
                  <p class="card-copy">Use a Google app password for authenticated mail through Gmail SMTP.</p>
                </div>
              </div>
              <div class="form-grid">
                <div class="field">
                  <label for="smtp_host">SMTP host</label>
                  <input id="smtp_host" name="smtp_host" value="{escape(_smtp.host or 'smtp.gmail.com')}" placeholder="smtp.gmail.com" autocomplete="off" />
                </div>
                <div class="field">
                  <label for="smtp_port">Port</label>
                  <input id="smtp_port" name="smtp_port" type="number" min="1" max="65535" value="{int(_smtp.port or 587)}" />
                </div>
                <div class="field">
                  <label for="smtp_username">Google Workspace email</label>
                  <input id="smtp_username" name="smtp_username" type="email" value="{escape(_smtp.username)}" placeholder="alerts@yourdomain.org" autocomplete="username" />
                </div>
                <div class="field">
                  <label for="smtp_from">From address</label>
                  <input id="smtp_from" name="smtp_from" type="email" value="{escape(_smtp.from_address)}" placeholder="alerts@yourdomain.org" autocomplete="email" />
                </div>
              </div>
              <div class="field">
                <label for="smtp_password">Google app password</label>
                <input id="smtp_password" name="smtp_password" type="password" placeholder="Leave blank to keep the saved password" autocomplete="new-password" />
              </div>
              <label class="mini-copy" style="display:flex;align-items:center;gap:8px;font-weight:700;color:var(--text);">
                <input name="smtp_use_tls" type="checkbox" value="1" {_smtp_tls_checked} style="width:auto;" />
                Use TLS / STARTTLS
              </label>
              <label class="mini-copy" style="display:flex;align-items:center;gap:8px;color:var(--muted);">
                <input name="clear_smtp_password" type="checkbox" value="1" style="width:auto;" />
                Clear saved app password
              </label>
              <div class="button-row">
                <button class="button button-primary" type="submit">Save SMTP Settings</button>
                <a class="button button-secondary" href="/super-admin?section=email-tool#email-tool">Open Email Tool</a>
              </div>
            </form>
            <div class="metrics-grid">
              <article class="metric-card" style="grid-column:1 / -1;">
                <div class="meta">Gmail defaults</div>
                <div style="margin-top:8px;font-weight:700;">smtp.gmail.com &middot; port 587 &middot; TLS on</div>
                <p class="mini-copy">The username, from address, and Google app password should usually belong to the same Workspace mailbox.</p>
              </article>
              <article class="metric-card" style="grid-column:1 / -1;">
                <div class="meta">Password handling</div>
                <div style="margin-top:8px;font-weight:700;">Saved in the platform database</div>
                <p class="mini-copy">For now this stores the app password so the backend can send mail after restarts. Use a dedicated Google app password, not your normal account password.</p>
              </article>
            </div>
          </div>
          <hr style="margin:28px 0;border:none;border-top:1px solid var(--border);" />
          <div id="email-delivery-subsection">
            {_render_email_delivery_section(email_delivery_settings, auto_reply_settings, "configuration")}
          </div>
          <hr style="margin:28px 0;border:none;border-top:1px solid var(--border);" />
          <div id="stripe-billing-subsection">
            {_render_stripe_section(stripe_settings, billing_plans, "configuration")}
          </div>
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

        <section class="panel command-section" id="sandbox"{_section_style("sandbox")}>
          <div class="panel-header">
            <div>
              <p class="eyebrow">Sandbox</p>
              <h2>Test &amp; Demo Environments</h2>
              <p class="card-copy">Clone a production district into an isolated test environment. Simulation mode suppresses all real push/SMS/APNs delivery. No production data is ever touched.</p>
            </div>
          </div>

          <div class="flash warning" style="margin-bottom:20px;">
            <strong>Safety:</strong> Test environments are hard-isolated from production. Push, SMS, and APNs are blocked when simulation mode is on.
          </div>

          <h3 style="margin-bottom:12px;">Clone production district into sandbox</h3>
          <form method="post" class="stack" style="max-width:560px;margin-bottom:32px;">
            <div class="form-grid">
              <div class="field">
                <label>Source district</label>
                <select name="district_id" id="sandbox-district-select" required>
                  <option value="">— select —</option>
                  {_sandbox_district_options(prod_districts)}
                </select>
              </div>
              <div class="field">
                <label>Test district slug</label>
                <input name="test_slug" placeholder="test-north-high" required />
              </div>
              <div class="field">
                <label>Test district name (optional)</label>
                <input name="test_name" placeholder="[TEST] North High" />
              </div>
            </div>
            <div class="button-row">
              <button class="button button-primary" type="submit" id="sandbox-clone-btn"
                onclick="var sel=document.getElementById('sandbox-district-select');if(!sel.value){{return false;}}this.form.action='/super-admin/districts/'+sel.value+'/clone-test';">
                Clone to Sandbox
              </button>
            </div>
          </form>

          <h3 style="margin-bottom:12px;">Sandbox environments</h3>
          {_sandbox_district_cards(sandbox_data)}
        </section>

        <section class="panel command-section" id="setup-codes"{_section_style("setup-codes")}>
          <div class="panel-header">
            <div>
              <p class="eyebrow">Setup Codes</p>
              <h2>District admin bootstrap codes</h2>
              <p class="card-copy">Generate a single-use setup code for a school. The first district admin uses this to create their account.</p>
            </div>
          </div>
          <form method="post" action="/super-admin/setup-codes/generate" class="stack" style="max-width:480px;margin-bottom:28px;">
            <div class="form-grid">
              <div class="field">
                <label>School slug</label>
                <input name="tenant_slug" placeholder="north-high" required />
              </div>
              <div class="field">
                <label>Expires (hours)</label>
                <input name="expires_hours" type="number" min="1" max="8760" value="168" />
              </div>
            </div>
            <div class="button-row">
              <button class="button button-primary" type="submit">Generate Setup Code</button>
            </div>
          </form>
          <div class="table-wrapper">
            <table class="data-table">
              <thead>
                <tr><th>Code</th><th>School</th><th>Slug</th><th>Status</th><th>Expires</th><th>Uses</th><th></th></tr>
              </thead>
              <tbody>{setup_code_rows}</tbody>
            </table>
          </div>
        </section>

        <section class="panel command-section" id="ai-insights"{_section_style("ai-insights")}>
          <div class="panel-header">
            <div>
              <p class="eyebrow">Developer Tool</p>
              <h2>🧠 AI Insights</h2>
              <p class="card-copy">Local AI analysis using Llama3 via Ollama. Each analysis is scoped to a single tenant and uses aggregate statistics only — no raw logs or PII. Disabled by default.</p>
            </div>
          </div>

          <div class="flash warning" style="margin-bottom:20px;">
            <strong>Setup required:</strong> Run <code>bash scripts/install_ollama.sh</code> then set
            <code>AI_INSIGHTS_GLOBAL_ENABLED=true</code> in your environment to activate the background job.
          </div>

          <h3 style="margin-bottom:12px;">Per-Tenant Toggles</h3>
          <p class="mini-copy" style="margin-bottom:16px;">Enable AI Insights for individual tenants. Changes take effect on the next background job run (every 10 min).</p>

          <div style="overflow-x:auto;margin-bottom:32px;">
            <table class="data-table" style="min-width:560px;">
              <thead><tr>
                <th>School</th>
                <th>Slug</th>
                <th>AI Insights</th>
                <th>Health / Trend</th>
                <th>Actions</th>
              </tr></thead>
              <tbody id="ai-insights-tenant-table">
                {_ai_insights_tenant_rows_html}
              </tbody>
            </table>
          </div>

          <div id="ai-insights-panel" style="display:none;margin-top:24px;">
            <h3 id="ai-insights-panel-title" style="margin-bottom:12px;">Recent Insights</h3>
            <div id="ai-insights-panel-body" style="font-size:0.9rem;"></div>
          </div>

          <div id="ai-reports-panel" style="display:none;margin-top:24px;">
            <h3 id="ai-reports-panel-title" style="margin-bottom:12px;">Weekly Reports</h3>
            <div id="ai-reports-panel-body" style="font-size:0.9rem;"></div>
          </div>

          <details style="margin-top:32px;">
            <summary style="cursor:pointer;font-size:0.85rem;color:var(--muted);padding:8px 0;">&#9658; AI Debug Logs (raw prompt/response)</summary>
            <div style="margin-top:12px;">
              <p class="mini-copy" style="margin-bottom:12px;">Only populated when Debug Mode is enabled for a tenant. Prompts are anonymized aggregate statistics.</p>
              <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;" id="ai-debug-slug-btns">
                {_ai_insights_debug_btns_html}
              </div>
              <div id="ai-debug-panel" style="font-size:0.85rem;"></div>
            </div>
          </details>

          <script>
          function bbAiToggle(slug, kind) {{
            var url = '/super-admin/tenants/' + encodeURIComponent(slug) + '/ai-insights/'
              + (kind === 'debug' ? 'debug-toggle' : 'toggle');
            fetch(url, {{method:'POST', headers:{{'Content-Type':'application/x-www-form-urlencoded'}}}})
              .then(function(r) {{ return r.json(); }})
              .then(function(d) {{
                if (kind === 'debug') {{
                  var el = document.getElementById('ai-debug-' + slug);
                  if (el) el.textContent = d.debug_mode ? '✓ ON' : 'OFF';
                }} else {{
                  var el = document.getElementById('ai-enabled-' + slug);
                  if (el) el.textContent = d.ai_insights_enabled ? '✓ ON' : 'OFF';
                  if (!d.global_enabled) {{
                    alert('AI Insights toggled for "' + slug + '" but the global toggle is OFF.\\n\\nSet AI_INSIGHTS_GLOBAL_ENABLED=true in your environment to activate the background job.');
                  }}
                }}
              }})
              .catch(function(e) {{ alert('Error: ' + e); }});
          }}
          var _BB_CAT_COLOR = {{security:'#dc2626', performance:'#d97706', readiness:'#2563eb'}};
          var _BB_CAT_ICON  = {{security:'🔒', performance:'⚡', readiness:'✅'}};
          function _bbConfBar(pct, color) {{
            return '<div title="' + pct + '%" style="background:var(--border);border-radius:3px;height:6px;width:100px;display:inline-block;vertical-align:middle;overflow:hidden;">'
              + '<div style="width:' + pct + '%;height:100%;background:' + color + ';transition:width .3s;"></div></div>';
          }}
          function _bbConfColor(pct) {{
            return pct >= 80 ? '#16a34a' : (pct >= 60 ? '#d97706' : '#dc2626');
          }}
          function _bbHealthColor(score) {{
            return score >= 80 ? '#16a34a' : (score >= 60 ? '#d97706' : '#dc2626');
          }}
          function bbAiViewHealth(slug) {{
            var cell = document.getElementById('ai-health-cell-' + slug);
            if (cell) cell.textContent = 'Loading…';
            fetch('/super-admin/tenants/' + encodeURIComponent(slug) + '/ai-insights/health')
              .then(function(r) {{ return r.json(); }})
              .then(function(d) {{
                if (!cell) return;
                if (d.health_score == null) {{
                  cell.innerHTML = '<span style="color:var(--muted);font-size:0.8rem;">No data yet</span>';
                  return;
                }}
                var hc = _bbHealthColor(d.health_score);
                var arrow = d.trend_arrow || '→';
                cell.innerHTML = '<span style="font-weight:700;color:' + hc + ';font-size:1rem;">' + d.health_score + '</span>'
                  + '<span style="font-size:0.9rem;margin-left:4px;">/100</span>'
                  + ' <span style="font-size:1rem;" title="' + (d.trend||'stable') + '">' + arrow + '</span>';
              }})
              .catch(function() {{ if(cell) cell.textContent = 'Error'; }});
          }}
          function bbAiViewReports(slug) {{
            var panel = document.getElementById('ai-reports-panel');
            var title = document.getElementById('ai-reports-panel-title');
            var body = document.getElementById('ai-reports-panel-body');
            document.getElementById('ai-insights-panel').style.display = 'none';
            panel.style.display = 'block';
            title.textContent = 'Weekly Reports — ' + slug;
            body.textContent = 'Loading…';
            fetch('/super-admin/tenants/' + encodeURIComponent(slug) + '/ai-insights/reports')
              .then(function(r) {{ return r.json(); }})
              .then(function(d) {{
                if (!d.reports || !d.reports.length) {{
                  body.innerHTML = '<p class="mini-copy">No weekly reports yet. Reports are generated automatically each week when AI Insights is enabled.</p>';
                  return;
                }}
                var html = '';
                d.reports.forEach(function(rep) {{
                  var hc = _bbHealthColor(rep.health_score);
                  html += '<div style="border:1px solid var(--border);border-radius:8px;padding:14px 16px;margin-bottom:12px;">'
                    + '<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap;">'
                    + '<strong>Week of ' + rep.week_start + '</strong>'
                    + '<span style="font-weight:700;color:' + hc + ';">' + rep.health_score + '/100</span>'
                    + '<span title="' + (rep.trend||'stable') + '">' + (rep.trend_arrow||'→') + ' ' + (rep.trend||'stable') + '</span>'
                    + '<span style="font-size:0.75rem;color:var(--muted);">Generated: ' + rep.generated_at.slice(0,10) + '</span>'
                    + '</div>'
                    + '<p style="margin:0 0 8px;">' + rep.summary + '</p>';
                  if (rep.recommendations && rep.recommendations.length) {{
                    html += '<ul style="margin:0;padding-left:18px;">';
                    rep.recommendations.forEach(function(r) {{ html += '<li style="font-size:0.85rem;">' + r + '</li>'; }});
                    html += '</ul>';
                  }}
                  html += '</div>';
                }});
                body.innerHTML = html;
              }})
              .catch(function(e) {{ body.textContent = 'Error: ' + e; }});
          }}
          function bbAiViewInsights(slug) {{
            var panel = document.getElementById('ai-insights-panel');
            var title = document.getElementById('ai-insights-panel-title');
            var body = document.getElementById('ai-insights-panel-body');
            document.getElementById('ai-reports-panel').style.display = 'none';
            panel.style.display = 'block';
            title.textContent = 'Recent Insights — ' + slug;
            body.textContent = 'Loading…';
            fetch('/super-admin/tenants/' + encodeURIComponent(slug) + '/ai-insights')
              .then(function(r) {{ return r.json(); }})
              .then(function(d) {{
                if (!d.insights || !d.insights.length) {{
                  body.innerHTML = '<p class="mini-copy">No insights yet (or all were filtered by confidence threshold). Enable AI Insights and wait for the next background run.</p>';
                  return;
                }}
                var html = '';
                d.insights.forEach(function(ins) {{
                  var sev = ins.severity || 'info';
                  var sevColor = sev === 'critical' ? '#dc2626' : (sev === 'warning' ? '#d97706' : '#16a34a');
                  var conf = ins.final_confidence != null ? ins.final_confidence : 50;
                  var confColor = _bbConfColor(conf);
                  var confLabel = ins.confidence_label || (conf >= 80 ? 'High' : (conf >= 60 ? 'Needs Review' : 'Low'));
                  var needsReview = ins.needs_review;
                  var cat = ins.category || 'readiness';
                  var catColor = _BB_CAT_COLOR[cat] || '#6b7280';
                  var catIcon = _BB_CAT_ICON[cat] || '📊';
                  var trendArrow = ins.trend_arrow || '→';
                  var hs = ins.health_score != null ? ins.health_score : '—';
                  var hsColor = ins.health_score != null ? _bbHealthColor(ins.health_score) : 'var(--muted)';
                  html += '<div style="border:1px solid ' + (needsReview ? '#d97706' : 'var(--border)') + ';border-radius:8px;padding:12px 16px;margin-bottom:12px;">';
                  html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;">'
                    + '<span style="background:' + catColor + ';color:#fff;font-size:0.7rem;padding:2px 8px;border-radius:4px;">' + catIcon + ' ' + cat.toUpperCase() + '</span>'
                    + '<span style="background:' + sevColor + ';color:#fff;font-size:0.7rem;padding:2px 7px;border-radius:4px;text-transform:uppercase;">' + sev + '</span>'
                    + '<span style="font-size:0.85rem;" title="trend">' + trendArrow + '</span>'
                    + '<span style="font-size:0.75rem;color:' + hsColor + ';font-weight:600;">Health: ' + hs + '/100</span>'
                    + (needsReview ? '<span style="background:#d97706;color:#fff;font-size:0.7rem;padding:2px 7px;border-radius:4px;">Needs Review</span>' : '')
                    + '<span style="font-size:0.75rem;color:var(--muted);margin-left:auto;">' + ins.timestamp.slice(0,19).replace('T',' ') + '</span>'
                    + '</div>';
                  html += '<p style="margin:0 0 8px;">' + ins.summary + '</p>';
                  if (ins.recommendations && ins.recommendations.length) {{
                    html += '<ul style="margin:0 0 10px;padding-left:18px;">';
                    ins.recommendations.forEach(function(rec) {{ html += '<li style="font-size:0.85rem;">' + rec + '</li>'; }});
                    html += '</ul>';
                  }}
                  html += '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding-top:8px;border-top:1px solid var(--border);">'
                    + '<span style="font-size:0.75rem;color:' + confColor + ';font-weight:600;">Confidence: ' + conf + '% &mdash; ' + confLabel + '</span>'
                    + _bbConfBar(conf, confColor)
                    + '</div>'
                    + '<details style="margin-top:6px;">'
                    + '<summary style="font-size:0.72rem;color:var(--muted);cursor:pointer;">Score breakdown</summary>'
                    + '<div style="font-size:0.72rem;color:var(--muted);margin-top:4px;display:grid;grid-template-columns:repeat(3,auto);gap:4px 16px;">'
                    + '<span>Rule signal: <strong>' + (ins.rule_score != null ? ins.rule_score : '—') + '</strong></span>'
                    + '<span>Data quality: <strong>' + (ins.data_quality_score != null ? ins.data_quality_score : '—') + '</strong></span>'
                    + '<span>LLM self-score: <strong>' + (ins.llm_confidence != null ? ins.llm_confidence : '—') + '</strong></span>'
                    + '</div></details>'
                    + '</div>';
                }});
                body.innerHTML = html;
              }})
              .catch(function(e) {{ body.textContent = 'Error: ' + e; }});
          }}
          function bbAiViewDebug(slug) {{
            var panel = document.getElementById('ai-debug-panel');
            panel.textContent = 'Loading debug logs for ' + slug + '…';
            fetch('/super-admin/tenants/' + encodeURIComponent(slug) + '/ai-insights/debug')
              .then(function(r) {{ return r.json(); }})
              .then(function(d) {{
                if (!d.debug_entries || !d.debug_entries.length) {{
                  panel.innerHTML = '<p class="mini-copy">No debug entries for "' + slug + '". Enable Debug Mode and wait for the next job run.</p>';
                  return;
                }}
                var html = '';
                d.debug_entries.forEach(function(e) {{
                  var conf = e.final_confidence != null ? e.final_confidence : '—';
                  var summLine = e.timestamp.slice(0,19).replace('T',' ')
                    + (e.latency_ms ? ' — ' + e.latency_ms + 'ms' : '')
                    + ' — confidence: ' + conf + '%'
                    + (e.error ? ' ⚠️ error' : '');
                  html += '<details style="border:1px solid var(--border);border-radius:6px;padding:8px 12px;margin-bottom:8px;">'
                    + '<summary style="cursor:pointer;font-size:0.8rem;">' + summLine + '</summary>'
                    + (e.error ? '<pre style="color:#dc2626;font-size:0.75rem;white-space:pre-wrap;">' + e.error + '</pre>' : '');
                  if (e.final_confidence != null) {{
                    html += '<div style="font-size:0.72rem;color:var(--muted);margin:6px 0;">'
                      + 'rule_score=' + e.rule_score + '  data_quality=' + e.data_quality_score
                      + '  llm_confidence=' + e.llm_confidence + '  final=' + e.final_confidence + '</div>';
                  }}
                  html += (e.prompt ? '<p style="font-size:0.75rem;color:var(--muted);margin:6px 0 2px;">Prompt:</p><pre style="font-size:0.75rem;white-space:pre-wrap;background:var(--surface-2);padding:8px;border-radius:4px;">' + e.prompt + '</pre>' : '')
                    + (e.response ? '<p style="font-size:0.75rem;color:var(--muted);margin:6px 0 2px;">Response:</p><pre style="font-size:0.75rem;white-space:pre-wrap;background:var(--surface-2);padding:8px;border-radius:4px;">' + e.response + '</pre>' : '')
                    + '</details>';
                }});
                panel.innerHTML = html;
              }})
              .catch(function(e) {{ panel.textContent = 'Error: ' + e; }});
          }}
          </script>
        </section>

      </section>
    </div>
  </div>
  <script>
  (function() {{
    var K = 'bb_theme', h = document.documentElement;
    function applyTheme(dark) {{
      if (dark) h.setAttribute('data-theme','dark'); else h.removeAttribute('data-theme');
      var btn = document.getElementById('bb-theme-btn');
      if (btn) btn.textContent = dark ? '☀ Light' : '☾ Dark';
    }}
    function bbToggleTheme() {{
      var dark = h.getAttribute('data-theme') === 'dark';
      localStorage.setItem(K, dark ? 'light' : 'dark');
      applyTheme(!dark);
    }}
    window.bbToggleTheme = bbToggleTheme;
    var saved = localStorage.getItem(K);
    if (!saved) saved = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    applyTheme(saved === 'dark');
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e) {{
      if (!localStorage.getItem(K)) applyTheme(e.matches);
    }});
  }})();
  </script>
  <script>
  /* ── Smart Confirm (Super Admin) ──────────────────────────────────── */
  (function() {{
    var _ov = null, _bx = null, _res = null;
    function _init() {{
      _ov = document.createElement('div'); _ov.className = 'bb-sconfirm-overlay';
      _ov.addEventListener('click', function(e) {{ if(e.target===_ov) _close(false); }});
      _bx = document.createElement('div'); _bx.className = 'bb-sconfirm';
      _ov.appendChild(_bx); document.body.appendChild(_ov);
    }}
    function _close(r) {{
      if(_ov) _ov.classList.remove('open');
      if(_res) {{ _res(r); _res = null; }}
    }}
    window.bbSmartConfirm = function(cfg) {{
      if(!_ov) _init();
      return new Promise(function(resolve) {{
        _res = resolve;
        var typeRow = cfg.requireType
          ? '<p class="bb-sconfirm-type-label">Type <strong>'+cfg.requireType+'</strong> to confirm:</p>'
            + '<input class="bb-sconfirm-type-input" id="bb-sc-ti" autocomplete="off" />' : '';
        var cq = cfg.consequence ? '<div class="bb-sconfirm-consequence">'+cfg.consequence+'</div>' : '';
        _bx.innerHTML = '<div class="bb-sconfirm-icon">'+(cfg.icon||(cfg.danger?'⚠️':'ℹ️'))+'</div>'
          + '<h3>'+(cfg.title||'Confirm')+'</h3>'
          + '<div class="bb-sconfirm-body">'+(cfg.body||'')+'</div>'
          + cq + typeRow
          + '<div class="bb-sconfirm-actions">'
          + '<button class="button button-secondary" style="min-height:36px;" onclick="window._saScCancel()">Cancel</button>'
          + '<button class="button '+(cfg.danger?'button-danger':'button-primary')+'" style="min-height:36px;" id="bb-sc-ok">'+(cfg.confirmLabel||'Confirm')+'</button>'
          + '</div>';
        var ok = document.getElementById('bb-sc-ok');
        if(cfg.requireType) {{
          ok.disabled = true;
          var ti = document.getElementById('bb-sc-ti');
          ti.addEventListener('input', function() {{ ok.disabled = ti.value.trim() !== cfg.requireType; }});
          ti.focus();
        }}
        ok.addEventListener('click', function() {{ _close(true); }});
        _ov.classList.add('open');
        if(!cfg.requireType && ok) ok.focus();
      }});
    }};
    window._saScCancel = function() {{ _close(false); }};
    window.bbConfirmSubmit = function(form, cfg) {{
      window.bbSmartConfirm(cfg).then(function(ok) {{ if(ok) form.submit(); }});
    }};

    /* ── Super Admin Command Bar ───────────────────────────────────── */
    var _cbOv=null, _cbIn=null, _cbRes=null, _cbItems=[], _cbSel=-1;
    var _SA_NAV = [
      {{t:'nav',i:'🏛',l:'Districts',d:'Manage districts and member schools',u:'/super-admin?section=districts#districts'}},
      {{t:'nav',i:'🏫',l:'Schools',d:'All provisioned school tenants',u:'/super-admin?section=schools#schools'}},
      {{t:'nav',i:'💳',l:'Licensing',d:'District license management',u:'/super-admin?section=billing#billing'}},
      {{t:'nav',i:'📡',l:'Operations / NOC',d:'Real-time network monitoring',u:'/super-admin?section=noc#noc'}},
      {{t:'nav',i:'📊',l:'MSP Dashboard',d:'Managed service overview',u:'/super-admin?section=msp#msp'}},
      {{t:'nav',i:'⚙',l:'Configuration',d:'Platform and email settings',u:'/super-admin?section=configuration#configuration'}},
      {{t:'nav',i:'❤',l:'System Health',d:'Service uptime and status',u:'/super-admin?section=health#health'}},
      {{t:'nav',i:'📧',l:'Email Tool',d:'Send test emails',u:'/super-admin?section=email-tool#email-tool'}},
      {{t:'nav',i:'👥',l:'Customers',d:'CRM leads and active customers',u:'/super-admin?section=customers#customers'}},
      {{t:'nav',i:'🔐',l:'Platform Control',d:'Brand and theme settings',u:'/super-admin?section=platform-control#platform-control'}},
      {{t:'nav',i:'🔧',l:'Server Tools',d:'Git pull, restart, debug',u:'/super-admin?section=server-tools#server-tools'}},
      {{t:'nav',i:'🏖',l:'Sandbox',d:'Test and demo environments',u:'/super-admin?section=sandbox#sandbox'}},
      {{t:'nav',i:'🔑',l:'Setup Codes',d:'First-admin handoff codes',u:'/super-admin?section=setup-codes#setup-codes'}},
      {{t:'nav',i:'🔒',l:'Security',d:'Super admin 2FA and password',u:'/super-admin?section=security#security'}},
      {{t:'nav',i:'🧠',l:'AI Insights',d:'Local Llama3 AI analysis per tenant',u:'/super-admin?section=ai-insights#ai-insights'}},
    ];
    var _SA_ENTITIES = [{', '.join(
        '{t:' + repr('entity') + ',i:' + repr('🏛') + ',l:' + json.dumps(str(d.get('name', ''))) + ',d:' + repr('District') + ',u:' + repr('/super-admin?section=districts#districts') + '}'
        for d in list(msp_districts)[:20] if d.get('name')
    )},{', '.join(
        '{t:' + repr('entity') + ',i:' + repr('🏫') + ',l:' + json.dumps(str(r.get('name', ''))) + ',d:' + repr('School') + ',u:' + repr('/super-admin?section=schools#schools') + '}'
        for r in list(school_rows)[:20] if r.get('name')
    )}];
    function _saFilter(q) {{
      var all = _SA_NAV.concat(_SA_ENTITIES);
      if(!q) return all.slice(0,9);
      q = q.toLowerCase();
      return all.filter(function(x){{ return (x.l+' '+x.d).toLowerCase().indexOf(q)>=0; }}).slice(0,10);
    }}
    function _saRender(q) {{
      var m = _saFilter(q); _cbSel = m.length?0:-1; _cbItems = m;
      if(!m.length) {{ _cbRes.innerHTML='<div class="bb-cmdbar-empty">No results</div>'; return; }}
      var tl={{nav:'Page',entity:'Entity',action:'Action'}};
      var html='', last='';
      m.forEach(function(x,i){{
        if(x.t!==last){{ html+='<div class="bb-cmdbar-section-label">'+(tl[x.t]||x.t)+'</div>'; last=x.t; }}
        html+='<div class="bb-cmdbar-item'+(i===0?' bb-cmd-sel':'')+'" data-idx="'+i+'">'
          +'<div class="bb-cmdbar-item-icon">'+x.i+'</div>'
          +'<div class="bb-cmdbar-item-info"><div class="bb-cmdbar-item-label">'+x.l+'</div>'
          +(x.d?'<div class="bb-cmdbar-item-desc">'+x.d+'</div>':'')+'</div>'
          +'<div class="bb-cmdbar-item-badge">'+(tl[x.t]||x.t)+'</div></div>';
      }});
      _cbRes.innerHTML=html;
      _cbRes.querySelectorAll('.bb-cmdbar-item').forEach(function(el){{
        el.addEventListener('mouseenter',function(){{ _saSelect(+el.getAttribute('data-idx')); }});
        el.addEventListener('click',function(){{ _saExec(+el.getAttribute('data-idx')); }});
      }});
    }}
    function _saSelect(i){{
      _cbSel=i;
      _cbRes.querySelectorAll('.bb-cmdbar-item').forEach(function(el){{
        el.classList.toggle('bb-cmd-sel',+el.getAttribute('data-idx')===i);
      }});
    }}
    function _saExec(i){{
      var x=_cbItems[i]; if(!x) return;
      window.bbCloseSaCmdBar();
      if(x.fn) x.fn(); else if(x.u) window.location.href=x.u;
    }}
    function _saInitCb(){{
      _cbOv=document.createElement('div'); _cbOv.className='bb-cmdbar-overlay';
      _cbOv.addEventListener('click',function(e){{ if(e.target===_cbOv) window.bbCloseSaCmdBar(); }});
      var box=document.createElement('div'); box.className='bb-cmdbar';
      box.innerHTML='<div class="bb-cmdbar-top">'
        +'<span class="bb-cmdbar-search-icon">&#128269;</span>'
        +'<input class="bb-cmdbar-input" id="bb-sa-cmdbar-input" placeholder="Search pages and districts&hellip;" autocomplete="off" />'
        +'<span class="bb-cmdbar-kbd">Esc</span></div>'
        +'<div class="bb-cmdbar-results" id="bb-sa-cmdbar-results"></div>'
        +'<div class="bb-cmdbar-footer"><span><kbd>&uarr;&darr;</kbd> navigate</span><span><kbd>Enter</kbd> open</span><span><kbd>Esc</kbd> close</span></div>';
      _cbOv.appendChild(box); document.body.appendChild(_cbOv);
      _cbIn=document.getElementById('bb-sa-cmdbar-input');
      _cbRes=document.getElementById('bb-sa-cmdbar-results');
      _cbIn.addEventListener('input',function(){{ _saRender(_cbIn.value.trim()); }});
      _cbIn.addEventListener('keydown',function(e){{
        if(e.key==='ArrowDown'){{ e.preventDefault(); _saSelect(Math.min(_cbSel+1,_cbItems.length-1)); }}
        else if(e.key==='ArrowUp'){{ e.preventDefault(); _saSelect(Math.max(_cbSel-1,0)); }}
        else if(e.key==='Enter'){{ e.preventDefault(); _saExec(_cbSel); }}
        else if(e.key==='Escape'){{ window.bbCloseSaCmdBar(); }}
      }});
    }}
    window.bbOpenSaCmdBar=function(){{
      if(!_cbOv) _saInitCb();
      _cbIn.value=''; _saRender(''); _cbOv.classList.add('open'); _cbIn.focus();
    }};
    window.bbCloseSaCmdBar=function(){{ if(_cbOv) _cbOv.classList.remove('open'); }};

    document.addEventListener('keydown',function(e){{
      if((e.ctrlKey||e.metaKey)&&e.key==='k'){{ e.preventDefault(); window.bbOpenSaCmdBar(); }}
      if(e.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){{ e.preventDefault(); window.bbOpenSaCmdBar(); }}
      if(e.key==='Escape'){{ window.bbCloseSaCmdBar(); if(window._saScCancel) window._saScCancel(); }}
    }});
    document.addEventListener('DOMContentLoaded',function(){{
      var btn=document.getElementById('bb-sa-cmdbar-btn');
      if(btn) btn.style.display='';
    }});
  }})();
  </script>
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
        return '<tr><td colspan="5" class="empty-state">No alerts logged yet.</td></tr>'
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


def _render_school_cards(items: Sequence[Mapping[str, object]], school_path_prefix: str) -> str:
    if not items:
        return '<p class="mini-copy">No schools found.</p>'
    prefix = escape(school_path_prefix)
    cards = []
    for item in items:
        slug = str(item.get("tenant_slug", ""))
        name = str(item.get("tenant_name", slug))
        is_active = bool(item.get("alarm_is_active", False))
        is_training = bool(item.get("alarm_is_training", False))
        message = str(item.get("alarm_message", "") or "")
        last_alert_at = item.get("last_alert_at")
        ack_count = int(item.get("ack_count", 0) or 0)
        expected_users = int(item.get("expected_users", 0) or 0)
        ack_rate = float(item.get("ack_rate", 0.0) or 0.0)

        if is_active and is_training:
            status_badge = '<span class="status-pill warn">TRAINING</span>'
            card_mod = "school-card--training"
        elif is_active:
            status_badge = '<span class="status-pill danger">LOCKDOWN</span>'
            card_mod = "school-card--alarm"
        else:
            status_badge = '<span class="status-pill ok">All Clear</span>'
            card_mod = "school-card--ok"

        message_note = (
            f'<p class="school-card-message">{escape(message[:80])}</p>'
            if is_active and message else ""
        )
        last_alert_str = escape(str(last_alert_at)[:16].replace("T", " ")) if last_alert_at else "—"

        if expected_users == 0:
            ack_html = '<span class="mini-copy">No users</span>'
        elif ack_rate >= 90:
            ack_html = f'<span class="status-pill ok">{ack_count}/{expected_users} ({ack_rate:.0f}%)</span>'
        elif ack_rate >= 60:
            ack_html = f'<span class="status-pill warn">{ack_count}/{expected_users} ({ack_rate:.0f}%)</span>'
        else:
            ack_html = f'<span class="status-pill danger">{ack_count}/{expected_users} ({ack_rate:.0f}%)</span>'

        manage_url = f"{prefix}/admin?tenant={escape(slug)}&section=dashboard"
        cards.append(
            f"<div class='school-card {card_mod}' draggable='true'"
            f" data-slug='{escape(slug)}' data-tenant-slug='{escape(slug)}'"
            f" data-expected-users='{expected_users}' data-href='{manage_url}'>"
            f"  <div class='school-card-header'>"
            f"    <span class='school-card-drag' title='Drag to reorder'>&#9776;</span>"
            f"    <span class='school-card-name'>{escape(name)}</span>"
            f"    {status_badge}"
            f"  </div>"
            f"  {message_note}"
            f"  <div class='school-card-footer'>"
            f"    <span class='school-card-last'>&#128337; {last_alert_str} UTC</span>"
            f"    {ack_html}"
            f"  </div>"
            f"</div>"
        )
    return "".join(cards)


def _render_drill_report_rows(alerts: Sequence[AlertRecord], prefix: str) -> str:
    if not alerts:
        return '<tr><td colspan="5" class="empty-state">No alerts logged yet.</td></tr>'
    rows = []
    for alert in alerts:
        type_badge = (
            '<span class="status-pill warn">Training</span>'
            if alert.is_training
            else '<span class="status-pill ok">Live</span>'
        )
        msg = escape(alert.message[:80] + ("…" if len(alert.message) > 80 else ""))
        p = escape(prefix)
        actions = (
            f'<a class="button button-secondary" style="font-size:11px;padding:4px 10px;" '
            f'href="{p}/admin/reports/{alert.id}" target="_blank">View JSON</a> '
            f'<a class="button button-secondary" style="font-size:11px;padding:4px 10px;" '
            f'href="{p}/admin/reports/{alert.id}/export.csv">CSV</a> '
            f'<a class="button button-secondary" style="font-size:11px;padding:4px 10px;" '
            f'href="{p}/admin/reports/{alert.id}/export.pdf">PDF</a>'
        )
        rows.append(
            "<tr>"
            f"<td>{alert.id}</td>"
            f"<td>{type_badge}</td>"
            f"<td class=\"mini-copy\">{escape(alert.created_at[:16])}</td>"
            f"<td>{msg}</td>"
            f"<td style=\"text-align:right;white-space:nowrap;\">{actions}</td>"
            "</tr>"
        )
    return "".join(rows)


def _render_audit_event_rows(events: Sequence[AuditEventRecord]) -> str:
    if not events:
        return '<tr><td colspan="5" class="empty-state">No audit events recorded yet.</td></tr>'
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
        return '<tr><td colspan="5" class="empty-state">No alerts yet.</td></tr>'
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
        return '<tr><td colspan="9" class="empty-state">No devices registered yet.</td></tr>'
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
        is_archived = bool(getattr(device, "archived_at", None))
        status_badge = (
            '<span class="badge badge-muted">Archived</span>'
            if is_archived
            else '<span class="badge badge-success">Active</span>'
        )
        row_style = ' style="opacity:0.55;"' if is_archived else ""
        device_id_display = escape(device.device_id[-12:]) if device.device_id else "—"
        rows.append(
            f"<tr{row_style}>"
            f"<td>{index}</td>"
            f"<td>{escape(device_name)}</td>"
            f"<td>{escape(device.platform)}</td>"
            f"<td>{escape(device.push_provider)}</td>"
            f"<td>{escape(owner)}</td>"
            f"<td>{escape(first_owner)}</td>"
            f"<td><code>...{escape(device.token[-12:])}</code></td>"
            f"<td><code title=\"{escape(device.device_id or '')}\">...{device_id_display}</code></td>"
            f"<td>{status_badge}</td>"
            "<td>"
            + (
                f"<form method=\"post\" action=\"{prefix}/admin/devices/delete\" onsubmit=\"return confirm('Delete this registered device token?');\">"
                f"<input type=\"hidden\" name=\"token\" value=\"{escape(device.token)}\" />"
                f"<input type=\"hidden\" name=\"push_provider\" value=\"{escape(device.push_provider)}\" />"
                "<button class=\"button button-danger-outline\" type=\"submit\">Delete</button>"
                "</form>"
                if not is_archived
                else "<span class=\"text-muted\" style=\"font-size:12px;\">Archived</span>"
            )
            + "</td>"
            "</tr>"
        )
    return "".join(rows)


_ROLE_BADGE_LABEL: dict[str, str] = {
    "district_admin": "District Admin",
    "admin": "Admin",
    "building_admin": "Building Admin",
    "teacher": "Teacher",
    "staff": "Staff",
    "law_enforcement": "Law Enforcement",
    "super_admin": "Super Admin",
}

_ROLE_PERMS_HUMAN: dict[str, list[str]] = {
    "teacher":  ["Send help requests", "View incident feed", "Submit quiet period request"],
    "staff":    ["Send help requests", "View incident feed", "Submit quiet period request"],
    "law_enforcement": ["Send help requests", "Submit quiet period request", "View assigned incidents", "Receive school alerts"],
    "admin":    ["Manage school users", "Trigger alerts", "Approve quiet requests", "Submit quiet period request"],
    "building_admin": ["Manage school users", "Trigger alerts", "Approve quiet requests", "Submit quiet period request"],
    "district_admin": ["Manage all school users", "Trigger alerts", "Approve quiet requests", "Manage district schools", "Generate access codes"],
    "super_admin": ["Full platform access — unrestricted"],
}


def _um_role_badge(role: str) -> str:
    label = _ROLE_BADGE_LABEL.get(role, role)
    return f'<span class="role-badge rb-{escape(role)}">{escape(label)}</span>'


def _um_avatar(name: str, role: str) -> str:
    initials = "".join(w[0] for w in (name or "?").split()[:2]).upper() or "?"
    return f'<div class="um-avatar ua-{escape(role)}">{escape(initials)}</div>'


def _um_health_bar(users: "Sequence[UserRecord]") -> str:
    archived = sum(1 for u in users if getattr(u, "is_archived", False))
    total = len(users)
    active = sum(1 for u in users if u.is_active and not getattr(u, "is_archived", False))
    login_enabled = sum(1 for u in users if getattr(u, "can_login", False) and not getattr(u, "is_archived", False))
    da_count = sum(1 for u in users if u.role == "district_admin" and u.is_active and not getattr(u, "is_archived", False))
    if da_count >= 2:
        da_cls, da_sub = "hc-ok", "Healthy — redundancy in place"
    elif da_count == 1:
        da_cls, da_sub = "hc-warn", "Warning — single point of failure"
    else:
        da_cls, da_sub = "hc-danger", "Critical — no district admin!"
    sec_cls = "hc-ok" if da_count >= 1 else "hc-danger"
    sec_label = "Healthy" if da_count >= 1 else "At Risk"
    archived_card = (
        f'<div class="um-hcard hc-warn"><div class="um-hcard-label">Archived</div>'
        f'<div class="um-hcard-value">{archived}</div>'
        f'<div class="um-hcard-sub">Awaiting permanent deletion</div></div>'
        if archived > 0 else ""
    )
    return (
        '<div class="um-health-bar">'
        f'<div class="um-hcard hc-ok"><div class="um-hcard-label">Total Users</div><div class="um-hcard-value">{total - archived}</div><div class="um-hcard-sub">{active} active</div></div>'
        f'<div class="um-hcard {da_cls}"><div class="um-hcard-label">District Admins</div><div class="um-hcard-value">{da_count}</div><div class="um-hcard-sub">{da_sub}</div></div>'
        f'<div class="um-hcard hc-ok"><div class="um-hcard-label">Login Enabled</div><div class="um-hcard-value">{login_enabled}</div><div class="um-hcard-sub">Can access dashboard</div></div>'
        f'<div class="um-hcard {sec_cls}"><div class="um-hcard-label">Security Status</div><div class="um-hcard-value" style="font-size:1.1rem;padding-top:2px;">{escape(sec_label)}</div><div class="um-hcard-sub">Role hierarchy integrity</div></div>'
        f'{archived_card}'
        '</div>'
    )


def _um_enterprise_table(
    users: "Sequence[UserRecord]",
    prefix: str,
    *,
    actor_role: str = "",
    actor_user_id: Optional[int] = None,
) -> str:
    if not users:
        return '<p class="mini-copy" style="padding:16px 0;">No users yet.</p>'
    rows = []
    for u in users:
        is_self = actor_user_id is not None and u.id == actor_user_id
        is_archived = getattr(u, "is_archived", False)
        if is_archived:
            status_badge = '<span class="status-pill offline" style="font-size:.72rem;padding:2px 9px;min-height:0;">Archived</span>'
        elif u.is_active:
            status_badge = '<span class="status-pill ok" style="font-size:.72rem;padding:2px 9px;min-height:0;">Active</span>'
        else:
            status_badge = '<span class="status-pill danger" style="font-size:.72rem;padding:2px 9px;min-height:0;">Inactive</span>'
        last = escape(getattr(u, "last_login_at", None) or "Never")[:16].replace("T", " ")
        title_str = f'<span class="um-sub">{escape(u.title)}</span>' if getattr(u, "title", "") else ""
        login_str = escape(u.login_name or "—")
        _can_mod = can_archive_user(actor_role, u.role)
        # 8.3: activity indicator
        _last_login_display = last if last != "Never" else None
        _activity_str = (
            f'<span class="um-sub" style="color:var(--muted);font-size:0.72rem;">Last login: {escape(_last_login_display)}</span>'
            if _last_login_display else
            '<span class="um-sub" style="color:var(--muted);font-size:0.72rem;opacity:0.7;">Never logged in</span>'
        )
        user_json = json.dumps({
            "id": u.id,
            "name": u.name,
            "role": u.role,
            "title": getattr(u, "title", "") or "",
            "login": u.login_name or "",
            "phone": getattr(u, "phone_e164", "") or "",
            "is_active": u.is_active,
            "is_archived": is_archived,
            "last_login": last,
            "is_self": is_self,
            "can_modify": _can_mod,
        })
        self_badge = ' <span class="role-badge" style="background:rgba(27,95,228,.1);color:#1e40af;font-size:.68rem;">You</span>' if is_self else ""
        row_style = ' style="opacity:0.62;"' if is_archived else ""
        if not _can_mod:
            _action_cell = (
                '<span style="font-size:0.72rem;color:#7c3aed;background:rgba(124,58,237,0.1);'
                'border-radius:6px;padding:3px 9px;white-space:nowrap;">&#128274; Protected Role</span>'
            )
        elif is_self:
            _action_cell = (
                f'<button class="button button-secondary um-edit-btn" style="min-height:32px;font-size:0.8rem;padding:0 12px;" '
                f'data-uid="{u.id}" onclick="event.stopPropagation();umToggleEdit({u.id})">Edit</button>'
            )
        else:
            _deactivate_btn = (
                f'<form method="post" action="{escape(prefix)}/admin/users/{u.id}/set-active" style="margin:0;"'
                f' onsubmit="event.stopPropagation();return confirm(\'Deactivate {escape(u.name)}?\');">'
                f'<input type="hidden" name="is_active" value="0" />'
                f'<button class="button button-secondary" type="submit" style="min-height:32px;font-size:0.8rem;padding:0 10px;" title="Temporarily deactivate without archiving">Deactivate</button>'
                f'</form>'
            ) if not is_archived else ""
            _archive_btn = (
                f'<form method="post" action="{escape(prefix)}/admin/users/{u.id}/archive" style="margin:0;"'
                f' onsubmit="event.stopPropagation();return confirm(\'Archive {escape(u.name)}?\');">'
                f'<button class="button button-danger-outline" type="submit" style="min-height:32px;font-size:0.8rem;padding:0 10px;">Archive</button>'
                f'</form>'
            ) if not is_archived else ""
            _action_cell = (
                f'<button class="button button-secondary um-edit-btn" style="min-height:32px;font-size:0.8rem;padding:0 12px;" '
                f'data-uid="{u.id}" onclick="event.stopPropagation();umToggleEdit({u.id})">Edit</button>'
                + _deactivate_btn
                + _archive_btn
            )
        # 9.1: View As button — visible to district_admin/super_admin for any user,
        #      visible to building_admin/admin for non-DA/SA users, never for self
        _can_view_as = (
            not is_self and (
                actor_role in {"district_admin", "super_admin"}
                or (actor_role in {"building_admin", "admin"} and u.role not in {"district_admin", "super_admin"})
            )
        )
        _view_as_btn = (
            f'<button class="button button-secondary" style="min-height:32px;font-size:0.78rem;padding:0 10px;white-space:nowrap;" '
            f'type="button" onclick="event.stopPropagation();umOpenViewAs({u.id},{json.dumps(u.name)})">View As</button>'
        ) if _can_view_as else ""

        # 8.2: checkbox cell (excluded for self to avoid accidental self-archival)
        _cb_cell = (
            f'<td style="width:36px;padding-left:8px;" onclick="event.stopPropagation();">'
            f'<input type="checkbox" class="um-bulk-cb" data-uid="{u.id}" style="width:16px;height:16px;cursor:pointer;" /></td>'
            if not is_self else
            '<td style="width:36px;"></td>'
        )
        rows.append(
            f'<tr class="um-row" data-uid="{u.id}" data-user=\'{escape(user_json)}\' title="Click to view details"{row_style}>'
            + _cb_cell
            + f'<td style="width:44px;">{_um_avatar(u.name, u.role)}</td>'
            f'<td><div class="um-name-cell"><div class="um-name-stack"><span class="um-name">{escape(u.name)}{self_badge}</span>{title_str}{_activity_str}</div></div></td>'
            f'<td style="font-size:0.8rem;color:var(--muted);">{login_str}</td>'
            f'<td>{_um_role_badge(u.role)}</td>'
            f'<td>{status_badge}</td>'
            f'<td style="text-align:right;">'
            f'<div style="display:inline-flex;gap:6px;align-items:center;">'
            + _view_as_btn
            + _action_cell
            + f'</div>'
            f'</td>'
            f'</tr>'
            f'<tr id="um-editrow-{u.id}" class="um-edit-row" style="display:none;">'
            f'<td colspan="7" style="padding:0;">'
            f'<div class="um-edit-inner" id="um-edit-{u.id}"></div>'
            f'</td>'
            f'</tr>'
        )
    return (
        '<div class="table-wrap">'
        '<table class="um-table">'
        '<thead><tr>'
        '<th style="width:36px;padding-left:8px;"><input type="checkbox" id="um-select-all" title="Select all" style="width:16px;height:16px;cursor:pointer;" /></th>'
        '<th></th><th>Name</th><th>Username</th><th>Role</th>'
        '<th>Status</th><th style="text-align:right;">Actions</th>'
        '</tr></thead>'
        '<tbody>' + "".join(rows) + '</tbody>'
        '</table></div>'
    )


def _um_slide_panel() -> str:
    return """
<div class="um-panel-overlay" id="um-overlay"></div>
<div class="um-detail-panel" id="um-panel">
  <div class="um-panel-hd">
    <button class="um-panel-close" id="um-panel-close" aria-label="Close">&#x2715;</button>
    <div class="um-panel-avatar" id="up-avatar"></div>
    <div class="um-panel-name" id="up-name"></div>
    <div class="um-panel-meta" id="up-meta"></div>
  </div>
  <div class="um-panel-body">
    <div>
      <div class="um-panel-sect-label">Role &amp; Status</div>
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
        <span id="up-role-badge"></span>
        <span id="up-status-pill"></span>
      </div>
    </div>
    <div>
      <div class="um-panel-sect-label">Access Permissions</div>
      <div class="um-perm-list" id="up-perms"></div>
    </div>
    <div id="up-contact-sect">
      <div class="um-panel-sect-label">Contact &amp; Login</div>
      <div style="display:grid;gap:6px;font-size:0.83rem;">
        <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(0,0,0,.06);">
          <span style="color:var(--muted);">Username</span><span id="up-login" style="font-weight:500;"></span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(0,0,0,.06);">
          <span style="color:var(--muted);">Last login</span><span id="up-last-login" style="font-weight:500;"></span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:5px 0;">
          <span style="color:var(--muted);">User ID</span><span id="up-uid" style="font-weight:500;font-family:monospace;"></span>
        </div>
      </div>
    </div>
    <div>
      <div class="um-panel-sect-label">Actions</div>
      <div class="um-panel-actions" id="up-actions"></div>
    </div>
    <div>
      <div class="um-panel-sect-label">Activity Timeline</div>
      <div id="up-timeline" style="font-size:0.8rem;max-height:320px;overflow-y:auto;">
        <span style="color:var(--muted);">Select a user to load timeline.</span>
      </div>
    </div>
  </div>
</div>
"""


def _um_delete_modal() -> str:
    return """
<div class="um-modal-wrap" id="um-delete-modal">
  <div class="um-modal">
    <h3>Delete User Permanently</h3>
    <p class="um-modal-desc">You are about to delete <strong id="dm-user-name"></strong>.</p>
    <p class="um-modal-desc" style="color:var(--danger);font-weight:600;">This will permanently delete the user and cannot be undone.</p>
    <div class="um-modal-actions">
      <button class="button button-secondary" id="dm-cancel">Cancel</button>
      <button class="button button-danger" id="dm-confirm">Delete Permanently</button>
    </div>
  </div>
</div>
"""


def _um_view_as_modal() -> str:
    return """
<div class="um-modal-wrap" id="um-viewas-modal" style="z-index:1100;">
  <div class="um-modal" style="max-width:560px;max-height:85vh;display:flex;flex-direction:column;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;flex-shrink:0;">
      <h3 style="margin:0;" id="va-title">View As — Read Only</h3>
      <button class="button button-secondary" id="va-close" style="min-height:30px;font-size:0.78rem;padding:0 12px;">Close</button>
    </div>
    <div style="background:rgba(220,38,38,0.08);border:1px solid rgba(220,38,38,0.22);border-radius:8px;padding:8px 14px;margin-bottom:14px;flex-shrink:0;">
      <strong style="color:#dc2626;font-size:0.82rem;">&#128274; READ ONLY TROUBLESHOOTING VIEW — Actions are disabled.</strong>
    </div>
    <div id="va-body" style="overflow-y:auto;flex:1;font-size:0.85rem;">
      <div style="color:var(--muted);text-align:center;padding:24px 0;">Loading…</div>
    </div>
  </div>
</div>
"""


def _um_bulk_modal() -> str:
    return """
<div class="um-modal-wrap" id="um-bulk-modal">
  <div class="um-modal">
    <h3 id="bm-title">Bulk Action</h3>
    <p class="um-modal-desc">Apply this action to <strong id="bm-count"></strong> selected user<span id="bm-plural"></span>?</p>
    <p class="um-modal-desc" id="bm-warning" style="color:var(--danger);font-weight:600;display:none;"></p>
    <div class="um-modal-actions">
      <button class="button button-secondary" id="bm-cancel">Cancel</button>
      <button class="button button-primary" id="bm-confirm">Confirm</button>
    </div>
  </div>
</div>
"""


def _um_role_modal() -> str:
    return """
<div class="um-modal-wrap" id="um-role-modal">
  <div class="um-modal">
    <h3>Confirm Role Change</h3>
    <p class="um-modal-desc">
      You are changing <strong id="rm-user"></strong> from
      <strong id="rm-old-role"></strong> &rarr; <strong id="rm-new-role"></strong>.
    </p>
    <div class="um-modal-warning" id="rm-warning" style="display:none;"></div>
    <div class="um-modal-actions">
      <button class="button button-secondary" id="rm-cancel">Cancel</button>
      <button class="button button-primary" id="rm-confirm">Confirm Change</button>
    </div>
  </div>
</div>
"""


def _user_archive_delete_html(prefix: str, user: UserRecord, *, actor_role: str = "") -> str:
    _can_mod = can_archive_user(actor_role, user.role)
    if not getattr(user, "is_archived", False):
        if not _can_mod:
            return (
                '<p class="mini-copy" style="color:#7c3aed;margin-top:8px;">'
                '&#128274; This is a protected role. Only district admins can archive this account.'
                '</p>'
            )
        return (
            f'<form method="post" action="{prefix}/admin/users/{user.id}/archive"'
            f' onsubmit="return confirm(\'Archive {escape(user.name)}? They will be deactivated and can be permanently deleted after.\');">'
            f'<div class="button-row"><button class="button button-danger-outline" type="submit">Archive user</button></div>'
            f'</form>'
        )
    if not _can_mod:
        return (
            '<div style="background:rgba(124,58,237,0.06);border:1px solid rgba(124,58,237,0.16);border-radius:12px;padding:12px 14px;margin-top:4px;">'
            '<p class="mini-copy" style="color:#7c3aed;margin:0;">&#128274; Protected Role — only district admins can restore or delete this account.</p>'
            '</div>'
        )
    _delete_url = json.dumps(f"{prefix}/admin/users/{user.id}/delete")
    _user_name_js = json.dumps(user.name)
    return (
        f'<div style="background:rgba(220,38,38,0.06);border:1px solid rgba(220,38,38,0.16);border-radius:12px;padding:12px 14px;margin-top:4px;">'
        f'<p class="mini-copy" style="color:var(--danger);margin:0 0 8px;">&#9888; This user is archived.</p>'
        f'<div class="button-row" style="gap:8px;">'
        f'<form method="post" action="{prefix}/admin/users/{user.id}/restore" style="margin:0;">'
        f'<button class="button button-secondary" type="submit">Restore user</button>'
        f'</form>'
        f'<button class="button button-danger" type="button"'
        f' onclick="umOpenDeleteModal({_delete_url},{_user_name_js})">Delete permanently</button>'
        f'</div></div>'
    )


def _render_user_cards(
    users: Sequence[UserRecord],
    school_path_prefix: str,
    *,
    tenant_label: Optional[str] = None,
    tenant_options: Sequence[Mapping[str, str]] = (),
    user_tenant_assignments: Optional[Mapping[int, Sequence[str]]] = None,
    allow_assignment_edit: bool = False,
    actor_role: str = "",
    actor_user_id: Optional[int] = None,
) -> str:
    if not users:
        return '<div class="mini-copy">No users yet.</div>'
    cards = []
    prefix = escape(school_path_prefix)
    _actor_can_change_roles = actor_role in {"district_admin", "super_admin"}
    for user in users:
        checked_active = "checked" if user.is_active else ""
        checked_clear_login = ""
        login_name = escape(user.login_name or "")
        phone = escape(user.phone_e164 or "")
        user_title = escape(user.title or "")
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
        title_display = f' <span class="mini-copy">— {escape(user.title)}</span>' if user.title else ""
        is_self = actor_user_id is not None and user.id == actor_user_id
        role_field = (
            '<p class="mini-copy" style="color:#b45309;margin:0;">You cannot change your own role.</p>'
            f'<input type="hidden" name="role" value="{escape(user.role)}" />'
            if is_self else (
                '<select name="role" class="um-role-select">'
                + f'<option value="teacher" {"selected" if user.role == "teacher" else ""}>Teacher / Standard</option>'
                + f'<option value="staff" {"selected" if user.role == "staff" else ""}>Staff</option>'
                + f'<option value="law_enforcement" {"selected" if user.role == "law_enforcement" else ""}>Law Enforcement</option>'
                + f'<option value="building_admin" {"selected" if user.role == "building_admin" else ""}>Building Admin</option>'
                + f'<option value="admin" {"selected" if user.role == "admin" else ""}>Admin</option>'
                + (f'<option value="district_admin" {"selected" if user.role == "district_admin" else ""}>District Admin</option>' if _actor_can_change_roles else '')
                + '</select>'
            )
        )
        cards.append(
            f'<div id="um-editcard-{user.id}" class="user-card" style="display:none;border-left:3px solid var(--accent);margin-bottom:4px;">'
            f'<form method="post" action="{prefix}/admin/users/{user.id}/update" class="stack"'
            f' data-role-change="1" data-current-role="{escape(user.role)}" data-user-name="{escape(user.name)}">'
            f'<div class="panel-header">'
            f'<div style="display:flex;align-items:center;gap:12px;">'
            f'{_um_avatar(user.name, user.role)}'
            f'<div><h3 style="margin:0;">{escape(user.name)}{title_display}</h3>'
            f'<p class="mini-copy" style="margin:2px 0 0;">User #{user.id} • created {escape(user.created_at)}{(" • " + escape(tenant_label)) if tenant_label else ""}</p></div>'
            f'</div>'
            f'<div style="display:flex;align-items:center;gap:8px;">'
            f'{_um_role_badge(user.role)}'
            f'<span class="status-pill {"ok" if user.is_active else "danger"}" style="font-size:.76rem;min-height:0;padding:3px 10px;">{"Active" if user.is_active else "Inactive"}</span>'
            f'<button type="button" class="button button-secondary" style="min-height:30px;font-size:0.78rem;padding:0 10px;" onclick="umToggleEdit({user.id})">Close</button>'
            f'</div></div>'
            f'<div class="form-grid">'
            f'<div class="field"><label>Name</label><input name="name" value="{escape(user.name)}" /></div>'
            f'<div class="field"><label>Role</label>{role_field}</div>'
            f'<div class="field"><label>Title</label><input name="title" value="{user_title}" placeholder="e.g. Principal" /></div>'
            f'<div class="field"><label>Phone</label><input name="phone_e164" value="{phone}" placeholder="+15551234567" /></div>'
            f'<div class="field"><label>Username</label><input name="login_name" value="{login_name}" placeholder="optional" /></div>'
            f'<div class="field"><label>New password</label><input name="password" type="password" placeholder="leave blank to keep" /></div>'
            f'<div class="checkbox-row"><input type="checkbox" name="is_active" value="1" {checked_active} /><span>Account active</span></div>'
            f'<div class="checkbox-row"><input type="checkbox" name="clear_login" value="1" {checked_clear_login} /><span>Clear login credentials</span></div>'
            f'</div>'
            f'<div class="button-row">'
            f'<button class="button button-primary" type="submit">Save changes</button>'
            f'</div>'
            f'<p class="mini-copy">Dashboard login: <strong>{"enabled" if user.can_login else "disabled"}</strong> • last login: {last_login}</p>'
            f'</form>'
            f'{assignment_block}'
            f'{_user_archive_delete_html(prefix, user, actor_role=actor_role)}'
            f'</div>'
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
) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  {_favicon_tags()}
  <style>{_base_styles()}</style>
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
  <script>(function(){{var t=localStorage.getItem('bb_theme')||(window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');if(t==='dark')document.documentElement.setAttribute('data-theme','dark');}})();</script>
</body>
</html>"""




def _render_tenant_settings_panels(
    prefix: str,
    settings: TenantSettings,
    can_edit: bool,
    hidden: str,
    is_district_admin: bool = False,
) -> str:
    """HTML for per-category tenant settings panels + inline JS.

    District-only panels (alerts, ai_insights) are completely omitted for
    building_admin users.  Sensitive fields within quiet_periods are also
    hidden for building_admin.
    """
    n = settings.notifications
    q = settings.quiet_periods
    a = settings.alerts
    d = settings.devices
    ac = settings.access_codes

    def _yesno(val: bool) -> str:
        color = "#16a34a" if val else "#9ca3af"
        return f'<span style="font-weight:600;color:{color};">{"Yes" if val else "No"}</span>'

    def _row_ro(label: str, value_html: str) -> str:
        return (
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:10px 0;border-bottom:1px solid var(--border);font-size:0.9rem;">'
            f'<span style="color:var(--text);">{escape(label)}</span>'
            f'<span>{value_html}</span>'
            f'</div>'
        )

    def _cb(fid: str, name: str, label: str, val: bool, hint: str = "") -> str:
        checked = " checked" if val else ""
        hint_html = (
            f'<span style="font-size:0.8rem;color:var(--muted);display:block;margin-top:2px;">{escape(hint)}</span>'
            if hint else ""
        )
        return (
            f'<div class="checkbox-row" style="margin-bottom:8px;">'
            f'<input type="checkbox" id="{fid}_{name}" name="{name}"{checked}/>'
            f'<label for="{fid}_{name}">{escape(label)}{hint_html}</label>'
            f'</div>'
        )

    def _num(fid: str, name: str, label: str, val: int, lo: int, hi: int, unit: str = "") -> str:
        unit_html = (
            f'<span style="font-size:0.85rem;color:var(--muted);margin-left:6px;">{escape(unit)}</span>'
            if unit else ""
        )
        return (
            f'<div class="field" style="margin-bottom:12px;">'
            f'<label for="{fid}_{name}">{escape(label)}</label>'
            f'<div style="display:flex;align-items:center;">'
            f'<input type="number" id="{fid}_{name}" name="{name}" value="{val}" min="{lo}" max="{hi}" style="width:130px;"/>'
            f'{unit_html}</div></div>'
        )

    def _sel(fid: str, name: str, label: str, val: str, opts: list[tuple[str, str]]) -> str:
        opts_html = "".join(
            f'<option value="{escape(v)}"{" selected" if v == val else ""}>{escape(lbl)}</option>'
            for v, lbl in opts
        )
        return (
            f'<div class="field" style="margin-bottom:12px;">'
            f'<label for="{fid}_{name}">{escape(label)}</label>'
            f'<select id="{fid}_{name}" name="{name}">{opts_html}</select>'
            f'</div>'
        )

    def _save(fid: str, category: str, sid: str) -> str:
        return (
            f'<div class="button-row" style="margin-top:16px;">'
            f'<button class="button button-primary" type="button" '
            f'onclick="tsSubmit(\'{category}\',\'{fid}\',\'{sid}\')">Save changes</button>'
            f'<span id="{sid}" style="font-size:0.88rem;margin-left:12px;"></span>'
            f'</div>'
        )

    locked_banner = (
        '<p style="font-size:0.88rem;color:var(--muted);margin-bottom:16px;padding:10px 14px;'
        'background:rgba(14,165,233,0.07);border:1px solid rgba(14,165,233,0.2);border-radius:6px;">'
        'View only — settings can only be changed by a district administrator.</p>'
    ) if not can_edit else ""

    district_only_banner = (
        '<p style="font-size:0.88rem;color:var(--muted);margin-bottom:16px;padding:10px 14px;'
        'background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.18);border-radius:6px;">'
        '🔒 District admin access required to view or change these settings.</p>'
    )

    # ── Notifications ────────────────────────────────────────────────────────
    if can_edit:
        notif_body = (
            '<form id="tsf-notifications" class="stack" style="max-width:580px;" onsubmit="return false;">'
            + _cb("tsf-n", "non_critical_sound_enabled", "Non-critical notification sound enabled",
                  n.non_critical_sound_enabled,
                  "Affects quiet period, access code, admin message pushes — never emergency alerts.")
            + _sel("tsf-n", "non_critical_sound_name", "Non-critical sound name",
                   n.non_critical_sound_name,
                   [("notification_soft", "notification_soft (default)")])
            + '<div style="height:1px;background:var(--border);margin:12px 0;"></div>'
            + _cb("tsf-n", "quiet_period_notifications_enabled", "Quiet period notifications",
                  n.quiet_period_notifications_enabled)
            + _cb("tsf-n", "admin_message_notifications_enabled", "Admin message notifications",
                  n.admin_message_notifications_enabled)
            + _cb("tsf-n", "access_code_notifications_enabled", "Access code notifications",
                  n.access_code_notifications_enabled)
            + _cb("tsf-n", "audit_notifications_enabled", "Audit event notifications",
                  n.audit_notifications_enabled)
            + _save("tsf-notifications", "notifications", "ts-notif-status")
            + '</form>'
            + '<p style="font-size:0.83rem;color:var(--muted);margin-top:8px;">'
              '\U0001f512 Emergency alert sound is system-locked and cannot be changed.</p>'
        )
    else:
        notif_body = (
            '<div style="max-width:580px;">'
            + _row_ro("Non-critical sound enabled", _yesno(n.non_critical_sound_enabled))
            + _row_ro("Non-critical sound name", f'<code>{escape(n.non_critical_sound_name)}</code>')
            + _row_ro("Quiet period notifications", _yesno(n.quiet_period_notifications_enabled))
            + _row_ro("Admin message notifications", _yesno(n.admin_message_notifications_enabled))
            + _row_ro("Access code notifications", _yesno(n.access_code_notifications_enabled))
            + _row_ro("Audit event notifications", _yesno(n.audit_notifications_enabled))
            + _row_ro("Emergency alert sound",
                      '<span style="font-weight:600;color:var(--muted);">\U0001f512 System-locked</span>')
            + '</div>'
        )

    # ── Quiet periods ────────────────────────────────────────────────────────
    if can_edit:
        qp_body = (
            '<form id="tsf-quiet_periods" class="stack" style="max-width:580px;" onsubmit="return false;">'
            + _cb("tsf-qp", "enabled", "Quiet periods enabled", q.enabled)
            + _cb("tsf-qp", "requires_approval", "Require admin approval", q.requires_approval)
            + _cb("tsf-qp", "allow_scheduling", "Allow scheduled quiet periods", q.allow_scheduling)
            + _num("tsf-qp", "max_duration_minutes", "Maximum duration",
                   q.max_duration_minutes, 15, 10080, "minutes")
            + _num("tsf-qp", "default_duration_minutes", "Default duration",
                   q.default_duration_minutes, 15, 1440, "minutes")
            # District-only quiet period fields
            + (
                _cb("tsf-qp", "district_admin_can_approve_all", "District admin can approve all buildings",
                    q.district_admin_can_approve_all)
                + _sel("tsf-qp", "building_admin_scope", "Building admin approval scope",
                       q.building_admin_scope,
                       [("building", "Building — own building only"),
                        ("district", "District — any building")])
                + _cb("tsf-qp", "allow_self_approval", "Allow self-approval", q.allow_self_approval,
                      "Caution: permits users to approve their own quiet period requests.")
                if is_district_admin else ""
            )
            + _save("tsf-quiet_periods", "quiet_periods", "ts-qp-status")
            + '</form>'
        )
    else:
        qp_body = (
            '<div style="max-width:580px;">'
            + _row_ro("Enabled", _yesno(q.enabled))
            + _row_ro("Requires approval", _yesno(q.requires_approval))
            + _row_ro("Allow scheduling", _yesno(q.allow_scheduling))
            + _row_ro("Max duration", f'<strong>{q.max_duration_minutes}</strong> min')
            + _row_ro("Default duration", f'<strong>{q.default_duration_minutes}</strong> min')
            # District-only quiet period fields (read-only view)
            + (
                _row_ro("District admin approves all", _yesno(q.district_admin_can_approve_all))
                + _row_ro("Building admin scope", f'<code>{escape(q.building_admin_scope)}</code>')
                + _row_ro("Allow self-approval", _yesno(q.allow_self_approval))
                if is_district_admin else ""
            )
            + '</div>'
        )

    # ── Alerts ───────────────────────────────────────────────────────────────
    if can_edit:
        alerts_body = (
            '<form id="tsf-alerts" class="stack" style="max-width:580px;" onsubmit="return false;">'
            + _cb("tsf-al", "teachers_can_trigger_secure_perimeter",
                  "Teachers can trigger Secure Perimeter", a.teachers_can_trigger_secure_perimeter)
            + _cb("tsf-al", "teachers_can_trigger_lockdown",
                  "Teachers can trigger Lockdown", a.teachers_can_trigger_lockdown)
            + _cb("tsf-al", "law_enforcement_can_trigger",
                  "Law enforcement can trigger alerts", a.law_enforcement_can_trigger)
            + _cb("tsf-al", "require_hold_to_activate",
                  "Require hold-to-activate", a.require_hold_to_activate,
                  "Staff must press and hold the emergency button for this many seconds before an alert fires. Prevents accidental triggers.")
            + _num("tsf-al", "hold_seconds", "Hold duration", a.hold_seconds, 1, 10, "seconds")
            + _cb("tsf-al", "disable_requires_admin",
                  "Only admins can disable alarm", a.disable_requires_admin)
            + _save("tsf-alerts", "alerts", "ts-alerts-status")
            + '</form>'
        )
    else:
        alerts_body = (
            '<div style="max-width:580px;">'
            + _row_ro("Teachers can trigger Secure Perimeter",
                      _yesno(a.teachers_can_trigger_secure_perimeter))
            + _row_ro("Teachers can trigger Lockdown", _yesno(a.teachers_can_trigger_lockdown))
            + _row_ro("Law enforcement can trigger", _yesno(a.law_enforcement_can_trigger))
            + _row_ro("Require hold-to-activate", _yesno(a.require_hold_to_activate))
            + _row_ro("Hold duration", f'<strong>{a.hold_seconds}</strong> sec')
            + _row_ro("Only admins can disable alarm", _yesno(a.disable_requires_admin))
            + '</div>'
        )

    # ── Devices ──────────────────────────────────────────────────────────────
    if can_edit:
        devices_body = (
            '<form id="tsf-devices" class="stack" style="max-width:580px;" onsubmit="return false;">'
            + _cb("tsf-dv", "device_status_reporting_enabled",
                  "Device status reporting enabled", d.device_status_reporting_enabled)
            + _num("tsf-dv", "mark_device_stale_after_minutes",
                   "Mark device stale after", d.mark_device_stale_after_minutes, 5, 1440, "minutes")
            + _cb("tsf-dv", "exclude_inactive_devices_from_push",
                  "Exclude inactive devices from push", d.exclude_inactive_devices_from_push)
            + _save("tsf-devices", "devices", "ts-devices-status")
            + '</form>'
        )
    else:
        devices_body = (
            '<div style="max-width:580px;">'
            + _row_ro("Status reporting", _yesno(d.device_status_reporting_enabled))
            + _row_ro("Mark stale after", f'<strong>{d.mark_device_stale_after_minutes}</strong> min')
            + _row_ro("Exclude inactive from push", _yesno(d.exclude_inactive_devices_from_push))
            + '</div>'
        )

    # ── Access codes ─────────────────────────────────────────────────────────
    if can_edit:
        ac_body = (
            '<form id="tsf-access_codes" class="stack" style="max-width:580px;" onsubmit="return false;">'
            + _cb("tsf-ac", "enabled", "Access codes enabled", ac.enabled)
            + _cb("tsf-ac", "auto_expire_enabled", "Auto-expire enabled", ac.auto_expire_enabled)
            + _num("tsf-ac", "default_expiration_days",
                   "Default expiration", ac.default_expiration_days, 1, 365, "days")
            + _cb("tsf-ac", "auto_archive_revoked_enabled",
                  "Auto-archive revoked codes", ac.auto_archive_revoked_enabled)
            + _num("tsf-ac", "auto_archive_revoked_after_days",
                   "Archive revoked codes after", ac.auto_archive_revoked_after_days, 1, 90, "days")
            + _save("tsf-access_codes", "access_codes", "ts-ac-status")
            + '</form>'
        )
    else:
        ac_body = (
            '<div style="max-width:580px;">'
            + _row_ro("Enabled", _yesno(ac.enabled))
            + _row_ro("Auto-expire", _yesno(ac.auto_expire_enabled))
            + _row_ro("Default expiration", f'<strong>{ac.default_expiration_days}</strong> days')
            + _row_ro("Auto-archive revoked", _yesno(ac.auto_archive_revoked_enabled))
            + _row_ro("Archive revoked after",
                      f'<strong>{ac.auto_archive_revoked_after_days}</strong> days')
            + '</div>'
        )

    # ── Assemble panels ──────────────────────────────────────────────────────
    alerts_panel = (f"""
    <section class="panel command-section" id="ts-alerts"{hidden}>
      <div class="panel-header"><div>
        <p class="eyebrow">District Settings</p>
        <h2>Alert trigger rules</h2>
        <p class="card-copy">Configure who can trigger alerts and how hold-to-activate works. District admin access required.</p>
      </div></div>
      {locked_banner}{alerts_body}
    </section>""") if is_district_admin else (f"""
    <section class="panel command-section" id="ts-alerts"{hidden}>
      <div class="panel-header"><div>
        <p class="eyebrow">District Settings</p>
        <h2>Alert trigger rules</h2>
        <p class="card-copy">Alert trigger policy is managed by your district administrator.</p>
      </div></div>
      {district_only_banner}
    </section>""")

    return f"""
    <section class="panel command-section" id="ts-notifications"{hidden}>
      <div class="panel-header"><div>
        <p class="eyebrow">School Settings</p>
        <h2>Notification preferences</h2>
        <p class="card-copy">Control which push channels are active and configure non-critical sound behaviour. Emergency alert sounds are system-locked.</p>
      </div></div>
      {locked_banner}{notif_body}
    </section>

    <section class="panel command-section" id="ts-quiet-periods"{hidden}>
      <div class="panel-header"><div>
        <p class="eyebrow">{"District Settings" if is_district_admin else "School Settings"}</p>
        <h2>Quiet period rules</h2>
        <p class="card-copy">Configure approval workflows and duration limits{", plus role-based scope (district admin only)" if is_district_admin else ""}.</p>
      </div></div>
      {locked_banner}{qp_body}
    </section>

    {alerts_panel}

    <section class="panel command-section" id="ts-devices"{hidden}>
      <div class="panel-header"><div>
        <p class="eyebrow">School Settings</p>
        <h2>Device management</h2>
        <p class="card-copy">Control device status reporting and staleness thresholds.</p>
      </div></div>
      {locked_banner}{devices_body}
    </section>

    <section class="panel command-section" id="ts-access-codes"{hidden}>
      <div class="panel-header"><div>
        <p class="eyebrow">School Settings</p>
        <h2>Access code settings</h2>
        <p class="card-copy">Configure access code defaults, auto-expiry, and lifecycle management.</p>
      </div></div>
      {locked_banner}{ac_body}
    </section>

    <script>
    (function() {{
      function tsSubmit(category, formId, statusId) {{
        var form = document.getElementById(formId);
        if (!form) return;
        var data = {{}};
        form.querySelectorAll('input[name], select[name]').forEach(function(el) {{
          if (el.type === 'checkbox') {{ data[el.name] = el.checked; }}
          else if (el.type === 'number') {{ data[el.name] = Number(el.value); }}
          else {{ data[el.name] = el.value; }}
        }});
        var statusEl = document.getElementById(statusId);
        fetch(BB_PATH_PREFIX + '/admin/settings/' + category, {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify(data),
        }}).then(function(r) {{
          return r.json().then(function(d) {{ return {{ok: r.ok, data: d}}; }});
        }}).then(function(res) {{
          if (res.ok) {{
            if (statusEl) {{ statusEl.textContent = '✓ Saved'; statusEl.style.color = '#16a34a'; }}
          }} else {{
            var d = res.data && res.data.detail;
            var errs = (d && d.errors) ? d.errors.join('; ') : JSON.stringify(d || res.data);
            if (statusEl) {{ statusEl.textContent = 'Error: ' + errs; statusEl.style.color = '#dc2626'; }}
          }}
          setTimeout(function() {{ if (statusEl) statusEl.textContent = ''; }}, 4000);
        }}).catch(function() {{
          if (statusEl) {{ statusEl.textContent = 'Network error'; statusEl.style.color = '#dc2626'; }}
        }});
      }}
      window.tsSubmit = tsSubmit;
    }})();
    </script>"""


def _render_settings_panels(
    prefix: str,
    school_name: str,
    school_slug: str,
    settings_history: Sequence[SettingsChangeRecord],
    _section_style,
    effective_settings: Optional[TenantSettings] = None,
    can_edit: bool = False,
    is_district_admin: bool = False,
) -> str:
    # ── Change History ───────────────────────────────────────────────────────
    if settings_history:
        history_rows = ""
        for rec in settings_history:
            undone_badge = '<span style="color:var(--muted);font-size:0.78rem;">(undone)</span>' if rec.is_undone else ""
            undo_btn = (
                f'<form method="post" action="{prefix}/admin/settings/undo/{rec.id}" style="display:inline;">'
                f'<button type="submit" class="button button-secondary" style="min-height:30px;padding:0 12px;font-size:0.82rem;">Undo</button>'
                f'</form>'
            ) if not rec.is_undone else ""
            old_display = ", ".join(f"{k}: {escape(str(v))}" for k, v in rec.old_value.items()) or "—"
            new_display = ", ".join(f"{k}: {escape(str(v))}" for k, v in rec.new_value.items()) or "—"
            history_rows += f"""
              <tr>
                <td style="white-space:nowrap;">{escape(rec.changed_at[:19].replace("T", " "))}</td>
                <td>{escape(rec.field)} {undone_badge}</td>
                <td style="color:var(--muted);font-size:0.85rem;">{old_display}</td>
                <td style="font-size:0.85rem;">{new_display}</td>
                <td>{undo_btn}</td>
              </tr>"""
        history_html = f"""
          <div style="overflow-x:auto;">
            <table style="width:100%;border-collapse:collapse;font-size:0.9rem;">
              <thead>
                <tr style="border-bottom:1px solid var(--border);color:var(--muted);">
                  <th style="text-align:left;padding:8px 10px;">When</th>
                  <th style="text-align:left;padding:8px 10px;">Field</th>
                  <th style="text-align:left;padding:8px 10px;">Before</th>
                  <th style="text-align:left;padding:8px 10px;">After</th>
                  <th style="text-align:left;padding:8px 10px;"></th>
                </tr>
              </thead>
              <tbody>{history_rows}</tbody>
            </table>
          </div>"""
    else:
        history_html = '<p class="card-copy">No settings changes recorded yet.</p>'

    hidden = _section_style("settings")
    tenant_panels_html = (
        _render_tenant_settings_panels(prefix, effective_settings, can_edit, hidden, is_district_admin=is_district_admin)
        if effective_settings is not None
        else ""
    )
    return f"""
        <section class="panel command-section" id="school-info"{hidden}>
          <div class="panel-header">
            <div>
              <p class="eyebrow">School Settings</p>
              <h2>School information</h2>
              <p class="card-copy">Update your school's display name. The school ID (slug) is permanent and cannot be changed here.</p>
            </div>
          </div>
          <div class="stack" style="max-width:520px;">
            <form method="post" action="{prefix}/admin/settings/name">
              <div class="field" style="margin-bottom:12px;">
                <label for="settings-name">School name</label>
                <input id="settings-name" name="name" type="text" value="{escape(school_name)}" required maxlength="200" />
              </div>
              <div style="display:flex;align-items:center;gap:12px;margin-bottom:6px;">
                <span style="color:var(--muted);font-size:0.88rem;">School ID: <strong>{escape(school_slug)}</strong></span>
              </div>
              <button type="submit" class="button button-primary">Save name</button>
            </form>
          </div>
        </section>

        {tenant_panels_html}

        <section class="panel command-section" id="settings-history"{hidden}>
          <div class="panel-header">
            <div>
              <p class="eyebrow">School Settings</p>
              <h2>Change history</h2>
              <p class="card-copy">Every settings change is recorded with its before and after values. You can undo any change that has not already been undone.</p>
            </div>
          </div>
          {history_html}
        </section>"""


def render_admin_page(
    *,
    school_name: str,
    school_slug: str,
    school_path_prefix: str,
    selected_tenant_slug: str,
    selected_tenant_name: str,
    tenant_options: Sequence[Mapping[str, str]],
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
    current_alert_id: Optional[int] = None,
    fcm_configured: bool = False,
    delivery_stats: Optional[Mapping[str, object]] = None,
    audit_events: Sequence[AuditEventRecord] = (),
    audit_event_types: Sequence[str] = (),
    audit_event_type_filter: str = "",
    district_overview_items: Sequence[Mapping[str, object]] = (),
    ws_api_key: str = "",
    current_user_id: Optional[int] = None,
    home_tenant_slug: str = "",
    access_code_records: Sequence[object] = (),
    base_domain: str = "bluebird-alerts.com",
    settings_history: Sequence[SettingsChangeRecord] = (),
    school_district_id: Optional[int] = None,
    active_sessions: Sequence[object] = (),
    sessions_users_by_id: Mapping[int, object] = {},
    active_tab: str = "",
    is_demo_mode: bool = False,
    effective_settings: Optional[TenantSettings] = None,
    can_edit_tenant_settings: bool = False,
    billing_banner: Optional[dict] = None,
) -> str:
    prefix = escape(school_path_prefix)
    role_counts = Counter(user.role for user in users)
    platform_counts = Counter(device.platform for device in devices)
    provider_counts = Counter(device.push_provider for device in devices)
    _active_user_list = [u for u in users if u.is_active and not getattr(u, "is_archived", False)]
    _inactive_user_list = [u for u in users if not u.is_active and not getattr(u, "is_archived", False)]
    _archived_user_list = [u for u in users if getattr(u, "is_archived", False)]
    _um_tab = active_tab if active_tab in {"active", "inactive", "archived", "codes"} else "active"
    # Count active district admins (for last-DA delete guard in UI)
    _active_da_count = sum(1 for u in _active_user_list if u.role == "district_admin")
    active_users = sum(1 for user in users if user.is_active)
    login_enabled = sum(1 for user in users if user.can_login)
    alarm_status_class = "danger" if alarm_state.is_active and not alarm_state.is_training else ("warn" if alarm_state.is_active else "ok")
    alarm_status_label = "TRAINING ACTIVE" if alarm_state.is_active and alarm_state.is_training else ("ALARM ACTIVE" if alarm_state.is_active else "Alarm clear")
    security_feedback = f"{_render_flash(flash_message, 'success')}{_render_flash(flash_error, 'error')}"
    section = active_section if active_section in {"dashboard", "user-management", "access-codes", "quiet-periods", "audit-logs", "settings", "drill-reports", "district", "devices", "analytics", "district-reports", "demo-analytics"} else "dashboard"
    _billing_banner_html = _render_billing_banner(billing_banner or {})
    _demo_banner_html = (
        '<div style="background:#fef3c7;border-bottom:2px solid #d97706;padding:8px 20px;'
        'font-size:0.85rem;color:#92400e;display:flex;align-items:center;gap:10px;position:sticky;top:0;z-index:200;">'
        '<span>⚠</span>'
        '<strong>Demo Environment</strong> — No real alerts are sent. All activity is simulated.'
        '<div style="margin-left:auto;display:flex;gap:8px;">'
        '<button onclick="showDemoWalkthrough()" style="background:#fff7ed;color:#92400e;border:1px solid #d97706;border-radius:6px;padding:4px 12px;font-size:0.8rem;cursor:pointer;">🎬 Walkthrough</button>'
        '<button onclick="startBluebirdTour()" style="background:#d97706;color:#fff;border:none;border-radius:6px;padding:4px 12px;font-size:0.8rem;cursor:pointer;">▶ Guided Tour</button>'
        '</div>'
        '</div>'
    ) if is_demo_mode else ""
    _demo_badge_html = (
        '<span style="background:#fef3c7;color:#92400e;font-size:0.7rem;font-weight:700;padding:2px 8px;'
        'border-radius:4px;border:1px solid #d97706;vertical-align:middle;margin-left:6px;">DEMO</span>'
    ) if is_demo_mode else ""
    _um_badge_count = len(quiet_periods_active)
    quiet_period_total = len(quiet_periods_active) + len(quiet_periods_history)
    refresh_meta = '<meta http-equiv="refresh" content="30">' if section in {"dashboard", "district", "devices"} else ""
    show_district_nav = str(getattr(current_user, "role", "")).strip().lower() in {"district_admin", "super_admin"}
    user_title = str(getattr(current_user, "title", "") or "").strip()
    user_display_name = f"{escape(current_user.name)} ({escape(user_title)})" if user_title else escape(current_user.name)
    _ack_pill_visible = alarm_state.is_active and acknowledgement_count > 0
    _ack_pill_hidden_attr = '' if _ack_pill_visible else ' style="display:none;"'
    _ack_plural = "s" if acknowledgement_count != 1 else ""
    ack_pill = (
        f'<span id="js-ack-pill" class="status-pill ok"{_ack_pill_hidden_attr}>'
        f'<strong>Acknowledged</strong>{acknowledgement_count} user{_ack_plural}</span>'
    )

    # District admin flag: district_admin or super_admin (used for settings + onboarding)
    is_district_admin = is_district_admin_or_higher(str(getattr(current_user, "role", "")))

    # Smart suggestions
    _sg_ack_rate: Optional[float] = (
        acknowledgement_count / max(active_users, 1)
        if alarm_state.is_active and active_users > 0 else None
    )
    _ack_pct = int(acknowledgement_count / max(active_users, 1) * 100) if alarm_state.is_active and active_users > 0 else 0
    _ack_bar_color = "#16a34a" if _ack_pct >= 90 else ("#d97706" if _ack_pct >= 60 else "#dc2626")
    _sg_ctx = SuggestionContext(
        role=str(getattr(current_user, "role", "")),
        prefix=school_path_prefix,
        user_count=len(users),
        active_user_count=active_users,
        device_count=len(devices),
        apns_configured=apns_configured,
        fcm_configured=fcm_configured,
        totp_enabled=totp_enabled,
        access_code_count=len(access_code_records),
        unread_messages=unread_admin_messages,
        help_requests_active=len(request_help_active),
        alert_count_7d=len(alerts),
        district_admin_count=sum(1 for u in users if getattr(u, "role", "") == "district_admin"),
        acknowledgement_rate=_sg_ack_rate,
    )
    _sg_suggestions = SuggestionEngine().evaluate(_sg_ctx)
    _sg_panel_html = _render_suggestion_panel(_sg_suggestions, school_path_prefix)

    # District admin onboarding
    _da_cl_html = _render_da_checklist(
        user_count=len(users),
        device_count=len(devices),
        apns_configured=apns_configured,
        fcm_configured=fcm_configured,
        alert_count_7d=len(alerts),
        totp_enabled=totp_enabled,
        prefix=school_path_prefix,
    ) if is_district_admin else ""
    _da_welcome_html = _render_da_welcome_modal(selected_tenant_name) if is_district_admin else ""

    # Phase 2 panel computed values
    _ds = delivery_stats or {}
    _ds_total = int(_ds.get("total", 0))
    _ds_ok = int(_ds.get("ok", 0))
    _ds_failed = int(_ds.get("failed", 0))
    _ds_last_error = str(_ds.get("last_error") or "") if _ds.get("last_error") else ""
    _ds_by_provider: dict = _ds.get("by_provider", {}) or {}  # type: ignore[assignment]
    def _provider_rows() -> str:
        rows = []
        for prov, pstats in _ds_by_provider.items():
            fail_count = int(pstats.get("failed", 0))
            fail_style = ' style="color:#ef4444;"' if fail_count > 0 else ""
            last_err = str(pstats.get("last_error") or "")
            err_row = (
                f'<tr><td colspan="4" class="mini-copy" style="color:#ef4444;">{escape(last_err[:100])}</td></tr>'
                if last_err else ""
            )
            rows.append(
                f'<tr>'
                f'<td style="font-family:monospace;font-size:0.78rem;">{escape(str(prov).upper())}</td>'
                f'<td>{int(pstats.get("total", 0))}</td>'
                f'<td>{int(pstats.get("ok", 0))}</td>'
                f'<td{fail_style}>{fail_count}</td>'
                f'</tr>{err_row}'
            )
        return "".join(rows)
    _push_configured = apns_configured or fcm_configured
    _ios_count = platform_counts.get("ios", 0)
    _android_count = platform_counts.get("android", 0)
    _apns_token_count = provider_counts.get("apns", 0)
    _fcm_token_count = provider_counts.get("fcm", 0)
    _total_device_count = len(devices)
    _thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
    _recently_active_device_count = sum(
        1 for d in devices
        if getattr(d, "last_seen_at", None) and str(d.last_seen_at) >= _thirty_days_ago
    )
    _coverage_ratio = (_recently_active_device_count / max(active_users, 1)) if active_users > 0 else 0.0
    _readiness_score = (
        (25 if _push_configured else 0)
        + (20 if _total_device_count > 0 else 0)
        + (15 if _coverage_ratio >= 0.5 else 0)
        + (20 if totp_enabled else 0)
        + (10 if len(access_code_records) > 0 else 0)
        + (10 if len(alerts) > 0 else 0)
    )
    _readiness_label = (
        "Excellent" if _readiness_score >= 90
        else "Good" if _readiness_score >= 70
        else "Fair" if _readiness_score >= 50
        else "Needs attention"
    )
    _readiness_class = (
        "ok" if _readiness_score >= 70
        else "warn" if _readiness_score >= 50
        else "danger"
    )

    _show_access_codes = can_generate_codes(str(getattr(current_user, "role", "")))
    _ac_status_class = {"active": "ok", "used": "warn", "expired": "warn", "revoked": "danger", "archived": "secondary"}

    # Build user-id → user lookup for claimed-by display (Phase 6)
    _ac_users_by_id = {int(getattr(u, "id", 0)): u for u in users}

    def _ac_row(r) -> str:
        _rid = int(getattr(r, "id", 0))
        _code = str(getattr(r, "code", ""))
        _status = str(getattr(r, "status", ""))
        _is_archived = bool(getattr(r, "is_archived", False))
        _is_active = _status == "active" and not _is_archived
        _qr_url = f"{prefix}/admin/access-codes/{_rid}/qr.png"
        _print_url = f"{prefix}/admin/access-codes/{_rid}/print"
        _download_url = f"{prefix}/admin/access-codes/{_rid}/qr.png"
        _pdf_url = f"{prefix}/admin/access-codes/{_rid}/packet.pdf"
        _assigned_name = str(getattr(r, "assigned_name", "") or "")
        _assigned_email = str(getattr(r, "assigned_email", "") or "")
        _label = str(getattr(r, "label", "") or "")
        _claimed_by_id = getattr(r, "claimed_by_user_id", None)
        _claimed_by_name = str(getattr(r, "claimed_by_name", "") or "")
        # Effective display status (archived overrides)
        _display_status = "archived" if _is_archived else _status

        # Phase 6: Claimed-user display
        if _status == "used":
            # Prefer claimed_by_name (actual claimant); fall back to assigned_name
            _claimer_name = _claimed_by_name or _assigned_name or "Self-registered"
            _claimer_user = _ac_users_by_id.get(int(_claimed_by_id)) if _claimed_by_id else None
            _claimer_link = (
                f'<button class="button button-secondary" style="font-size:0.72rem;padding:2px 7px;margin-top:2px;" '
                f'onclick="umOpenViewAs({int(_claimed_by_id)})">View User</button>'
                if (_claimed_by_id and _claimer_user) else ""
            )
            _assigned_cell = (
                f'<span style="font-size:0.82rem;color:var(--success);">&#10003; Claimed by: {escape(_claimer_name)}</span>'
                + (f'<br/><span style="color:var(--muted);font-size:0.75rem;">{escape(_assigned_email)}</span>' if _assigned_email else "")
                + (f'<br/>{_claimer_link}' if _claimer_link else "")
            )
        else:
            _assigned_cell = (
                f'<span style="font-size:0.82rem;">{escape(_assigned_name)}'
                + (f'<br/><span style="color:var(--muted);font-size:0.75rem;">{escape(_assigned_email)}</span>' if _assigned_email else "")
                + "</span>"
                if (_assigned_name or _assigned_email) else "—"
            )

        _qr_img = (
            f'<img src="{_qr_url}" alt="QR {escape(_code)}" width="80" height="80"'
            f' style="display:block;image-rendering:pixelated;border:1px solid #ddd;border-radius:4px;" />'
            if _is_active else
            '<span class="mini-copy" style="color:var(--muted);">—</span>'
        )
        _badge_url = f"{prefix}/admin/access-codes/{_rid}/badge.pdf"
        _send_invite_btn = (
            f'<button class="button button-secondary" style="font-size:0.75rem;padding:4px 10px;"'
            f' onclick="acSendSingleInvite({_rid})">Send Invite</button>'
            if (_is_active and _assigned_email) else ""
        )
        _action_buttons = (
            f'<a href="{_download_url}" download="bluebird-invite-{escape(_code)}.png"'
            f' class="button button-secondary" style="font-size:0.75rem;padding:4px 10px;text-decoration:none;">Download QR</a>'
            f'<a href="{_print_url}" target="_blank"'
            f' class="button button-secondary" style="font-size:0.75rem;padding:4px 10px;text-decoration:none;">Print Sheet</a>'
            f'<a href="{_pdf_url}" download="bluebird-onboarding-{escape(_code)}.pdf"'
            f' class="button button-secondary" style="font-size:0.75rem;padding:4px 10px;text-decoration:none;">PDF Packet</a>'
            f'<a href="{_badge_url}" download="bluebird-badge-{escape(_code)}.pdf"'
            f' class="button button-secondary" style="font-size:0.75rem;padding:4px 10px;text-decoration:none;">Badge Card</a>'
            + _send_invite_btn
        ) if _is_active else ""
        # Archive button: non-active and not already archived
        _archive_btn = (
            f'<form method="post" action="{prefix}/admin/access-codes/{_rid}/archive" style="margin:0;">'
            f'<button class="button button-secondary" type="submit"'
            f' style="font-size:0.75rem;padding:4px 10px;" title="Archive this code">Archive</button></form>'
        ) if (not _is_active and not _is_archived) else ""
        # Row styling: archived rows are muted and hidden by default
        _row_attrs = (
            ' data-archived="1" style="opacity:0.45;display:none;"'
            if _is_archived else ""
        )
        return (
            f"<tr{_row_attrs}>"
            f"<td style='min-width:90px;'>{_qr_img}</td>"
            f"<td><code style='font-size:1rem;letter-spacing:.05em;'>{escape(_code)}</code></td>"
            f"<td>{escape(str(getattr(r, 'role', '')))}</td>"
            f"<td>{escape(str(getattr(r, 'title', '') or '—'))}</td>"
            f"<td>{_assigned_cell}</td>"
            f"<td style='font-size:0.82rem;'>{escape(_label) if _label else '—'}</td>"
            f"<td><span class=\"status-pill {_ac_status_class.get(_display_status, 'warn')}\">"
            f"{escape(_display_status)}</span></td>"
            f"<td>{escape(str(getattr(r, 'expires_at', ''))[:16])}</td>"
            f"<td>{int(getattr(r, 'use_count', 0))}/{int(getattr(r, 'max_uses', 1))}</td>"
            f"<td><div style='display:flex;flex-direction:column;gap:4px;align-items:flex-start;'>"
            f"{_action_buttons}"
            f"<form method=\"post\" action=\"{prefix}/admin/access-codes/{_rid}/revoke\""
            f" onsubmit=\"return confirm('Revoke this code?');\" style='margin:0;'>"
            f"<button class=\"button button-danger-outline\" type=\"submit\""
            f" style='font-size:0.75rem;padding:4px 10px;' {'disabled' if not _is_active else ''}>Revoke</button></form>"
            f"{_archive_btn}"
            f"</div></td>"
            "</tr>"
        )

    _archived_count = sum(1 for r in access_code_records if getattr(r, "is_archived", False))
    _access_code_rows = "".join(_ac_row(r) for r in access_code_records) or '<tr><td colspan="10" class="empty-state">No access codes generated yet.</td></tr>'

    _client_type_label = {"mobile": "Mobile", "web": "Web"}
    _client_type_class = {"mobile": "rb-law_enforcement", "web": "rb-admin"}

    def _fmt_dt(raw: str) -> str:
        return str(raw or "")[:16].replace("T", " ")

    def _session_status_info(last_seen_at: str) -> tuple[str, str]:
        """Returns (label, css_class) based on how recently the session was seen."""
        if not last_seen_at:
            return ("Unknown", "warn")
        try:
            last = datetime.fromisoformat(str(last_seen_at).replace("Z", "+00:00"))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            mins = (datetime.now(timezone.utc) - last).total_seconds() / 60
            if mins < 5:
                return ("Active", "ok")
            elif mins < 30:
                return ("Delayed", "warn")
            else:
                return ("Offline", "danger")
        except Exception:
            return ("Unknown", "warn")

    _session_row_parts = []
    for _sess in active_sessions:
        _su = sessions_users_by_id.get(int(getattr(_sess, "user_id", 0)))
        _slast = str(getattr(_sess, "last_seen_at", ""))
        _slabel, _scls = _session_status_info(_slast)
        _savatar = (
            f'<span class="um-avatar ua-{escape(str(getattr(_su, "role", ""))[:20])}" style="width:28px;height:28px;font-size:11px;margin-right:8px;flex-shrink:0;">'
            + escape("".join(w[0].upper() for w in str(getattr(_su, "name", "?")).split()[:2]))
            + "</span>"
            + escape(str(getattr(_su, "name", f"user #{getattr(_sess, 'user_id', '?')}")))
        ) if _su else escape(f"user #{getattr(_sess, 'user_id', '?')}")
        _session_row_parts.append(
            "<tr>"
            f"<td style='overflow:hidden;'>{_savatar}</td>"
            f'<td><span class="role-badge {_client_type_class.get(str(getattr(_sess, "client_type", "mobile")), "rb-teacher")}">'
            + escape(_client_type_label.get(str(getattr(_sess, "client_type", "mobile")), str(getattr(_sess, "client_type", ""))))
            + "</span></td>"
            f'<td class="mini-copy">{escape(str(getattr(_su, "role", "—") if _su else "—"))}</td>'
            f'<td><span class="status-pill {_scls}" style="font-size:12px;">{_slabel}</span></td>'
            f'<td class="mini-copy">{escape(_fmt_dt(_slast))}</td>'
            f'<td class="mini-copy">{escape(_fmt_dt(str(getattr(_sess, "created_at", ""))))}</td>'
            f'<td><form method="post" action="{prefix}/admin/devices/{int(getattr(_sess, "id", 0))}/revoke"'
            f' onsubmit="return confirm(\'Force logout this device session?\');" style="margin:0;">'
            f'<button class="button button-danger-outline" type="submit" style="font-size:12px;padding:4px 12px;min-height:auto;">Force Logout</button>'
            f"</form></td>"
            "</tr>"
        )
    _session_rows = "".join(_session_row_parts) or '<tr><td colspan="7" class="empty-state">No active device sessions.</td></tr>'

    _reg_device_row_parts = []
    _reg_user_lookup = {u.id: u for u in users}
    for _rd in devices:
        _rdu = _reg_user_lookup.get(_rd.user_id) if _rd.user_id is not None else None
        _rd_owner = (
            escape(_rdu.login_name or _rdu.name) if _rdu
            else (escape("Unassigned") if _rd.user_id is None else escape(f"User #{_rd.user_id}"))
        )
        _rd_archived = bool(getattr(_rd, "archived_at", None))
        _rd_status = (
            '<span class="status-pill" style="background:var(--surface-alt,#f3f4f6);color:var(--text-muted);font-size:11px;">Archived</span>'
            if _rd_archived
            else '<span class="status-pill ok" style="font-size:11px;">Active</span>'
        )
        _rd_row_style = ' style="opacity:0.6;"' if _rd_archived else ""
        _rd_platform = escape(str(_rd.platform or "—"))
        _rd_provider = escape(str(_rd.push_provider or "—"))
        _rd_token_short = escape(_rd.token[-12:]) if _rd.token else "—"
        _rd_name = escape(_rd.device_name or "Unnamed device")
        _rd_plat_cls = "rb-law_enforcement" if _rd.platform == "ios" else ("rb-admin" if _rd.platform == "android" else "rb-teacher")
        _rd_prov_cls = "rb-law_enforcement" if _rd.push_provider == "apns" else ("rb-admin" if _rd.push_provider == "fcm" else "rb-teacher")
        _rd_last = escape(_fmt_dt(str(getattr(_rd, "last_seen_at", "") or ""))) or "—"
        _rd_action = (
            f'<form method="post" action="{prefix}/admin/devices/delete" onsubmit="bbConfirmSubmit(this,{{title:\'Remove device?\',body:\'This un-registers the device. The user will need to re-open the app to re-register.\',confirmLabel:\'Remove\',danger:true}});return false;" style="margin:0;">'
            f'<input type="hidden" name="token" value="{escape(_rd.token)}" />'
            f'<input type="hidden" name="push_provider" value="{escape(_rd.push_provider)}" />'
            f'<button class="button button-danger-outline" type="submit" style="font-size:11px;padding:4px 10px;min-height:auto;">Remove</button>'
            f'</form>'
            if not _rd_archived
            else '<span class="mini-copy" style="color:var(--text-muted);">Archived</span>'
        )
        _rd_initials = "".join(w[0].upper() for w in str(getattr(_rdu, "name", "?")).split()[:2]) if _rdu else "?"
        _rd_av_role = escape(str(getattr(_rdu, "role", ""))[:20]) if _rdu else ""
        _reg_device_row_parts.append(
            f'<tr{_rd_row_style}>'
            f'<td style="overflow:hidden;">'
            f'<span class="um-avatar ua-{_rd_av_role}" style="width:26px;height:26px;font-size:10px;margin-right:6px;flex-shrink:0;">{_rd_initials}</span>'
            f'{_rd_owner}</td>'
            f'<td><div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;">{_rd_name}</div>'
            f'<span class="role-badge {_rd_plat_cls}" style="font-size:10px;margin-top:2px;">{_rd_platform}</span></td>'
            f'<td><span class="role-badge {_rd_prov_cls}" style="font-size:10px;">{_rd_provider}</span>'
            f'<br><code style="font-size:10px;color:var(--text-muted);">…{_rd_token_short}</code></td>'
            f'<td>{_rd_status}</td>'
            f'<td class="mini-copy">{_rd_last}</td>'
            f'<td>{_rd_action}</td>'
            f'</tr>'
        )
    _reg_device_rows = "".join(_reg_device_row_parts) or '<tr><td colspan="6" class="empty-state">No registered devices.</td></tr>'

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
    _bb_911_notice_html = (
        '<div class="bb-911-notice" id="bb-911-notice" style="display:none;">'
        '<span>&#9888; <strong>BlueBird is an internal communication tool.</strong>'
        ' It does not contact 911 or replace emergency services.'
        ' Always call 911 in a real emergency.</span>'
        '<button class="bb-911-notice-close" onclick="bb911Dismiss()" aria-label="Dismiss">&times;</button>'
        '</div>'
        if section == "dashboard" else ""
    )
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
    if _show_access_codes:
        _bulk_generate_url = f"{prefix}/admin/access-codes/bulk-generate"
        _import_csv_url = f"{prefix}/admin/access-codes/import-csv"
        _send_invites_url = f"{prefix}/admin/access-codes/send-invites"
        _send_reminders_url = f"{prefix}/admin/access-codes/send-reminders"
        _onboarding_reports_url = f"{prefix}/admin/onboarding/reports"
        _gen_api_url = f"{prefix}/admin/access-codes/generate-api"
        _ac_user_opts = (
            '<option value="">— No pre-assignment —</option>'
            + "".join(
                f'<option value="{u.id}" data-name="{escape(u.name)}" data-email="{escape(getattr(u, "email", "") or "")}">'
                f'{escape(u.name)} ({escape(u.role)})</option>'
                for u in users if u.is_active and not getattr(u, "is_archived", False)
            )
        )
        _access_codes_panel_html = f"""
          <!-- ── Generate Code Modal ─────────────────────────────────────────── -->
          <div id="ac-gen-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:1100;align-items:center;justify-content:center;">
            <div style="background:var(--card,#fff);border-radius:12px;padding:28px 32px;max-width:500px;width:100%;max-height:92vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,.25);">
              <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;">
                <h3 style="margin:0;">Generate Access Code</h3>
                <button type="button" class="button button-secondary" style="padding:4px 10px;font-size:0.8rem;" onclick="acCloseGenModal()">&#x2715;</button>
              </div>
              <!-- Step 1: form -->
              <div id="ag-form-step">
                <div class="field" style="margin-bottom:12px;">
                  <label>Role</label>
                  <select id="ag-role" style="width:100%;">
                    <option value="building_admin">Building Admin</option>
                    <option value="teacher">Teacher / Standard</option>
                    <option value="staff">Staff</option>
                    <option value="law_enforcement">Law Enforcement</option>
                  </select>
                </div>
                <div class="field" style="margin-bottom:12px;">
                  <label>Pre-assign to existing user (optional)</label>
                  <select id="ag-user" style="width:100%;">{_ac_user_opts}</select>
                </div>
                <div class="field" style="margin-bottom:12px;">
                  <label>Job title override (optional)</label>
                  <input id="ag-title" placeholder="e.g. Science Teacher" style="width:100%;" />
                </div>
                <div class="checkbox-row" style="margin-bottom:10px;">
                  <input type="checkbox" id="ag-autoexpire" checked onchange="document.getElementById('ag-expiry-row').style.display=this.checked?'block':'none'" />
                  <label for="ag-autoexpire">Set expiry date</label>
                </div>
                <div id="ag-expiry-row" class="field" style="margin-bottom:12px;">
                  <label>Expires in (hours) <span style="color:var(--muted);font-size:0.78rem;">default 48h = 2 days</span></label>
                  <input id="ag-expires" type="number" min="1" max="8760" value="48" style="width:100%;" />
                </div>
                <div class="field" style="margin-bottom:20px;">
                  <label>Max uses</label>
                  <input id="ag-maxuses" type="number" min="1" max="20" value="1" style="width:100%;" />
                </div>
                <div id="ag-error" style="display:none;padding:10px;border-radius:8px;background:#fef2f2;border:1px solid #fca5a5;font-size:0.85rem;color:#dc2626;margin-bottom:12px;"></div>
                <div class="button-row">
                  <button class="button button-primary" type="button" onclick="acDoGenerate()">Generate Code</button>
                  <button class="button button-secondary" type="button" onclick="acCloseGenModal()">Cancel</button>
                </div>
              </div>
              <!-- Step 2: QR result -->
              <div id="ag-result-step" style="display:none;text-align:center;">
                <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:20px;margin-bottom:16px;">
                  <div style="font-size:0.78rem;color:#065f46;font-weight:700;text-transform:uppercase;letter-spacing:.04em;margin-bottom:12px;">Code Generated</div>
                  <img id="ag-qr-img" src="" alt="QR code" width="164" height="164" style="display:block;margin:0 auto 14px;image-rendering:pixelated;border:2px solid #ddd;border-radius:6px;" />
                  <div id="ag-code-text" style="font-family:monospace;font-size:1.6rem;letter-spacing:.14em;font-weight:800;color:#065f46;margin-bottom:6px;"></div>
                  <div id="ag-invite-url" style="font-size:0.7rem;color:var(--muted);word-break:break-all;"></div>
                </div>
                <div class="button-row" id="ag-result-actions" style="flex-wrap:wrap;justify-content:center;gap:6px;margin-bottom:16px;"></div>
                <div class="button-row" style="justify-content:center;gap:8px;">
                  <button class="button button-secondary" type="button" onclick="acGenAnother()">Generate Another</button>
                  <button class="button button-primary" type="button" onclick="acCloseGenModal();window.location.reload();">Done</button>
                </div>
              </div>
            </div>
          </div>

          <!-- ── Toast notification ───────────────────────────────────────── -->
          <div id="ac-toast" style="display:none;position:fixed;bottom:24px;right:24px;z-index:2000;background:#1e293b;color:#fff;padding:12px 20px;border-radius:10px;font-size:0.9rem;box-shadow:0 8px 24px rgba(0,0,0,.25);max-width:340px;pointer-events:none;"></div>

          <!-- ── Codes tab actions bar ──────────────────────────────────────── -->
          <div id="ac-codes-header" style="display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin-bottom:12px;">
            <button class="button button-primary" style="min-height:36px;font-size:0.85rem;" onclick="acOpenGenModal()">+ Generate Code</button>
            <button class="button button-secondary" style="min-height:36px;font-size:0.85rem;" onclick="document.getElementById('ac-bulk-modal').style.display='flex'">Bulk Generate</button>
            <button class="button button-secondary" style="min-height:36px;font-size:0.85rem;" onclick="document.getElementById('ac-csv-modal').style.display='flex'">Import CSV</button>
            <button class="button button-secondary" style="min-height:36px;font-size:0.85rem;" onclick="document.getElementById('ac-invites-modal').style.display='flex'">Send Invites</button>
            <button class="button button-secondary" style="min-height:36px;font-size:0.85rem;" onclick="document.getElementById('ac-reminders-modal').style.display='flex'">Send Reminders</button>
            <button class="button button-secondary" style="min-height:36px;font-size:0.85rem;" onclick="acLoadReports()">Onboarding Reports</button>
            <button class="button button-secondary" style="min-height:36px;font-size:0.85rem;" onclick="document.getElementById('ac-archive-revoked-modal').style.display='flex'">Archive All Revoked</button>
          </div>
          <!-- ── Secondary toolbar: filter + archived controls ─────────────── -->
          <div style="display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:16px;padding:8px 12px;background:var(--surface,#f8fafc);border-radius:8px;border:1px solid var(--border,#e5e7eb);">
            <label style="display:flex;align-items:center;gap:6px;font-size:0.85rem;cursor:pointer;">
              <input type="checkbox" id="ac-show-archived" onchange="acToggleArchived(this.checked)" />
              Show archived ({_archived_count})
            </label>
            <button id="ac-delete-archived-btn" class="button button-danger-outline" style="min-height:30px;font-size:0.8rem;padding:0 12px;display:none;" onclick="document.getElementById('ac-delete-archived-modal').style.display='flex'">Delete Archived Codes</button>
            <span style="margin-left:auto;font-size:0.8rem;color:var(--muted);">
              Auto-archive:
              <button id="ac-autoarchive-toggle" class="button button-secondary" style="font-size:0.78rem;padding:2px 10px;min-height:26px;" onclick="acOpenAutoArchiveSettings()">Configure</button>
            </span>
          </div>
          <div class="table-wrapper" style="overflow-x:auto;">
            <table class="data-table">
              <thead><tr><th>QR</th><th>Code</th><th>Role</th><th>Title</th><th>Claimed / Assigned</th><th>Label</th><th>Status</th><th>Expires</th><th>Uses</th><th>Actions</th></tr></thead>
              <tbody id="ac-table-body">{_access_code_rows}</tbody>
            </table>
          </div>

          <!-- ── Bulk Generate Modal ────────────────────────────────────────── -->
          <div id="ac-bulk-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:1100;align-items:center;justify-content:center;">
            <div style="background:var(--card,#fff);border-radius:12px;padding:28px 32px;max-width:480px;width:100%;max-height:90vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,.25);">
              <h3 style="margin-bottom:16px;">Bulk Generate Codes</h3>
              <div class="field" style="margin-bottom:12px;">
                <label>Quantity (1–100)</label>
                <input id="bg-qty" type="number" min="1" max="100" value="10" style="width:100%;" />
              </div>
              <div class="field" style="margin-bottom:12px;">
                <label>Role</label>
                <select id="bg-role" style="width:100%;">
                  <option value="teacher">Teacher / Standard</option>
                  <option value="staff">Staff</option>
                  <option value="building_admin">Building Admin</option>
                  <option value="law_enforcement">Law Enforcement</option>
                </select>
              </div>
              <div class="field" style="margin-bottom:12px;">
                <label>Job title (optional)</label>
                <input id="bg-title" placeholder="e.g. Science Teacher" style="width:100%;" />
              </div>
              <div class="field" style="margin-bottom:12px;">
                <label>Expires (hours)</label>
                <input id="bg-expires" type="number" min="1" max="720" value="48" style="width:100%;" />
              </div>
              <div class="field" style="margin-bottom:20px;">
                <label>Batch label (optional)</label>
                <input id="bg-label" placeholder="e.g. HS Science Dept" style="width:100%;" />
              </div>
              <div id="bg-result" style="display:none;margin-bottom:16px;padding:12px;border-radius:8px;background:#f0fdf4;border:1px solid #bbf7d0;font-size:0.9rem;"></div>
              <div id="bg-dl-links" style="display:none;margin-bottom:16px;"></div>
              <div class="button-row">
                <button class="button button-primary" onclick="acDoBulkGenerate()">Generate</button>
                <button class="button button-secondary" onclick="document.getElementById('ac-bulk-modal').style.display='none'">Cancel</button>
              </div>
            </div>
          </div>

          <!-- Import CSV Modal -->
          <div id="ac-csv-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:1100;align-items:center;justify-content:center;">
            <div style="background:var(--card,#fff);border-radius:12px;padding:28px 32px;max-width:460px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.25);">
              <h3 style="margin-bottom:8px;">Import CSV</h3>
              <p style="font-size:0.85rem;color:var(--muted);margin-bottom:16px;">Upload a CSV with columns <strong>name</strong> and <strong>email</strong>. One code will be pre-assigned per row.</p>
              <form id="ac-csv-form" style="display:flex;flex-direction:column;gap:12px;">
                <div class="field">
                  <label>CSV file</label>
                  <input id="csv-file" type="file" accept=".csv,text/csv" required style="width:100%;" />
                </div>
                <div class="field">
                  <label>Role</label>
                  <select id="csv-role" style="width:100%;">
                    <option value="teacher">Teacher / Standard</option>
                    <option value="staff">Staff</option>
                    <option value="building_admin">Building Admin</option>
                    <option value="law_enforcement">Law Enforcement</option>
                  </select>
                </div>
                <div class="field">
                  <label>Expires (hours)</label>
                  <input id="csv-expires" type="number" min="1" max="720" value="48" style="width:100%;" />
                </div>
                <div class="field">
                  <label>Batch label (optional)</label>
                  <input id="csv-label" placeholder="e.g. Fall Onboarding" style="width:100%;" />
                </div>
                <div id="csv-result" style="display:none;padding:10px;border-radius:8px;font-size:0.85rem;"></div>
                <div class="button-row">
                  <button type="button" class="button button-primary" onclick="acDoImportCsv()">Import</button>
                  <button type="button" class="button button-secondary" onclick="document.getElementById('ac-csv-modal').style.display='none'">Cancel</button>
                </div>
              </form>
            </div>
          </div>

          <!-- Send Invites Modal -->
          <div id="ac-invites-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:1100;align-items:center;justify-content:center;">
            <div style="background:var(--card,#fff);border-radius:12px;padding:28px 32px;max-width:460px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.25);">
              <h3 style="margin-bottom:8px;">Send Invite Emails</h3>
              <p style="font-size:0.85rem;color:var(--muted);margin-bottom:16px;">Send invitation emails to all codes that have an assigned email address and are still active. Codes without an assigned email will be skipped.</p>
              <div id="ac-invites-result" style="display:none;margin-bottom:12px;padding:10px;border-radius:8px;font-size:0.85rem;"></div>
              <div class="button-row">
                <button class="button button-primary" onclick="acDoSendAllInvites()">Send All Invites</button>
                <button class="button button-secondary" onclick="document.getElementById('ac-invites-modal').style.display='none'">Cancel</button>
              </div>
            </div>
          </div>

          <!-- Send Reminders Modal -->
          <div id="ac-reminders-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:1100;align-items:center;justify-content:center;">
            <div style="background:var(--card,#fff);border-radius:12px;padding:28px 32px;max-width:460px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.25);">
              <h3 style="margin-bottom:8px;">Send Reminder Emails</h3>
              <p style="font-size:0.85rem;color:var(--muted);margin-bottom:16px;">Send reminder emails to all unclaimed codes with an assigned email. Claimed, expired, and revoked codes are automatically skipped.</p>
              <div id="ac-reminders-result" style="display:none;margin-bottom:12px;padding:10px;border-radius:8px;font-size:0.85rem;"></div>
              <div class="button-row">
                <button class="button button-primary" onclick="acDoSendReminders()">Send Reminders</button>
                <button class="button button-secondary" onclick="document.getElementById('ac-reminders-modal').style.display='none'">Cancel</button>
              </div>
            </div>
          </div>

          <!-- ── Archive All Revoked Modal (Phase 2+3) ─────────────────────── -->
          <div id="ac-archive-revoked-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:1100;align-items:center;justify-content:center;">
            <div style="background:var(--card,#fff);border-radius:12px;padding:28px 32px;max-width:440px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.25);">
              <h3 style="margin:0 0 12px;">Archive all revoked access codes?</h3>
              <p style="font-size:0.88rem;color:var(--muted);margin-bottom:20px;">This will move all revoked access codes to the archive. Archived codes are hidden from the main list but are not deleted. This action can be undone by contacting support.</p>
              <div class="button-row">
                <button class="button button-primary" onclick="acDoArchiveRevoked()">Confirm Archive</button>
                <button class="button button-secondary" onclick="document.getElementById('ac-archive-revoked-modal').style.display='none'">Cancel</button>
              </div>
            </div>
          </div>

          <!-- ── Delete Archived Modal (Phase 7) ───────────────────────────── -->
          <div id="ac-delete-archived-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:1100;align-items:center;justify-content:center;">
            <div style="background:var(--card,#fff);border-radius:12px;padding:28px 32px;max-width:440px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.25);">
              <h3 style="margin:0 0 12px;color:#dc2626;">Delete all archived access codes?</h3>
              <p style="font-size:0.88rem;color:var(--muted);margin-bottom:8px;">This permanently deletes all archived codes. <strong>This cannot be undone.</strong></p>
              <p style="font-size:0.85rem;color:#dc2626;margin-bottom:20px;">Active, used, and expired codes are not affected — only archived codes are deleted.</p>
              <div class="button-row">
                <button class="button button-danger-outline" onclick="acDoDeleteArchived()">Delete Permanently</button>
                <button class="button button-secondary" onclick="document.getElementById('ac-delete-archived-modal').style.display='none'">Cancel</button>
              </div>
            </div>
          </div>

          <!-- ── Auto-Archive Settings Modal (Phase 5) ─────────────────────── -->
          <div id="ac-autoarchive-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:1100;align-items:center;justify-content:center;">
            <div style="background:var(--card,#fff);border-radius:12px;padding:28px 32px;max-width:420px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.25);">
              <h3 style="margin:0 0 8px;">Auto-Archive Settings</h3>
              <p style="font-size:0.85rem;color:var(--muted);margin-bottom:18px;">Automatically archive revoked codes after a set number of days.</p>
              <div class="checkbox-row" style="margin-bottom:14px;">
                <input type="checkbox" id="aa-enabled" onchange="document.getElementById('aa-days-row').style.display=this.checked?'flex':'none'" />
                <label for="aa-enabled" style="font-weight:600;">Auto-archive revoked codes</label>
              </div>
              <div id="aa-days-row" class="field" style="display:none;margin-bottom:18px;">
                <label>Archive after (days)</label>
                <input id="aa-days" type="number" min="1" max="365" value="7" style="width:100%;" />
              </div>
              <div id="aa-result" style="display:none;margin-bottom:12px;padding:10px;border-radius:8px;font-size:0.85rem;"></div>
              <div class="button-row">
                <button class="button button-primary" onclick="acSaveAutoArchive()">Save Settings</button>
                <button class="button button-secondary" onclick="document.getElementById('ac-autoarchive-modal').style.display='none'">Cancel</button>
              </div>
            </div>
          </div>

          <!-- Onboarding Reports Panel -->
          <div id="ac-reports-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:1100;align-items:center;justify-content:center;">
            <div style="background:var(--card,#fff);border-radius:12px;padding:28px 32px;max-width:620px;width:100%;max-height:85vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,.25);">
              <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
                <h3 style="margin:0;">Onboarding Reports</h3>
                <button class="button button-secondary" onclick="document.getElementById('ac-reports-modal').style.display='none'" style="font-size:0.8rem;padding:4px 10px;">Close</button>
              </div>
              <div id="ac-reports-body">
                <p style="color:var(--muted);font-size:0.9rem;">Loading...</p>
              </div>
            </div>
          </div>

          <script>
          (function() {{
            var _bgUrl = {json.dumps(_bulk_generate_url)};
            var _csvUrl = {json.dumps(_import_csv_url)};
            var _invitesUrl = {json.dumps(_send_invites_url)};
            var _remindersUrl = {json.dumps(_send_reminders_url)};
            var _reportsUrl = {json.dumps(_onboarding_reports_url)};
            var _genApiUrl = {json.dumps(_gen_api_url)};
            var _tenantSlug = {json.dumps(school_slug)};
            var _pathPrefix = {json.dumps(school_path_prefix)};

            window.acOpenGenModal = function() {{
              document.getElementById('ag-form-step').style.display = 'block';
              document.getElementById('ag-result-step').style.display = 'none';
              document.getElementById('ag-error').style.display = 'none';
              document.getElementById('ac-gen-modal').style.display = 'flex';
            }};

            window.acCloseGenModal = function() {{
              document.getElementById('ac-gen-modal').style.display = 'none';
            }};

            window.acGenAnother = function() {{
              document.getElementById('ag-form-step').style.display = 'block';
              document.getElementById('ag-result-step').style.display = 'none';
              document.getElementById('ag-error').style.display = 'none';
            }};

            window.acDoGenerate = function() {{
              var role = document.getElementById('ag-role').value;
              var userSel = document.getElementById('ag-user');
              var selOpt = userSel.options[userSel.selectedIndex];
              var assignedName = selOpt.dataset.name || null;
              var assignedEmail = selOpt.dataset.email || null;
              var title = document.getElementById('ag-title').value.trim() || null;
              var autoExpire = document.getElementById('ag-autoexpire').checked;
              var expiresHours = autoExpire ? (parseInt(document.getElementById('ag-expires').value) || 48) : 87600;
              var maxUses = parseInt(document.getElementById('ag-maxuses').value) || 1;
              var errEl = document.getElementById('ag-error');
              errEl.style.display = 'none';
              fetch(_genApiUrl, {{
                method: 'POST',
                credentials: 'same-origin',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                  role: role, title: title, tenant_slug: _tenantSlug,
                  max_uses: maxUses, expires_hours: expiresHours,
                  assigned_name: assignedName, assigned_email: assignedEmail,
                }})
              }})
              .then(function(r) {{
                if (!r.ok) {{ return r.json().then(function(e) {{ throw new Error(e.detail || 'Server error'); }}); }}
                return r.json();
              }})
              .then(function(d) {{
                document.getElementById('ag-form-step').style.display = 'none';
                document.getElementById('ag-result-step').style.display = 'block';
                document.getElementById('ag-code-text').textContent = d.code;
                document.getElementById('ag-qr-img').src = _pathPrefix + '/admin/access-codes/' + d.id + '/qr.png';
                document.getElementById('ag-invite-url').textContent = d.invite_url || '';
                var acts = document.getElementById('ag-result-actions');
                acts.innerHTML =
                  '<a href="' + _pathPrefix + '/admin/access-codes/' + d.id + '/qr.png" download="bb-code-' + d.code + '.png" class="button button-secondary" style="font-size:0.8rem;text-decoration:none;">Download QR</a>' +
                  '<a href="' + _pathPrefix + '/admin/access-codes/' + d.id + '/print" target="_blank" class="button button-secondary" style="font-size:0.8rem;text-decoration:none;">Print Sheet</a>' +
                  '<a href="' + _pathPrefix + '/admin/access-codes/' + d.id + '/packet.pdf" download="bb-packet-' + d.code + '.pdf" class="button button-secondary" style="font-size:0.8rem;text-decoration:none;">PDF Packet</a>' +
                  '<a href="' + _pathPrefix + '/admin/access-codes/' + d.id + '/badge.pdf" download="bb-badge-' + d.code + '.pdf" class="button button-secondary" style="font-size:0.8rem;text-decoration:none;">Badge Card</a>';
              }})
              .catch(function(e) {{
                errEl.style.display = 'block';
                errEl.textContent = 'Error: ' + e.message;
              }});
            }};

            window.acSendSingleInvite = function(codeId) {{
              if (!confirm('Send invite email to the assigned address for this code?')) return;
              fetch(_invitesUrl, {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{code_ids: [codeId]}})
              }})
              .then(function(r) {{ return r.json(); }})
              .then(function(d) {{
                alert('Sent: ' + d.sent + ', Skipped: ' + d.skipped + ', Failed: ' + d.failed);
              }})
              .catch(function(e) {{ alert('Error: ' + e.message); }});
            }};

            window.acDoSendAllInvites = function() {{
              fetch(_invitesUrl, {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{code_ids: []}})
              }})
              .then(function(r) {{ return r.json(); }})
              .then(function(d) {{
                var res = document.getElementById('ac-invites-result');
                res.style.display = 'block';
                res.style.background = '#f0fdf4';
                res.style.border = '1px solid #bbf7d0';
                res.textContent = 'Sent: ' + d.sent + ' | Skipped: ' + d.skipped + ' | Failed: ' + d.failed;
              }})
              .catch(function(e) {{
                var res = document.getElementById('ac-invites-result');
                res.style.display = 'block';
                res.style.background = '#fef2f2';
                res.style.border = '1px solid #fca5a5';
                res.textContent = 'Error: ' + e.message;
              }});
            }};

            window.acDoSendReminders = function() {{
              fetch(_remindersUrl, {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{}}),
              }})
              .then(function(r) {{ return r.json(); }})
              .then(function(d) {{
                var res = document.getElementById('ac-reminders-result');
                res.style.display = 'block';
                res.style.background = '#f0fdf4';
                res.style.border = '1px solid #bbf7d0';
                res.textContent = 'Sent: ' + d.sent + ' | Skipped: ' + d.skipped + ' | Failed: ' + d.failed;
              }})
              .catch(function(e) {{
                var res = document.getElementById('ac-reminders-result');
                res.style.display = 'block';
                res.style.background = '#fef2f2';
                res.style.border = '1px solid #fca5a5';
                res.textContent = 'Error: ' + e.message;
              }});
            }};

            window.acLoadReports = function() {{
              document.getElementById('ac-reports-modal').style.display = 'flex';
              document.getElementById('ac-reports-body').innerHTML = '<p style="color:var(--muted);font-size:0.9rem;">Loading...</p>';
              fetch(_reportsUrl)
              .then(function(r) {{ return r.json(); }})
              .then(function(d) {{
                var groups = d.groups || [];
                if (!groups.length) {{
                  document.getElementById('ac-reports-body').innerHTML = '<p style="color:var(--muted);">No codes found.</p>';
                  return;
                }}
                var html = '';
                groups.forEach(function(g) {{
                  var pct = g.total > 0 ? Math.round(g.claimed / g.total * 100) : 0;
                  var label = g.label || '(no label)';
                  html += '<div style="margin-bottom:20px;">';
                  html += '<div style="display:flex;justify-content:space-between;margin-bottom:4px;">';
                  html += '<span style="font-weight:600;">' + label + ' &mdash; ' + g.role + '</span>';
                  html += '<span style="font-size:0.85rem;color:var(--muted);">' + g.claimed + '/' + g.total + ' claimed (' + pct + '%)</span>';
                  html += '</div>';
                  html += '<div style="background:#e5e7eb;border-radius:4px;height:8px;overflow:hidden;margin-bottom:6px;">';
                  html += '<div style="background:#1a56db;height:100%;width:' + pct + '%;border-radius:4px;"></div>';
                  html += '</div>';
                  html += '<div style="font-size:0.8rem;color:var(--muted);">Unclaimed: ' + g.unclaimed + ' &nbsp;|&nbsp; Expired: ' + g.expired + ' &nbsp;|&nbsp; Revoked: ' + g.revoked + '</div>';
                  html += '</div>';
                }});
                document.getElementById('ac-reports-body').innerHTML = html;
              }})
              .catch(function(e) {{
                document.getElementById('ac-reports-body').innerHTML = '<p style="color:#dc2626;">Error loading reports: ' + e.message + '</p>';
              }});
            }};

            window.acDoBulkGenerate = function() {{
              var qty = parseInt(document.getElementById('bg-qty').value) || 1;
              var role = document.getElementById('bg-role').value;
              var title = document.getElementById('bg-title').value.trim() || null;
              var expires = parseInt(document.getElementById('bg-expires').value) || 48;
              var label = document.getElementById('bg-label').value.trim() || null;
              fetch(_bgUrl, {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{quantity: qty, role: role, title: title, expires_hours: expires, label: label}})
              }})
              .then(function(r) {{ return r.json(); }})
              .then(function(d) {{
                var res = document.getElementById('bg-result');
                res.style.display = 'block';
                res.textContent = 'Generated ' + d.created + ' codes.';
                var ids = (d.codes || []).map(function(c) {{ return c.id; }}).join(',');
                if (ids) {{
                  var dl = document.getElementById('bg-dl-links');
                  dl.style.display = 'block';
                  dl.innerHTML =
                    '<a href="{prefix}/admin/access-codes/bulk-packets.pdf?ids=' + ids + '" download class="button button-secondary" style="margin-right:8px;font-size:0.85rem;text-decoration:none;">Download PDF Packets</a>' +
                    '<a href="{prefix}/admin/access-codes/bulk.zip?ids=' + ids + '" download class="button button-secondary" style="font-size:0.85rem;text-decoration:none;">Download QR ZIP</a>';
                }}
                setTimeout(function() {{ window.location.reload(); }}, 3000);
              }})
              .catch(function(e) {{
                var res = document.getElementById('bg-result');
                res.style.display = 'block';
                res.style.background = '#fef2f2';
                res.style.borderColor = '#fca5a5';
                res.textContent = 'Error: ' + e.message;
              }});
            }};

            window.acDoImportCsv = function() {{
              var fileInput = document.getElementById('csv-file');
              if (!fileInput.files.length) {{ alert('Please select a CSV file.'); return; }}
              var fd = new FormData();
              fd.append('file', fileInput.files[0]);
              fd.append('role', document.getElementById('csv-role').value);
              fd.append('expires_hours', document.getElementById('csv-expires').value);
              fd.append('label', document.getElementById('csv-label').value);
              fetch(_csvUrl, {{method: 'POST', body: fd}})
              .then(function(r) {{ return r.json(); }})
              .then(function(d) {{
                var res = document.getElementById('csv-result');
                res.style.display = 'block';
                res.style.background = '#f0fdf4';
                res.style.border = '1px solid #bbf7d0';
                res.textContent = 'Created ' + d.created + ' codes' + (d.skipped ? ', skipped ' + d.skipped + ' rows.' : '.');
                setTimeout(function() {{ window.location.reload(); }}, 2500);
              }})
              .catch(function(e) {{
                var res = document.getElementById('csv-result');
                res.style.display = 'block';
                res.style.background = '#fef2f2';
                res.style.border = '1px solid #fca5a5';
                res.textContent = 'Error: ' + e.message;
              }});
            }};

            // ── Toast helper (Phase 8) ──────────────────────────────────────
            window.acToast = function(msg, isError) {{
              var t = document.getElementById('ac-toast');
              t.textContent = msg;
              t.style.background = isError ? '#dc2626' : '#1e293b';
              t.style.display = 'block';
              clearTimeout(t._timer);
              t._timer = setTimeout(function() {{ t.style.display = 'none'; }}, 3500);
            }};

            // ── Archived row toggle (Phase 7) ───────────────────────────────
            window.acToggleArchived = function(show) {{
              var rows = document.querySelectorAll('#ac-table-body tr[data-archived="1"]');
              rows.forEach(function(r) {{ r.style.display = show ? '' : 'none'; }});
              var delBtn = document.getElementById('ac-delete-archived-btn');
              if (delBtn) delBtn.style.display = show ? 'inline-flex' : 'none';
            }};

            // ── Archive All Revoked (Phase 4) ───────────────────────────────
            window.acDoArchiveRevoked = function() {{
              fetch(_pathPrefix + '/admin/access-codes/archive-revoked', {{
                method: 'POST', credentials: 'same-origin',
                headers: {{'Content-Type': 'application/json'}},
              }})
              .then(function(r) {{ return r.json(); }})
              .then(function(d) {{
                document.getElementById('ac-archive-revoked-modal').style.display = 'none';
                acToast('Revoked codes archived: ' + d.archived);
                setTimeout(function() {{ window.location.reload(); }}, 1500);
              }})
              .catch(function(e) {{
                document.getElementById('ac-archive-revoked-modal').style.display = 'none';
                acToast('Error: ' + e.message, true);
              }});
            }};

            // ── Delete Archived (Phase 7) ───────────────────────────────────
            window.acDoDeleteArchived = function() {{
              fetch(_pathPrefix + '/admin/access-codes/delete-archived', {{
                method: 'POST', credentials: 'same-origin',
                headers: {{'Content-Type': 'application/json'}},
              }})
              .then(function(r) {{ return r.json(); }})
              .then(function(d) {{
                document.getElementById('ac-delete-archived-modal').style.display = 'none';
                acToast('Archived codes deleted: ' + d.deleted);
                setTimeout(function() {{ window.location.reload(); }}, 1500);
              }})
              .catch(function(e) {{
                document.getElementById('ac-delete-archived-modal').style.display = 'none';
                acToast('Error: ' + e.message, true);
              }});
            }};

            // ── Auto-Archive Settings (Phase 5) ─────────────────────────────
            window.acOpenAutoArchiveSettings = function() {{
              fetch(_pathPrefix + '/admin/access-codes/settings')
              .then(function(r) {{ return r.json(); }})
              .then(function(d) {{
                document.getElementById('aa-enabled').checked = !!d.enabled;
                document.getElementById('aa-days').value = d.days || 7;
                document.getElementById('aa-days-row').style.display = d.enabled ? 'flex' : 'none';
                document.getElementById('aa-result').style.display = 'none';
                document.getElementById('ac-autoarchive-modal').style.display = 'flex';
              }})
              .catch(function(e) {{ acToast('Could not load settings: ' + e.message, true); }});
            }};

            window.acSaveAutoArchive = function() {{
              var enabled = document.getElementById('aa-enabled').checked;
              var days = parseInt(document.getElementById('aa-days').value) || 7;
              fetch(_pathPrefix + '/admin/access-codes/settings', {{
                method: 'POST', credentials: 'same-origin',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{auto_archive_enabled: enabled, auto_archive_days: days}}),
              }})
              .then(function(r) {{ return r.json(); }})
              .then(function(d) {{
                document.getElementById('ac-autoarchive-modal').style.display = 'none';
                acToast(d.auto_archive_enabled
                  ? 'Auto-archive enabled: archive after ' + d.auto_archive_days + ' days'
                  : 'Auto-archive disabled');
              }})
              .catch(function(e) {{
                acToast('Error saving settings: ' + e.message, true);
              }});
            }};
          }})();
          </script>"""
    else:
        _access_codes_panel_html = ""

    # Pre-compute inactive tab HTML
    _inactive_actor_role = str(getattr(current_user, "role", "") or "")

    def _inactive_rows() -> str:
        parts = []
        for u in _inactive_user_list:
            title_span = f'<span class="um-sub">{escape(u.title)}</span>' if getattr(u, "title", "") else ""
            name_esc = escape(u.name)
            _can_act = can_archive_user(_inactive_actor_role, u.role)
            if _can_act:
                _reactivate_btn = (
                    f'<form method="post" action="{prefix}/admin/users/{u.id}/set-active" style="margin:0;">'
                    f'<input type="hidden" name="is_active" value="1" />'
                    f'<button class="button button-secondary" style="min-height:30px;font-size:0.78rem;padding:0 10px;" type="submit">Reactivate</button>'
                    f'</form>'
                )
                _archive_btn = (
                    f'<form method="post" action="{prefix}/admin/users/{u.id}/archive" style="margin:0;"'
                    f' onsubmit="return confirm(\'Archive {name_esc}? They can be permanently deleted after.\');">'
                    f'<button class="button button-danger-outline" style="min-height:30px;font-size:0.78rem;padding:0 10px;" type="submit">Archive</button>'
                    f'</form>'
                )
                _row_actions = _reactivate_btn + _archive_btn
            else:
                _row_actions = (
                    '<span style="font-size:0.72rem;color:#7c3aed;background:rgba(124,58,237,0.1);'
                    'border-radius:6px;padding:3px 9px;white-space:nowrap;">&#128274; Protected Role</span>'
                )
            parts.append(
                f'<tr class="um-row">'
                f'<td style="width:44px;">{_um_avatar(u.name, u.role)}</td>'
                f'<td><span class="um-name" style="opacity:0.85;">{name_esc}</span>{title_span}</td>'
                f'<td>{_um_role_badge(u.role)}</td>'
                f'<td><span class="status-pill danger" style="font-size:.72rem;padding:2px 9px;min-height:0;">Inactive</span></td>'
                f'<td style="text-align:right;">'
                f'<div style="display:flex;gap:6px;justify-content:flex-end;align-items:center;">'
                + _row_actions
                + f'</div></td>'
                f'</tr>'
            )
        return "".join(parts)

    if _inactive_user_list:
        _inactive_tab_html = (
            '<div class="table-search" style="margin-bottom:14px;">'
            '<input type="search" id="user-search-inactive" placeholder="Search inactive users..." style="max-width:320px;"'
            ' oninput="(function(v){document.querySelectorAll(\'#um-inactive-table tbody tr.um-row\').forEach(function(r){r.style.display=r.textContent.toLowerCase().includes(v.toLowerCase())?\'\':\''
            'none\';})})(this.value)" />'
            f'<span class="mini-copy" style="margin-left:auto;">{len(_inactive_user_list)} inactive</span>'
            '</div>'
            '<div class="table-wrap">'
            '<table class="um-table" id="um-inactive-table">'
            '<thead><tr>'
            '<th></th><th>Name</th><th>Role</th><th>Status</th><th style="text-align:right;">Actions</th>'
            '</tr></thead>'
            f'<tbody>{_inactive_rows()}</tbody>'
            '</table></div>'
        )
    else:
        _inactive_tab_html = '<p class="mini-copy" style="color:var(--muted);padding:24px 0;">No inactive users.</p>'

    # Pre-compute archived tab HTML (avoids nested triple-quote f-strings)
    _archived_actor_role = str(getattr(current_user, "role", "") or "")

    def _archived_rows() -> str:
        parts = []
        for u in _archived_user_list:
            title_span = f'<span class="um-sub">{escape(u.title)}</span>' if getattr(u, "title", "") else ""
            archived_date = str(getattr(u, "archived_at", "") or "")[:10]
            name_esc = escape(u.name)
            _can_act = can_archive_user(_archived_actor_role, u.role)
            if _can_act:
                _delete_url = f"{prefix}/admin/users/{u.id}/delete"
                # 8.1: disable delete if this is the last district admin (archived count + active count = 1)
                _is_last_da = (
                    u.role == "district_admin" and
                    _active_da_count == 0 and
                    sum(1 for x in _archived_user_list if x.role == "district_admin") == 1
                )
                if _is_last_da:
                    _delete_btn = (
                        '<button class="button button-danger-outline" style="min-height:30px;font-size:0.78rem;padding:0 10px;opacity:0.45;cursor:not-allowed;" '
                        'type="button" disabled title="At least one district admin is required">Delete</button>'
                    )
                else:
                    _delete_btn = (
                        f'<button class="button button-danger-outline" style="min-height:30px;font-size:0.78rem;padding:0 10px;" type="button"'
                        f' onclick="umOpenDeleteModal({json.dumps(_delete_url)},{json.dumps(u.name)})">Delete</button>'
                    )
                _row_actions = (
                    f'<form method="post" action="{prefix}/admin/users/{u.id}/restore" style="margin:0;">'
                    f'<button class="button button-secondary" style="min-height:30px;font-size:0.78rem;padding:0 10px;" type="submit">Restore</button>'
                    f'</form>'
                    + _delete_btn
                )
            else:
                _row_actions = (
                    '<span style="font-size:0.72rem;color:#7c3aed;background:rgba(124,58,237,0.1);'
                    'border-radius:6px;padding:3px 9px;white-space:nowrap;">&#128274; Protected Role</span>'
                )
            parts.append(
                f'<tr class="um-row">'
                f'<td style="width:44px;">{_um_avatar(u.name, u.role)}</td>'
                f'<td><span class="um-name" style="opacity:0.7;">{name_esc}</span>{title_span}</td>'
                f'<td>{_um_role_badge(u.role)}</td>'
                f'<td style="color:var(--muted);font-size:0.8rem;">{archived_date}</td>'
                f'<td style="text-align:right;">'
                f'<div style="display:flex;gap:6px;justify-content:flex-end;align-items:center;">'
                + _row_actions
                + f'</div></td>'
                f'</tr>'
            )
        return "".join(parts)

    if _archived_user_list:
        _archived_tab_html = (
            '<div class="table-search" style="margin-bottom:14px;">'
            '<input type="search" id="user-search-archived" placeholder="Search archived users..." style="max-width:320px;"'
            ' oninput="(function(v){document.querySelectorAll(\'#um-archived-table tbody tr.um-row\').forEach(function(r){r.style.display=r.textContent.toLowerCase().includes(v.toLowerCase())?\'\':\''
            'none\';})})(this.value)" />'
            f'<span class="mini-copy" style="margin-left:auto;">{len(_archived_user_list)} archived</span>'
            '</div>'
            '<div class="table-wrap">'
            '<table class="um-table" id="um-archived-table">'
            '<thead><tr>'
            '<th></th><th>Name</th><th>Role</th><th>Archived</th><th style="text-align:right;">Actions</th>'
            '</tr></thead>'
            f'<tbody>{_archived_rows()}</tbody>'
            '</table></div>'
        )
    else:
        _archived_tab_html = '<p class="mini-copy" style="color:var(--muted);padding:24px 0;">No archived users.</p>'

    # Phase 12: pre-compute demo mode script block (avoids nested f-string/triple-quote limitation)
    _demo_analytics_url = prefix + "/admin/analytics/demo"
    _demo_slug_js = escape(school_slug)
    _tour_done_key = "bluebird_tour_done_" + escape(school_slug)
    _demo_push_feed_url = prefix + "/demo/push-feed"
    if is_demo_mode:
        # Inject server config + load external demo JS (tour + analytics live in bb-demo.js)
        _demo_mode_script_html = (
            f'\n  <script>window.BB_CONFIG = {{'
            f' isDemo: true,'
            f' demoSlug: \'{_demo_slug_js}\','
            f' demoAnalyticsUrl: \'{_demo_analytics_url}\','
            f' demoPushFeedUrl: \'{_demo_push_feed_url}\''
            f' }};</script>'
            f'\n  <script src="/static/js/bb-demo.js"></script>'
        )
    else:
        _demo_mode_script_html = ""


    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BlueBird Admin</title>
  {_favicon_tags()}
  {refresh_meta}
  <style>{_base_styles()}</style>
  <script>(function(){{var t=localStorage.getItem('bb_theme')||(window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');if(t==='dark')document.documentElement.setAttribute('data-theme','dark');}})();</script>
  <script src="/static/js/bb-safe.js"></script>
  <script>
  // Server-injected config — do not edit by hand.
  var BB_WS_API_KEY = {json.dumps(ws_api_key)};
  var BB_USER_ID = {json.dumps(current_user_id or 0)};
  var BB_HOME_TENANT = {json.dumps(home_tenant_slug)};
  var BB_TENANT_SLUG = {json.dumps(selected_tenant_slug)};
  var BB_SHOW_DISTRICT_WS = {json.dumps(show_district_nav)};
  var BB_PATH_PREFIX = {json.dumps(school_path_prefix)};
  var BB_ACTIVE_USERS = {json.dumps(active_users)};
  var BB_CURRENT_ALERT_ID = {json.dumps(current_alert_id)};
  </script>
  <script src="/static/js/bb-admin.js"></script>
{_demo_mode_script_html}

</head>
<body{"" if not is_demo_mode else ' data-demo="true"'}>
  <div class="app-shell">
    {_admin_header_html(
        user_display=user_display_name,
        school_name=school_name,
        tenant_selector_html=tenant_selector_html,
        logout_url=f"{prefix}/admin/logout",
        extra_action_html=super_admin_shell_action_html,
        selected_tenant_name=selected_tenant_name,
    )}
    <aside class="sidebar nav-panel">
      <section class="signal-card">
        <div class="nav-group">
          <p class="nav-label">Command Deck</p>
          <nav class="nav-list">
            {_nav_item("dashboard", "Dashboard")}
            {_nav_item("user-management", "User Management", str(_um_badge_count) if _um_badge_count else None)}
            {_nav_item("drill-reports", "Drill Reports")}
            {_nav_item("audit-logs", "Audit Logs")}
            {_nav_item("analytics", "Analytics")}
            {_nav_item("district-reports", "District Reports") if show_district_nav else ""}
            {_nav_item("demo-analytics", "📊 Demo Analytics") if is_demo_mode else ""}
            {_nav_item("settings", "Settings")}
            {_nav_item("district", "District Overview") if show_district_nav else ""}
            {_nav_item("devices", "Active Devices")}
          </nav>
        </div>
      </section>
    </aside>

      <section class="content-stack workspace">
        {_demo_banner_html}
        {_billing_banner_html}
        {_render_flash(flash_message, "success")}
        {_render_flash(flash_error, "error")}
        {super_admin_banner_html}

        {_bb_911_notice_html}

        <section class="panel command-section" id="overview"{_section_style("dashboard")}>
          <div class="panel-header hero-band">
            <div>
              <p class="eyebrow">Command Deck</p>
              <h1>Admin dashboard</h1>
              <p class="hero-copy">Manage users, see device readiness, review alerts, and control the active alarm state for <strong>{escape(selected_tenant_name)}</strong> from one place.</p>
            </div>
            <div class="status-row">
              <span id="js-alarm-status-pill" class="status-pill {alarm_status_class}"><strong>{alarm_status_label}</strong>{escape(alarm_state.message or 'No active alarm')}</span>
              {"<span class='status-pill warn'><strong>TRAINING</strong>" + escape(alarm_state.training_label or "This is a drill") + "</span>" if alarm_state.is_active and alarm_state.is_training else ""}
              {ack_pill}
              <span class="status-pill {'ok' if apns_configured else 'danger'}"><strong>APNs</strong>{'ready' if apns_configured else 'not configured'}{_help_tip('Apple Push Notifications — required for iPhone alert delivery. Configure in Settings if not ready.', right=True)}</span>
              <span class="status-pill {'ok' if twilio_configured else 'danger'}"><strong>SMS</strong>{'ready' if twilio_configured else 'not configured'}{_help_tip('Twilio SMS service — sends text alerts to phone numbers. Optional but recommended for users without the app.', right=True)}</span>
            </div>
          </div>
          <div class="metrics-grid">
            <article class="metric-card"><div class="meta">Users</div><div class="metric-value">{len(users)}</div></article>
            <article class="metric-card"><div class="meta">Active users</div><div class="metric-value">{active_users}</div></article>
            <article class="metric-card"><div class="meta">Login-enabled{_help_tip('Users who have a username and password set. All users receive push alerts regardless.')}</div><div class="metric-value">{login_enabled}</div></article>
            <article class="metric-card"><div class="meta">Devices</div><div class="metric-value">{len(devices)}</div></article>
            <article class="metric-card"><div class="meta">Recent alerts</div><div class="metric-value">{len(alerts)}</div></article>
            <article class="metric-card"><div class="meta">User reports</div><div class="metric-value">{len(reports)}</div></article>
            <article class="metric-card"><div class="meta">Open messages</div><div class="metric-value">{unread_admin_messages}</div></article>
            <article class="metric-card"><div class="meta">Active help requests</div><div class="metric-value">{len(request_help_active)}</div></article>
            <article class="metric-card"><div class="meta">Quiet period requests{_help_tip('Staff requests to suppress non-emergency notification sounds during sensitive activities (tests, performances).')}</div><div class="metric-value">{len(quiet_periods_active)}</div></article>
          </div>
          <div class="status-row" style="margin-top:16px;">
            {_count_list(role_counts)}
          </div>
        </section>

        {_render_next_steps_panel(
            role=str(getattr(current_user, "role", "")),
            user_count=len(users),
            device_count=len(devices),
            apns_configured=apns_configured,
            fcm_configured=fcm_configured,
            totp_enabled=totp_enabled,
            access_code_count=len(access_code_records),
            unread_messages=unread_admin_messages,
            help_requests_active=len(request_help_active),
            prefix=prefix,
        ) if section == "dashboard" else ""}

        {_sg_panel_html if section == "dashboard" else ""}

        {_da_cl_html if section == "dashboard" else ""}

        {_render_settings_panels(prefix, school_name, school_slug, settings_history, _section_style, effective_settings=effective_settings, can_edit=can_edit_tenant_settings, is_district_admin=is_district_admin)}

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
          {'''
          <div style="margin-top:24px;padding-top:20px;border-top:1px solid var(--border);">
            <p class="eyebrow">Onboarding</p>
            <h3 style="margin:0 0 6px;font-size:1rem;">Admin Console Tour</h3>
            <p class="card-copy" style="margin-bottom:14px;">Reset the guided tour so it shows again on your next visit. Also resets the district setup checklist.</p>
            <button class="button button-secondary" type="button" onclick="bbDaResetOnboarding()">&#8635; Reset Tour &amp; Checklist</button>
          </div>''' if is_district_admin else ''}
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
              {(" — Silent audio test" if getattr(alarm_state, "silent_audio", False) else "")}
            </div>
            <form method="post" action="{prefix}/admin/alarm/deactivate" class="stack" data-confirm-deactivate>
              <div class="button-row">
                <button class="button button-danger" type="submit">End alarm now</button>
              </div>
            </form>
            <!-- ── Alert Accountability ────────────────────────────────── -->
            <div id="accountability-panel" style="margin:14px 0 0;padding:14px;background:rgba(220,38,38,0.05);border:1px solid rgba(220,38,38,0.18);border-radius:12px;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                <span style="font-size:0.78rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--danger,#dc2626);">Alert Accountability</span>
                <button id="remind-all-btn" class="button button-secondary" style="font-size:0.76rem;padding:4px 10px;height:28px;"
                  onclick="adminRemindAll()" title="Send push reminder to all users who haven't acknowledged">
                  Send Reminders
                </button>
              </div>
              <!-- Progress bar -->
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">
                <span id="js-ack-progress-label" style="font-size:0.84rem;font-weight:600;">{acknowledgement_count} / {active_users} acknowledged</span>
                <span id="js-ack-progress-pct" style="font-size:0.84rem;font-weight:700;color:{_ack_bar_color};">{_ack_pct}%</span>
              </div>
              <div style="background:rgba(0,0,0,0.12);border-radius:6px;height:9px;overflow:hidden;margin-bottom:10px;">
                <div id="js-ack-progress-bar" style="height:100%;width:{_ack_pct}%;border-radius:6px;background:{_ack_bar_color};transition:width .5s ease,background .5s ease;"></div>
              </div>
              <!-- Tabs -->
              <div style="display:flex;gap:2px;border-bottom:1px solid rgba(0,0,0,0.10);margin-bottom:10px;">
                <button class="acc-tab acc-tab--active" data-tab="not-acked" onclick="switchAccTab('not-acked',this)" style="background:none;border:none;cursor:pointer;padding:5px 10px;font-size:0.78rem;font-weight:600;border-bottom:2px solid #dc2626;color:#dc2626;">Not Yet</button>
                <button class="acc-tab" data-tab="acked" onclick="switchAccTab('acked',this)" style="background:none;border:none;cursor:pointer;padding:5px 10px;font-size:0.78rem;font-weight:600;border-bottom:2px solid transparent;color:var(--muted);">Acknowledged</button>
                <button class="acc-tab" data-tab="messages" onclick="switchAccTab('messages',this)" style="background:none;border:none;cursor:pointer;padding:5px 10px;font-size:0.78rem;font-weight:600;border-bottom:2px solid transparent;color:var(--muted);">Communication <span id="acc-msg-badge" style="display:none;background:#dc2626;color:#fff;border-radius:9px;padding:0 5px;font-size:0.7rem;font-weight:700;margin-left:3px;"></span></button>
              </div>
              <!-- Not-yet tab -->
              <div id="acc-tab-not-acked">
                <div id="js-unack-list" style="display:grid;gap:5px;font-size:0.8rem;max-height:260px;overflow-y:auto;">
                  <span class="mini-copy">Loading…</span>
                </div>
              </div>
              <!-- Acknowledged tab -->
              <div id="acc-tab-acked" style="display:none;">
                <div id="js-acked-list" style="display:grid;gap:5px;font-size:0.8rem;max-height:260px;overflow-y:auto;">
                  <span class="mini-copy">Loading…</span>
                </div>
              </div>
              <!-- Communication tab -->
              <div id="acc-tab-messages" style="display:none;">
                <div style="margin-bottom:10px;">
                  <div style="display:flex;gap:6px;">
                    <input id="broadcast-input" type="text" placeholder="Broadcast message to all users…"
                      style="flex:1;padding:7px 10px;border:1px solid rgba(0,0,0,0.15);border-radius:8px;font-size:0.83rem;"
                      onkeydown="if(event.key==='Enter')sendBroadcast()"/>
                    <button class="button" onclick="sendBroadcast()" style="font-size:0.83rem;padding:7px 14px;">Broadcast</button>
                  </div>
                  <p class="mini-copy" style="margin-top:5px;">Message will be delivered to all active users on their alert screen.</p>
                </div>
                <div id="js-messages-list" style="display:grid;gap:6px;font-size:0.8rem;max-height:230px;overflow-y:auto;">
                  <span class="mini-copy">No messages yet.</span>
                </div>
              </div>
              <div id="remind-feedback" style="display:none;margin-top:8px;font-size:0.8rem;padding:6px 10px;border-radius:6px;"></div>
              <p class="mini-copy" style="margin-top:8px;">Auto-reminders sent every 3 min. Manual reminders button sends immediately to all unacknowledged users with a registered device.</p>
            </div>
            ''' if alarm_state.is_active else f'''
            {super_admin_recorded_badge_html}
            <div id="live_alert_warning" class="flash error" style="display:none; margin-bottom:12px;">
              <strong>&#9888; Live alert mode.</strong> Training mode is off.
              This will send real emergency notifications to all registered devices for this school.
            </div>
            <form id="alarm_activate_form" method="post" action="{prefix}/admin/alarm/activate" class="stack">
              <div class="checkbox-row" style="background:color-mix(in srgb,var(--warning) 10%,white);border-color:color-mix(in srgb,var(--warning) 25%,transparent);">
                <input type="checkbox" name="is_training" value="1" id="is_training" checked />
                <label for="is_training">Training mode — no real push/SMS delivery{_help_tip('Safe mode for drills. Alarm screens appear on devices but no push notifications or SMS are actually sent. Leave this on unless responding to a real emergency.')}</label>
              </div>
              <div class="checkbox-row" style="background:rgba(14,165,233,.08);border-color:rgba(14,165,233,.22);">
                <input type="checkbox" name="silent_audio" value="1" id="silent_audio" />
                <label for="silent_audio">Silent audio test — show alarm screens without siren volume{_help_tip('Useful for testing the visual alert flow without triggering the siren sound in a occupied building.')}</label>
              </div>
              <div id="ems-ack-row" class="checkbox-row" style="display:none; background:rgba(185,28,28,.07); border-color:rgba(185,28,28,.35);">
                <input type="checkbox" name="ems_acknowledged" value="1" id="ems_acknowledged" />
                <label for="ems_acknowledged"><strong>911 / emergency services have been contacted or are not required for this situation.</strong>{_help_tip('Required before sending a live alarm. Confirms that professional emergency services have already been called or that this situation does not require them.')}</label>
              </div>
              <div id="ems-ack-err" class="flash error" style="display:none; margin-bottom:0; padding:8px 12px; font-size:0.85rem;">
                Please confirm emergency services status before activating a live alarm.
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
                <tr><td><strong>Active devices (30d)</strong></td><td><span class="status-pill {"ok" if _recently_active_device_count > 0 else "warn"}">{_recently_active_device_count}</span></td></tr>
                <tr><td><strong>Acknowledgements (current)</strong></td><td>{acknowledgement_count if alarm_state.is_active else "—"}</td></tr>
                <tr><td><strong>Last alarm activated</strong></td><td>{escape(alarm_state.activated_at or "Never")}</td></tr>
                <tr><td><strong>Last alarm deactivated</strong></td><td>{escape(alarm_state.deactivated_at or "Never")}</td></tr>
              </tbody>
            </table>
          </section>

          <section class="panel span-7" id="recent-activity"{_section_style("dashboard")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Recent Activity</p>
                <h2>Last 5 alerts</h2>
              </div>
            </div>
            <table class="data-table">
              <thead><tr><th>ID</th><th>Type</th><th>Time (UTC)</th><th>Message</th><th>By</th></tr></thead>
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
            <div style="display:flex;align-items:center;gap:14px;margin-bottom:16px;padding:12px 14px;background:var(--blue-soft,#eff6ff);border-radius:10px;border:1px solid rgba(27,95,228,.13);">
              <div style="font-size:2rem;font-weight:800;color:{"#16a34a" if _readiness_score >= 70 else "#d97706" if _readiness_score >= 50 else "#dc2626"};">{_readiness_score}</div>
              <div>
                <div style="font-weight:700;font-size:0.9rem;color:var(--text,#10203f);">Readiness Score <span class="status-pill {_readiness_class}" style="margin-left:6px;font-size:0.75rem;">{_readiness_label}</span></div>
                <div style="font-size:0.78rem;color:var(--muted,#5d7398);margin-top:2px;">Out of 100 — push config, devices, coverage, 2FA, access codes, recent drill</div>
              </div>
            </div>
            <table class="data-table" style="margin-bottom:12px;">
              <tbody>
                <tr><td><strong>Push configured</strong></td><td><span class="status-pill {"ok" if _push_configured else "warn"}">{("Yes" if _push_configured else "No — set up APNs or FCM")}</span></td></tr>
                <tr><td><strong>Devices registered</strong></td><td><span class="status-pill {"ok" if _total_device_count > 0 else "warn"}">{(_total_device_count if _total_device_count > 0 else "None registered")}</span></td></tr>
                <tr><td><strong>Active devices (30d)</strong></td><td><span class="status-pill {"ok" if _recently_active_device_count > 0 else "warn"}">{_recently_active_device_count}</span></td></tr>
                <tr><td><strong>Device coverage</strong></td><td><span class="status-pill {"ok" if _coverage_ratio >= 0.5 else "warn"}">{int(_coverage_ratio * 100)}%</span></td></tr>
                <tr><td><strong>2FA enabled</strong></td><td><span class="status-pill {"ok" if totp_enabled else "warn"}">{("Yes" if totp_enabled else "Not enabled")}</span></td></tr>
                <tr><td><strong>Access codes</strong></td><td><span class="status-pill {"ok" if len(access_code_records) > 0 else "warn"}">{(len(access_code_records) if access_code_records else "None")}</span></td></tr>
                <tr><td><strong>Recent drill (7d)</strong></td><td><span class="status-pill {"ok" if len(alerts) > 0 else "warn"}">{("Yes" if len(alerts) > 0 else "No recent drill")}</span></td></tr>
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
            {f'''
            <div class="button-row" style="margin-top:10px;">
              <a class="button button-secondary" href="{escape(prefix)}/admin/reports/{alerts[0].id}/export.pdf" style="font-size:12px;">
                Export last drill PDF
              </a>
              <a class="button button-secondary" href="{escape(prefix)}/admin?section=drill-reports" style="font-size:12px;">
                View all reports
              </a>
            </div>
            ''' if alerts else ""}
          </section>

          <section class="panel span-12" id="drill-reports"{_section_style("drill-reports")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Drill Reports</p>
                <h2>Alert &amp; drill history</h2>
                <p class="card-copy">Download official compliance reports for past alerts and training drills. Reports include acknowledgement stats, timelines, and delivery data.</p>
              </div>
            </div>
            <div class="table-search"><input type="search" id="drill-search" placeholder="Filter reports..." /></div>
            <table class="data-table">
              <thead>
                <tr><th>ID</th><th>Type</th><th>Date (UTC)</th><th>Message</th><th style="text-align:right;">Actions</th></tr>
              </thead>
              <tbody>
                {_render_drill_report_rows(alerts, prefix)}
              </tbody>
            </table>
          </section>

          <!-- 9.2: Per-building analytics (lazy-loaded) -->
          <section class="panel command-section span-12" id="analytics"{_section_style("analytics")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Analytics</p>
                <h2>Building &amp; School Performance</h2>
                <p class="card-copy">Operational metrics per building/school. Data is loaded on demand — not computed on every page visit.</p>
              </div>
            </div>
            <div style="display:flex;gap:8px;margin-bottom:18px;align-items:center;">
              <span style="font-size:0.82rem;color:var(--muted);">Period:</span>
              <button class="button button-secondary" data-analytics-days="7" data-analytics-target="analytics-cards" style="min-height:28px;font-size:0.78rem;padding:0 10px;">7 days</button>
              <button class="button button-primary" data-analytics-days="30" data-analytics-target="analytics-cards" style="min-height:28px;font-size:0.78rem;padding:0 10px;">30 days</button>
              <button class="button button-secondary" data-analytics-days="90" data-analytics-target="analytics-cards" style="min-height:28px;font-size:0.78rem;padding:0 10px;">90 days</button>
              <button class="button button-secondary" data-analytics-days="365" data-analytics-target="analytics-cards" style="min-height:28px;font-size:0.78rem;padding:0 10px;">All time</button>
            </div>
            <div id="analytics-cards" class="um-health-bar" style="flex-wrap:wrap;gap:14px;">
              <span class="mini-copy">Loading analytics…</span>
            </div>
          </section>

          <!-- 9.3: District reports dashboard (lazy-loaded, district_admin/super_admin only) -->
          {'<section class="panel command-section span-12" id="district-reports"' + _section_style("district-reports") + '>' if show_district_nav else '<section class="panel command-section span-12" id="district-reports" style="display:none;">'}
            <div class="panel-header">
              <div>
                <p class="eyebrow">District Reports</p>
                <h2>Cross-school reporting</h2>
                <p class="card-copy">District-wide operational overview across all assigned schools. Use the CSV export for compliance reporting.</p>
              </div>
              <div class="button-row">
                <a class="button button-secondary" href="{prefix}/admin/reports/district.csv?days=30" style="text-decoration:none;min-height:36px;font-size:0.82rem;">Export CSV (30d)</a>
              </div>
            </div>
            <div style="display:flex;gap:8px;margin-bottom:18px;align-items:center;">
              <span style="font-size:0.82rem;color:var(--muted);">Period:</span>
              <button class="button button-secondary" data-analytics-days="7" data-analytics-target="dr-cards" style="min-height:28px;font-size:0.78rem;padding:0 10px;">7 days</button>
              <button class="button button-primary" data-analytics-days="30" data-analytics-target="dr-cards" style="min-height:28px;font-size:0.78rem;padding:0 10px;">30 days</button>
              <button class="button button-secondary" data-analytics-days="90" data-analytics-target="dr-cards" style="min-height:28px;font-size:0.78rem;padding:0 10px;">90 days</button>
              <button class="button button-secondary" data-analytics-days="365" data-analytics-target="dr-cards" style="min-height:28px;font-size:0.78rem;padding:0 10px;">All time</button>
            </div>
            <div id="dr-cards" class="um-health-bar" style="flex-wrap:wrap;gap:14px;">
              <span class="mini-copy">Loading district data…</span>
            </div>
          </section>

          <!-- Phase 12: Demo Analytics section (sandbox tenants only) -->
          <section class="panel command-section span-12" id="demo-analytics"{_section_style("demo-analytics")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Demo Analytics {_demo_badge_html}</p>
                <h2>System Metrics Overview</h2>
                <p class="card-copy">Live metrics aggregated from this sandbox environment. Data is seeded with realistic synthetic values when volume is low.</p>
              </div>
              <div class="button-row" style="margin-top:0;">
                <button class="button button-secondary" onclick="showDemoWalkthrough()" title="Feature overview">🎬 Walkthrough</button>
                <button class="button button-secondary" onclick="loadDemoAnalytics(30)">30 days</button>
                <button class="button button-secondary" onclick="loadDemoAnalytics(7)">7 days</button>
                <button class="button button-secondary" onclick="loadDemoAnalytics(90)">90 days</button>
              </div>
            </div>
            <div id="demo-analytics-body" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:24px;">
              <div class="signal-card" style="text-align:center;"><p class="mini-copy">Loading…</p></div>
            </div>
            <div id="demo-chart-area" style="margin-top:8px;"></div>
            <!-- Live push event ticker -->
            <div style="margin-top:20px;border-top:1px solid var(--border);padding-top:16px;">
              <p class="eyebrow" style="margin-bottom:8px;">Live Activity Feed</p>
              <div id="demo-push-feed" style="font-size:0.8rem;color:var(--muted);min-height:40px;">
                <span class="mini-copy">Waiting for activity…</span>
              </div>
            </div>
          </section>

          <section class="panel command-section span-12" id="user-management"{_section_style("user-management")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">User Management</p>
                <h2>Accounts &amp; Access Control</h2>
                <p class="card-copy">Create and manage staff accounts. Roles control what each person can access — use Access Codes to let staff self-register on the mobile app. All role changes are fully audited.</p>
              </div>
              <div class="button-row" id="um-add-btn-wrap"{"" if _um_tab == "active" else ' style="display:none;"'}>
                <button class="button button-primary" style="min-height:38px;font-size:0.85rem;padding:0 16px;" onclick="umToggleCreate()">+ Add User</button>
              </div>
            </div>

            {_um_health_bar(users)}

            <!-- Active / Inactive / Archived tab strip -->
            <div class="um-tabs" style="display:flex;gap:0;border-bottom:2px solid var(--border);margin-bottom:18px;">
              <a href="{prefix}/admin?section=user-management"
                 class="um-tab{"  um-tab-active" if _um_tab == "active" else ""}"
                 style="padding:8px 20px;font-size:0.85rem;font-weight:600;text-decoration:none;color:{"var(--accent)" if _um_tab == "active" else "var(--muted)"};border-bottom:{"2px solid var(--accent);margin-bottom:-2px" if _um_tab == "active" else "none"};">
                Active
                <span class="count-badge" style="margin-left:6px;">{len(_active_user_list)}</span>
              </a>
              <a href="{prefix}/admin?section=user-management&tab=inactive"
                 class="um-tab{"  um-tab-active" if _um_tab == "inactive" else ""}"
                 style="padding:8px 20px;font-size:0.85rem;font-weight:600;text-decoration:none;color:{"var(--accent)" if _um_tab == "inactive" else "var(--muted)"};border-bottom:{"2px solid var(--accent);margin-bottom:-2px" if _um_tab == "inactive" else "none"};">
                Inactive
                {f'<span class="count-badge" style="margin-left:6px;background:rgba(245,158,11,0.12);color:#b45309;">{len(_inactive_user_list)}</span>' if _inactive_user_list else ""}
              </a>
              <a href="{prefix}/admin?section=user-management&tab=archived"
                 class="um-tab{"  um-tab-active" if _um_tab == "archived" else ""}"
                 style="padding:8px 20px;font-size:0.85rem;font-weight:600;text-decoration:none;color:{"var(--accent)" if _um_tab == "archived" else "var(--muted)"};border-bottom:{"2px solid var(--accent);margin-bottom:-2px" if _um_tab == "archived" else "none"};">
                Archived{_help_tip('Archived users cannot log in but are preserved for audit history. They do not count against active user limits.')}
                {f'<span class="count-badge" style="margin-left:6px;background:rgba(220,38,38,0.12);color:#dc2626;">{len(_archived_user_list)}</span>' if _archived_user_list else ""}
              </a>
              <a href="{prefix}/admin?section=user-management&tab=codes"
                 class="um-tab{"  um-tab-active" if _um_tab == "codes" else ""}"
                 style="padding:8px 20px;font-size:0.85rem;font-weight:600;text-decoration:none;color:{"var(--accent)" if _um_tab == "codes" else "var(--muted)"};border-bottom:{"2px solid var(--accent);margin-bottom:-2px" if _um_tab == "codes" else "none"};">
                Codes{_help_tip('One-time codes staff can use to self-register on the mobile app. Generate a code, share the link or QR, and they join automatically.')}
                {f'<span class="count-badge" style="margin-left:6px;background:rgba(27,95,228,0.12);color:var(--accent);">{len(access_code_records)}</span>' if access_code_records else ""}
              </a>
            </div>

            <!-- Active tab content -->
            <div id="um-tab-active"{"" if _um_tab == "active" else ' style="display:none;"'}>
              <div id="um-create-wrap" style="display:none;margin-bottom:18px;">
                <div class="user-card" style="border-left:3px solid var(--success);">
                  <div class="panel-header">
                    <div><h3 style="margin:0;">Create new user</h3><p class="mini-copy" style="margin:2px 0 0;">Fill in the fields below — username and password are optional.</p></div>
                    <button type="button" class="button button-secondary" style="min-height:30px;font-size:0.78rem;padding:0 10px;" onclick="umToggleCreate()">Cancel</button>
                  </div>
                  <form method="post" action="{prefix}/admin/users/create" class="stack">
                    <div class="form-grid">
                      <div class="field"><label>Name</label><input name="name" placeholder="Full name" /></div>
                      <div class="field">
                        <label>Role{_help_tip('Teacher/Staff: alert-receive only. Building Admin: full school management. District Admin: cross-school access. Law Enforcement: alert-receive with responder view.')}</label>
                        <select name="role">
                          <option value="teacher">Teacher / Standard</option>
                          <option value="staff">Staff</option>
                          <option value="law_enforcement">Law Enforcement</option>
                          <option value="building_admin">Building Admin</option>
                          {'<option value="district_admin">District Admin</option>' if current_user.role in {"district_admin", "super_admin"} else ''}
                        </select>
                      </div>
                      <div class="field"><label>Title</label><input name="title" placeholder="e.g. Principal" /></div>
                      <div class="field"><label>Phone</label><input name="phone_e164" placeholder="+15551234567" /></div>
                      <div class="field"><label>Username</label><input name="login_name" placeholder="optional login username" /></div>
                      <div class="field"><label>Password</label><input name="password" type="password" placeholder="optional login password" /></div>
                      <div class="checkbox-row">
                        <input type="checkbox" name="must_change_password" value="1" id="must_change_password" />
                        <label for="must_change_password">Require password change on first login</label>
                      </div>
                    </div>
                    <div class="button-row">
                      <button class="button button-primary" type="submit">Create user</button>
                    </div>
                  </form>
                </div>
              </div>

              <div class="table-search" style="margin-bottom:8px;">
                <input type="search" id="user-search" placeholder="Search by name, username, or role..." style="max-width:320px;" />
                <span class="mini-copy" style="margin-left:auto;">{len(_active_user_list)} user{"s" if len(_active_user_list) != 1 else ""}</span>
              </div>

              <!-- 8.2: Bulk action bar (hidden until rows are selected) -->
              <div id="um-bulk-bar" style="display:none;align-items:center;gap:10px;padding:8px 12px;margin-bottom:10px;background:rgba(27,95,228,0.07);border:1px solid rgba(27,95,228,0.18);border-radius:8px;">
                <span class="mini-copy" id="um-bulk-count" style="font-weight:600;"></span>
                <button class="button button-danger-outline" id="um-bulk-archive-btn" style="min-height:30px;font-size:0.78rem;padding:0 12px;">Archive Selected</button>
                <button class="button button-secondary" id="um-bulk-clear-btn" style="min-height:30px;font-size:0.78rem;padding:0 10px;">Clear</button>
              </div>

              {_um_enterprise_table(_active_user_list, school_path_prefix, actor_role=str(getattr(current_user, "role", "") or ""), actor_user_id=current_user_id)}

              <div id="um-edit-forms" style="margin-top:16px;">
                {_render_user_cards(
                    _active_user_list,
                    school_path_prefix,
                    tenant_label=selected_tenant_name,
                    tenant_options=[{"id": str(item.get("id", "")), "slug": str(item.get("slug", "")), "name": str(item.get("name", ""))} for item in tenant_options],
                    user_tenant_assignments=user_tenant_assignments,
                    allow_assignment_edit=(current_user.role in {"district_admin", "super_admin"}),
                    actor_role=str(getattr(current_user, "role", "") or ""),
                    actor_user_id=current_user_id,
                )}
              </div>
            </div>

            <!-- Inactive tab content -->
            <div id="um-tab-inactive"{"" if _um_tab == "inactive" else ' style="display:none;"'}>
              {_inactive_tab_html}
            </div>

            <!-- Archived tab content -->
            <div id="um-tab-archived"{"" if _um_tab == "archived" else ' style="display:none;"'}>
              {_archived_tab_html}
            </div>

            <!-- Codes tab content -->
            <div id="um-tab-codes"{"" if _um_tab == "codes" else ' style="display:none;"'}>
              {_access_codes_panel_html}
            </div>
          </section>

          {_um_slide_panel()}
          {_um_role_modal()}
          {_um_delete_modal()}
          {_um_bulk_modal()}
          {_um_view_as_modal()}

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
            <table class="data-table" style="margin-top:16px;">
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
                <h2>User messages inbox {'<span class="count-badge">' + str(unread_admin_messages) + '</span>' if unread_admin_messages > 0 else ''}</h2>
                <p class="card-copy">Review incoming mobile messages and reply directly from the admin console.</p>
              </div>
            </div>
            <div class="table-wrap"><table class="data-table">
              <thead>
                <tr><th>ID</th><th>Created</th><th>From</th><th>Message</th><th>Status</th><th>Response</th><th>Action</th></tr>
              </thead>
              <tbody>
                {_render_admin_message_rows(admin_messages, school_path_prefix)}
              </tbody>
            </table></div>
          </section>

          <section class="panel command-section span-12" id="request-help"{_section_style("dashboard")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Request Help</p>
                <h2>Active help requests</h2>
                <p class="card-copy">Admins can clear help requests directly from the console. This clear action does not require two-person cancellation consent.</p>
              </div>
            </div>
            <table class="data-table">
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
            <table class="data-table">
              <thead>
                <tr><th>ID</th><th>Created</th><th>Category</th><th>Note</th></tr>
              </thead>
              <tbody>
                {_render_report_rows(reports)}
              </tbody>
            </table>
          </section>

          <section class="panel command-section span-12" id="quiet-periods"{"" if section in {"user-management", "quiet-periods"} else " style='display:none;'"}>
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
            <table class="data-table" style="margin-top:16px;">
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
            <table class="data-table">
              <thead>
                <tr><th>ID</th><th>Type</th><th>Created</th><th>Message</th><th>Triggered by</th></tr>
              </thead>
              <tbody>
                {_render_alert_rows(alerts)}
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
            <div class="table-search"><input type="search" id="audit-search" placeholder="Filter audit events by text..." /></div>
            <table class="data-table">
              <thead>
                <tr><th>Timestamp (UTC)</th><th>Event</th><th>Actor</th><th>Target</th><th>Summary</th></tr>
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
            <table class="data-table">
              <thead>
                <tr><th>User</th><th>Status</th><th>Reason</th><th>Approved By</th><th>Requested</th><th>Expires</th><th>Action</th></tr>
              </thead>
              <tbody>
                {_render_quiet_period_rows(quiet_periods_history, users, school_path_prefix, tenant_label=selected_tenant_name, include_actions=False)}
              </tbody>
            </table>
          </section>

          <section class="panel command-section span-12" id="district-overview"{_section_style("district")}>
            <div class="panel-header" style="position:sticky;top:0;z-index:20;background:var(--surface);padding-bottom:12px;margin-bottom:4px;">
              <div>
                <p class="eyebrow">District Overview</p>
                <h2>All assigned schools</h2>
                <p class="card-copy">Read-only status across all schools in your district. Switch to a school to manage alerts.</p>
              </div>
              <div class="status-row" style="align-self:flex-start;gap:10px;">
                <span id="dist-ws-badge" class="status-pill" style="display:none;font-size:12px;">&#x25CF;&nbsp;Live</span>
                <button id="dist-save-order-btn" class="button button-secondary"
                  style="display:none;font-size:13px;padding:6px 16px;min-height:auto;"
                  onclick="distSaveOrder()">Save Order</button>
                <span id="dist-order-status" class="mini-copy" style="display:none;"></span>
              </div>
            </div>
            <div class="flash" style="margin-bottom:16px;">
              <strong>Alert controls are disabled in District Overview.</strong>
              Click a school card to manage alerts. Drag cards to reorder.
            </div>
            <div class="school-grid" id="school-card-grid">
              {_render_school_cards(district_overview_items, school_path_prefix)}
            </div>
          </section>
          <script>
          (function() {{
            var grid = document.getElementById('school-card-grid');
            var saveBtn = document.getElementById('dist-save-order-btn');
            var statusEl = document.getElementById('dist-order-status');
            if (!grid) return;
            var dragSrc = null;
            var originalOrder = null;
            var didDrag = false;

            function cards() {{
              return Array.from(grid.querySelectorAll('.school-card[data-slug]'));
            }}

            function getSlugOrder() {{
              return cards().map(function(c) {{ return c.getAttribute('data-slug'); }});
            }}

            function markDirty() {{
              if (saveBtn) {{ saveBtn.style.display = ''; }}
              if (statusEl) {{ statusEl.style.display = 'none'; statusEl.textContent = ''; }}
            }}

            grid.addEventListener('click', function(e) {{
              if (didDrag) {{ didDrag = false; return; }}
              var card = e.target.closest('.school-card[data-href]');
              if (!card) return;
              window.location.href = card.getAttribute('data-href');
            }});

            grid.addEventListener('dragstart', function(e) {{
              dragSrc = e.target.closest('.school-card[data-slug]');
              if (!dragSrc) return;
              if (originalOrder === null) originalOrder = getSlugOrder();
              didDrag = true;
              dragSrc.style.opacity = '0.4';
              e.dataTransfer.effectAllowed = 'move';
              e.dataTransfer.setData('text/plain', dragSrc.getAttribute('data-slug'));
            }});

            grid.addEventListener('dragend', function(e) {{
              var card = e.target.closest('.school-card[data-slug]');
              if (card) card.style.opacity = '';
              cards().forEach(function(c) {{ c.classList.remove('drag-over'); }});
            }});

            grid.addEventListener('dragover', function(e) {{
              e.preventDefault();
              e.dataTransfer.dropEffect = 'move';
              var target = e.target.closest('.school-card[data-slug]');
              if (!target || target === dragSrc) return;
              cards().forEach(function(c) {{ c.classList.remove('drag-over'); }});
              target.classList.add('drag-over');
            }});

            grid.addEventListener('drop', function(e) {{
              e.preventDefault();
              var target = e.target.closest('.school-card[data-slug]');
              if (!target || !dragSrc || target === dragSrc) return;
              var list = cards();
              var srcIdx = list.indexOf(dragSrc);
              var tgtIdx = list.indexOf(target);
              if (srcIdx < tgtIdx) {{
                grid.insertBefore(dragSrc, target.nextSibling);
              }} else {{
                grid.insertBefore(dragSrc, target);
              }}
              markDirty();
            }});

            window.distSaveOrder = function() {{
              var slugs = getSlugOrder();
              if (saveBtn) saveBtn.disabled = true;
              if (statusEl) {{ statusEl.style.display = ''; statusEl.textContent = 'Saving…'; }}
              fetch('/admin/district/schools/reorder', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ ordered_slugs: slugs }})
              }}).then(function(r) {{ return r.json(); }}).then(function(data) {{
                if (saveBtn) {{ saveBtn.style.display = 'none'; saveBtn.disabled = false; }}
                if (data.ok) {{
                  if (statusEl) {{ statusEl.textContent = 'Order saved.'; statusEl.style.display = ''; }}
                  originalOrder = null;
                }} else {{
                  if (statusEl) {{ statusEl.textContent = 'Error: ' + (data.error || 'unknown'); statusEl.style.display = ''; }}
                }}
              }}).catch(function() {{
                if (saveBtn) {{ saveBtn.style.display = ''; saveBtn.disabled = false; }}
                if (statusEl) {{ statusEl.textContent = 'Network error — try again.'; statusEl.style.display = ''; }}
              }});
            }};
          }})();
          </script>

          <section class="panel command-section span-12" id="devices"{_section_style("devices")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Device Management</p>
                <h2>Active Devices{_help_tip('Devices must register on the BlueBird app to receive push alerts. Unregistered devices will not get notified during an alarm.')}</h2>
                <p class="card-copy">All devices and active sessions for <strong>{escape(selected_tenant_name)}</strong>. Only registered devices receive push alerts.</p>
              </div>
              <div class="status-row">
                <span class="status-pill ok"><strong>{_total_device_count}</strong> registered</span>
                <span class="status-pill ok"><strong>{len(active_sessions)}</strong> session{"s" if len(active_sessions) != 1 else ""}</span>
                <span class="status-pill"><strong>iOS</strong>&nbsp;{_ios_count}</span>
                <span class="status-pill"><strong>Android</strong>&nbsp;{_android_count}</span>
              </div>
            </div>

            <div class="metrics-grid" style="margin-bottom:20px;">
              <article class="metric-card"><div class="meta">Registered Devices</div><div class="metric-value">{_total_device_count}</div></article>
              <article class="metric-card"><div class="meta">Active Sessions</div><div class="metric-value">{len(active_sessions)}</div></article>
              <article class="metric-card"><div class="meta">iOS</div><div class="metric-value">{_ios_count}</div></article>
              <article class="metric-card"><div class="meta">Android</div><div class="metric-value">{_android_count}</div></article>
            </div>

            <div style="display:flex;gap:0;border-bottom:2px solid var(--border);margin-bottom:20px;">
              <button id="dm-tab-sessions" onclick="bbDmTab('sessions')"
                style="background:none;border:none;border-bottom:3px solid var(--accent,#3b82f6);margin-bottom:-2px;padding:8px 20px;font-size:14px;font-weight:600;color:var(--accent,#3b82f6);cursor:pointer;outline:none;">
                Active Sessions
              </button>
              <button id="dm-tab-registered" onclick="bbDmTab('registered')"
                style="background:none;border:none;border-bottom:3px solid transparent;margin-bottom:-2px;padding:8px 20px;font-size:14px;font-weight:600;color:var(--text-muted);cursor:pointer;outline:none;">
                Registered Devices
              </button>
            </div>

            <div id="dm-pane-sessions">
              <p class="mini-copy" style="margin-bottom:10px;">Active login sessions. Force logout revokes immediately — device must re-authenticate on next use.</p>
              <table class="data-table" style="width:100%;border-collapse:collapse;table-layout:fixed;">
                <colgroup>
                  <col style="width:24%"><col style="width:11%"><col style="width:13%">
                  <col style="width:12%"><col style="width:15%"><col style="width:15%"><col style="width:10%">
                </colgroup>
                <thead>
                  <tr>
                    <th>User</th><th>Client</th><th>Role</th>
                    <th>Status</th><th>Last Seen</th><th>Session Created</th><th>Action</th>
                  </tr>
                </thead>
                <tbody>{_session_rows}</tbody>
              </table>
            </div>

            <div id="dm-pane-registered" style="display:none;">
              <div class="table-search"><input type="search" id="reg-device-search" placeholder="Filter registered devices..." /></div>
              <table class="data-table" style="width:100%;border-collapse:collapse;table-layout:fixed;" id="reg-device-table">
                <colgroup>
                  <col style="width:22%"><col style="width:22%"><col style="width:18%">
                  <col style="width:11%"><col style="width:14%"><col style="width:13%">
                </colgroup>
                <thead>
                  <tr>
                    <th>User</th><th>Device / Platform</th><th>Push Token</th>
                    <th>Status</th><th>Last Seen</th><th>Actions</th>
                  </tr>
                </thead>
                <tbody>{_reg_device_rows}</tbody>
              </table>
            </div>

            <script>
            (function() {{
              function bbDmTab(name) {{
                ['sessions', 'registered'].forEach(function(p) {{
                  var pane = document.getElementById('dm-pane-' + p);
                  var tab = document.getElementById('dm-tab-' + p);
                  if (!pane || !tab) return;
                  var active = p === name;
                  pane.style.display = active ? '' : 'none';
                  tab.style.borderBottomColor = active ? 'var(--accent,#3b82f6)' : 'transparent';
                  tab.style.color = active ? 'var(--accent,#3b82f6)' : 'var(--text-muted)';
                  tab.style.fontWeight = active ? '700' : '600';
                }});
              }}
              window.bbDmTab = bbDmTab;
              if (window.location.hash === '#registered') bbDmTab('registered');
              var rSearch = document.getElementById('reg-device-search');
              if (rSearch) {{
                rSearch.addEventListener('input', function() {{
                  var q = this.value.toLowerCase();
                  var rows = document.querySelectorAll('#reg-device-table tbody tr');
                  rows.forEach(function(r) {{
                    r.style.display = r.textContent.toLowerCase().includes(q) ? '' : 'none';
                  }});
                }});
              }}
            }})();
            </script>
          </section>

        </section>
      </section>
    </div>
  </div>
  <script>
  (function() {{
    var THEME_KEY = 'bb_theme';
    var h = document.documentElement;
    function applyTheme(dark) {{
      if (dark) h.setAttribute('data-theme', 'dark'); else h.removeAttribute('data-theme');
      var btn = document.getElementById('bb-theme-btn');
      if (btn) btn.textContent = dark ? '☀ Light' : '☾ Dark';
    }}
    function bbToggleTheme() {{
      var dark = h.getAttribute('data-theme') === 'dark';
      localStorage.setItem(THEME_KEY, dark ? 'light' : 'dark');
      applyTheme(!dark);
    }}
    window.bbToggleTheme = bbToggleTheme;
    var saved = localStorage.getItem(THEME_KEY);
    if (!saved) saved = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    applyTheme(saved === 'dark');
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e) {{
      if (!localStorage.getItem(THEME_KEY)) applyTheme(e.matches);
    }});
  }})();
  </script>

  <!-- ── Smart Confirm + Next Steps + Command Bar ──────────────────────── -->
  <script>
  (function() {{
    /* ── Smart Confirm ─────────────────────────────────────────────────── */
    var _scOverlay = null, _scBox = null, _scResolve = null;

    function _scInit() {{
      _scOverlay = document.createElement('div');
      _scOverlay.className = 'bb-sconfirm-overlay';
      _scOverlay.addEventListener('click', function(e) {{ if (e.target === _scOverlay) _scClose(false); }});
      document.body.appendChild(_scOverlay);
      _scBox = document.createElement('div');
      _scBox.className = 'bb-sconfirm';
      _scOverlay.appendChild(_scBox);
    }}

    function _scClose(result) {{
      if (_scOverlay) _scOverlay.classList.remove('open');
      if (_scResolve) {{ _scResolve(result); _scResolve = null; }}
    }}

    window.bbSmartConfirm = function(cfg) {{
      if (!_scOverlay) _scInit();
      return new Promise(function(resolve) {{
        _scResolve = resolve;
        var icon = cfg.icon || (cfg.danger ? '⚠️' : 'ℹ️');
        var typeRow = '';
        if (cfg.requireType) {{
          typeRow = '<p class="bb-sconfirm-type-label">Type <strong>' + cfg.requireType + '</strong> to confirm:</p>'
            + '<input class="bb-sconfirm-type-input" id="bb-sc-typeinput" autocomplete="off" />';
        }}
        var consequence = cfg.consequence
          ? '<div class="bb-sconfirm-consequence">' + cfg.consequence + '</div>'
          : '';
        _scBox.innerHTML = (
          '<div class="bb-sconfirm-icon">' + icon + '</div>'
          + '<h3>' + (cfg.title || 'Confirm action') + '</h3>'
          + '<div class="bb-sconfirm-body">' + (cfg.body || '') + '</div>'
          + consequence + typeRow
          + '<div class="bb-sconfirm-actions">'
          + '<button class="button button-secondary" style="min-height:36px;" onclick="window._bbScCancel()">Cancel</button>'
          + '<button class="button ' + (cfg.danger ? 'button-danger' : 'button-primary') + '" style="min-height:36px;" id="bb-sc-ok">'
          + (cfg.confirmLabel || 'Confirm') + '</button>'
          + '</div>'
        );
        var okBtn = document.getElementById('bb-sc-ok');
        if (cfg.requireType) {{
          okBtn.disabled = true;
          var ti = document.getElementById('bb-sc-typeinput');
          ti.addEventListener('input', function() {{
            okBtn.disabled = ti.value.trim() !== cfg.requireType;
          }});
          ti.focus();
        }}
        okBtn.addEventListener('click', function() {{ _scClose(true); }});
        _scOverlay.classList.add('open');
        if (!cfg.requireType && okBtn) okBtn.focus();
      }});
    }};

    window._bbScCancel = function() {{ _scClose(false); }};

    /* Convenience wrapper for form submissions */
    window.bbConfirmSubmit = function(form, cfg) {{
      window.bbSmartConfirm(cfg).then(function(ok) {{ if (ok) form.submit(); }});
    }};

    /* ── Next Steps Panel ──────────────────────────────────────────────── */
    window.bbNspDismiss = function() {{
      var el = document.getElementById('bb-next-steps');
      if (el) el.style.display = 'none';
      localStorage.setItem('bb_nsp_dismissed', String(Date.now()));
    }};

    /* ── Smart Suggestions Panel ───────────────────────────────────────── */
    window.bbSgDismiss = function(btn) {{
      var sid = btn.getAttribute('data-sid');
      var ttlHours = parseInt(btn.getAttribute('data-ttl') || '72', 10);
      if (sid) {{
        var expiresAt = ttlHours > 0 ? String(Date.now() + ttlHours * 3600000) : '0';
        localStorage.setItem('bb_sg_d_' + sid, expiresAt);
      }}
      var item = btn.closest('.bb-sg-item');
      if (item) {{
        item.style.opacity = '0';
        item.style.transition = 'opacity 0.25s';
        setTimeout(function() {{
          item.style.display = 'none';
          var panel = document.getElementById('bb-suggestions');
          var items = panel && panel.querySelectorAll('.bb-sg-item[style*="display: none"], .bb-sg-item[style*="display:none"]');
          var visible = panel && panel.querySelectorAll('.bb-sg-item:not([style*="display: none"]):not([style*="display:none"])');
          if (panel && visible && visible.length === 0) panel.style.display = 'none';
        }}, 280);
      }}
    }};

    /* ── Command Bar ───────────────────────────────────────────────────── */
    var _cbOverlay = null, _cbInput = null, _cbResults = null;
    var _cbItems = [], _cbSel = -1;
    var _PREFIX = {json.dumps(prefix)};
    var _ROLE = {json.dumps(str(getattr(current_user, "role", "")))};
    var _SHOW_DISTRICT = {json.dumps(show_district_nav)};
    var _IS_DA = {json.dumps(is_district_admin)};

    var _NAV = [
      {{t:'nav', i:'📊', l:'Dashboard', d:'Main overview', u:_PREFIX+'/admin?section=dashboard'}},
      {{t:'nav', i:'👤', l:'User Management', d:'Accounts and roles', u:_PREFIX+'/admin?section=user-management'}},
      {{t:'nav', i:'🔑', l:'Access Codes', d:'Staff self-registration codes', u:_PREFIX+'/admin?section=user-management&tab=codes'}},
      {{t:'nav', i:'📱', l:'Active Devices', d:'Registered devices and sessions', u:_PREFIX+'/admin?section=devices'}},
      {{t:'nav', i:'⚙', l:'Settings', d:'Alert and notification settings', u:_PREFIX+'/admin?section=settings'}},
      {{t:'nav', i:'🔇', l:'Quiet Periods', d:'Sound suppression requests', u:_PREFIX+'/admin?section=quiet-periods'}},
      {{t:'nav', i:'📋', l:'Audit Logs', d:'System activity history', u:_PREFIX+'/admin?section=audit-logs'}},
      {{t:'nav', i:'📈', l:'Drill Reports', d:'Training drill history', u:_PREFIX+'/admin?section=drill-reports'}},
      {{t:'nav', i:'📊', l:'Analytics', d:'Alert and device analytics', u:_PREFIX+'/admin?section=analytics'}},
    ].concat(_SHOW_DISTRICT ? [
      {{t:'nav', i:'🏛', l:'District Overview', d:'Cross-school district view', u:_PREFIX+'/admin?section=district'}},
    ] : []);

    var _ACTIONS = [
      {{t:'action', i:'➕', l:'Add User', d:'Create a new staff account',
        fn:function(){{ window.location.href=_PREFIX+'/admin?section=user-management'; setTimeout(function(){{if(window.umToggleCreate)umToggleCreate();}},350); }}}},
      {{t:'action', i:'▶', l:'Guided Tour', d:'Walkthrough of the admin console',
        fn:function(){{ if(window.startBluebirdTour) startBluebirdTour(); }}}},
      {{t:'action', i:'🚨', l:'Alarm Control', d:'Activate or end emergency alert',
        fn:function(){{ window.location.href=_PREFIX+'/admin?section=dashboard'; }}}},
      {{t:'action', i:'❓', l:'Help Tour', d:'Restart the guided onboarding tour',
        fn:function(){{ localStorage.removeItem('bb_tour_seen'); if(window.startBluebirdTour)startBluebirdTour(); }}}},
    ];

    /* Server-rendered entity index (user names) */
    var _ENTITIES = [{', '.join(
        '{t:' + repr('entity') + ', i:' + repr('👤') + ', l:' + json.dumps(str(getattr(u, 'name', '') or '')) + ', d:' + json.dumps(str(getattr(u, 'role', '') or '')) + ', u:_PREFIX+' + repr('/admin?section=user-management') + '}'
        for u in list(users)[:25] if getattr(u, 'name', '')
    )}];

    function _cbAllItems() {{
      return _NAV.concat(_ACTIONS).concat(_ENTITIES);
    }}

    function _cbFilter(q) {{
      if (!q) return _cbAllItems().slice(0, 8);
      q = q.toLowerCase();
      return _cbAllItems().filter(function(x) {{
        return (x.l + ' ' + x.d).toLowerCase().indexOf(q) >= 0;
      }}).slice(0, 10);
    }}

    function _cbRender(q) {{
      var matches = _cbFilter(q);
      _cbSel = matches.length ? 0 : -1;
      if (!matches.length) {{
        _cbResults.innerHTML = '<div class="bb-cmdbar-empty">No results for &ldquo;' + q + '&rdquo;</div>';
        return;
      }}
      var typeLabels = {{nav:'Page', action:'Action', entity:'User'}};
      var html = '';
      var lastType = '';
      for (var idx = 0; idx < matches.length; idx++) {{
        var x = matches[idx];
        if (x.t !== lastType) {{
          html += '<div class="bb-cmdbar-section-label">' + (typeLabels[x.t] || x.t) + '</div>';
          lastType = x.t;
        }}
        html += '<div class="bb-cmdbar-item' + (idx === 0 ? ' bb-cmd-sel' : '') + '" data-idx="' + idx + '">'
          + '<div class="bb-cmdbar-item-icon">' + x.i + '</div>'
          + '<div class="bb-cmdbar-item-info">'
          + '<div class="bb-cmdbar-item-label">' + x.l + '</div>'
          + (x.d ? '<div class="bb-cmdbar-item-desc">' + x.d + '</div>' : '')
          + '</div>'
          + '<div class="bb-cmdbar-item-badge">' + (typeLabels[x.t] || x.t) + '</div>'
          + '</div>';
      }}
      _cbResults.innerHTML = html;
      _cbItems = matches;
      _cbResults.querySelectorAll('.bb-cmdbar-item').forEach(function(el) {{
        el.addEventListener('mouseenter', function() {{
          _cbSelect(+el.getAttribute('data-idx'));
        }});
        el.addEventListener('click', function() {{
          _cbExecute(+el.getAttribute('data-idx'));
        }});
      }});
    }}

    function _cbSelect(idx) {{
      _cbSel = idx;
      _cbResults.querySelectorAll('.bb-cmdbar-item').forEach(function(el) {{
        el.classList.toggle('bb-cmd-sel', +el.getAttribute('data-idx') === idx);
      }});
    }}

    function _cbExecute(idx) {{
      var x = _cbItems[idx];
      if (!x) return;
      bbCloseCmdBar();
      if (x.fn) {{ x.fn(); }}
      else if (x.u) {{ window.location.href = x.u; }}
    }}

    function _cbInit() {{
      _cbOverlay = document.createElement('div');
      _cbOverlay.className = 'bb-cmdbar-overlay';
      _cbOverlay.addEventListener('click', function(e) {{
        if (e.target === _cbOverlay) bbCloseCmdBar();
      }});
      var box = document.createElement('div');
      box.className = 'bb-cmdbar';
      var top = '<div class="bb-cmdbar-top">'
        + '<span class="bb-cmdbar-search-icon">&#128269;</span>'
        + '<input class="bb-cmdbar-input" id="bb-cmdbar-input" placeholder="Search pages and actions&hellip;" autocomplete="off" spellcheck="false" />'
        + '<span class="bb-cmdbar-kbd">Esc</span>'
        + '</div>';
      var footer = '<div class="bb-cmdbar-footer">'
        + '<span><kbd>&uarr;&darr;</kbd> navigate</span>'
        + '<span><kbd>Enter</kbd> open</span>'
        + '<span><kbd>Esc</kbd> close</span>'
        + '</div>';
      box.innerHTML = top + '<div class="bb-cmdbar-results" id="bb-cmdbar-results"></div>' + footer;
      _cbOverlay.appendChild(box);
      document.body.appendChild(_cbOverlay);
      _cbInput = document.getElementById('bb-cmdbar-input');
      _cbResults = document.getElementById('bb-cmdbar-results');
      _cbInput.addEventListener('input', function() {{ _cbRender(_cbInput.value.trim()); }});
      _cbInput.addEventListener('keydown', function(e) {{
        if (e.key === 'ArrowDown') {{ e.preventDefault(); _cbSelect(Math.min(_cbSel + 1, _cbItems.length - 1)); }}
        else if (e.key === 'ArrowUp') {{ e.preventDefault(); _cbSelect(Math.max(_cbSel - 1, 0)); }}
        else if (e.key === 'Enter') {{ e.preventDefault(); _cbExecute(_cbSel); }}
        else if (e.key === 'Escape') {{ bbCloseCmdBar(); }}
      }});
    }}

    window.bbOpenCmdBar = function() {{
      if (!_cbOverlay) _cbInit();
      _cbInput.value = '';
      _cbRender('');
      _cbOverlay.classList.add('open');
      _cbInput.focus();
    }};

    window.bbCloseCmdBar = function() {{
      if (_cbOverlay) _cbOverlay.classList.remove('open');
    }};

    /* Global keyboard shortcuts */
    document.addEventListener('keydown', function(e) {{
      /* Ctrl+K or Cmd+K → command bar */
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {{
        e.preventDefault(); window.bbOpenCmdBar();
      }}
      /* / → command bar (when not in input) */
      if (e.key === '/' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)) {{
        e.preventDefault(); window.bbOpenCmdBar();
      }}
      /* Esc → close command bar or confirm dialog */
      if (e.key === 'Escape') {{
        window.bbCloseCmdBar();
        if (window._bbScCancel) window._bbScCancel();
      }}
    }});

    /* ── Alarm activation interceptor ──────────────────────────────────── */
    document.addEventListener('DOMContentLoaded', function() {{
      /* Next Steps Panel: show if not recently dismissed */
      var nsp = document.getElementById('bb-next-steps');
      if (nsp) {{
        var dismissed = parseInt(localStorage.getItem('bb_nsp_dismissed') || '0', 10);
        var week = 7 * 24 * 60 * 60 * 1000;
        if (Date.now() - dismissed > week) nsp.style.display = 'block';
      }}

      /* Smart Suggestions Panel: hide individually dismissed items, show panel if any remain */
      var sgPanel = document.getElementById('bb-suggestions');
      if (sgPanel) {{
        var sgItems = sgPanel.querySelectorAll('.bb-sg-item[data-sid]');
        var anyVisible = false;
        sgItems.forEach(function(item) {{
          var sid = item.getAttribute('data-sid');
          var storedVal = localStorage.getItem('bb_sg_d_' + sid);
          if (storedVal !== null) {{
            var expiresAt = parseInt(storedVal, 10);
            /* expiresAt === 0 means permanent dismiss; otherwise check expiry */
            if (expiresAt === 0 || Date.now() < expiresAt) {{
              item.style.display = 'none';
              return;
            }}
            /* TTL elapsed — clear and show again */
            localStorage.removeItem('bb_sg_d_' + sid);
          }}
          anyVisible = true;
        }});
        if (anyVisible) sgPanel.style.display = 'block';
      }}

      /* 911 notice banner — show once, dismiss stores flag in localStorage */
      (function() {{
        var _KEY = 'bb_911_notice_v1';
        var el = document.getElementById('bb-911-notice');
        if (el && !localStorage.getItem(_KEY)) el.style.display = '';
      }})();
      window.bb911Dismiss = function() {{
        try {{ localStorage.setItem('bb_911_notice_v1', '1'); }} catch(e) {{}}
        var el = document.getElementById('bb-911-notice');
        if (el) el.style.display = 'none';
      }};

      /* Upgrade alarm activation form for live (non-training) alerts */
      var alarmForm = document.getElementById('alarm_activate_form');
      if (alarmForm) {{
        var _trainingCb = document.getElementById('is_training');
        var _emsRow = document.getElementById('ems-ack-row');
        var _emsErr = document.getElementById('ems-ack-err');
        var _emsCb  = document.getElementById('ems_acknowledged');
        var _liveWarn = document.getElementById('live_alert_warning');

        function _syncLiveMode() {{
          var live = _trainingCb && !_trainingCb.checked;
          if (_emsRow) _emsRow.style.display = live ? '' : 'none';
          if (_emsErr) _emsErr.style.display = 'none';
          if (_emsCb && !live) _emsCb.checked = false;
          if (_liveWarn) _liveWarn.style.display = live ? '' : 'none';
        }}

        if (_trainingCb) _trainingCb.addEventListener('change', _syncLiveMode);
        _syncLiveMode();

        alarmForm.addEventListener('submit', function(e) {{
          var live = _trainingCb && !_trainingCb.checked;
          if (live) {{
            e.preventDefault();
            if (!_emsCb || !_emsCb.checked) {{
              if (_emsErr) _emsErr.style.display = '';
              if (_emsRow) _emsRow.scrollIntoView({{behavior:'smooth', block:'nearest'}});
              return;
            }}
            if (_emsErr) _emsErr.style.display = 'none';
            var devCount = {json.dumps(len(devices))};
            window.bbSmartConfirm({{
              icon: '🚨',
              title: 'Send live emergency alert?',
              body: 'Training mode is OFF. This will immediately send real push notifications'
                + ' and SMS messages to all registered devices.'
                + '<br><br><strong style="color:#b91c1c;">&#9888; This system does not contact emergency services.'
                + ' If this is a real emergency, ensure 911 has already been called.</strong>',
              consequence: 'Affects <strong>' + devCount + ' registered device'
                + (devCount === 1 ? '' : 's') + '</strong>. Cannot be cancelled once sent.',
              confirmLabel: 'Send live alert',
              danger: true
            }}).then(function(ok) {{ if (ok) alarmForm.submit(); }});
          }}
        }});
      }}

      /* Show command bar button in header once JS is ready */
      var cb = document.getElementById('bb-cmdbar-btn');
      if (cb) cb.style.display = '';
    }});
  }})();
  </script>

  {_da_welcome_html}

  <!-- ── Guided Tour ─────────────────────────────────────────────────────── -->
  <script>
  (function() {{
    var PREFIX = '{prefix}';
    /* Generic 5-step tour (all roles except district_admin). */
    var STEPS = [
      {{
        nav: 'dashboard', el: '#overview',
        title: 'Admin Dashboard',
        text: 'Your command center. Track user counts, device readiness, active alarm status, and incoming messages — all in one place.'
      }},
      {{
        nav: 'dashboard', el: '#alarm',
        title: 'Alarm Control',
        text: 'Activate or end school alerts here. Leave Training Mode on for drills — no real push notifications are sent. Uncheck it only during a live emergency.'
      }},
      {{
        nav: 'user-management', el: '#user-management',
        title: 'User Management',
        text: 'Create and manage staff accounts. Each role controls a different level of access. Use the Codes tab to generate one-time links so staff can self-register on the mobile app.'
      }},
      {{
        nav: 'devices', el: '#devices',
        title: 'Registered Devices',
        text: 'Every phone with the BlueBird app installed appears here. Devices must register to receive push alerts during an alarm.'
      }},
      {{
        nav: 'settings', el: null,
        title: 'Settings',
        text: 'Configure alert hold duration, quiet periods, notification sounds, and access code behavior. Changes take effect immediately across all devices.'
      }}
    ];
    /* District-admin-specific 9-step tour — replaces the generic tour for this role. */
    var _DA_STEPS = [
      {{ nav: 'dashboard', el: '#overview',
        title: 'Welcome to BlueBird Alerts',
        text: 'This dashboard gives you real-time visibility into your district\'s emergency alert system. Track users, devices, and alert readiness at a glance.' }},
      {{ nav: 'dashboard', el: '#alarm',
        title: 'Trigger Emergency Alerts',
        text: 'Press and hold the Activate Alarm button to send an emergency alert across your district. Leave Training Mode on for safe drills — no real notifications are sent.' }},
      {{ nav: 'dashboard', el: '#overview',
        title: 'Track Staff Response',
        text: 'During an active alarm, the acknowledgement counter shows how many staff members have confirmed they received the alert in real time.' }},
      {{ nav: 'user-management', el: '#user-management',
        title: 'Manage Staff Accounts',
        text: 'Add teachers and staff here so they can receive push alerts. Use the Codes tab to generate self-registration links — staff install the app and register themselves.' }},
      {{ nav: 'devices', el: '#devices',
        title: 'Device Readiness',
        text: 'Every registered phone appears here. Staff must install the BlueBird app and register to receive push notifications during an alarm.' }},
      {{ nav: 'district', el: '#district-overview',
        title: 'Multi-School Management',
        text: 'View and manage all buildings in your district from one place. Click any school card to switch to that school\'s dashboard.' }},
      {{ nav: 'district-reports', el: '#district-reports',
        title: 'District Reports',
        text: 'Review drill history and alert activity across all buildings. Use this to verify that training exercises reach every school in your district.' }},
      {{ nav: 'audit-logs', el: '#audit-events',
        title: 'Audit & Accountability',
        text: 'Every alert activation, user change, and system event is logged here with timestamps and actor names — full transparency for compliance.' }},
      {{ nav: null, el: null,
        title: 'You\'re All Set!',
        text: 'Setup complete. We recommend running a training drill next to verify push notifications reach all registered devices. Your setup checklist on the dashboard tracks progress.' }}
    ];
    /* Use the DA tour for district_admin, generic tour for everyone else. */
    if ({json.dumps(is_district_admin)}) {{ STEPS = _DA_STEPS; }}

    var _step = 0;
    var _overlay = null;
    var _card = null;

    function _init() {{
      _overlay = document.createElement('div');
      _overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.52);z-index:9000;display:none;';
      _overlay.addEventListener('click', function(e) {{ if (e.target === _overlay) bbEndTour(); }});
      document.body.appendChild(_overlay);

      _card = document.createElement('div');
      _card.style.cssText = 'position:fixed;bottom:28px;left:50%;transform:translateX(-50%);'
        + 'background:var(--surface,#fff);border:1px solid var(--border);border-radius:18px;'
        + 'padding:24px 28px;max-width:480px;width:calc(100% - 48px);z-index:9001;'
        + 'box-shadow:0 20px 60px rgba(0,0,0,0.28);display:none;';
      document.body.appendChild(_card);
    }}

    function _navigateTo(nav) {{
      /* null nav means "stay in place" (e.g. final completion step). */
      if (!nav) return;
      /* Skip navigation (and the page reload it triggers) if already on this section. */
      var currentSection = new URLSearchParams(window.location.search).get('section') || 'dashboard';
      if (currentSection === nav) return;
      /* Store the step to resume after the page reload caused by nav-link click. */
      sessionStorage.setItem('bb_tour_resume', String(_step));
      var link = document.querySelector('.nav-item[href*="section=' + nav + '"]');
      if (link) link.click();
    }}

    function _highlightEl(sel) {{
      if (!sel) return;
      setTimeout(function() {{
        var el = document.querySelector(sel);
        if (!el) return;
        el.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
        el.classList.add('bb-tour-highlight');
        setTimeout(function() {{ el.classList.remove('bb-tour-highlight'); }}, 2400);
      }}, 200);
    }}

    function _dots(current, total) {{
      var html = '';
      for (var i = 0; i < total; i++) {{
        html += '<span style="display:inline-block;width:7px;height:7px;border-radius:50%;margin:0 3px;'
          + 'background:' + (i === current ? 'var(--accent,#1b5fe4)' : 'rgba(0,0,0,0.15)') + ';'
          + 'transition:background 0.2s;"></span>';
      }}
      return html;
    }}

    function _showStep(i) {{
      if (i < 0 || i >= STEPS.length) {{ bbEndTour(); return; }}
      _step = i;
      var s = STEPS[i];
      _navigateTo(s.nav);
      _highlightEl(s.el);

      var backBtn = i > 0
        ? '<button onclick="window._bbTourBack()" style="background:var(--btn-secondary-bg,#f3f4f6);border:1px solid var(--border);'
          + 'border-radius:8px;padding:8px 16px;font-size:0.82rem;font-weight:600;cursor:pointer;color:var(--text);">&#8592; Back</button>'
        : '';
      var nextLbl = i === STEPS.length - 1 ? 'Finish' : 'Next &#8594;';

      _card.innerHTML = (
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">'
        + '<span style="font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.09em;color:var(--accent,#1b5fe4);">Guided Tour &mdash; ' + (i+1) + ' of ' + STEPS.length + '</span>'
        + '<button onclick="bbEndTour()" style="background:none;border:none;cursor:pointer;color:var(--muted);font-size:1.1rem;line-height:1;padding:0 2px;" title="Close tour">&#x2715;</button>'
        + '</div>'
        + '<h3 style="margin:0 0 8px;font-size:1.05rem;color:var(--text);">' + s.title + '</h3>'
        + '<p style="margin:0 0 20px;color:var(--muted);font-size:0.88rem;line-height:1.55;">' + s.text + '</p>'
        + '<div style="display:flex;gap:10px;align-items:center;">'
        + backBtn
        + '<button onclick="window._bbTourNext()" style="background:var(--accent,#1b5fe4);color:#fff;border:none;'
          + 'border-radius:8px;padding:8px 18px;font-size:0.84rem;font-weight:600;cursor:pointer;">' + nextLbl + '</button>'
        + '<span style="margin-left:auto;">' + _dots(i, STEPS.length) + '</span>'
        + '</div>'
      );

      _overlay.style.display = 'block';
      _card.style.display = 'block';
    }}

    window.startBluebirdTour = function() {{
      localStorage.setItem('bb_tour_seen', '1');
      _showStep(0);
    }};
    window._bbTourNext = function() {{ _showStep(_step + 1); }};
    window._bbTourBack = function() {{ _showStep(_step - 1); }};
    window.bbEndTour = function() {{
      if (_overlay) _overlay.style.display = 'none';
      if (_card) _card.style.display = 'none';
      document.querySelectorAll('.bb-tour-highlight').forEach(function(el) {{
        el.classList.remove('bb-tour-highlight');
      }});
    }};

    document.addEventListener('DOMContentLoaded', function() {{
      _init();
      var btn = document.getElementById('bb-tour-btn');
      if (btn) btn.style.display = '';

      /* Resume tour after a cross-section nav-link navigation. */
      var resumeStep = sessionStorage.getItem('bb_tour_resume');
      if (resumeStep !== null) {{
        sessionStorage.removeItem('bb_tour_resume');
        setTimeout(function() {{ _showStep(parseInt(resumeStep, 10) || 0); }}, 200);
        return;
      }}

      /* Auto-start for first-time non-DA visitors (not in demo mode).
         DA users get their own welcome prompt from the onboarding IIFE instead. */
      if (!{json.dumps(is_district_admin)} && !localStorage.getItem('bb_tour_seen') && !document.querySelector('[data-demo]')) {{
        setTimeout(window.startBluebirdTour, 1400);
      }}
    }});
  }})();
  </script>

  <!-- ── District Admin Onboarding (welcome prompt + checklist) ──────────── -->
  <script>
  (function() {{
    if (!{json.dumps(is_district_admin)}) return;

    var _OB_KEY = 'bb_da_ob_v';
    var _CL_KEY = 'bb_da_cl_dismissed';

    function _showWelcome() {{
      var ov = document.getElementById('bb-da-wb-ov');
      if (ov) ov.classList.add('open');
    }}

    function _hideWelcome() {{
      var ov = document.getElementById('bb-da-wb-ov');
      if (ov) ov.classList.remove('open');
    }}

    window.bbDaStartOnboarding = function() {{
      localStorage.setItem(_OB_KEY, '1');
      _hideWelcome();
      if (window.startBluebirdTour) window.startBluebirdTour();
    }};

    window.bbDaSkipOnboarding = function() {{
      localStorage.setItem(_OB_KEY, '1');
      _hideWelcome();
    }};

    window.bbDaResetOnboarding = function() {{
      localStorage.removeItem(_OB_KEY);
      localStorage.removeItem('bb_tour_seen');
      localStorage.removeItem(_CL_KEY);
      _showWelcome();
    }};

    window.bbDaClDismiss = function() {{
      localStorage.setItem(_CL_KEY, String(Date.now()));
      var el = document.getElementById('bb-da-checklist');
      if (el) el.style.display = 'none';
    }};

    document.addEventListener('DOMContentLoaded', function() {{
      if (!localStorage.getItem(_OB_KEY) && !document.querySelector('[data-demo]')) {{
        setTimeout(_showWelcome, 900);
      }}
      var cl = document.getElementById('bb-da-checklist');
      if (cl) {{
        var done  = parseInt(cl.getAttribute('data-done')  || '0', 10);
        var total = parseInt(cl.getAttribute('data-total') || '1', 10);
        var dismissed = parseInt(localStorage.getItem(_CL_KEY) || '0', 10);
        var week = 7 * 24 * 60 * 60 * 1000;
        if (done < total && !(dismissed > 0 && Date.now() - dismissed < week)) {{
          cl.style.display = 'block';
        }}
      }}
    }});
  }})();
  </script>
</body>
</html>"""
