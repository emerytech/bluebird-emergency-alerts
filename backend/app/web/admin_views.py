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
from app.services.email_service import EmailLogRecord, GmailSettings, SMTPConfig, TEMPLATE_KEYS as EMAIL_TEMPLATE_KEYS
from app.services.health_monitor import HeartbeatRecord, HealthStatus, UptimeStats
from app.services.device_registry import RegisteredDevice
from app.services.incident_store import TeamAssistRecord
from app.services.quiet_period_store import QuietPeriodRecord
from app.services.report_store import AdminMessageRecord, BroadcastUpdateRecord, ReportRecord
from app.services.school_registry import SchoolRecord
from app.services.tenant_settings_store import SettingsChangeRecord
from app.services.user_store import UserRecord


LOGO_PATH = "/static/bluebird-alert-logo.png"


def _favicon_tags(logo_url: Optional[str] = None) -> str:
    icon = logo_url if logo_url else LOGO_PATH
    return (
        f'<link rel="icon" type="image/png" href="{icon}" />'
        f'<link rel="apple-touch-icon" href="{icon}" />'
    )


def _brand_mark(logo_url: Optional[str] = None) -> str:
    img_src = logo_url if logo_url else LOGO_PATH
    alt = "School logo" if logo_url else "BlueBird Alerts logo"
    return (
        f'<div class="brand-mark"><img src="{img_src}" alt="{alt}"'
        f' onerror="this.onerror=null;this.src=\'{LOGO_PATH}\';" /></div>'
    )


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


def _theme_vars() -> str:
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
      --card: var(--color-card);
      --surface: rgba(255,255,255,0.98);
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


def _base_styles() -> str:
    return _theme_vars() + """
    * { box-sizing: border-box; }
    html[data-theme="dark"] {
      --color-background-light: #0d1829;
      --color-background-dark: #0a1020;
      --color-card: #131f35;
      --color-input-background: #1a2540;
      --color-text-primary: #e8f0fe;
      --color-text-secondary: #8baad4;
      --color-border: rgba(99, 140, 210, 0.15);
      --bg: var(--color-background-light);
      --bg-deep: var(--color-background-dark);
      --panel: rgba(19, 31, 53, 0.92);
      --panel-strong: rgba(19, 31, 53, 0.99);
      --border: var(--color-border);
      --text: var(--color-text-primary);
      --muted: var(--color-text-secondary);
      --card: var(--color-card);
      --surface: rgba(19, 31, 53, 0.99);
    }
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
      background: #fff;
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
    .school-card.drag-over { outline: 2px solid var(--color-primary, #1B5FE4); }
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
      background:#fff; border-left:1px solid var(--border);
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
      background:#fff; border-radius:20px; padding:28px 30px;
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
    """


