from __future__ import annotations

from collections import Counter
from html import escape
from typing import Mapping, Optional, Sequence

from app.services.alert_log import AlertRecord
from app.services.alarm_store import AlarmStateRecord
from app.services.device_registry import RegisteredDevice
from app.services.quiet_period_store import QuietPeriodRecord
from app.services.report_store import BroadcastUpdateRecord, ReportRecord
from app.services.school_registry import SchoolRecord
from app.services.user_store import UserRecord


def _base_styles() -> str:
    return """
    :root {
      --bg: #f0f4f8;
      --bg-deep: #dce8f4;
      --panel: rgba(255, 255, 255, 0.88);
      --panel-strong: rgba(255, 255, 255, 0.97);
      --border: rgba(15, 23, 42, 0.08);
      --text: #0f172a;
      --muted: #64748b;
      --accent: #2563eb;
      --accent-strong: #3b82f6;
      --accent-soft: rgba(37, 99, 235, 0.16);
      --success: #16a34a;
      --success-soft: rgba(22, 163, 74, 0.12);
      --danger: #dc2626;
      --danger-soft: rgba(220, 38, 38, 0.12);
      --shadow: 0 12px 36px rgba(15, 23, 42, 0.10);
      --radius: 24px;
      --radius-soft: 18px;
      --headline: "Avenir Next", "Segoe UI Variable Display", "SF Pro Display", "Trebuchet MS", sans-serif;
      --body: "Avenir Next", "Segoe UI Variable Text", "SF Pro Text", "Helvetica Neue", sans-serif;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; color: var(--text); font-family: var(--body); }
    body {
      min-height: 100vh;
      background:
        radial-gradient(circle at top left, rgba(59, 130, 246, 0.12), transparent 24%),
        radial-gradient(circle at 80% 10%, rgba(37, 99, 235, 0.08), transparent 18%),
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
    .hero-card, .panel, .login-panel {
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
        linear-gradient(180deg, rgba(255,255,255,0.98), rgba(248,251,255,0.92)),
        linear-gradient(140deg, rgba(37, 99, 235, 0.06), rgba(59, 130, 246, 0.02));
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
    .button-danger { background: linear-gradient(180deg, #ef4444, var(--danger)); color: #fff; }
    .button-danger-outline {
      background: rgba(254, 242, 242, 0.98);
      color: var(--danger);
      border: 1px solid rgba(220, 38, 38, 0.18);
    }
    .flash {
      padding: 14px 16px;
      border-radius: 16px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.95);
      color: var(--text);
    }
    .flash.error { border-color: rgba(220,38,38,0.2); background: rgba(254,242,242,0.96); color: #991b1b; }
    .flash.success { border-color: rgba(22,163,74,0.2); background: rgba(240,253,244,0.96); color: #166534; }
    .app-shell {
      display: grid;
      grid-template-columns: 290px minmax(0, 1fr);
      gap: 18px;
      align-items: start;
    }
    .sidebar, .content-stack { display: grid; gap: 18px; }
    .sidebar {
      position: sticky;
      top: 24px;
    }
    .brand-card, .panel { padding: 22px; }
    .nav-list { display: grid; gap: 10px; margin-top: 16px; }
    .nav-item {
      display: block;
      padding: 12px 14px;
      border-radius: 14px;
      color: var(--text);
      background: rgba(255,255,255,0.72);
      border: 1px solid var(--border);
    }
    .hero-band {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
    }
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
        rows.append(
            f"<tr><td>{escape(item.created_at)}</td><td>{escape(str(item.admin_user_id) if item.admin_user_id is not None else 'admin')}</td><td>{escape(item.message)}</td></tr>"
        )
    return "".join(rows)


def _render_quiet_period_rows(records: Sequence[QuietPeriodRecord], users: Sequence[UserRecord]) -> str:
    if not records:
        return '<tr><td colspan="5" class="mini-copy">No quiet periods yet.</td></tr>'
    user_names = {user.id: user.name for user in users}
    rows = []
    for item in records:
        rows.append(
            f"<tr><td>{escape(user_names.get(item.user_id, f'User #{item.user_id}'))}</td><td>{escape(item.status)}</td><td>{escape(item.reason or '—')}</td><td>{escape(item.requested_at)}</td><td>{escape(item.expires_at or '—')}</td></tr>"
        )
    return "".join(rows)


def render_login_page(
    *,
    message: Optional[str] = None,
    error: Optional[str] = None,
    setup_mode: bool,
    school_name: str = "School",
    school_slug: str = "default",
) -> str:
    heading = "Create the first BlueBird admin" if setup_mode else "Sign in to BlueBird Admin"
    button = "Create admin account" if setup_mode else "Sign in"
    action = "/admin/setup" if setup_mode else "/admin/login"
    helper = (
        "This first account becomes the dashboard operator account. After that, you can create and edit the rest of the school users from inside the portal."
        if setup_mode
        else "Use your admin credentials to manage users, alarms, devices, and the audit trail."
    )
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
  <style>{_base_styles()}</style>
</head>
<body>
  <main class="login-shell">
    <section class="hero-card">
      <div class="stack">
        <p class="eyebrow">School Safety Command Deck</p>
        <h1>BlueBird Alerts admin portal</h1>
        <p class="hero-copy">
          A calm command surface for alarm activation, account management, recent alert review, and device readiness.
          This version reuses the same visual language as your accounting app, just tuned for emergency operations instead of finance.
        </p>
        <p class="mini-copy">School: <strong>{escape(school_name)}</strong> ({escape(school_slug)})</p>
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
      {_render_flash(message, "success")}
      {_render_flash(error, "error")}
      <form method="post" action="{action}" class="stack">
        {extra_fields}
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
  <style>{_base_styles()}</style>
</head>
<body>
  <main class="login-shell">
    <section class="hero-card">
      <div class="stack">
        <p class="eyebrow">Platform Control</p>
        <h1>BlueBird super admin</h1>
        <p class="hero-copy">Provision schools, hand out school-specific admin URLs, and keep the multi-school platform organized from one place.</p>
      </div>
      <div class="hero-metrics">
        <span class="metric-pill"><strong>School setup</strong> centralized</span>
        <span class="metric-pill"><strong>Tenant routing</strong> subdomain based</span>
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


def render_super_admin_page(
    *,
    base_domain: str,
    schools: Sequence[SchoolRecord],
    git_pull_configured: bool,
    cloudflare_dns_configured: bool,
    flash_message: Optional[str] = None,
    flash_error: Optional[str] = None,
) -> str:
    rows = "".join(
        f"<tr><td>{escape(item.name)}</td><td><code>{escape(item.slug)}</code></td><td><a href=\"https://{escape(item.slug)}.{escape(base_domain)}/admin\" target=\"_blank\">{escape(item.slug)}.{escape(base_domain)}</a></td><td>{'Active' if item.is_active else 'Inactive'}</td></tr>"
        for item in schools
    ) or '<tr><td colspan="4" class="mini-copy">No schools yet.</td></tr>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BlueBird Super Admin</title>
  <style>{_base_styles()}</style>
</head>
<body>
  <main class="page-shell">
    <div class="app-shell">
      <aside class="sidebar">
        <section class="brand-card hero-card">
          <div class="stack">
            <p class="eyebrow">BlueBird Platform</p>
            <h2>Super admin</h2>
            <p class="hero-copy">Manage school provisioning across <strong>{escape(base_domain)}</strong>.</p>
          </div>
          <nav class="nav-list">
            <a class="nav-item" href="#schools">Schools</a>
            <a class="nav-item" href="#create-school">Create school</a>
            <a class="nav-item" href="/super-admin/change-password">Change password</a>
            <a class="nav-item" href="#server-tools">Server tools</a>
          </nav>
          <div class="button-row">
            <a class="button button-secondary" href="/super-admin/change-password">Change Password</a>
          </div>
          <form method="post" action="/super-admin/logout">
            <button class="button button-secondary" type="submit">Log out</button>
          </form>
        </section>
      </aside>
      <section class="content-stack">
        {_render_flash(flash_message, "success")}
        {_render_flash(flash_error, "error")}
        <section class="panel" id="schools">
          <div class="panel-header hero-band">
            <div>
              <p class="eyebrow">Tenant Registry</p>
              <h1>Schools</h1>
              <p class="hero-copy">Each school gets its own subdomain and isolated database. School admins still manage their own users from their tenant dashboard.</p>
            </div>
            <div class="status-row">
              <span class="status-pill ok"><strong>Base domain</strong>{escape(base_domain)}</span>
              <span class="status-pill"><strong>Schools</strong>{len(schools)}</span>
              <span class="status-pill {'ok' if cloudflare_dns_configured else 'danger'}"><strong>Cloudflare DNS</strong>{'configured' if cloudflare_dns_configured else 'not configured'}</span>
              <span class="status-pill {'ok' if git_pull_configured else 'danger'}"><strong>Git pull</strong>{'configured' if git_pull_configured else 'not configured'}</span>
            </div>
          </div>
          <table>
            <thead>
              <tr><th>Name</th><th>Slug</th><th>Admin URL</th><th>Status</th></tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
        </section>
        <section class="panel" id="create-school">
          <div class="panel-header">
            <div>
              <p class="eyebrow">Provisioning</p>
              <h2>Create a new school</h2>
              <p class="card-copy">This creates the school registry entry and, when configured, also creates the Cloudflare DNS record for that school's subdomain. The first school admin is still created from that school's own admin portal.</p>
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
            </div>
            <div class="button-row">
              <button class="button button-primary" type="submit">Create school</button>
            </div>
          </form>
        </section>
        <section class="panel" id="server-tools">
          <div class="panel-header">
            <div>
              <p class="eyebrow">Server Tools</p>
              <h2>Update backend from Git</h2>
              <p class="card-copy">Pull the latest <code>main</code> branch on the server without opening a terminal. This only runs if a server-side pull command is configured.</p>
            </div>
          </div>
          <p class="mini-copy" style="margin-bottom:14px;">
            {'Configured and ready to run.' if git_pull_configured else 'Set <code>SERVER_GIT_PULL_COMMAND</code> in the backend environment to enable this action.'}
          </p>
          <form method="post" action="/super-admin/server/pull-latest"
                onsubmit="return confirm('Pull the latest main branch on the server now?');">
            <div class="button-row">
              <button class="button button-primary" type="submit" {'disabled' if not git_pull_configured else ''}>Pull Latest Main</button>
            </div>
          </form>
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


def _render_alert_rows(alerts: Sequence[AlertRecord]) -> str:
    if not alerts:
        return '<tr><td colspan="4" class="mini-copy">No alerts logged yet.</td></tr>'
    rows = []
    for alert in alerts:
        rows.append(
            "<tr>"
            f"<td>{alert.id}</td>"
            f"<td>{escape(alert.created_at)}</td>"
            f"<td>{escape(alert.message)}</td>"
            f"<td>{escape(str(alert.triggered_by_user_id) if alert.triggered_by_user_id is not None else 'Unknown')}</td>"
            "</tr>"
        )
    return "".join(rows)


def _render_device_rows(devices: Sequence[RegisteredDevice], users: Sequence[UserRecord]) -> str:
    if not devices:
        return '<tr><td colspan="8" class="mini-copy">No devices registered yet.</td></tr>'
    user_lookup = {user.id: user for user in users}
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
            f"<form method=\"post\" action=\"/admin/devices/delete\" onsubmit=\"return confirm('Delete this registered device token?');\">"
            f"<input type=\"hidden\" name=\"token\" value=\"{escape(device.token)}\" />"
            f"<input type=\"hidden\" name=\"push_provider\" value=\"{escape(device.push_provider)}\" />"
            "<button class=\"button button-danger-outline\" type=\"submit\">Delete</button>"
            "</form>"
            "</td>"
            "</tr>"
        )
    return "".join(rows)


def _render_user_cards(users: Sequence[UserRecord]) -> str:
    if not users:
        return '<div class="mini-copy">No users yet.</div>'
    cards = []
    for user in users:
        checked_active = "checked" if user.is_active else ""
        checked_clear_login = ""
        login_name = escape(user.login_name or "")
        phone = escape(user.phone_e164 or "")
        last_login = escape(user.last_login_at or "Never")
        cards.append(
            f"""
            <article class="user-card">
              <form method="post" action="/admin/users/{user.id}/update" class="stack">
                <div class="panel-header">
                  <div>
                    <h3>{escape(user.name)}</h3>
                    <p class="mini-copy">User #{user.id} • created {escape(user.created_at)}</p>
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
                      <option value="admin" {'selected' if user.role == 'admin' else ''}>admin</option>
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
              <form method="post" action="/admin/users/{user.id}/delete" onsubmit="return confirm('Delete {escape(user.name)}? This cannot be undone.');">
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
  <style>{_base_styles()}</style>
