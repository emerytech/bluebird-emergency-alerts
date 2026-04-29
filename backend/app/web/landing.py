"""
BlueBird Alerts — public marketing landing page + district/school login portal.

render_landing_page() → GET /
render_login_portal()  → GET /login

Both are self-contained HTMLResponses; CSS is inline; logo from /static/.
"""
from __future__ import annotations

LOGO = "/static/bluebird-alert-logo.png"
DEMO_EMAIL = "taylor@emerytechsolutions.com"


def render_landing_page() -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>BlueBird Alerts — Emergency Alert System for Schools</title>
  <meta name="description" content="Fast, simple emergency alerts for schools and districts. Push notifications reach every registered device in seconds." />
  <meta property="og:title" content="BlueBird Alerts" />
  <meta property="og:description" content="Fast, simple emergency alerts for schools and districts." />
  <meta property="og:image" content="{LOGO}" />
  <link rel="icon" type="image/png" href="{LOGO}" />
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --blue:      #1b5fe4;
      --blue-dark: #1048c0;
      --blue-soft: #eff6ff;
      --dark:      #0f172a;
      --text:      #10203f;
      --muted:     #5d7398;
      --border:    rgba(18,52,120,.10);
      --white:     #ffffff;
      --radius:    12px;
    }}
    html {{ scroll-behavior: smooth; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
      color: var(--text);
      background: var(--white);
      line-height: 1.6;
    }}

    /* ── NAV ───────────────────────────────────────────────────────────── */
    .nav {{
      position: sticky; top: 0; z-index: 100;
      background: rgba(255,255,255,.92);
      backdrop-filter: saturate(180%) blur(12px);
      border-bottom: 1px solid var(--border);
      padding: 0 24px;
    }}
    .nav-inner {{
      max-width: 1100px; margin: 0 auto;
      display: flex; align-items: center; justify-content: space-between;
      height: 60px;
    }}
    .nav-logo {{
      display: flex; align-items: center; gap: 10px;
      text-decoration: none; font-weight: 700; font-size: 1.05rem; color: var(--text);
    }}
    .nav-logo img {{ width: 32px; height: 32px; object-fit: contain; }}
    .nav-actions {{ display: flex; gap: 10px; align-items: center; }}
    .btn {{
      display: inline-flex; align-items: center; justify-content: center;
      font-size: 0.88rem; font-weight: 600; border-radius: 8px;
      padding: 9px 20px; cursor: pointer; text-decoration: none;
      transition: opacity .15s, transform .1s;
      border: none; white-space: nowrap;
    }}
    .btn:hover {{ opacity: .88; transform: translateY(-1px); }}
    .btn-primary {{ background: var(--blue); color: #fff; }}
    .btn-secondary {{
      background: transparent; color: var(--blue);
      border: 1.5px solid var(--blue);
    }}
    .btn-lg {{ font-size: 1rem; padding: 13px 28px; border-radius: 10px; }}
    .btn-ghost {{
      background: rgba(255,255,255,.15); color: #fff;
      border: 1.5px solid rgba(255,255,255,.4);
    }}
    .btn-ghost:hover {{ background: rgba(255,255,255,.25); }}

    /* ── HERO ──────────────────────────────────────────────────────────── */
    .hero {{
      background: linear-gradient(135deg, #0f172a 0%, #1b3a7a 60%, #1b5fe4 100%);
      color: #fff;
      padding: 96px 24px 80px;
      text-align: center;
    }}
    .hero-eyebrow {{
      display: inline-block;
      background: rgba(255,255,255,.12);
      border: 1px solid rgba(255,255,255,.22);
      border-radius: 100px;
      padding: 5px 16px;
      font-size: 0.78rem; font-weight: 700;
      text-transform: uppercase; letter-spacing: .08em;
      color: #93c5fd; margin-bottom: 24px;
    }}
    .hero h1 {{
      font-size: clamp(2.2rem, 5vw, 3.6rem);
      font-weight: 800; line-height: 1.15;
      letter-spacing: -.02em;
      margin-bottom: 20px;
    }}
    .hero h1 span {{ color: #60a5fa; }}
    .hero-sub {{
      font-size: clamp(1rem, 2vw, 1.2rem);
      color: #bfdbfe; max-width: 560px;
      margin: 0 auto 36px;
    }}
    .hero-actions {{
      display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;
      align-items: flex-start;
    }}
    .hero-login-wrap {{ display: flex; flex-direction: column; align-items: center; gap: 7px; }}
    .hero-login-hint {{
      font-size: 0.73rem; color: rgba(255,255,255,.52);
      letter-spacing: .02em;
    }}
    .hero-stats {{
      display: flex; gap: 40px; justify-content: center; flex-wrap: wrap;
      margin-top: 60px; padding-top: 40px;
      border-top: 1px solid rgba(255,255,255,.12);
    }}
    .hero-stat-num {{
      font-size: 2rem; font-weight: 800; color: #60a5fa;
      display: block; line-height: 1;
    }}
    .hero-stat-lbl {{ font-size: 0.82rem; color: #93c5fd; margin-top: 4px; }}

    /* ── SECTION WRAPPER ──────────────────────────────────────────────── */
    .section {{ padding: 80px 24px; }}
    .section-inner {{ max-width: 1100px; margin: 0 auto; }}
    .section-alt {{ background: var(--blue-soft); }}
    .section-dark {{ background: var(--dark); color: #fff; }}
    .section-tag {{
      display: inline-block;
      font-size: 0.72rem; font-weight: 700;
      text-transform: uppercase; letter-spacing: .1em;
      color: var(--blue); margin-bottom: 10px;
    }}
    .section-dark .section-tag {{ color: #60a5fa; }}
    .section-h {{ font-size: clamp(1.6rem, 3vw, 2.2rem); font-weight: 800; margin-bottom: 14px; }}
    .section-sub {{ font-size: 1rem; color: var(--muted); max-width: 540px; }}
    .section-dark .section-sub {{ color: #94a3b8; }}
    .section-header {{ margin-bottom: 48px; }}

    /* ── PROBLEM ──────────────────────────────────────────────────────── */
    .problem-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 24px;
    }}
    .problem-card {{
      background: #fff;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 28px 24px;
      box-shadow: 0 2px 12px rgba(0,0,0,.04);
    }}
    .problem-icon {{ font-size: 2rem; margin-bottom: 14px; display: block; }}
    .problem-card h3 {{ font-size: 1.05rem; font-weight: 700; margin-bottom: 8px; }}
    .problem-card p {{ font-size: 0.9rem; color: var(--muted); }}

    /* ── FEATURES ─────────────────────────────────────────────────────── */
    .features-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 20px;
    }}
    .feature-card {{
      background: #fff;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 24px 22px;
      display: flex; gap: 16px;
      box-shadow: 0 2px 10px rgba(0,0,0,.04);
      transition: box-shadow .2s, transform .2s;
    }}
    .feature-card:hover {{
      box-shadow: 0 8px 28px rgba(27,95,228,.1);
      transform: translateY(-2px);
    }}
    .feature-icon {{
      width: 44px; height: 44px; border-radius: 10px;
      background: var(--blue-soft); display: grid;
      place-items: center; font-size: 1.3rem; flex-shrink: 0;
    }}
    .feature-card h3 {{ font-size: 0.97rem; font-weight: 700; margin-bottom: 5px; }}
    .feature-card p {{ font-size: 0.84rem; color: var(--muted); line-height: 1.5; }}

    /* ── HOW IT WORKS ─────────────────────────────────────────────────── */
    .steps {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 0;
      position: relative;
    }}
    .step {{
      text-align: center; padding: 28px 24px;
      position: relative;
    }}
    .step-num {{
      width: 48px; height: 48px; border-radius: 50%;
      background: var(--blue); color: #fff;
      font-size: 1.1rem; font-weight: 800;
      display: grid; place-items: center;
      margin: 0 auto 16px;
    }}
    .step h3 {{ font-size: 1rem; font-weight: 700; margin-bottom: 8px; }}
    .step p {{ font-size: 0.87rem; color: var(--muted); }}

    /* ── DISTRICT SECTION ─────────────────────────────────────────────── */
    .district-layout {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 60px;
      align-items: center;
    }}
    .district-list {{ list-style: none; display: flex; flex-direction: column; gap: 16px; }}
    .district-list li {{
      display: flex; gap: 14px; align-items: flex-start;
    }}
    .district-check {{
      width: 24px; height: 24px; border-radius: 50%;
      background: var(--blue); color: #fff;
      font-size: 0.75rem; font-weight: 700;
      display: grid; place-items: center; flex-shrink: 0; margin-top: 2px;
    }}
    .district-list h4 {{ font-size: 0.97rem; font-weight: 700; margin-bottom: 3px; }}
    .district-list p {{ font-size: 0.85rem; color: var(--muted); }}
    .district-visual {{
      background: linear-gradient(135deg, #1b3a7a, #1b5fe4);
      border-radius: 16px; padding: 32px;
      color: #fff;
    }}
    .school-card-demo {{
      background: rgba(255,255,255,.12);
      border: 1px solid rgba(255,255,255,.2);
      border-radius: 10px; padding: 16px 20px;
      margin-bottom: 12px; display: flex;
      justify-content: space-between; align-items: center;
    }}
    .school-card-demo:last-child {{ margin-bottom: 0; }}
    .school-name {{ font-weight: 700; font-size: 0.9rem; }}
    .school-meta {{ font-size: 0.75rem; color: #93c5fd; margin-top: 2px; }}
    .school-pill {{
      background: rgba(16,185,129,.2); color: #6ee7b7;
      border: 1px solid rgba(16,185,129,.3);
      font-size: 0.7rem; font-weight: 700;
      padding: 3px 10px; border-radius: 100px;
    }}
    .school-pill.warn {{
      background: rgba(245,158,11,.15); color: #fbbf24;
      border-color: rgba(245,158,11,.3);
    }}

    /* ── SAFETY ───────────────────────────────────────────────────────── */
    .safety-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 20px;
    }}
    .safety-card {{
      border: 1px solid rgba(255,255,255,.1);
      border-radius: var(--radius); padding: 24px 22px;
      background: rgba(255,255,255,.05);
    }}
    .safety-card h3 {{ font-size: 0.97rem; font-weight: 700; color: #fff; margin-bottom: 8px; }}
    .safety-card p {{ font-size: 0.85rem; color: #94a3b8; line-height: 1.55; }}
    .safety-icon {{ font-size: 1.6rem; margin-bottom: 12px; display: block; }}

    /* ── CTA ──────────────────────────────────────────────────────────── */
    .cta-section {{
      background: linear-gradient(135deg, #1b5fe4, #1048c0);
      padding: 80px 24px;
      text-align: center;
      color: #fff;
    }}
    .cta-section h2 {{
      font-size: clamp(1.6rem, 3vw, 2.3rem);
      font-weight: 800; margin-bottom: 14px;
    }}
    .cta-section p {{
      color: #bfdbfe; font-size: 1rem; margin-bottom: 32px;
    }}

    /* ── FOOTER ───────────────────────────────────────────────────────── */
    footer {{
      background: var(--dark); color: #94a3b8;
      padding: 40px 24px;
      text-align: center;
    }}
    footer a {{ color: #60a5fa; text-decoration: none; }}
    footer a:hover {{ text-decoration: underline; }}
    .footer-inner {{ max-width: 700px; margin: 0 auto; }}
    .footer-logo {{
      display: flex; align-items: center; gap: 10px;
      justify-content: center; margin-bottom: 16px;
    }}
    .footer-logo img {{ width: 28px; height: 28px; object-fit: contain; }}
    .footer-logo span {{ font-weight: 700; font-size: 1rem; color: #fff; }}
    .footer-links {{
      display: flex; gap: 20px; justify-content: center;
      flex-wrap: wrap; margin: 16px 0;
    }}
    .footer-copy {{ font-size: 0.82rem; color: #475569; }}

    /* ── RESPONSIVE ───────────────────────────────────────────────────── */
    @media (max-width: 768px) {{
      .district-layout {{ grid-template-columns: 1fr; gap: 32px; }}
      .district-visual {{ display: none; }}
      .nav-actions .btn-secondary {{ display: none; }}
      .hero {{ padding: 64px 20px 56px; }}
      .hero-stats {{ gap: 24px; }}
      .section {{ padding: 56px 20px; }}
    }}

    @media (prefers-color-scheme: dark) {{
      body {{ background: #0f172a; color: #e2e8f0; }}
      .nav {{ background: rgba(15,23,42,.92); border-bottom-color: rgba(255,255,255,.08); }}
      .nav-logo {{ color: #e2e8f0; }}
      .section-alt {{ background: #1e293b; }}
      .problem-card, .feature-card {{
        background: #1e293b;
        border-color: rgba(255,255,255,.08);
      }}
      .problem-card p, .feature-card p, .step p {{ color: #94a3b8; }}
      .feature-icon {{ background: rgba(27,95,228,.2); }}
      .section-sub {{ color: #94a3b8; }}
      .btn-secondary {{ border-color: #60a5fa; color: #60a5fa; }}
    }}
  </style>
</head>
<body>

<!-- ── NAV ──────────────────────────────────────────────────────────────── -->
<nav class="nav">
  <div class="nav-inner">
    <a href="/" class="nav-logo">
      <img src="{LOGO}" alt="BlueBird Alerts logo" />
      BlueBird Alerts
    </a>
    <div class="nav-actions">
      <a href="mailto:{DEMO_EMAIL}?subject=BlueBird%20Alerts%20Demo%20Request" class="btn btn-secondary">Request Demo</a>
      <a href="/login" class="btn btn-primary">Admin Login</a>
    </div>
  </div>
</nav>

<!-- ── HERO ─────────────────────────────────────────────────────────────── -->
<section class="hero">
  <div class="hero-eyebrow">School Emergency Alerting</div>
  <h1>Fast, simple emergency alerts<br /><span>for every school in your district.</span></h1>
  <p class="hero-sub">BlueBird Alerts puts instant push notifications and real-time acknowledgement tracking in the hands of every administrator — no complex setup, no delays.</p>
  <div class="hero-actions">
    <a href="mailto:{DEMO_EMAIL}?subject=BlueBird%20Alerts%20Demo%20Request" class="btn btn-primary btn-lg">&#128231; Schedule a Demo</a>
    <div class="hero-login-wrap">
      <a href="/login" class="btn btn-ghost btn-lg">Admin Login &rarr;</a>
      <span class="hero-login-hint">Select your district &amp; school to sign in</span>
    </div>
  </div>
  <div class="hero-stats">
    <div>
      <span class="hero-stat-num">&#60; 2s</span>
      <div class="hero-stat-lbl">Alert delivery to devices</div>
    </div>
    <div>
      <span class="hero-stat-num">100%</span>
      <div class="hero-stat-lbl">Tenant data isolation</div>
    </div>
    <div>
      <span class="hero-stat-num">iOS + Android</span>
      <div class="hero-stat-lbl">Native push support</div>
    </div>
    <div>
      <span class="hero-stat-num">Full audit</span>
      <div class="hero-stat-lbl">Every action logged</div>
    </div>
  </div>
</section>

<!-- ── PROBLEM ──────────────────────────────────────────────────────────── -->
<section class="section">
  <div class="section-inner">
    <div class="section-header">
      <span class="section-tag">The Challenge</span>
      <h2 class="section-h">Emergency communication shouldn't be hard.</h2>
      <p class="section-sub">Schools face a unique problem: seconds matter, everyone needs to know, and normal channels don't cut it.</p>
    </div>
    <div class="problem-grid">
      <div class="problem-card">
        <span class="problem-icon">&#128161;</span>
        <h3>Speed matters in a crisis</h3>
        <p>When a real emergency happens, every second counts. PA systems, phone trees, and group texts can't reach all staff simultaneously.</p>
      </div>
      <div class="problem-card">
        <span class="problem-icon">&#128100;</span>
        <h3>Staff need clear instructions</h3>
        <p>Staff don't just need an alert — they need to know what to do. BlueBird delivers a clear message that every registered device receives.</p>
      </div>
      <div class="problem-card">
        <span class="problem-icon">&#128202;</span>
        <h3>Admins need real-time visibility</h3>
        <p>Who got the alert? Who acknowledged it? Is the system ready? Administrators need answers before an emergency, not after.</p>
      </div>
    </div>
  </div>
</section>

<!-- ── FEATURES ──────────────────────────────────────────────────────────── -->
<section class="section section-alt">
  <div class="section-inner">
    <div class="section-header">
      <span class="section-tag">Platform Features</span>
      <h2 class="section-h">Everything a district needs, nothing it doesn't.</h2>
      <p class="section-sub">Built specifically for K–12 schools. Every feature is practical, fast, and purpose-built.</p>
    </div>
    <div class="features-grid">
      <div class="feature-card">
        <div class="feature-icon">&#128680;</div>
        <div>
          <h3>Hold-to-Activate Alarms</h3>
          <p>Prevents accidental triggering. Admins press and hold to send a live alert or training drill across all registered devices.</p>
        </div>
      </div>
      <div class="feature-card">
        <div class="feature-icon">&#128241;</div>
        <div>
          <h3>Native Push Notifications</h3>
          <p>APNs (iOS) and FCM (Android) push notifications reach devices in under two seconds — even when the app is closed.</p>
        </div>
      </div>
      <div class="feature-card">
        <div class="feature-icon">&#9989;</div>
        <div>
          <h3>Real-Time Acknowledgement</h3>
          <p>See exactly how many staff have confirmed receipt during an active alert. No guessing who got the message.</p>
        </div>
      </div>
      <div class="feature-card">
        <div class="feature-icon">&#128263;</div>
        <div>
          <h3>Quiet Period Management</h3>
          <p>Staff can request silence during tests, performances, or sensitive activities. Admins approve or deny from the dashboard.</p>
        </div>
      </div>
      <div class="feature-card">
        <div class="feature-icon">&#128247;</div>
        <div>
          <h3>Device Readiness Dashboard</h3>
          <p>Every registered device is visible at a glance. Know which staff are ready to receive alerts before an emergency occurs.</p>
        </div>
      </div>
      <div class="feature-card">
        <div class="feature-icon">&#128202;</div>
        <div>
          <h3>Full Audit Logs</h3>
          <p>Every action — alert activation, user change, role update — is permanently logged with timestamps and actor attribution.</p>
        </div>
      </div>
      <div class="feature-card">
        <div class="feature-icon">&#127979;</div>
        <div>
          <h3>Training Drill Mode</h3>
          <p>Run realistic practice drills without sending real push notifications. Staff see it as a drill; the system behaves as in a live emergency.</p>
        </div>
      </div>
      <div class="feature-card">
        <div class="feature-icon">&#128294;</div>
        <div>
          <h3>Sandbox &amp; Demo Environment</h3>
          <p>Evaluate BlueBird risk-free. Demo tenants use synthetic data and simulated push events with no real devices required.</p>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- ── HOW IT WORKS ──────────────────────────────────────────────────────── -->
<section class="section">
  <div class="section-inner">
    <div class="section-header" style="text-align:center;">
      <span class="section-tag">How It Works</span>
      <h2 class="section-h" style="max-width:500px;margin:0 auto 14px;">Up and running in a single afternoon.</h2>
      <p class="section-sub" style="margin:0 auto;">No enterprise software complexity. No dedicated IT staff required.</p>
    </div>
    <div class="steps">
      <div class="step">
        <div class="step-num">1</div>
        <h3>Admin provisions the school</h3>
        <p>Create accounts for teachers and staff. Assign roles — building admin, district admin, staff, or law enforcement.</p>
      </div>
      <div class="step">
        <div class="step-num">2</div>
        <h3>Staff install the app</h3>
        <p>Generate one-time access codes. Staff scan a QR or enter the code to self-register on iOS or Android — no IT intervention needed.</p>
      </div>
      <div class="step">
        <div class="step-num">3</div>
        <h3>Alerts reach every device instantly</h3>
        <p>Activate an alert from the dashboard. Push notifications arrive on every registered device in under two seconds.</p>
      </div>
      <div class="step">
        <div class="step-num">4</div>
        <h3>Track and verify response</h3>
        <p>The acknowledgement counter updates live. Admins see who responded and who hasn't, with a full audit trail afterward.</p>
      </div>
    </div>
  </div>
</section>

<!-- ── DISTRICT ───────────────────────────────────────────────────────────── -->
<section class="section section-alt">
  <div class="section-inner">
    <div class="district-layout">
      <div>
        <span class="section-tag">District Management</span>
        <h2 class="section-h">One platform for every building in your district.</h2>
        <p class="section-sub" style="margin-bottom:32px;">District admins get full visibility across all schools — with strict data isolation between buildings.</p>
        <ul class="district-list">
          <li>
            <div class="district-check">&#10003;</div>
            <div>
              <h4>District-level licensing</h4>
              <p>One license covers all buildings. Add or remove schools without managing separate subscriptions.</p>
            </div>
          </li>
          <li>
            <div class="district-check">&#10003;</div>
            <div>
              <h4>Cross-school analytics</h4>
              <p>View aggregated user counts, device readiness, and drill history across every building from one dashboard.</p>
            </div>
          </li>
          <li>
            <div class="district-check">&#10003;</div>
            <div>
              <h4>Tenant-isolated alerts</h4>
              <p>An alert at Lincoln Elementary never reaches staff at Jefferson High. Isolation is architectural, not a setting.</p>
            </div>
          </li>
          <li>
            <div class="district-check">&#10003;</div>
            <div>
              <h4>Click-through school management</h4>
              <p>District admins switch into any building's dashboard in one click to manage users, devices, or settings.</p>
            </div>
          </li>
        </ul>
      </div>
      <div class="district-visual">
        <p style="font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#93c5fd;margin-bottom:16px;">District Overview</p>
        <div class="school-card-demo">
          <div>
            <div class="school-name">Lincoln Elementary</div>
            <div class="school-meta">18 devices &nbsp;·&nbsp; 24 users</div>
          </div>
          <span class="school-pill">Alert clear</span>
        </div>
        <div class="school-card-demo">
          <div>
            <div class="school-name">Jefferson Middle School</div>
            <div class="school-meta">31 devices &nbsp;·&nbsp; 41 users</div>
          </div>
          <span class="school-pill">Alert clear</span>
        </div>
        <div class="school-card-demo">
          <div>
            <div class="school-name">Roosevelt High School</div>
            <div class="school-meta">47 devices &nbsp;·&nbsp; 68 users</div>
          </div>
          <span class="school-pill warn">Drill active</span>
        </div>
        <p style="font-size:.72rem;color:#93c5fd;text-align:center;margin-top:16px;">&#8593; Click any card to manage that school</p>
      </div>
    </div>
  </div>
</section>

<!-- ── SAFETY ─────────────────────────────────────────────────────────────── -->
<section class="section section-dark">
  <div class="section-inner">
    <div class="section-header" style="text-align:center;">
      <span class="section-tag">Safety &amp; Accountability</span>
      <h2 class="section-h" style="color:#fff;margin:0 auto 14px;max-width:500px;">Every action is recorded. Nothing is anonymous.</h2>
      <p class="section-sub" style="margin:0 auto;">BlueBird Alerts provides a complete, tamper-evident record of every event for compliance and accountability.</p>
    </div>
    <div class="safety-grid">
      <div class="safety-card">
        <span class="safety-icon">&#128373;</span>
        <h3>Who triggered the alert</h3>
        <p>Every alert activation is attributed to a named admin account with a timestamp — never anonymous, always accountable.</p>
      </div>
      <div class="safety-card">
        <span class="safety-icon">&#9989;</span>
        <h3>Acknowledgement tracking</h3>
        <p>During an active alarm, see a live count of staff who have confirmed receipt. Know who hasn't responded and follow up immediately.</p>
      </div>
      <div class="safety-card">
        <span class="safety-icon">&#128203;</span>
        <h3>Permanent audit logs</h3>
        <p>User changes, role updates, setting edits, and alert events are all logged with actor, timestamp, and before/after values.</p>
      </div>
      <div class="safety-card">
        <span class="safety-icon">&#128274;</span>
        <h3>Role-based access control</h3>
        <p>Staff see only what they need. Admins control what each role can access, trigger, and approve — enforced at the API level.</p>
      </div>
    </div>
    <p style="text-align:center;margin-top:40px;font-size:0.82rem;color:#475569;">
      BlueBird Alerts is a staff notification tool and is not intended to replace official emergency response systems, law enforcement, or district emergency protocols.
    </p>
  </div>
</section>

<!-- ── CTA ────────────────────────────────────────────────────────────────── -->
<section class="cta-section">
  <div style="max-width:600px;margin:0 auto;">
    <h2>Ready to see BlueBird in action?</h2>
    <p>Schedule a free demo and we'll walk you through the full platform — from first login to your first training drill.</p>
    <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap;">
      <a href="mailto:{DEMO_EMAIL}?subject=BlueBird%20Alerts%20Demo%20Request" class="btn btn-primary btn-lg" style="background:#fff;color:var(--blue);">&#128231; Schedule a Demo</a>
      <a href="mailto:{DEMO_EMAIL}" class="btn btn-ghost btn-lg">{DEMO_EMAIL}</a>
    </div>
  </div>
</section>

<!-- ── FOOTER ─────────────────────────────────────────────────────────────── -->
<footer>
  <div class="footer-inner">
    <div class="footer-logo">
      <img src="{LOGO}" alt="BlueBird Alerts" />
      <span>BlueBird Alerts</span>
    </div>
    <div class="footer-links">
      <a href="mailto:{DEMO_EMAIL}?subject=BlueBird%20Alerts%20Demo%20Request">Request Demo</a>
      <a href="/login">Admin Login</a>
      <a href="mailto:{DEMO_EMAIL}">Contact</a>
    </div>
    <p class="footer-copy">
      &copy; 2026 Emery Tech Solutions &nbsp;&middot;&nbsp; BlueBird Alerts &nbsp;&middot;&nbsp;
      Built for schools and districts.
    </p>
  </div>
</footer>

</body>
</html>"""


def render_login_portal() -> str:
    """
    Unified typeahead login portal at GET /login.

    User types a school or district name → results appear instantly →
    clicking redirects to /{tenant_slug}/admin/login.

    localStorage key:
      bb_login_school – {{"slug": "...", "name": "...", "district": "..."}}

    Backed by GET /api/public/search?q=  (no credentials exposed).
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Sign In — BlueBird Alerts</title>
  <meta name="robots" content="noindex" />
  <link rel="icon" type="image/png" href="{LOGO}" />
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --blue:      #1b5fe4;
      --blue-dark: #1048c0;
      --blue-soft: #eff6ff;
      --text:      #10203f;
      --muted:     #5d7398;
      --border:    rgba(18,52,120,.12);
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

    /* ── CARD ──────────────────────────────────────────────────────────── */
    .portal-card {{
      background: #fff; border-radius: 20px;
      padding: 40px 44px;
      max-width: 480px; width: 100%;
      box-shadow: 0 32px 80px rgba(0,0,0,.35);
    }}
    .portal-logo {{
      display: flex; align-items: center; gap: 10px;
      margin-bottom: 28px;
    }}
    .portal-logo img {{ width: 36px; height: 36px; object-fit: contain; }}
    .portal-logo span {{ font-weight: 800; font-size: 1.1rem; color: var(--text); }}

    /* ── HEADER ────────────────────────────────────────────────────────── */
    .portal-title {{
      font-size: 1.3rem; font-weight: 800;
      color: var(--text); margin-bottom: 5px;
    }}
    .portal-sub {{ font-size: 0.87rem; color: var(--muted); margin-bottom: 22px; }}

    /* ── QUICK ACCESS ─────────────────────────────────────────────────── */
    .quick-access {{
      background: var(--blue-soft); border: 1px solid rgba(27,95,228,.18);
      border-radius: 12px; padding: 14px 16px;
      margin-bottom: 22px; display: none;
    }}
    .quick-label {{
      font-size: 0.7rem; font-weight: 700; color: var(--blue);
      text-transform: uppercase; letter-spacing: .06em; margin-bottom: 6px;
    }}
    .quick-name {{ font-size: 0.95rem; font-weight: 700; color: var(--text); }}
    .quick-dist {{ font-size: 0.78rem; color: var(--muted); margin-top: 2px; }}
    .quick-actions {{
      display: flex; gap: 10px; margin-top: 10px; align-items: center;
    }}
    .btn-quick {{
      display: inline-flex; align-items: center; justify-content: center;
      background: var(--blue); color: #fff;
      font-size: 0.88rem; font-weight: 600; border-radius: 8px;
      padding: 9px 20px; cursor: pointer;
      transition: opacity .15s; border: none;
    }}
    .btn-quick:hover {{ opacity: .88; }}
    .btn-ghost {{
      background: none; color: var(--muted); font-size: 0.84rem;
      font-weight: 600; border: none; cursor: pointer; padding: 0;
    }}
    .btn-ghost:hover {{ color: var(--blue); }}

    /* ── SEARCH ────────────────────────────────────────────────────────── */
    .search-wrap {{ position: relative; margin-bottom: 6px; }}
    .search-icon {{
      position: absolute; left: 13px; top: 50%;
      transform: translateY(-50%);
      font-size: 1rem; color: var(--muted);
      pointer-events: none; line-height: 1;
    }}
    .search-input {{
      width: 100%;
      padding: 13px 44px 13px 42px;
      border: 1.5px solid var(--border); border-radius: 12px;
      font-size: 0.95rem; color: var(--text);
      background: #fff; outline: none;
      transition: border-color .15s, box-shadow .15s;
      font-family: inherit;
    }}
    .search-input::placeholder {{ color: var(--muted); }}
    .search-input:focus {{
      border-color: var(--blue);
      box-shadow: 0 0 0 3px rgba(27,95,228,.12);
    }}
    .search-spinner {{
      position: absolute; right: 14px; top: 50%;
      width: 18px; height: 18px;
      border: 2px solid rgba(27,95,228,.2);
      border-top-color: var(--blue);
      border-radius: 50%;
      animation: bbSpin .6s linear infinite;
      display: none;
      transform: translateY(-50%);
    }}
    @keyframes bbSpin {{ to {{ transform: translateY(-50%) rotate(360deg); }} }}
    .search-hint {{
      font-size: 0.78rem; color: var(--muted);
      padding-left: 2px; margin-bottom: 0; margin-top: 6px;
    }}

    /* ── RESULTS ───────────────────────────────────────────────────────── */
    .results-list {{
      display: flex; flex-direction: column; gap: 6px;
      max-height: 320px; overflow-y: auto;
      margin-top: 10px;
    }}
    .results-list::-webkit-scrollbar {{ width: 4px; }}
    .results-list::-webkit-scrollbar-thumb {{
      background: rgba(27,95,228,.2); border-radius: 4px;
    }}
    .result-item {{
      display: flex; align-items: center; justify-content: space-between;
      padding: 13px 16px; border-radius: 10px;
      border: 1.5px solid var(--border); background: #fff;
      cursor: pointer; text-align: left; width: 100%;
      transition: border-color .12s, background .12s, transform .1s;
      font-family: inherit;
    }}
    .result-item:hover, .result-item:focus {{
      border-color: var(--blue); background: var(--blue-soft);
      transform: translateX(2px); outline: none;
    }}
    .result-item.selecting {{
      border-color: var(--blue); background: var(--blue-soft);
      transform: none; transition: none;
    }}
    .result-name {{ font-size: 0.93rem; font-weight: 700; color: var(--text); }}
    .result-district {{ font-size: 0.76rem; color: var(--muted); margin-top: 3px; }}
    .result-arrow {{
      color: var(--blue); font-size: 1rem;
      flex-shrink: 0; margin-left: 12px;
    }}
    mark {{
      background: rgba(27,95,228,.14); color: var(--blue);
      border-radius: 2px; padding: 0 1px; font-weight: 700;
      font-style: normal;
    }}

    /* ── EMPTY ─────────────────────────────────────────────────────────── */
    .empty-msg {{
      text-align: center; padding: 24px 0 8px;
      font-size: 0.87rem; color: var(--muted);
      display: none;
    }}
    .empty-msg strong {{
      display: block; font-size: 0.95rem;
      color: var(--text); margin-bottom: 5px;
    }}

    /* ── FOOTER ────────────────────────────────────────────────────────── */
    .portal-footer {{
      text-align: center; margin-top: 20px;
      font-size: 0.8rem; color: rgba(255,255,255,.5);
    }}
    .portal-footer a {{ color: rgba(255,255,255,.7); text-decoration: none; }}
    .portal-footer a:hover {{ color: #fff; text-decoration: underline; }}

    @media (max-width: 520px) {{
      .portal-card {{ padding: 28px 24px; }}
    }}
    @media (prefers-color-scheme: dark) {{
      .portal-card {{ background: #1e293b; }}
      .portal-logo span, .portal-title, .result-name {{ color: #e2e8f0; }}
      .portal-sub, .result-district, .search-hint {{ color: #94a3b8; }}
      .search-input {{
        background: #0f172a; color: #e2e8f0;
        border-color: rgba(255,255,255,.12);
      }}
      .search-input:focus {{
        border-color: #60a5fa;
        box-shadow: 0 0 0 3px rgba(96,165,250,.12);
      }}
      .result-item {{ background: #1e293b; border-color: rgba(255,255,255,.08); }}
      .result-item:hover, .result-item:focus {{
        background: rgba(27,95,228,.2); border-color: #60a5fa;
      }}
      .quick-access {{
        background: rgba(27,95,228,.15);
        border-color: rgba(27,95,228,.3);
      }}
      .quick-name {{ color: #e2e8f0; }}
    }}
  </style>
</head>
<body>

<div class="portal-card">

  <div class="portal-logo">
    <img src="{LOGO}" alt="BlueBird Alerts" />
    <span>BlueBird Alerts</span>
  </div>

  <!-- Quick-access banner (returning users) -->
  <div class="quick-access" id="quick-access">
    <div class="quick-label">&#9889; Quick access</div>
    <div class="quick-name" id="quick-name"></div>
    <div class="quick-dist" id="quick-dist"></div>
    <div class="quick-actions">
      <button class="btn-quick" id="quick-go-btn" onclick="bbQuickGo()">
        Continue &rarr;
      </button>
      <button class="btn-ghost" onclick="bbClearQuick()">Change school</button>
    </div>
  </div>

  <h2 class="portal-title">Find your school</h2>
  <p class="portal-sub">Type your school or district name to sign in</p>

  <div class="search-wrap">
    <span class="search-icon" aria-hidden="true">&#128269;</span>
    <input class="search-input" type="text" id="search-input"
           placeholder="Search school or district..."
           autocomplete="off" autocorrect="off" spellcheck="false"
           aria-label="Search for your school or district"
           aria-controls="results-list" aria-autocomplete="list" />
    <div class="search-spinner" id="search-spinner" aria-hidden="true"></div>
  </div>
  <p class="search-hint" id="search-hint">Type at least 2 characters to search</p>

  <div class="empty-msg" id="empty-msg" aria-live="polite">
    <strong>No schools found</strong>
    Try a different search term or contact your administrator.
  </div>

  <div class="results-list" id="results-list"
       role="listbox" aria-label="Matching schools"></div>

</div>

<div class="portal-footer">
  <a href="/">&larr; Back to home</a>
</div>

<script>
(function() {{
  var _URL    = '/api/public/search';
  var _LS_KEY = 'bb_login_school';
  var _timer  = null;
  var _lastQ  = null;
  var _results = [];

  /* ── Helpers ────────────────────────────────────────────────────────── */
  function _$(id)    {{ return document.getElementById(id); }}
  function _show(id) {{ _$(id).style.display = ''; }}
  function _hide(id) {{ _$(id).style.display = 'none'; }}

  function _esc(s) {{
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }}

  /* Highlight the matched portion of text */
  function _hl(text, q) {{
    if (!q) return _esc(text);
    var i = text.toLowerCase().indexOf(q.toLowerCase());
    if (i === -1) return _esc(text);
    return _esc(text.slice(0, i))
         + '<mark>' + _esc(text.slice(i, i + q.length)) + '</mark>'
         + _esc(text.slice(i + q.length));
  }}

  /* ── localStorage ─────────────────────────────────────────────────── */
  function _save(s) {{ try {{ localStorage.setItem(_LS_KEY, JSON.stringify(s)); }} catch(e) {{}} }}
  function _load()  {{ try {{ return JSON.parse(localStorage.getItem(_LS_KEY)); }} catch(e) {{ return null; }} }}
  function _clear() {{ try {{ localStorage.removeItem(_LS_KEY); }} catch(e) {{}} }}

  /* ── Quick-access ─────────────────────────────────────────────────── */
  function _maybeShowQuick() {{
    var s = _load();
    if (!s || !s.slug || !s.name) return;
    _$('quick-name').textContent = s.name;
    _$('quick-dist').textContent = s.district || '';
    _$('quick-go-btn').setAttribute('data-slug', s.slug);
    _show('quick-access');
  }}

  window.bbQuickGo = function() {{
    var slug = _$('quick-go-btn').getAttribute('data-slug') || '';
    if (slug) window.location.href = '/' + slug + '/admin/login';
  }};

  window.bbClearQuick = function() {{
    _clear();
    _hide('quick-access');
    _$('search-input').focus();
  }};

  /* ── Render ───────────────────────────────────────────────────────── */
  function _render(results, q) {{
    var list = _$('results-list');
    _hide('empty-msg');
    if (!results.length) {{
      list.innerHTML = '';
      _show('empty-msg');
      return;
    }}
    var html = '';
    results.forEach(function(r, i) {{
      var distHtml = r.district_name
        ? '<div class="result-district">' + _esc(r.district_name) + '</div>'
        : '';
      html += '<button class="result-item" role="option" tabindex="0"'
            + ' data-idx="' + i + '"'
            + ' onclick="bbSelect(' + i + ')"'
            + ' onkeydown="bbItemKey(event,' + i + ')">'
            + '<div>'
            + '<div class="result-name">' + _hl(r.tenant_name, q) + '</div>'
            + distHtml
            + '</div>'
            + '<span class="result-arrow" aria-hidden="true">&#8594;</span>'
            + '</button>';
    }});
    list.innerHTML = html;
  }}

  /* ── Fetch ────────────────────────────────────────────────────────── */
  function _fetch(q) {{
    if (q === _lastQ) return;
    _lastQ = q;
    _show('search-spinner');
    _hide('empty-msg');
    fetch(_URL + '?q=' + encodeURIComponent(q))
      .then(function(r) {{ return r.json(); }})
      .then(function(data) {{
        _hide('search-spinner');
        if (Array.isArray(data)) {{
          _results = data;
          _render(data, q);
        }}
      }})
      .catch(function() {{
        _hide('search-spinner');
        _$('results-list').innerHTML = '';
        _show('empty-msg');
      }});
  }}

  /* ── Select → redirect ────────────────────────────────────────────── */
  window.bbSelect = function(idx) {{
    var r = _results[idx];
    if (!r) return;
    var btn = _$('results-list').querySelector('[data-idx="' + idx + '"]');
    if (btn) btn.classList.add('selecting');
    _save({{ slug: r.tenant_slug, name: r.tenant_name, district: r.district_name }});
    setTimeout(function() {{
      window.location.href = '/' + r.tenant_slug + '/admin/login';
    }}, 130);
  }};

  /* ── Keyboard: result items ───────────────────────────────────────── */
  window.bbItemKey = function(e, idx) {{
    var items = _$('results-list').querySelectorAll('.result-item');
    if (e.key === 'ArrowDown') {{
      e.preventDefault();
      if (idx + 1 < items.length) items[idx + 1].focus();
    }} else if (e.key === 'ArrowUp') {{
      e.preventDefault();
      if (idx <= 0) {{ _$('search-input').focus(); }}
      else {{ items[idx - 1].focus(); }}
    }} else if (e.key === 'Enter') {{
      e.preventDefault(); bbSelect(idx);
    }} else if (e.key === 'Escape') {{
      _$('search-input').focus();
    }}
  }};

  /* ── Input events ─────────────────────────────────────────────────── */
  var _inp = _$('search-input');

  _inp.addEventListener('input', function() {{
    var q = this.value.trim();
    clearTimeout(_timer);
    _hide('search-spinner');
    if (q.length < 2) {{
      _results = [];
      _lastQ = null;
      _$('results-list').innerHTML = '';
      _hide('empty-msg');
      _show('search-hint');
      return;
    }}
    _hide('search-hint');
    _timer = setTimeout(function() {{ _fetch(q); }}, 250);
  }});

  _inp.addEventListener('keydown', function(e) {{
    var items = _$('results-list').querySelectorAll('.result-item');
    if (e.key === 'ArrowDown' && items.length) {{
      e.preventDefault(); items[0].focus();
    }} else if (e.key === 'Escape') {{
      _$('results-list').innerHTML = '';
      _results = [];
      _lastQ = null;
      _hide('empty-msg');
      _show('search-hint');
      this.value = '';
    }}
  }});

  /* ── Init ─────────────────────────────────────────────────────────── */
  _maybeShowQuick();
  _inp.focus();
}})();
</script>

</body>
</html>"""