def _render_flash(message: Optional[str], kind: str = "success") -> str:
    if not message:
        return ""
    return f'<div class="flash {escape(kind)}">{escape(message)}</div>'


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
  <style>{_base_styles()}</style>
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
    sim_class = "success" if sim_on else "neutral"
    sim_label = "SIM ON" if sim_on else "SIM OFF"
    audio_class = "warning" if audio_on else "neutral"
    audio_label = "AUDIO MUTED" if audio_on else "AUDIO ON"
    confirm_msg = "Reset simulation data for " + str(s.get("slug", "")) + "?"
    return (
        '<div style="border-top:1px solid #e5e7eb;padding:10px 0;display:flex;align-items:center;gap:12px;flex-wrap:wrap;">'
        f'<code style="flex:1;min-width:120px;">{slug}</code>'
        f'<span style="flex:2;">{name}</span>'
        f'<span class="status-pill {sim_class}">{sim_label}</span>'
        f'<span class="status-pill {audio_class}">{audio_label}</span>'
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
    ) or '<tr><td colspan="5" class="empty-state">No schools yet.</td></tr>'
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

    section = active_section if active_section in {"schools", "billing", "platform-audit", "create-school", "security", "configuration", "server-tools", "health", "email-tool", "setup-codes", "noc", "msp", "platform-control", "sandbox"} else "schools"

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
            {_nav_item("platform-control", "Platform Control")}
            {_nav_item("msp", "MSP Dashboard", "!" if any(str(d.get("status","")) == "alarm" for d in msp_districts) else (str(len(msp_districts)) if msp_districts else None))}
            {_nav_item("noc", "Operations", "!" if (health_status and health_status.overall != "ok") or any(bool(t.get("alarm_active")) for t in noc_tenant_data) else None)}
            {_nav_item("schools", "Schools", str(len(school_rows)) if school_rows else None)}
            {_nav_item("billing", "Billing", str(len(billing_rows)) if billing_rows else None)}
            {_nav_item("create-school", "Create School")}
            {_nav_item("platform-audit", "Platform Audit")}
            {_nav_item("health", "System Health", None if (not health_status or health_status.overall == 'ok') else "!")}
            {_nav_item("email-tool", "Email Tool")}
            {_nav_item("configuration", "Configuration", None if email_configured else "!")}
            {_nav_item("setup-codes", "Setup Codes")}
            {_nav_item("security", "Security")}
            {_nav_item("server-tools", "Server Tools")}
            {_nav_item("sandbox", "Sandbox")}
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
          <div class="table-search"><input type="search" id="school-search" placeholder="Filter schools..." /></div>
          <div class="table-wrap"><table class="data-table" id="schools-table">
            <thead>
              <tr><th>Name</th><th>Slug</th><th>School URLs</th><th>Setup</th><th>Status</th></tr>
            </thead>
            <tbody>{rows}</tbody>
          </table></div>
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
          <div class="table-wrap"><table class="data-table">
            <thead>
              <tr><th>School</th><th>Plan</th><th>Status</th><th>Trial End</th><th>Renewal</th><th>Free Override</th><th>Stripe IDs</th><th>Controls</th></tr>
            </thead>
            <tbody>{billing_table_rows}</tbody>
          </table></div>
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

      </section>
    </div>
  </main>
  <script>(function(){{var t=localStorage.getItem('bb_theme')||(window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');if(t==='dark')document.documentElement.setAttribute('data-theme','dark');}})();</script>
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
        return '<tr><td colspan="8" class="empty-state">No devices registered yet.</td></tr>'
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
    total = len(users)
    active = sum(1 for u in users if u.is_active)
    login_enabled = sum(1 for u in users if getattr(u, "can_login", False))
    da_count = sum(1 for u in users if u.role == "district_admin" and u.is_active)
    if da_count >= 2:
        da_cls, da_sub = "hc-ok", "Healthy — redundancy in place"
    elif da_count == 1:
        da_cls, da_sub = "hc-warn", "Warning — single point of failure"
    else:
        da_cls, da_sub = "hc-danger", "Critical — no district admin!"
    sec_cls = "hc-ok" if da_count >= 1 else "hc-danger"
    sec_label = "Healthy" if da_count >= 1 else "At Risk"
    return (
        '<div class="um-health-bar">'
        f'<div class="um-hcard hc-ok"><div class="um-hcard-label">Total Users</div><div class="um-hcard-value">{total}</div><div class="um-hcard-sub">{active} active</div></div>'
        f'<div class="um-hcard {da_cls}"><div class="um-hcard-label">District Admins</div><div class="um-hcard-value">{da_count}</div><div class="um-hcard-sub">{da_sub}</div></div>'
        f'<div class="um-hcard hc-ok"><div class="um-hcard-label">Login Enabled</div><div class="um-hcard-value">{login_enabled}</div><div class="um-hcard-sub">Can access dashboard</div></div>'
        f'<div class="um-hcard {sec_cls}"><div class="um-hcard-label">Security Status</div><div class="um-hcard-value" style="font-size:1.1rem;padding-top:2px;">{escape(sec_label)}</div><div class="um-hcard-sub">Role hierarchy integrity</div></div>'
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
        status_badge = (
            '<span class="status-pill ok" style="font-size:.72rem;padding:2px 9px;min-height:0;">Active</span>'
            if u.is_active else
            '<span class="status-pill danger" style="font-size:.72rem;padding:2px 9px;min-height:0;">Inactive</span>'
        )
        last = escape(getattr(u, "last_login_at", None) or "Never")[:16].replace("T", " ")
        title_str = f'<span class="um-sub">{escape(u.title)}</span>' if getattr(u, "title", "") else ""
        login_str = escape(u.login_name or "—")
        # Build user JSON for slide panel (no password fields)
        user_json = json.dumps({
            "id": u.id,
            "name": u.name,
            "role": u.role,
            "title": getattr(u, "title", "") or "",
            "login": u.login_name or "",
            "phone": getattr(u, "phone_e164", "") or "",
            "is_active": u.is_active,
            "last_login": last,
            "is_self": is_self,
        })
        self_badge = ' <span class="role-badge" style="background:rgba(27,95,228,.1);color:#1e40af;font-size:.68rem;">You</span>' if is_self else ""
        rows.append(
            f'<tr class="um-row" data-uid="{u.id}" data-user=\'{escape(user_json)}\' title="Click to view details">'
            f'<td style="width:44px;">{_um_avatar(u.name, u.role)}</td>'
            f'<td><div class="um-name-cell"><div class="um-name-stack"><span class="um-name">{escape(u.name)}{self_badge}</span>{title_str}</div></div></td>'
            f'<td style="font-size:0.8rem;color:var(--muted);">{login_str}</td>'
            f'<td>{_um_role_badge(u.role)}</td>'
            f'<td>{status_badge}</td>'
            f'<td style="color:var(--muted);font-size:0.8rem;">{last}</td>'
            f'<td style="text-align:right;">'
            f'<button class="button button-secondary um-edit-btn" style="min-height:32px;font-size:0.8rem;padding:0 12px;" '
            f'data-uid="{u.id}" onclick="event.stopPropagation();umToggleEdit({u.id})">Edit</button>'
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
        '<th></th><th>Name</th><th>Username</th><th>Role</th>'
        '<th>Status</th><th>Last Login</th><th style="text-align:right;">Actions</th>'
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
            f'<form method="post" action="{prefix}/admin/users/{user.id}/delete" onsubmit="return confirm(\'Delete {escape(user.name)}? This cannot be undone.\');">'
            f'<div class="button-row"><button class="button button-danger-outline" type="submit">Delete user</button></div>'
            f'</form>'
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




def _render_settings_panels(
    prefix: str,
    school_name: str,
    school_slug: str,
    settings_history: Sequence[SettingsChangeRecord],
    _section_style,
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
    base_domain: str = "app.bluebirdalerts.com",
    settings_history: Sequence[SettingsChangeRecord] = (),
    school_district_id: Optional[int] = None,
    active_sessions: Sequence[object] = (),
    sessions_users_by_id: Mapping[int, object] = {},
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
    section = active_section if active_section in {"dashboard", "user-management", "access-codes", "quiet-periods", "audit-logs", "settings", "drill-reports", "district", "devices"} else "dashboard"
    quiet_period_total = len(quiet_periods_active) + len(quiet_periods_history)
    refresh_meta = '<meta http-equiv="refresh" content="30">' if section in {"dashboard", "district"} else ""
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

    _show_access_codes = str(getattr(current_user, "role", "")).strip().lower() in {"district_admin", "super_admin"}
    _ac_status_class = {"active": "ok", "used": "warn", "expired": "warn", "revoked": "danger"}

    def _ac_row(r) -> str:
        _rid = int(getattr(r, "id", 0))
        _code = str(getattr(r, "code", ""))
        _status = str(getattr(r, "status", ""))
        _is_active = _status == "active"
        _qr_url = f"{prefix}/admin/access-codes/{_rid}/qr.png"
        _print_url = f"{prefix}/admin/access-codes/{_rid}/print"
        _download_url = f"{prefix}/admin/access-codes/{_rid}/qr.png"
        _qr_img = (
            f'<img src="{_qr_url}" alt="QR {escape(_code)}" width="80" height="80"'
            f' style="display:block;image-rendering:pixelated;border:1px solid #ddd;border-radius:4px;" />'
            if _is_active else
            '<span class="mini-copy" style="color:var(--muted);">—</span>'
        )
        _action_buttons = (
            f'<a href="{_download_url}" download="bluebird-invite-{escape(_code)}.png"'
            f' class="button button-secondary" style="font-size:0.75rem;padding:4px 10px;text-decoration:none;">Download QR</a>'
            f'<a href="{_print_url}" target="_blank"'
            f' class="button button-secondary" style="font-size:0.75rem;padding:4px 10px;text-decoration:none;">Print Sheet</a>'
        ) if _is_active else ""
        return (
            "<tr>"
            f"<td style='min-width:90px;'>{_qr_img}</td>"
            f"<td><code style='font-size:1rem;letter-spacing:.05em;'>{escape(_code)}</code></td>"
            f"<td>{escape(str(getattr(r, 'role', '')))}</td>"
            f"<td>{escape(str(getattr(r, 'title', '') or '—'))}</td>"
            f"<td><span class=\"status-pill {_ac_status_class.get(_status, 'warn')}\">{escape(_status)}</span></td>"
            f"<td>{escape(str(getattr(r, 'expires_at', ''))[:16])}</td>"
            f"<td>{int(getattr(r, 'use_count', 0))}/{int(getattr(r, 'max_uses', 1))}</td>"
            f"<td><div style='display:flex;flex-direction:column;gap:4px;align-items:flex-start;'>"
            f"{_action_buttons}"
            f"<form method=\"post\" action=\"{prefix}/admin/access-codes/{_rid}/revoke\""
            f" onsubmit=\"return confirm('Revoke this code?');\" style='margin:0;'>"
            f"<button class=\"button button-danger-outline\" type=\"submit\""
            f" style='font-size:0.75rem;padding:4px 10px;' {'disabled' if not _is_active else ''}>Revoke</button></form>"
            f"</div></td>"
            "</tr>"
        )

    _access_code_rows = "".join(_ac_row(r) for r in access_code_records) or '<tr><td colspan="8" class="empty-state">No access codes generated yet.</td></tr>'

    _client_type_label = {"mobile": "Mobile", "web": "Web"}
    _client_type_class = {"mobile": "rb-law_enforcement", "web": "rb-admin"}

    def _fmt_dt(raw: str) -> str:
        return str(raw or "")[:16].replace("T", " ")

    _session_rows = "".join(
        (
            "<tr>"
            "<td>"
            + (
                lambda u, s: (
                    f'<span class="um-avatar ua-{escape(str(getattr(u, "role", ""))[:20])}" style="width:28px;height:28px;font-size:11px;margin-right:8px;">'
                    + escape("".join(w[0].upper() for w in str(getattr(u, "name", "?")).split()[:2]))
                    + "</span>"
                    + escape(str(getattr(u, "name", f"user #{s.user_id}")))
                )
            )(sessions_users_by_id.get(int(getattr(s, "user_id", 0))), s)
            + "</td>"
            + f'<td><span class="role-badge {_client_type_class.get(str(getattr(s, "client_type", "mobile")), "rb-teacher")}">'
            + escape(_client_type_label.get(str(getattr(s, "client_type", "mobile")), str(getattr(s, "client_type", ""))))
            + "</span></td>"
            + f'<td class="mini-copy">{escape(str(getattr(sessions_users_by_id.get(int(getattr(s, "user_id", 0))), "role", "—")))}</td>'
            + f'<td class="mini-copy">{escape(_fmt_dt(str(getattr(s, "last_seen_at", ""))))}</td>'
            + f'<td class="mini-copy">{escape(_fmt_dt(str(getattr(s, "created_at", ""))))}</td>'
            + f'<td><form method="post" action="{prefix}/admin/devices/{int(getattr(s, "id", 0))}/revoke"'
            + ' onsubmit="return confirm(\'Force logout this device session?\');">'
            + '<button class="button button-danger-outline" type="submit" style="font-size:12px;padding:4px 14px;min-height:auto;">Force Logout</button>'
            + "</form></td>"
            + "</tr>"
        )
        for s in active_sessions
    ) or '<tr><td colspan="6" class="empty-state">No active device sessions.</td></tr>'

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
    if _show_access_codes:
        _access_codes_panel_html = f"""
          <section class="panel command-section span-12" id="access-codes"{_section_style("access-codes")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Access Codes</p>
                <h2>Invite codes for onboarding</h2>
                <p class="card-copy">Generate a code so a new user can self-register via the mobile app. Codes are single-use by default and expire after 48 hours.</p>
              </div>
            </div>
            <form method="post" action="{prefix}/admin/access-codes/generate" class="stack" style="max-width:560px;margin-bottom:28px;">
              <input type="hidden" name="tenant_slug" value="{escape(school_slug)}" />
              <div class="form-grid">
                <div class="field">
                  <label>Role</label>
                  <select name="role">
                    <option value="building_admin">Building Admin</option>
                    <option value="teacher">Teacher / Standard</option>
                    <option value="staff">Staff</option>
                    <option value="law_enforcement">Law Enforcement</option>
                  </select>
                </div>
                <div class="field">
                  <label>Job title (optional)</label>
                  <input name="title" placeholder="e.g. Principal" />
                </div>
                <div class="field">
                  <label>Max uses</label>
                  <input name="max_uses" type="number" min="1" max="20" value="1" />
                </div>
                <div class="field">
                  <label>Expires (hours)</label>
                  <input name="expires_hours" type="number" min="1" max="720" value="48" />
                </div>
              </div>
              <div class="button-row">
                <button class="button button-primary" type="submit">Generate Code</button>
              </div>
            </form>
            <div class="table-wrapper">
              <table class="data-table">
                <thead><tr><th>QR</th><th>Code</th><th>Role</th><th>Title</th><th>Status</th><th>Expires</th><th>Uses</th><th>Actions</th></tr></thead>
                <tbody>{_access_code_rows}</tbody>
              </table>
            </div>
          </section>"""
    else:
        _access_codes_panel_html = ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BlueBird Admin</title>
  {_favicon_tags()}
  {refresh_meta}
  <style>{_base_styles()}</style>
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
  <script>
  // Server-injected config — do not edit by hand.
  var BB_WS_API_KEY = {json.dumps(ws_api_key)};
  var BB_USER_ID = {json.dumps(current_user_id or 0)};
  var BB_HOME_TENANT = {json.dumps(home_tenant_slug)};
  var BB_TENANT_SLUG = {json.dumps(selected_tenant_slug)};
  var BB_SHOW_DISTRICT_WS = {json.dumps(show_district_nav)};
  var BB_PATH_PREFIX = {json.dumps(school_path_prefix)};
  </script>
  <script>
  (function() {{
    var wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';

    // ── Single-school dashboard WebSocket ──────────────────────────────────
    function makeSingleSchoolWS() {{
      if (!BB_WS_API_KEY || !BB_USER_ID || !BB_TENANT_SLUG) return;
      // WS bypasses the HTTP middleware — no path prefix stripping — use bare /ws/... path.
      var url = wsProto + '//' + location.host + '/ws/' + BB_TENANT_SLUG + '/alerts'
        + '?user_id=' + BB_USER_ID + '&api_key=' + encodeURIComponent(BB_WS_API_KEY);
      var backoff = 1000;
      function connect() {{
        var ws = new WebSocket(url);
        ws.onopen = function() {{ backoff = 1000; }};
        ws.onmessage = function(evt) {{
          try {{
            var data = JSON.parse(evt.data);
            updateSingleSchoolUI(data);
          }} catch(e) {{}}
        }};
        ws.onclose = function(evt) {{
          if (evt.code >= 4400 && evt.code < 4500) return; // auth failure — don't retry
          setTimeout(connect, backoff);
          backoff = Math.min(backoff * 2, 30000);
        }};
      }}
      connect();
    }}

    function updateSingleSchoolUI(data) {{
      var pill = document.getElementById('js-alarm-status-pill');
      var ackPill = document.getElementById('js-ack-pill');
      if (!pill || !data.alarm) return;
      var alarm = data.alarm;
      var cls = 'ok';
      var label = 'Alarm clear';
      var msg = alarm.message || 'No active alarm';
      if (alarm.is_active && alarm.is_training) {{ cls = 'warn'; label = 'TRAINING ACTIVE'; }}
      else if (alarm.is_active) {{ cls = 'danger'; label = 'ALARM ACTIVE'; }}
      pill.className = 'status-pill ' + cls;
      pill.innerHTML = '<strong>' + label + '</strong>' + msg;
      if (ackPill) {{
        var ackCount = alarm.acknowledgement_count || 0;
        if (alarm.is_active && ackCount > 0) {{
          ackPill.style.display = '';
          ackPill.innerHTML = '<strong>Acknowledged</strong>' + ackCount + ' user' + (ackCount !== 1 ? 's' : '');
        }} else {{
          ackPill.style.display = 'none';
        }}
      }}
    }}

    // ── District overview WebSocket ────────────────────────────────────────
    function makeDistrictWS() {{
      if (!BB_SHOW_DISTRICT_WS || !BB_WS_API_KEY || !BB_USER_ID || !BB_HOME_TENANT) return;
      var badge = document.getElementById('dist-ws-badge');
      // WS bypasses HTTP middleware — no prefix; district endpoint has its own path.
      var url = wsProto + '//' + location.host + '/ws/district/alerts'
        + '?user_id=' + BB_USER_ID + '&home_tenant=' + encodeURIComponent(BB_HOME_TENANT)
        + '&api_key=' + encodeURIComponent(BB_WS_API_KEY);
      var backoff = 1000;
      function setBadge(state) {{
        if (!badge) return;
        badge.style.display = '';
        if (state === 'live') {{
          badge.className = 'status-pill ok';
          badge.innerHTML = '&#x25CF;&nbsp;Live';
        }} else if (state === 'reconnecting') {{
          badge.className = 'status-pill warn';
          badge.innerHTML = '&#x25CB;&nbsp;Reconnecting';
        }} else {{
          badge.className = 'status-pill danger';
          badge.innerHTML = '&#x25A0;&nbsp;Offline';
        }}
      }}
      function connect() {{
        setBadge('reconnecting');
        var ws = new WebSocket(url);
        ws.onopen = function() {{ backoff = 1000; setBadge('live'); }};
        ws.onmessage = function(evt) {{
          try {{
            var data = JSON.parse(evt.data);
            updateDistrictRow(data);
          }} catch(e) {{}}
        }};
        ws.onclose = function(evt) {{
          setBadge(evt.code >= 4400 && evt.code < 4500 ? 'offline' : 'reconnecting');
          if (evt.code >= 4400 && evt.code < 4500) return;
          setTimeout(connect, backoff);
          backoff = Math.min(backoff * 2, 30000);
        }};
      }}
      connect();
    }}

    function updateDistrictRow(data) {{
      if (!data.tenant_slug || !data.alarm) return;
      var slug = data.tenant_slug;
      var alarm = data.alarm;
      var rows = document.querySelectorAll('#district-overview tr[data-tenant-slug="' + slug + '"]');
      rows.forEach(function(row) {{
        var statusCell = row.querySelector('.dist-status-cell');
        var ackCell = row.querySelector('.dist-ack-cell');
        var lastCell = row.querySelector('.dist-last-cell');
        if (statusCell) {{
          var badge = '';
          if (alarm.is_active && alarm.is_training) badge = '<span class="status-pill warn">TRAINING</span>';
          else if (alarm.is_active) badge = '<span class="status-pill danger">LOCKDOWN</span>';
          else badge = '<span class="status-pill ok">All Clear</span>';
          var note = (alarm.is_active && alarm.message) ? '<div class="mini-copy">' + alarm.message.substring(0, 80) + '</div>' : '';
          statusCell.innerHTML = badge + note;
        }}
        if (ackCell) {{
          var ackCount = alarm.acknowledgement_count || 0;
          var expectedUsers = parseInt(row.dataset.expectedUsers, 10) || 0;
          if (expectedUsers === 0) {{
            ackCell.innerHTML = '<span class="mini-copy">No users</span>';
          }} else {{
            var rate = Math.round(ackCount / expectedUsers * 100);
            var cls = rate >= 90 ? 'ok' : (rate >= 60 ? 'warn' : 'danger');
            ackCell.innerHTML = '<span class="status-pill ' + cls + '">' + ackCount + '/' + expectedUsers + ' (' + rate + '%)</span>';
          }}
        }}
        if (lastCell && alarm.activated_at) {{
          lastCell.textContent = (alarm.activated_at || '').substring(0, 16).replace('T', ' ');
        }}
      }});
    }}

    document.addEventListener('DOMContentLoaded', function() {{
      makeSingleSchoolWS();
      makeDistrictWS();
    }});
  }})();
  </script>
  <script>
  document.addEventListener('DOMContentLoaded', function() {{
    function makeSearchFilter(inputId, containerSelector, rowSelector) {{
      var input = document.getElementById(inputId);
      var container = document.querySelector(containerSelector);
      if (!input || !container) return;
      input.addEventListener('input', function() {{
        var q = input.value.trim().toLowerCase();
        container.querySelectorAll(rowSelector).forEach(function(el) {{
          el.style.display = (!q || el.textContent.toLowerCase().includes(q)) ? '' : 'none';
        }});
      }});
    }}
    makeSearchFilter('audit-search', '#audit-events', 'tbody tr');
    makeSearchFilter('device-search', '#devices', 'tbody tr');
    makeSearchFilter('drill-search', '#drill-reports', 'tbody tr');
    // User search — filters table rows (and mirrors to edit cards)
    var userSearchEl = document.getElementById('user-search');
    if (userSearchEl) {{
      userSearchEl.addEventListener('input', function() {{
        var q = userSearchEl.value.trim().toLowerCase();
        document.querySelectorAll('.um-row').forEach(function(row) {{
          var match = !q || row.textContent.toLowerCase().includes(q);
          row.style.display = match ? '' : 'none';
          // Also hide the paired edit row if visible
          var uid = row.dataset.uid;
          var editRow = document.getElementById('um-editcard-' + uid);
          if (editRow && !match) editRow.style.display = 'none';
        }});
      }});
    }}
  }});
  </script>
  <script>
  /* ── Enterprise User Management ─────────────────────────────────────────── */
  (function() {{
    var ROLE_LABELS = {{
      'teacher': 'Teacher / Standard', 'staff': 'Staff',
      'law_enforcement': 'Law Enforcement', 'admin': 'Admin',
      'building_admin': 'Building Admin', 'district_admin': 'District Admin',
      'super_admin': 'Super Admin'
    }};
    var ROLE_PERMS = {{
      'teacher': ['Send help requests', 'View incident feed', 'Submit quiet period request'],
      'staff': ['Send help requests', 'View incident feed', 'Submit quiet period request'],
      'law_enforcement': ['Send help requests', 'Submit quiet period request', 'View assigned incidents', 'Receive school alerts'],
      'admin': ['Manage school users', 'Trigger alerts', 'Approve quiet requests', 'Submit quiet period request'],
      'building_admin': ['Manage school users', 'Trigger alerts', 'Approve quiet requests', 'Submit quiet period request'],
      'district_admin': ['Manage all school users', 'Trigger alerts', 'Approve quiet requests', 'Manage district schools', 'Generate access codes'],
      'super_admin': ['Full platform access']
    }};
    var ROLE_BADGE_CLS = {{
      'district_admin': 'rb-district_admin', 'admin': 'rb-admin',
      'building_admin': 'rb-building_admin', 'teacher': 'rb-teacher',
      'staff': 'rb-staff', 'law_enforcement': 'rb-law_enforcement', 'super_admin': 'rb-super_admin'
    }};
    var panel = document.getElementById('um-panel');
    var overlay = document.getElementById('um-overlay');
    var roleModal = document.getElementById('um-role-modal');
    var pendingRoleForm = null;
    var openEditId = null;

    function roleBadgeHtml(role) {{
      return '<span class="role-badge ' + (ROLE_BADGE_CLS[role] || '') + '">' + (ROLE_LABELS[role] || role) + '</span>';
    }}

    function openPanel(userData) {{
      var role = userData.role || 'teacher';
      // avatar
      var av = document.getElementById('up-avatar');
      if (av) {{
        av.className = 'um-panel-avatar ua-' + role;
        var initials = (userData.name || '?').split(' ').map(function(w){{return w[0]||'';}} ).join('').slice(0,2).toUpperCase();
        av.textContent = initials;
      }}
      var el = function(id){{return document.getElementById(id);}};
      if (el('up-name')) el('up-name').textContent = userData.name || '';
      if (el('up-role-badge')) el('up-role-badge').innerHTML = roleBadgeHtml(role);
      var statusCls = userData.is_active ? 'ok' : 'danger';
      var statusTxt = userData.is_active ? 'Active' : 'Inactive';
      if (el('up-status-pill')) el('up-status-pill').innerHTML = '<span class="status-pill ' + statusCls + '" style="font-size:.76rem;min-height:0;padding:3px 10px;">' + statusTxt + '</span>';
      var metaParts = [];
      if (userData.title) metaParts.push(userData.title);
      if (userData.phone) metaParts.push(userData.phone);
      if (el('up-meta')) el('up-meta').textContent = metaParts.join(' · ') || 'No additional info';
      if (el('up-login')) el('up-login').textContent = userData.login || '—';
      if (el('up-last-login')) el('up-last-login').textContent = userData.last_login || 'Never';
      if (el('up-uid')) el('up-uid').textContent = '#' + userData.id;
      // permissions
      var perms = ROLE_PERMS[role] || [];
      if (el('up-perms')) {{
        el('up-perms').innerHTML = perms.map(function(p) {{
          return '<div class="um-perm-item"><div class="um-perm-dot"></div><span>' + p + '</span></div>';
        }}).join('') || '<span class="mini-copy">No permissions defined</span>';
      }}
      // actions
      if (el('up-actions')) {{
        var isSelf = userData.is_self;
        var editBtn = '<button class="button button-primary" style="min-height:36px;font-size:0.82rem;" onclick="umToggleEdit(' + userData.id + ');umClosePanel();">Edit User</button>';
        var selfNote = isSelf ? '<p class="mini-copy" style="color:#b45309;">You cannot modify your own account role.</p>' : '';
        el('up-actions').innerHTML = editBtn + selfNote;
      }}
      // mark active row
      document.querySelectorAll('.um-row').forEach(function(r){{r.classList.remove('um-row-active');}});
      var activeRow = document.querySelector('.um-row[data-uid="' + userData.id + '"]');
      if (activeRow) activeRow.classList.add('um-row-active');
      // show
      panel.classList.add('open');
      overlay.classList.add('open');
    }}

    window.umClosePanel = function() {{
      if (panel) panel.classList.remove('open');
      if (overlay) overlay.classList.remove('open');
      document.querySelectorAll('.um-row').forEach(function(r){{r.classList.remove('um-row-active');}});
    }};

    window.umToggleEdit = function(uid) {{
      var card = document.getElementById('um-editcard-' + uid);
      if (!card) return;
      if (openEditId && openEditId !== uid) {{
        var prev = document.getElementById('um-editcard-' + openEditId);
        if (prev) prev.style.display = 'none';
      }}
      var nowOpen = card.style.display !== 'none';
      card.style.display = nowOpen ? 'none' : 'block';
      openEditId = nowOpen ? null : uid;
      if (!nowOpen) card.scrollIntoView({{behavior: 'smooth', block: 'nearest'}});
    }};

    window.umToggleCreate = function() {{
      var wrap = document.getElementById('um-create-wrap');
      if (!wrap) return;
      var nowOpen = wrap.style.display !== 'none';
      wrap.style.display = nowOpen ? 'none' : 'block';
      if (!nowOpen) wrap.scrollIntoView({{behavior: 'smooth', block: 'start'}});
    }};

    document.addEventListener('DOMContentLoaded', function() {{
      // Table row click → open panel
      document.querySelectorAll('.um-row').forEach(function(row) {{
        row.addEventListener('click', function(e) {{
          if (e.target.closest('button, a, input, select, form')) return;
          try {{
            var userData = JSON.parse(row.dataset.user);
            openPanel(userData);
          }} catch(err) {{}}
        }});
      }});

      // Panel close
      if (overlay) overlay.addEventListener('click', window.umClosePanel);
      var closeBtn = document.getElementById('um-panel-close');
      if (closeBtn) closeBtn.addEventListener('click', window.umClosePanel);

      // Role change modal — intercept user-update form submit when role changes
      document.querySelectorAll('form[data-role-change]').forEach(function(form) {{
        form.addEventListener('submit', function(e) {{
          if (form.dataset.skipConfirm) {{ delete form.dataset.skipConfirm; return; }}
          var sel = form.querySelector('select[name="role"]');
          if (!sel) return;
          var oldRole = form.dataset.currentRole || '';
          var newRole = sel.value;
          if (!newRole || newRole === oldRole) return;
          e.preventDefault();
          pendingRoleForm = form;
          var el = function(id){{return document.getElementById(id);}};
          if (el('rm-user')) el('rm-user').textContent = form.dataset.userName || 'this user';
          if (el('rm-old-role')) el('rm-old-role').textContent = ROLE_LABELS[oldRole] || oldRole;
          if (el('rm-new-role')) el('rm-new-role').textContent = ROLE_LABELS[newRole] || newRole;
          var warn = el('rm-warning');
          if (warn) {{
            if (newRole === 'district_admin') {{
              warn.textContent = 'This grants full administrative control over the district. This action is audited.';
              warn.style.display = '';
            }} else if (newRole === 'admin' || newRole === 'building_admin') {{
              warn.textContent = 'This grants dashboard access and admin capabilities. This action is audited.';
              warn.style.display = '';
            }} else {{
              warn.style.display = 'none';
            }}
          }}
          var confirmBtn = el('rm-confirm');
          if (confirmBtn) {{
            var isElevation = ['admin','building_admin','district_admin'].includes(newRole);
            confirmBtn.className = isElevation ? 'button button-danger' : 'button button-primary';
          }}
          if (roleModal) roleModal.classList.add('open');
        }});
      }});

      var rmCancel = document.getElementById('rm-cancel');
      if (rmCancel) rmCancel.addEventListener('click', function() {{
        if (roleModal) roleModal.classList.remove('open');
        pendingRoleForm = null;
      }});
      var rmConfirm = document.getElementById('rm-confirm');
      if (rmConfirm) rmConfirm.addEventListener('click', function() {{
        if (roleModal) roleModal.classList.remove('open');
        if (pendingRoleForm) {{
          pendingRoleForm.dataset.skipConfirm = '1';
          pendingRoleForm.submit();
          pendingRoleForm = null;
        }}
      }});
    }});
  }})();
  </script>
  <script>
  /* ── Live branding preview ──────────────────────────────────────────────── */
  (function() {{
    var root = document.documentElement;
    var CSS_VAR_MAP = {{
      'bp-accent':        '--color-primary',
      'bp-accent-strong': '--color-primary-strong',
      'bp-sidebar-start': '--color-sidebar-start',
      'bp-sidebar-end':   '--color-sidebar-end',
    }};
    function applyVar(cssVar, value) {{
      if (/^#[0-9a-fA-F]{{6}}$/.test(value)) {{
        root.style.setProperty(cssVar, value);
        updateSidebarPreview();
      }}
    }}
    function wireInput(textId, pickerId, cssVar) {{
      var text = document.getElementById(textId);
      var picker = document.getElementById(pickerId);
      if (!text || !picker) return;
      text.addEventListener('input', function() {{ applyVar(cssVar, text.value.trim()); picker.value = text.value.trim(); }});
      picker.addEventListener('input', function() {{ text.value = picker.value; applyVar(cssVar, picker.value); }});
    }}
    function updateSidebarPreview() {{
      var preview = document.getElementById('bp-sidebar-preview');
      if (!preview) return;
      var start = getComputedStyle(root).getPropertyValue('--color-sidebar-start').trim() || '#092054';
      var end   = getComputedStyle(root).getPropertyValue('--color-sidebar-end').trim()   || '#071536';
      var accent = getComputedStyle(root).getPropertyValue('--color-primary').trim()       || '#1b5fe4';
      preview.style.background = 'linear-gradient(180deg, ' + start + ' 0%, ' + end + ' 100%)';
      var dot = preview.querySelector('.bp-preview-dot');
      if (dot) dot.style.background = accent;
      var glow = preview.querySelector('.bp-preview-glow');
      if (glow) glow.style.background = 'radial-gradient(circle at top left, ' + accent + '28, transparent 60%)';
    }}
    document.addEventListener('DOMContentLoaded', function() {{
      wireInput('s-accent',        'bp-accent-picker',        '--color-primary');
      wireInput('s-accent-strong', 'bp-accent-strong-picker', '--color-primary-strong');
      wireInput('s-sidebar-start', 'bp-sidebar-start-picker', '--color-sidebar-start');
      wireInput('s-sidebar-end',   'bp-sidebar-end-picker',   '--color-sidebar-end');
      updateSidebarPreview();
    }});
  }})();
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
            <p class="hero-copy">Signed in as <strong>{user_display_name}</strong> ({escape(current_user.login_name or 'admin')}).</p>
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
            {_nav_item("access-codes", "Access Codes") if _show_access_codes else ""}
            {_nav_item("quiet-periods", "Quiet Period Requests", str(len(quiet_periods_active)) if quiet_periods_active else None)}
            {_nav_item("drill-reports", "Drill Reports")}
            {_nav_item("audit-logs", "Audit Logs")}
            {_nav_item("settings", "Settings")}
            {_nav_item("district", "District Overview") if show_district_nav else ""}
            {_nav_item("devices", "Active Devices") if show_district_nav else ""}
          </nav>
          </div>
          <div class="shell-actions">
            <p class="signal-copy">Manage people, alerts, readiness, and response from one school operations console.</p>
            {super_admin_shell_action_html}
            <button class="theme-toggle-btn" onclick="bbToggleTheme()" id="bb-theme-btn" type="button">&#9790; Dark mode</button>
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
              <span id="js-alarm-status-pill" class="status-pill {alarm_status_class}"><strong>{alarm_status_label}</strong>{escape(alarm_state.message or 'No active alarm')}</span>
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

        {_render_settings_panels(prefix, school_name, school_slug, settings_history, _section_style)}

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
              {(" — Silent audio test" if getattr(alarm_state, "silent_audio", False) else "")}
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
              <div class="checkbox-row" style="background:rgba(14,165,233,.08);border-color:rgba(14,165,233,.22);">
                <input type="checkbox" name="silent_audio" value="1" id="silent_audio" />
                <label for="silent_audio">Silent audio test — show alarm screens without siren volume</label>
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

          <section class="panel command-section span-12" id="user-management"{_section_style("user-management")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">User Management</p>
                <h2>Accounts &amp; Access Control</h2>
                <p class="card-copy">Enterprise-grade user management. Role changes require confirmation and are fully audited.</p>
              </div>
              <div class="button-row">
                <button class="button button-primary" style="min-height:38px;font-size:0.85rem;padding:0 16px;" onclick="umToggleCreate()">+ Add User</button>
              </div>
            </div>

            {_um_health_bar(users)}

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
                      <label>Role</label>
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

            <div class="table-search" style="margin-bottom:14px;">
              <input type="search" id="user-search" placeholder="Search by name, username, or role..." style="max-width:320px;" />
              <span class="mini-copy" style="margin-left:auto;">{len(users)} user{"s" if len(users) != 1 else ""} total</span>
            </div>

            {_um_enterprise_table(users, school_path_prefix, actor_role=str(getattr(current_user, "role", "") or ""), actor_user_id=current_user_id)}

            <div id="um-edit-forms" style="margin-top:16px;">
              {_render_user_cards(
                  users,
                  school_path_prefix,
                  tenant_label=selected_tenant_name,
                  tenant_options=[{"id": str(item.get("id", "")), "slug": str(item.get("slug", "")), "name": str(item.get("name", ""))} for item in tenant_options],
                  user_tenant_assignments=user_tenant_assignments,
                  allow_assignment_edit=(current_user.role in {"district_admin", "super_admin"}),
                  actor_role=str(getattr(current_user, "role", "") or ""),
                  actor_user_id=current_user_id,
              )}
            </div>
          </section>

          {_um_slide_panel()}
          {_um_role_modal()}

          {_access_codes_panel_html}

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

          <section class="panel span-5" id="devices"{_section_style("dashboard")}>
            <div class="panel-header">
              <div>
                <p class="eyebrow">Devices</p>
                <h2>Registered devices</h2>
              </div>
            </div>
            <div class="table-search"><input type="search" id="device-search" placeholder="Filter devices..." /></div>
            <div class="table-wrap"><table class="data-table">
              <thead>
                <tr><th>#</th><th>Device</th><th>Platform</th><th>Provider</th><th>Current user</th><th>First user</th><th>Token</th><th>Action</th></tr>
              </thead>
              <tbody>
                {_render_device_rows(devices, users, school_path_prefix)}
              </tbody>
            </table></div>
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
                <h2>Active Devices</h2>
                <p class="card-copy">All active login sessions for <strong>{escape(selected_tenant_name)}</strong>. Force logout revokes the session immediately — the device must re-authenticate on next use.</p>
              </div>
              <div class="status-row">
                <span class="status-pill ok"><strong>{len(active_sessions)}</strong> active session{"s" if len(active_sessions) != 1 else ""}</span>
              </div>
            </div>
            <div class="table-wrap" style="overflow-x:auto;margin-top:16px;">
              <table class="um-table" style="width:100%;border-collapse:collapse;">
                <thead>
                  <tr style="text-align:left;border-bottom:2px solid var(--border);">
                    <th style="padding:8px 12px;font-size:13px;font-weight:600;">User</th>
                    <th style="padding:8px 12px;font-size:13px;font-weight:600;">Client</th>
                    <th style="padding:8px 12px;font-size:13px;font-weight:600;">Role</th>
                    <th style="padding:8px 12px;font-size:13px;font-weight:600;">Last Seen</th>
                    <th style="padding:8px 12px;font-size:13px;font-weight:600;">Session Created</th>
                    <th style="padding:8px 12px;font-size:13px;font-weight:600;">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {_session_rows}
                </tbody>
              </table>
            </div>
          </section>

        </section>
      </section>
    </div>
  </main>
  <script>
  (function() {{
    var THEME_KEY = 'bb_theme';
    var html = document.documentElement;
    function applyTheme(dark) {{
      if (dark) {{ html.setAttribute('data-theme', 'dark'); }}
      else {{ html.removeAttribute('data-theme'); }}
      var btn = document.getElementById('bb-theme-btn');
      if (btn) {{ btn.textContent = dark ? '☀ Light mode' : '☾ Dark mode'; }}
    }}
    function bbToggleTheme() {{
      var dark = html.getAttribute('data-theme') === 'dark';
      localStorage.setItem(THEME_KEY, dark ? 'light' : 'dark');
      applyTheme(!dark);
    }}
    window.bbToggleTheme = bbToggleTheme;
    var saved = localStorage.getItem(THEME_KEY);
    if (!saved) {{
      saved = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }}
    applyTheme(saved === 'dark');
  }})();
  </script>
</body>
</html>"""