</head>
<body>
  <main class="login-shell">
    <section class="hero-card">
      <div class="stack">
        <p class="eyebrow">{escape(eyebrow)}</p>
        <h1>{escape(heading)}</h1>
        <p class="hero-copy">{escape(helper)}</p>
      </div>
    </section>
    <section class="login-panel">
      <div class="stack">
        <p class="eyebrow">Welcome, {escape(user_name)}</p>
        <h2>Set a new password</h2>
      </div>
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
    current_user: UserRecord,
    users: Sequence[UserRecord],
    alerts: Sequence[AlertRecord],
    devices: Sequence[RegisteredDevice],
    alarm_state: AlarmStateRecord,
    reports: Sequence[ReportRecord],
    broadcasts: Sequence[BroadcastUpdateRecord],
    quiet_periods: Sequence[QuietPeriodRecord],
    apns_configured: bool,
    twilio_configured: bool,
    server_info: Mapping[str, str],
    flash_message: Optional[str] = None,
    flash_error: Optional[str] = None,
) -> str:
    role_counts = Counter(user.role for user in users)
    platform_counts = Counter(device.platform for device in devices)
    provider_counts = Counter(device.push_provider for device in devices)
    active_users = sum(1 for user in users if user.is_active)
    login_enabled = sum(1 for user in users if user.can_login)
    alarm_status_class = "danger" if alarm_state.is_active else "ok"
    alarm_status_label = "ALARM ACTIVE" if alarm_state.is_active else "Alarm clear"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BlueBird Admin</title>
  <style>{_base_styles()}</style>
