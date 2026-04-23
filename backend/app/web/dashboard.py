from __future__ import annotations

from collections import Counter
from html import escape
from typing import Iterable, Mapping, Sequence

from app.services.alert_log import AlertRecord
from app.services.alarm_store import AlarmStateRecord
from app.services.device_registry import RegisteredDevice
from app.services.user_store import UserRecord


def _render_count_list(items: Mapping[str, int]) -> str:
    if not items:
        return '<span class="muted">None yet</span>'
    parts = []
    for key, value in sorted(items.items()):
        parts.append(
            f'<span class="pill"><span class="pill-label">{escape(str(key))}</span>'
            f'<span class="pill-value">{int(value)}</span></span>'
        )
    return "".join(parts)


def _render_users(users: Sequence[UserRecord]) -> str:
    if not users:
        return '<div class="empty">No users yet.</div>'

    rows = []
    for user in users:
        active = "Active" if user.is_active else "Inactive"
        phone = escape(user.phone_e164) if user.phone_e164 else '<span class="muted">No phone</span>'
        rows.append(
            "<tr>"
            f"<td>{int(user.id)}</td>"
            f"<td>{escape(user.name)}</td>"
            f"<td>{escape(user.role)}</td>"
            f"<td>{phone}</td>"
            f"<td>{active}</td>"
            f"<td>{escape(user.created_at)}</td>"
            "</tr>"
        )
    return "".join(rows)


def _render_devices(devices: Sequence[RegisteredDevice]) -> str:
    if not devices:
        return '<div class="empty">No registered devices yet.</div>'

    rows = []
    for index, device in enumerate(devices, start=1):
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{escape(device.platform)}</td>"
            f"<td>{escape(device.push_provider)}</td>"
            f"<td><code>...{escape(device.token[-12:])}</code></td>"
            "</tr>"
        )
    return "".join(rows)


def _render_alerts(alerts: Sequence[AlertRecord]) -> str:
    if not alerts:
        return '<div class="empty">No alerts logged yet.</div>'

    rows = []
    for alert in alerts:
        triggered_by = (
            str(alert.triggered_by_user_id)
            if alert.triggered_by_user_id is not None
            else '<span class="muted">Unknown</span>'
        )
        rows.append(
            "<tr>"
            f"<td>{int(alert.id)}</td>"
            f"<td>{escape(alert.created_at)}</td>"
            f"<td>{escape(alert.message)}</td>"
            f"<td>{triggered_by}</td>"
            "</tr>"
        )
    return "".join(rows)


def _render_role_counts(users: Iterable[UserRecord]) -> Mapping[str, int]:
    return dict(Counter(user.role for user in users))