</head>
<body>
  <main class="page-shell">
    <div class="app-shell">
      <aside class="sidebar">
        <section class="brand-card hero-card">
          <div class="stack">
            <p class="eyebrow">BlueBird Alerts</p>
            <h2>Safety operations</h2>
            <p class="hero-copy">Signed in as <strong>{escape(current_user.name)}</strong> ({escape(current_user.login_name or 'admin')}).</p>
            <p class="mini-copy">School: <strong>{escape(school_name)}</strong> ({escape(school_slug)})</p>
          </div>
          <nav class="nav-list">
            <a class="nav-item" href="#overview">Overview</a>
            <a class="nav-item" href="#users">Users</a>
            <a class="nav-item" href="#alarm">Alarm</a>
            <a class="nav-item" href="#reports">Reports</a>
            <a class="nav-item" href="#quiet-periods">Quiet Periods</a>
            <a class="nav-item" href="#alerts">Alert log</a>
            <a class="nav-item" href="#devices">Devices</a>
            <a class="nav-item" href="#server">Server</a>
          </nav>
          <form method="post" action="/admin/logout">
            <button class="button button-secondary" type="submit">Log out</button>
          </form>
        </section>
      </aside>

      <section class="content-stack">
        {_render_flash(flash_message, "success")}
        {_render_flash(flash_error, "error")}

        <section class="panel" id="overview">
          <div class="panel-header hero-band">
            <div>
              <p class="eyebrow">Command Deck</p>
              <h1>Admin dashboard</h1>
              <p class="hero-copy">Manage users, see device readiness, review alerts, and control the active alarm state for <strong>{escape(school_name)}</strong> from one place.</p>
            </div>
            <div class="status-row">
              <span class="status-pill {alarm_status_class}"><strong>{alarm_status_label}</strong>{escape(alarm_state.message or 'No active alarm')}</span>
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
            <article class="metric-card"><div class="meta">Quiet periods</div><div class="metric-value">{len(quiet_periods)}</div></article>
          </div>
          <div class="status-row" style="margin-top:16px;">
            {_count_list(role_counts)}
            {_count_list(platform_counts)}
            {_count_list(provider_counts)}
          </div>
        </section>

        <section class="grid">
          <section class="panel span-5" id="alarm">
            <div class="panel-header">
              <div>
                <p class="eyebrow">Alarm Control</p>
                <h2>Activate or clear the alarm</h2>
                <p class="card-copy">Dashboard actions are attributed to your logged-in admin account automatically.</p>
              </div>
            </div>
            <form method="post" action="/admin/alarm/activate" class="stack">
              <div class="field">
                <label for="alarm_message">Alarm message</label>
                <textarea id="alarm_message" name="message">{escape(alarm_state.message or 'Emergency alert. Please follow school procedures.')}</textarea>
              </div>
              <div class="button-row">
                <button class="button button-danger" type="submit">Activate alarm</button>
              </div>
            </form>
            <form method="post" action="/admin/alarm/deactivate" class="stack" style="margin-top:14px;">
              <div class="button-row">
                <button class="button button-secondary" type="submit">Deactivate alarm</button>
              </div>
            </form>
            <p class="mini-copy">Activated at: {escape(alarm_state.activated_at or 'Never')} • Deactivated at: {escape(alarm_state.deactivated_at or 'Not yet')}</p>
          </section>

          <section class="panel span-7" id="users">
            <div class="panel-header">
              <div>
                <p class="eyebrow">Accounts</p>
                <h2>Create a user</h2>
                <p class="card-copy">Create standard users or new admins. Add a username and password if the account should be able to sign in.</p>
              </div>
            </div>
            <form method="post" action="/admin/users/create" class="stack">
              <div class="form-grid">
                <div class="field">
                  <label>Name</label>
                  <input name="name" />
                </div>
                <div class="field">
                  <label>Role</label>
                  <select name="role">
                    <option value="teacher">standard / teacher</option>
                    <option value="admin">admin</option>
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

          <section class="panel span-12">
            <div class="panel-header">
              <div>
                <p class="eyebrow">Account Editor</p>
                <h2>Edit existing users</h2>
                <p class="card-copy">Update role, phone, active status, and login credentials without leaving the dashboard.</p>
              </div>
            </div>
            <div class="user-grid">
              {_render_user_cards(users)}
            </div>
          </section>

          <section class="panel span-5" id="reports">
            <div class="panel-header">
              <div>
                <p class="eyebrow">Admin Broadcasts</p>
                <h2>Send official updates</h2>
                <p class="card-copy">Post short verified updates that all signed-in mobile users will see on their app status screen.</p>
              </div>
            </div>
            <form method="post" action="/admin/broadcasts/create" class="stack">
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

          <section class="panel span-7">
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

          <section class="panel span-12" id="quiet-periods">
            <div class="panel-header">
              <div>
                <p class="eyebrow">Quiet Periods</p>
                <h2>Grant a 24-hour notification pause</h2>
                <p class="card-copy">Use this for approved temporary exceptions like weddings or funerals. Quiet periods expire automatically after 24 hours.</p>
              </div>
            </div>
            <form method="post" action="/admin/quiet-periods/grant" class="stack">
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
                <tr><th>User</th><th>Status</th><th>Reason</th><th>Requested</th><th>Expires</th></tr>
              </thead>
              <tbody>
                {_render_quiet_period_rows(quiet_periods, users)}
              </tbody>
            </table>
          </section>

          <section class="panel span-7" id="alerts">
            <div class="panel-header">
              <div>
                <p class="eyebrow">Alert Log</p>
                <h2>Recent alerts</h2>
              </div>
            </div>
            <table>
              <thead>
                <tr><th>ID</th><th>Created</th><th>Message</th><th>Triggered by</th></tr>
              </thead>
              <tbody>
                {_render_alert_rows(alerts)}
              </tbody>
            </table>
          </section>

          <section class="panel span-5" id="devices">
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
                {_render_device_rows(devices, users)}
              </tbody>
            </table>
          </section>

          <section class="panel span-12" id="server">
            <div class="panel-header">
              <div>
                <p class="eyebrow">Server Management</p>
                <h2>Backend service</h2>
                <p class="card-copy">Current process info and service controls. Restart applies the latest deployed code.</p>
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
              {'Uses <code>SERVER_RESTART_COMMAND</code> env var.' if server_info.get("restart_configured") == "yes" else 'No <code>SERVER_RESTART_COMMAND</code> set — will self-restart the process.'}
            </p>
            <form method="post" action="/admin/server/restart"
                  onsubmit="return confirm('Restart the backend service now? The dashboard will be unavailable for a few seconds.');">
              <div class="button-row">
                <button class="button button-danger" type="submit">Restart service</button>
              </div>
            </form>
          </section>
        </section>
      </section>
    </div>
  </main>
</body>
</html>"""