def render_dashboard(
    *,
    alerts: Sequence[AlertRecord],
    devices: Sequence[RegisteredDevice],
    users: Sequence[UserRecord],
    alarm_state: AlarmStateRecord,
    apns_configured: bool,
    twilio_configured: bool,
) -> str:
    role_counts = _render_role_counts(users)
    active_users = sum(1 for user in users if user.is_active)
    inactive_users = len(users) - active_users
    platform_counts = Counter(device.platform for device in devices)
    provider_counts = Counter(device.push_provider for device in devices)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BlueBird Alerts Admin</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f7fb;
      --surface: #ffffff;
      --surface-2: #f9fbff;
      --border: #d9e2ef;
      --text: #10243e;
      --muted: #64748b;
      --accent: #165dff;
      --danger: #d92d20;
      --success: #0f9f62;
      --shadow: 0 18px 40px rgba(16, 36, 62, 0.08);
    }}

    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}

    main {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 24px;
    }}

    .hero {{
      display: grid;
      gap: 18px;
      padding: 28px;
      background: linear-gradient(140deg, #ffffff 0%, #eef4ff 100%);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }}

    .hero-top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }}

    h1 {{
      margin: 0;
      font-size: 2rem;
      line-height: 1.1;
    }}

    .subtitle {{
      margin: 8px 0 0;
      color: var(--muted);
      max-width: 820px;
      line-height: 1.5;
    }}

    .status-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}

    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 14px;
      align-items: end;
    }}

    .field {{
      display: grid;
      gap: 6px;
      min-width: 220px;
      flex: 1 1 220px;
    }}

    .field label {{
      font-size: 0.9rem;
      color: var(--muted);
    }}

    .field input {{
      min-height: 42px;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0 12px;
      font: inherit;
      color: var(--text);
      background: var(--surface);
    }}

    .action-button {{
      min-height: 42px;
      border: 0;
      border-radius: 8px;
      padding: 0 18px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}

    .action-danger {{
      background: var(--danger);
      color: #fff;
    }}

    .action-safe {{
      background: var(--accent);
      color: #fff;
    }}

    .status-chip, .pill {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 34px;
      padding: 0 12px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--surface);
      font-size: 0.95rem;
    }}

    .status-chip strong {{
      font-weight: 700;
    }}

    .ok {{
      color: var(--success);
      border-color: rgba(15, 159, 98, 0.2);
      background: rgba(15, 159, 98, 0.08);
    }}

    .warn {{
      color: var(--danger);
      border-color: rgba(217, 45, 32, 0.2);
      background: rgba(217, 45, 32, 0.08);
    }}

    .grid {{
      display: grid;
      gap: 18px;
      margin-top: 22px;
      grid-template-columns: repeat(12, minmax(0, 1fr));
    }}

    .card {{
      grid-column: span 12;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }}

    .card-header {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 20px 14px;
      border-bottom: 1px solid var(--border);
      background: var(--surface-2);
    }}

    .card h2 {{
      margin: 0;
      font-size: 1.15rem;
    }}

    .card p {{
      margin: 6px 0 0;
      color: var(--muted);
      line-height: 1.45;
    }}

    .card-body {{
      padding: 18px 20px 20px;
    }}

    .metrics {{
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    }}

    .metric {{
      padding: 16px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface-2);
    }}

    .metric-label {{
      color: var(--muted);
      font-size: 0.92rem;
    }}

    .metric-value {{
      margin-top: 8px;
      font-size: 1.9rem;
      font-weight: 800;
      line-height: 1;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
    }}

    th, td {{
      padding: 12px 10px;
      text-align: left;
      vertical-align: top;
      border-top: 1px solid var(--border);
      font-size: 0.95rem;
    }}

    th {{
      color: var(--muted);
      font-weight: 700;
      border-top: 0;
      background: var(--surface-2);
    }}

    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.88rem;
    }}

    .muted {{
      color: var(--muted);
    }}

    .empty {{
      padding: 18px;
      border: 1px dashed var(--border);
      border-radius: 8px;
      color: var(--muted);
      background: var(--surface-2);
    }}

    .footnote {{
      margin-top: 12px;
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.5;
    }}

    .pill-label {{
      color: var(--muted);
      font-size: 0.88rem;
    }}

    .pill-value {{
      font-weight: 700;
    }}

    @media (min-width: 920px) {{
      .span-4 {{ grid-column: span 4; }}
      .span-5 {{ grid-column: span 5; }}
      .span-7 {{ grid-column: span 7; }}
      .span-8 {{ grid-column: span 8; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div class="hero-top">
        <div>
          <h1>BlueBird Alerts Admin</h1>
          <p class="subtitle">
            Local operator dashboard for monitoring alerts, registered devices, and user setup.
            This is the foundation for the next step: authenticated admin and standard-user accounts
            with alarm activation, location sharing, and admin-only alert resolution.
          </p>
        </div>
        <div class="status-row">
          <span class="status-chip {'ok' if apns_configured else 'warn'}"><strong>APNs</strong>{'Configured' if apns_configured else 'Not configured'}</span>
          <span class="status-chip {'ok' if twilio_configured else 'warn'}"><strong>SMS</strong>{'Configured' if twilio_configured else 'Not configured'}</span>
        </div>
      </div>
    </section>

    <section class="grid">
      <article class="card span-12">
        <div class="card-header">
          <div>
            <h2>Alarm State</h2>
            <p>Current school alarm state and quick local test controls.</p>
          </div>
        </div>
        <div class="card-body">
          <div class="status-row">
            <span class="status-chip {'warn' if alarm_state.is_active else 'ok'}">
              <strong>Alarm</strong>{'ACTIVE' if alarm_state.is_active else 'Clear'}
            </span>
            <span class="status-chip"><strong>Message</strong>{escape(alarm_state.message or 'No active alarm')}</span>
            <span class="status-chip"><strong>Activated</strong>{escape(alarm_state.activated_at or 'Never')}</span>
            <span class="status-chip"><strong>By User</strong>{escape(str(alarm_state.activated_by_user_id) if alarm_state.activated_by_user_id is not None else 'Unknown')}</span>
          </div>
          <div class="actions">
            <form method="post" action="/admin/alarm/activate" class="actions">
              <div class="field">
                <label for="message">Alarm message</label>
                <input id="message" name="message" value="{escape(alarm_state.message or 'Emergency alert. Please follow school procedures.')}" />
              </div>
              <div class="field">
                <label for="activate_user_id">Trigger user id (optional numeric id)</label>
                <input id="activate_user_id" name="user_id" inputmode="numeric" placeholder="Example: 2" />
              </div>
              <button class="action-button action-danger" type="submit">Activate Alarm</button>
            </form>
            <form method="post" action="/admin/alarm/deactivate" class="actions">
              <div class="field">
                <label for="deactivate_user_id">Admin user id (numeric)</label>
                <input id="deactivate_user_id" name="user_id" inputmode="numeric" placeholder="Example: 2" />
              </div>
              <button class="action-button action-safe" type="submit">Deactivate Alarm</button>
            </form>
          </div>
          <p class="footnote">
            For now these controls are local-operator tools. The backend already enforces that deactivation requires an active admin user id.
          </p>
        </div>
      </article>

      <article class="card span-12">
        <div class="card-header">
          <div>
            <h2>Create User</h2>
            <p>Create an admin or standard teacher account for local testing.</p>
          </div>
        </div>
        <div class="card-body">
          <form method="post" action="/admin/users/create" class="actions">
            <div class="field">
              <label for="user_name">Name</label>
              <input id="user_name" name="name" />
            </div>
            <div class="field">
              <label for="user_role">Role</label>
              <input id="user_role" name="role" value="teacher" />
            </div>
            <div class="field">
              <label for="user_phone">Phone (optional, E.164)</label>
              <input id="user_phone" name="phone_e164" placeholder="+15551234567" />
            </div>
            <button class="action-button action-safe" type="submit">Create User</button>
          </form>
          <p class="footnote">
            Use role <code>admin</code> for accounts that can deactivate alarms. Use role <code>teacher</code> for standard users who can trigger alarms.
          </p>
        </div>
      </article>

      <article class="card span-4">
        <div class="card-header">
          <div>
            <h2>Overview</h2>
            <p>Quick counts for operator awareness.</p>
          </div>
        </div>
        <div class="card-body metrics">
          <div class="metric">
            <div class="metric-label">Registered devices</div>
            <div class="metric-value">{len(devices)}</div>
          </div>
          <div class="metric">
            <div class="metric-label">Users</div>
            <div class="metric-value">{len(users)}</div>
          </div>
          <div class="metric">
            <div class="metric-label">Active users</div>
            <div class="metric-value">{active_users}</div>
          </div>
          <div class="metric">
            <div class="metric-label">Inactive users</div>
            <div class="metric-value">{inactive_users}</div>
          </div>
          <div class="metric">
            <div class="metric-label">Logged alerts</div>
            <div class="metric-value">{len(alerts)}</div>
          </div>
        </div>
      </article>

      <article class="card span-8">
        <div class="card-header">
          <div>
            <h2>Breakdown</h2>
            <p>Current registrations and user roles.</p>
          </div>
        </div>
        <div class="card-body">
          <p><strong>Platforms</strong></p>
          <div class="status-row">{_render_count_list(platform_counts)}</div>
          <p><strong>Push providers</strong></p>
          <div class="status-row">{_render_count_list(provider_counts)}</div>
          <p><strong>User roles</strong></p>
          <div class="status-row">{_render_count_list(role_counts)}</div>
        </div>
      </article>

      <article class="card span-7">
        <div class="card-header">
          <div>
            <h2>Recent Alerts</h2>
            <p>Most recent alert records from the append-only audit log.</p>
          </div>
        </div>
        <div class="card-body">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Created</th>
                <th>Message</th>
                <th>Triggered By</th>
              </tr>
            </thead>
            <tbody>{_render_alerts(alerts)}</tbody>
          </table>
        </div>
      </article>

      <article class="card span-5">
        <div class="card-header">
          <div>
            <h2>Registered Devices</h2>
            <p>Devices currently eligible for outbound notification delivery.</p>
          </div>
        </div>
        <div class="card-body">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Platform</th>
                <th>Provider</th>
                <th>Token</th>
              </tr>
            </thead>
            <tbody>{_render_devices(devices)}</tbody>
          </table>
        </div>
      </article>

      <article class="card span-12">
        <div class="card-header">
          <div>
            <h2>Users</h2>
            <p>
              Current user records. This is where we will hang real login, role checks,
              and admin-only alarm resolution next.
            </p>
          </div>
        </div>
        <div class="card-body">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Role</th>
                <th>Phone</th>
                <th>Status</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>{_render_users(users)}</tbody>
          </table>
          <p class="footnote">
            Planned next step: replace the shared API key with real per-user authentication,
            then enforce two roles. Standard users will be able to activate an alarm, share location,
            and receive notifications. Admin users will also be able to acknowledge and resolve an active alert.
          </p>
        </div>
      </article>
    </section>
  </main>
</body>
</html>"""
