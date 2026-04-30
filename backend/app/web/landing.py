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
  <link rel="icon" href="/favicon.ico?v=1" />
  <link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png?v=1" />
  <link rel="icon" type="image/png" sizes="16x16" href="/static/favicon-16x16.png?v=1" />
  <link rel="apple-touch-icon" href="/static/apple-touch-icon.png?v=1" />
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
    .footer-disclaimer {{
      font-size: 0.72rem; color: #374151;
      margin-top: 12px; line-height: 1.5;
      border-top: 1px solid rgba(255,255,255,.06);
      padding-top: 12px;
    }}

    /* ── MOBILE DEMO ──────────────────────────────────────────────────── */
    .demo-layout {{
      display: grid;
      grid-template-columns: 240px 1fr;
      gap: 56px;
      align-items: center;
    }}
    .demo-phone-col {{ display: flex; flex-direction: column; align-items: center; gap: 16px; }}
    .demo-phone {{
      width: 210px; height: 430px;
      background: #0f172a;
      border-radius: 38px;
      border: 6px solid #1e293b;
      overflow: hidden;
      position: relative;
      box-shadow: 0 0 0 1px rgba(255,255,255,.07), 0 24px 64px rgba(0,0,0,.35);
    }}
    .demo-phone::before {{
      content: '';
      position: absolute; top: 0; left: 50%;
      transform: translateX(-50%);
      width: 70px; height: 20px;
      background: #0f172a;
      border-radius: 0 0 14px 14px;
      z-index: 10;
    }}
    .demo-statusbar {{
      display: flex; justify-content: space-between; align-items: center;
      padding: 5px 14px 0;
      font-size: 0.52rem; font-weight: 700; color: #94a3b8;
      position: relative; z-index: 5;
    }}
    .demo-screen {{
      display: none; height: calc(100% - 24px);
      flex-direction: column; overflow: hidden;
    }}
    .demo-screen.active {{ display: flex; }}
    /* Home screen */
    .ds-home {{ background: linear-gradient(160deg,#0f172a 0%,#1e293b 100%); color:#fff; }}
    .ds-home-header {{ padding: 8px 12px 7px; border-bottom: 1px solid rgba(255,255,255,.07); }}
    .ds-home-logo {{ display:flex; align-items:center; gap:6px; font-weight:800; font-size:0.62rem; color:#60a5fa; text-transform:uppercase; letter-spacing:.06em; }}
    .ds-home-logo img {{ width:16px; height:16px; border-radius:4px; }}
    .ds-home-school {{ font-size:0.65rem; color:#e2e8f0; margin-top:2px; font-weight:600; }}
    .ds-home-status {{ display:inline-flex; align-items:center; gap:4px; background:rgba(22,163,74,.2); color:#4ade80; border-radius:20px; padding:2px 7px; font-size:0.52rem; font-weight:700; margin-top:4px; }}
    .ds-home-status::before {{ content:''; width:5px; height:5px; background:#4ade80; border-radius:50%; }}
    .ds-home-body {{ padding:8px 12px; flex:1; }}
    .ds-stat-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-top:4px; }}
    .ds-stat-card {{ background:rgba(255,255,255,.05); border-radius:9px; padding:8px 9px; text-align:center; }}
    .ds-stat-num {{ font-size:1.05rem; font-weight:800; color:#60a5fa; }}
    .ds-stat-lbl {{ font-size:0.47rem; color:#94a3b8; margin-top:2px; }}
    .ds-hold-btn {{
      display:flex; align-items:center; justify-content:center;
      width:68px; height:68px;
      background: radial-gradient(circle,#dc2626 0%,#991b1b 100%);
      border-radius:50%; margin:10px auto 0;
      font-size:0.52rem; font-weight:800; color:#fff;
      text-transform:uppercase; letter-spacing:.04em;
      box-shadow:0 0 0 5px rgba(220,38,38,.18),0 0 0 10px rgba(220,38,38,.08);
      text-align:center; line-height:1.3; cursor:pointer;
    }}
    /* Alert screen */
    .ds-alert {{ background: linear-gradient(160deg,#7f1d1d 0%,#991b1b 100%); color:#fff; }}
    .ds-alert-header {{ padding:10px 12px; text-align:center; border-bottom:1px solid rgba(255,255,255,.1); }}
    .ds-alert-pulse {{ width:12px; height:12px; border-radius:50%; background:#fca5a5; margin:0 auto 5px; animation:ds-pulse 1s ease-in-out infinite; }}
    @keyframes ds-pulse {{ 0%,100% {{ box-shadow:0 0 0 0 rgba(252,165,165,.7); }} 50% {{ box-shadow:0 0 0 7px rgba(252,165,165,0); }} }}
    .ds-alert-title {{ font-size:0.72rem; font-weight:900; text-transform:uppercase; letter-spacing:.05em; }}
    .ds-alert-sub {{ font-size:0.5rem; color:rgba(255,255,255,.65); margin-top:2px; }}
    .ds-alert-body {{ padding:10px 12px; flex:1; }}
    .ds-alert-msg {{ font-size:0.58rem; color:#fca5a5; line-height:1.5; margin-bottom:10px; }}
    .ds-alert-ack {{ background:#fff; color:#991b1b; border:none; border-radius:20px; padding:6px 14px; font-size:0.55rem; font-weight:800; cursor:pointer; display:block; margin:0 auto; text-transform:uppercase; letter-spacing:.04em; }}
    .ds-alert-by {{ font-size:0.46rem; color:rgba(255,255,255,.4); text-align:center; margin-top:7px; }}
    /* Ack screen */
    .ds-ack {{ background: linear-gradient(160deg,#14532d 0%,#166534 100%); color:#fff; }}
    .ds-ack-header {{ padding:10px 12px; text-align:center; }}
    .ds-ack-count {{ font-size:1.35rem; font-weight:900; color:#4ade80; }}
    .ds-ack-lbl {{ font-size:0.52rem; color:rgba(255,255,255,.7); margin-top:2px; }}
    .ds-ack-bar-wrap {{ margin:7px 12px; background:rgba(255,255,255,.1); border-radius:20px; height:7px; }}
    .ds-ack-bar {{ width:67%; height:100%; background:#4ade80; border-radius:20px; }}
    .ds-ack-list {{ padding:0 12px; flex:1; overflow:hidden; }}
    .ds-ack-item {{ display:flex; align-items:center; gap:5px; padding:4px 0; border-bottom:1px solid rgba(255,255,255,.05); font-size:0.52rem; color:#d1fae5; }}
    .ds-ack-item::before {{ content:'✓'; color:#4ade80; font-weight:800; }}
    .ds-ack-item.pending {{ color:rgba(255,255,255,.3); }}
    .ds-ack-item.pending::before {{ content:'○'; color:rgba(255,255,255,.25); }}
    /* Quiet screen */
    .ds-quiet {{ background: linear-gradient(160deg,#0c4a6e 0%,#075985 100%); color:#fff; }}
    .ds-quiet-header {{ padding:10px 12px; text-align:center; border-bottom:1px solid rgba(255,255,255,.1); }}
    .ds-quiet-title {{ font-size:0.68rem; font-weight:800; }}
    .ds-quiet-sub {{ font-size:0.5rem; color:rgba(255,255,255,.6); margin-top:2px; }}
    .ds-quiet-body {{ padding:10px 12px; flex:1; }}
    .ds-quiet-field {{ margin-bottom:9px; }}
    .ds-quiet-label {{ font-size:0.47rem; font-weight:700; color:rgba(255,255,255,.55); text-transform:uppercase; letter-spacing:.06em; margin-bottom:3px; }}
    .ds-quiet-value {{ font-size:0.56rem; color:#bae6fd; background:rgba(255,255,255,.08); border-radius:6px; padding:4px 7px; }}
    .ds-quiet-submit {{ background:#0ea5e9; color:#fff; border:none; border-radius:20px; padding:6px 14px; font-size:0.56rem; font-weight:700; cursor:pointer; display:block; margin:8px auto 0; text-transform:uppercase; letter-spacing:.04em; }}
    /* Devices screen */
    .ds-devices {{ background:#0f172a; color:#fff; }}
    .ds-devices-header {{ padding:10px 12px; border-bottom:1px solid rgba(255,255,255,.07); }}
    .ds-devices-title {{ font-size:0.68rem; font-weight:800; color:#e2e8f0; }}
    .ds-devices-sub {{ font-size:0.48rem; color:#64748b; margin-top:2px; }}
    .ds-devices-body {{ padding:8px 12px; flex:1; }}
    .ds-dev-row {{ display:flex; justify-content:space-between; align-items:center; padding:4px 0; border-bottom:1px solid rgba(255,255,255,.04); }}
    .ds-dev-name {{ font-size:0.53rem; color:#cbd5e1; }}
    .ds-dev-pill {{ font-size:0.44rem; font-weight:700; padding:2px 6px; border-radius:10px; background:rgba(22,163,74,.2); color:#4ade80; }}
    .ds-dev-pill.warn {{ background:rgba(234,179,8,.2); color:#facc15; }}
    /* Demo controls */
    .demo-controls {{ display:flex; flex-wrap:wrap; gap:7px; justify-content:center; }}
    .demo-btn {{ padding:6px 13px; border-radius:20px; font-size:0.76rem; font-weight:600; cursor:pointer; border:none; transition:opacity .15s; }}
    .demo-btn:hover {{ opacity:.8; }}
    .demo-btn-alert {{ background:#dc2626; color:#fff; }}
    .demo-btn-ack {{ background:#16a34a; color:#fff; }}
    .demo-btn-quiet {{ background:#0284c7; color:#fff; }}
    .demo-btn-devices {{ background:#7c3aed; color:#fff; }}
    .demo-btn-reset {{ background:rgba(0,0,0,.07); color:#1e293b; border:1px solid rgba(0,0,0,.1); }}
    .demo-disclaimer {{ font-size:0.68rem; color:var(--muted); text-align:center; margin-top:2px; }}
    /* Right column bullets */
    .demo-bullets {{ list-style:none; padding:0; display:flex; flex-direction:column; gap:16px; margin-bottom:28px; }}
    .demo-bullets li {{ display:flex; gap:12px; align-items:flex-start; }}
    .demo-bullet-icon {{ width:38px; height:38px; border-radius:10px; background:var(--blue-soft); display:grid; place-items:center; font-size:1.15rem; flex-shrink:0; }}
    .demo-bullet-title {{ font-size:0.93rem; font-weight:700; margin-bottom:3px; }}
    .demo-bullet-desc {{ font-size:0.83rem; color:var(--muted); line-height:1.5; }}

    /* ── RESPONSIVE ───────────────────────────────────────────────────── */
    @media (max-width: 768px) {{
      .district-layout {{ grid-template-columns: 1fr; gap: 32px; }}
      .district-visual {{ display: none; }}
      .nav-actions .btn-secondary {{ display: none; }}
      .hero {{ padding: 64px 20px 56px; }}
      .hero-stats {{ gap: 24px; }}
      .section {{ padding: 56px 20px; }}
      .demo-layout {{ grid-template-columns: 1fr; gap: 36px; }}
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
      <a href="/request-demo" class="btn btn-secondary">Request Demo</a>
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
    <a href="/request-demo" class="btn btn-primary btn-lg">&#128231; Schedule a Demo</a>
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

<!-- ── MOBILE DEMO ─────────────────────────────────────────────────────── -->
<section class="section" id="demo">
  <div class="section-inner">
    <div class="section-header" style="text-align:center;margin-bottom:48px;">
      <span class="section-tag">Interactive Demo</span>
      <h2 class="section-h" style="max-width:540px;margin:0 auto 14px;">See BlueBird Alerts in action.</h2>
      <p class="section-sub" style="margin:0 auto;">Explore how staff receive alerts, acknowledge emergencies, and manage their status — all from the mobile app.</p>
    </div>
    <div class="demo-layout">
      <!-- Phone mockup -->
      <div class="demo-phone-col">
        <div class="demo-phone">
          <div class="demo-statusbar"><span>9:41</span><span>&#9679;&#9679;&#9679; 100%</span></div>
          <!-- Home screen -->
          <div class="demo-screen ds-home active" id="ds-home">
            <div class="ds-home-header">
              <div class="ds-home-logo"><img src="{LOGO}" alt="" />BlueBird Alerts</div>
              <div class="ds-home-school">Lincoln Elementary</div>
              <div class="ds-home-status">Alert clear</div>
            </div>
            <div class="ds-home-body">
              <div style="font-size:0.5rem;color:#64748b;text-transform:uppercase;letter-spacing:.06em;font-weight:700;margin-bottom:5px;">System Status</div>
              <div class="ds-stat-grid">
                <div class="ds-stat-card"><div class="ds-stat-num">18</div><div class="ds-stat-lbl">Devices</div></div>
                <div class="ds-stat-card"><div class="ds-stat-num">24</div><div class="ds-stat-lbl">Staff</div></div>
                <div class="ds-stat-card"><div class="ds-stat-num">3</div><div class="ds-stat-lbl">Drills (30d)</div></div>
                <div class="ds-stat-card"><div class="ds-stat-num">94%</div><div class="ds-stat-lbl">Ack Rate</div></div>
              </div>
              <div class="ds-hold-btn" onclick="bbDemo('alert')">HOLD<br>TO<br>ALERT</div>
            </div>
          </div>
          <!-- Alert screen -->
          <div class="demo-screen ds-alert" id="ds-alert">
            <div class="ds-alert-header">
              <div class="ds-alert-pulse"></div>
              <div class="ds-alert-title">Emergency Alert</div>
              <div class="ds-alert-sub">Lincoln Elementary &mdash; 9:42 AM</div>
            </div>
            <div class="ds-alert-body">
              <div class="ds-alert-msg">Emergency alert. Please follow school procedures. Secure all students. Do not use hallways until cleared.</div>
              <div style="font-size:0.48rem;color:rgba(255,255,255,.45);margin-bottom:10px;">&#128100; Activated by Principal Harris</div>
              <button class="ds-alert-ack" onclick="bbDemo('ack')">Acknowledge</button>
              <div class="ds-alert-by">Tap to confirm you received this alert</div>
            </div>
          </div>
          <!-- Acknowledgement screen -->
          <div class="demo-screen ds-ack" id="ds-ack">
            <div class="ds-ack-header">
              <div class="ds-ack-count">12 / 18</div>
              <div class="ds-ack-lbl">Staff acknowledged</div>
            </div>
            <div class="ds-ack-bar-wrap"><div class="ds-ack-bar"></div></div>
            <div class="ds-ack-list">
              <div class="ds-ack-item">J. Martinez &mdash; 9:42 AM</div>
              <div class="ds-ack-item">L. Chen &mdash; 9:42 AM</div>
              <div class="ds-ack-item">M. Thompson &mdash; 9:43 AM</div>
              <div class="ds-ack-item">S. Williams &mdash; 9:43 AM</div>
              <div class="ds-ack-item pending">K. Davis</div>
              <div class="ds-ack-item pending">R. Johnson</div>
            </div>
          </div>
          <!-- Quiet period screen -->
          <div class="demo-screen ds-quiet" id="ds-quiet">
            <div class="ds-quiet-header">
              <div class="ds-quiet-title">Request Quiet Period</div>
              <div class="ds-quiet-sub">Temporarily pause push notifications</div>
            </div>
            <div class="ds-quiet-body">
              <div class="ds-quiet-field"><div class="ds-quiet-label">Reason</div><div class="ds-quiet-value">IEP Meeting</div></div>
              <div class="ds-quiet-field"><div class="ds-quiet-label">Duration</div><div class="ds-quiet-value">60 minutes</div></div>
              <div class="ds-quiet-field"><div class="ds-quiet-label">Note</div><div class="ds-quiet-value">Room 12 &mdash; confidential session</div></div>
              <button class="ds-quiet-submit">Submit Request</button>
            </div>
          </div>
          <!-- Devices screen -->
          <div class="demo-screen ds-devices" id="ds-devices">
            <div class="ds-devices-header">
              <div class="ds-devices-title">Device Readiness</div>
              <div class="ds-devices-sub">Lincoln Elementary &mdash; 18 registered</div>
            </div>
            <div class="ds-devices-body">
              <div class="ds-dev-row"><span class="ds-dev-name">J. Martinez (iOS)</span><span class="ds-dev-pill">Active</span></div>
              <div class="ds-dev-row"><span class="ds-dev-name">L. Chen (Android)</span><span class="ds-dev-pill">Active</span></div>
              <div class="ds-dev-row"><span class="ds-dev-name">M. Thompson (iOS)</span><span class="ds-dev-pill">Active</span></div>
              <div class="ds-dev-row"><span class="ds-dev-name">K. Davis (Android)</span><span class="ds-dev-pill warn">30d ago</span></div>
              <div class="ds-dev-row"><span class="ds-dev-name">P. Brown (iOS)</span><span class="ds-dev-pill warn">45d ago</span></div>
              <div style="font-size:0.48rem;color:#475569;margin-top:9px;text-align:center;">+ 13 more devices</div>
            </div>
          </div>
        </div>
        <!-- Controls -->
        <div class="demo-controls">
          <button class="demo-btn demo-btn-alert" onclick="bbDemo('alert')">&#128680; Alert</button>
          <button class="demo-btn demo-btn-ack" onclick="bbDemo('ack')">&#10003; Ack</button>
          <button class="demo-btn demo-btn-quiet" onclick="bbDemo('quiet')">&#128263; Quiet</button>
          <button class="demo-btn demo-btn-devices" onclick="bbDemo('devices')">&#128241; Devices</button>
          <button class="demo-btn demo-btn-reset" onclick="bbDemo('home')">&#8635; Reset</button>
        </div>
        <p class="demo-disclaimer">&#9888; Simulated demo &mdash; no real alerts are sent.</p>
      </div>
      <!-- Right column -->
      <div>
        <span class="section-tag">Mobile App Experience</span>
        <h2 class="section-h" style="margin-bottom:24px;">Every role.<br>Every device.<br>One clear interface.</h2>
        <ul class="demo-bullets">
          <li>
            <div class="demo-bullet-icon">&#128680;</div>
            <div>
              <div class="demo-bullet-title">One-tap emergency activation</div>
              <div class="demo-bullet-desc">A single hold gesture sends push notifications to every registered device in under two seconds. No menus. No delays.</div>
            </div>
          </li>
          <li>
            <div class="demo-bullet-icon">&#10003;</div>
            <div>
              <div class="demo-bullet-title">Live acknowledgement counter</div>
              <div class="demo-bullet-desc">See exactly who confirmed receipt — and who hasn't — in real time from the admin dashboard or your phone.</div>
            </div>
          </li>
          <li>
            <div class="demo-bullet-icon">&#128263;</div>
            <div>
              <div class="demo-bullet-title">Quiet period requests</div>
              <div class="demo-bullet-desc">Staff in a meeting can request a timed notification pause. Admins approve or deny instantly from their dashboard.</div>
            </div>
          </li>
          <li>
            <div class="demo-bullet-icon">&#128241;</div>
            <div>
              <div class="demo-bullet-title">Device health visibility</div>
              <div class="demo-bullet-desc">Admins see every registered device and its last-seen date — no surprises about coverage when a real alert is needed.</div>
            </div>
          </li>
        </ul>
        <div style="display:flex;gap:12px;flex-wrap:wrap;">
          <a class="btn btn-primary" href="/login">Get started</a>
          <a class="btn btn-secondary" href="/request-demo">Request a demo</a>
        </div>
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
<section class="section section-dark" id="safety">
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
      <a href="/request-demo" class="btn btn-primary btn-lg" style="background:#fff;color:var(--blue);">&#128231; Schedule a Demo</a>
      <a href="/request-demo" class="btn btn-ghost btn-lg">Request a Demo &rarr;</a>
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
      <a href="/request-demo">Request Demo</a>
      <a href="/login">Admin Login</a>
      <a href="/request-demo">Contact</a>
    </div>
    <p class="footer-copy">
      &copy; 2026 Emery Tech Solutions &nbsp;&middot;&nbsp; BlueBird Alerts &nbsp;&middot;&nbsp;
      Built for schools and districts.
    </p>
    <p class="footer-disclaimer">
      BlueBird Alerts is a communication tool and is not a replacement for 911.
      Always contact emergency services in a real emergency. &nbsp;
      <a href="/#safety">Safety &amp; Liability</a>
    </p>
  </div>
</footer>

<script>
(function() {{
  function bbDemo(screen) {{
    var screens = document.querySelectorAll('.demo-screen');
    screens.forEach(function(s) {{ s.classList.remove('active'); }});
    var target = document.getElementById('ds-' + screen);
    if (target) target.classList.add('active');
  }}
  window.bbDemo = bbDemo;
}})();
</script>

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
  <link rel="icon" href="/favicon.ico?v=1" />
  <link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png?v=1" />
  <link rel="icon" type="image/png" sizes="16x16" href="/static/favicon-16x16.png?v=1" />
  <link rel="apple-touch-icon" href="/static/apple-touch-icon.png?v=1" />
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
    .countdown-wrap {{
      margin-top: 10px;
    }}
    .countdown-bar-track {{
      height: 3px; background: rgba(27,95,228,.15);
      border-radius: 2px; overflow: hidden; margin-bottom: 6px;
    }}
    .countdown-bar {{
      height: 100%; background: var(--blue); border-radius: 2px;
      width: 100%; transition: width 1s linear;
    }}
    .countdown-text {{
      font-size: 0.76rem; color: var(--muted);
      display: flex; align-items: center; gap: 6px;
    }}
    .countdown-cancel {{
      background: none; border: none; cursor: pointer;
      color: var(--muted); font-size: 0.76rem; font-weight: 600;
      text-decoration: underline; padding: 0;
    }}
    .countdown-cancel:hover {{ color: var(--blue); }}
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
    .portal-disclaimer {{
      margin-top: 10px;
      font-size: 0.71rem; color: rgba(255,255,255,.35);
      line-height: 1.5; max-width: 340px; margin-left: auto; margin-right: auto;
    }}

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
    <div class="quick-label">&#9889; Welcome back</div>
    <div class="quick-name" id="quick-name"></div>
    <div class="quick-dist" id="quick-dist"></div>
    <div class="countdown-wrap" id="countdown-wrap">
      <div class="countdown-bar-track">
        <div class="countdown-bar" id="countdown-bar"></div>
      </div>
      <div class="countdown-text">
        Redirecting in <strong id="countdown-num">3</strong>s
        &nbsp;&middot;&nbsp;
        <button class="countdown-cancel" onclick="bbCancelCountdown()">Cancel</button>
      </div>
    </div>
    <div class="quick-actions">
      <button class="btn-quick" id="quick-go-btn" onclick="bbQuickGo()">
        Continue &rarr;
      </button>
      <button class="btn-ghost" onclick="bbClearQuick()">Choose different school</button>
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
  <p class="portal-disclaimer">
    This system does not replace emergency services.
    Always call 911 in a real emergency.
  </p>
</div>

<script>
(function() {{
  var _URL    = '/api/public/search';
  var _LS_KEY = 'bb_login_school';
  var _timer  = null;
  var _lastQ  = null;
  var _results = [];

  /* Countdown state */
  var _cdTimer = null;
  var _cdN     = 3;

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

  /* ── Countdown helpers ────────────────────────────────────────────── */
  function _stopCountdown() {{
    if (_cdTimer) {{ clearInterval(_cdTimer); _cdTimer = null; }}
  }}

  function _startCountdown(slug) {{
    _cdN = 3;
    var numEl = _$('countdown-num');
    var bar   = _$('countdown-bar');
    if (numEl) numEl.textContent = _cdN;
    /* Animate bar from 100% → 0% over 3 s */
    if (bar) {{
      bar.style.transition = 'none';
      bar.style.width = '100%';
      void bar.offsetHeight;
      bar.style.transition = 'width 3s linear';
      bar.style.width = '0%';
    }}
    _cdTimer = setInterval(function() {{
      _cdN--;
      if (numEl) numEl.textContent = _cdN;
      if (_cdN <= 0) {{
        _stopCountdown();
        window.location.href = '/' + slug + '/admin/login';
      }}
    }}, 1000);
  }}

  window.bbCancelCountdown = function() {{
    _stopCountdown();
    _hide('countdown-wrap');
    var bar = _$('countdown-bar');
    if (bar) {{ bar.style.transition = 'none'; bar.style.width = '100%'; }}
  }};

  /* ── Quick-access ─────────────────────────────────────────────────── */
  function _maybeShowQuick() {{
    var s = _load();
    if (!s || !s.slug || !s.name) return;
    _$('quick-name').textContent = 'Continue to ' + s.name;
    _$('quick-dist').textContent = s.district || '';
    _$('quick-go-btn').setAttribute('data-slug', s.slug);
    _show('quick-access');
    _startCountdown(s.slug);
  }}

  window.bbQuickGo = function() {{
    _stopCountdown();
    var slug = _$('quick-go-btn').getAttribute('data-slug') || '';
    if (slug) window.location.href = '/' + slug + '/admin/login';
  }};

  window.bbClearQuick = function() {{
    _stopCountdown();
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
  var _params     = new URLSearchParams(window.location.search);
  var _isSwitching = _params.get('switch') === 'true';
  if (_isSwitching) {{
    /* User clicked "Change school" — skip the auto-redirect and clean the URL. */
    window.history.replaceState({{}}, document.title, '/login');
  }} else {{
    _maybeShowQuick();
  }}
  _inp.focus();
}})();
</script>

</body>
</html>"""


def render_safety_page() -> str:
    """GET /safety — public compliance and safety information page."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Safety &amp; Compliance — BlueBird Alerts</title>
  <meta name="description" content="How BlueBird Alerts approaches safety, emergency protocols, data privacy, and system reliability for schools." />
  <link rel="icon" href="/favicon.ico?v=1" />
  <link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png?v=1" />
  <link rel="icon" type="image/png" sizes="16x16" href="/static/favicon-16x16.png?v=1" />
  <link rel="apple-touch-icon" href="/static/apple-touch-icon.png?v=1" />
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
    .nav {{
      position: sticky; top: 0; z-index: 100;
      background: var(--dark);
      padding: 0 5%;
      display: flex; align-items: center; justify-content: space-between;
      height: 60px;
    }}
    .nav-logo {{ display: flex; align-items: center; gap: 10px; text-decoration: none; }}
    .nav-logo img {{ height: 32px; border-radius: 6px; }}
    .nav-logo span {{ color: #fff; font-weight: 700; font-size: 1.05rem; }}
    .nav-actions {{ display: flex; gap: 12px; align-items: center; }}
    .nav-link {{ color: rgba(255,255,255,.75); text-decoration: none; font-size: 0.9rem; }}
    .nav-link:hover {{ color: #fff; }}
    .btn {{ display: inline-flex; align-items: center; justify-content: center; padding: 8px 18px; border-radius: 8px; font-weight: 600; font-size: 0.9rem; text-decoration: none; cursor: pointer; border: none; }}
    .btn-primary {{ background: var(--blue); color: #fff; }}
    .btn-primary:hover {{ background: var(--blue-dark); }}
    .page-hero {{
      background: linear-gradient(135deg, var(--dark) 0%, #1a2d5a 100%);
      color: #fff;
      padding: 64px 5% 56px;
      text-align: center;
    }}
    .page-hero .eyebrow {{
      font-size: 0.78rem; font-weight: 700; letter-spacing: .12em;
      text-transform: uppercase; color: rgba(255,255,255,.6); margin-bottom: 12px;
    }}
    .page-hero h1 {{ font-size: clamp(1.8rem, 4vw, 2.8rem); font-weight: 800; margin-bottom: 16px; }}
    .page-hero p {{ font-size: 1.05rem; color: rgba(255,255,255,.8); max-width: 620px; margin: 0 auto; }}
    .disclaimer-banner {{
      background: rgba(251,191,36,.12);
      border: 1px solid rgba(217,119,6,.3);
      border-left: 4px solid #d97706;
      padding: 16px 5%;
      text-align: center;
      color: #78350f;
      font-size: 0.92rem;
      line-height: 1.5;
    }}
    .content-wrap {{
      max-width: 860px;
      margin: 0 auto;
      padding: 56px 5% 80px;
    }}
    .safety-section {{ margin-bottom: 48px; }}
    .safety-section:last-child {{ margin-bottom: 0; }}
    .section-num {{
      display: inline-flex; align-items: center; justify-content: center;
      width: 26px; height: 26px;
      background: var(--blue); color: #fff;
      border-radius: 50%; font-size: 0.76rem; font-weight: 700;
      margin-right: 10px; flex-shrink: 0;
    }}
    .safety-section h2 {{
      font-size: 1.18rem; font-weight: 700; margin-bottom: 14px;
      display: flex; align-items: center;
      border-bottom: 1px solid var(--border); padding-bottom: 12px;
    }}
    .safety-section p {{ color: var(--muted); margin-bottom: 10px; line-height: 1.7; }}
    .safety-section ul {{ padding-left: 0; list-style: none; display: flex; flex-direction: column; gap: 8px; margin-bottom: 10px; }}
    .safety-section li {{ color: var(--muted); padding-left: 20px; position: relative; line-height: 1.6; }}
    .safety-section li::before {{ content: '→'; position: absolute; left: 0; color: var(--blue); font-weight: 700; }}
    .callout {{
      background: var(--blue-soft); border: 1px solid rgba(27,95,228,.15);
      border-left: 4px solid var(--blue);
      border-radius: 8px; padding: 14px 18px; margin: 16px 0;
      color: #1e3a6e; font-size: 0.92rem; line-height: 1.6;
    }}
    .warn-callout {{
      background: rgba(254,243,199,.7); border: 1px solid rgba(180,83,9,.22);
      border-left: 4px solid #d97706;
      border-radius: 8px; padding: 14px 18px; margin: 16px 0;
      color: #78350f; font-size: 0.92rem; line-height: 1.6;
    }}
    footer {{
      background: var(--dark); color: rgba(255,255,255,.5);
      padding: 28px 5%; text-align: center; font-size: 0.82rem;
    }}
    footer a {{ color: rgba(255,255,255,.6); text-decoration: none; }}
    footer a:hover {{ color: #fff; }}
    .footer-links {{ display: flex; gap: 20px; justify-content: center; flex-wrap: wrap; margin-bottom: 12px; }}
    .footer-disclaimer {{ max-width: 640px; margin: 12px auto 0; font-size: 0.78rem; color: rgba(255,255,255,.38); line-height: 1.5; }}
  </style>
</head>
<body>

<nav class="nav">
  <a class="nav-logo" href="/">
    <img src="{LOGO}" alt="BlueBird Alerts" />
    <span>BlueBird Alerts</span>
  </a>
  <div class="nav-actions">
    <a class="nav-link" href="/#features">Features</a>
    <a class="nav-link" href="/#pricing">Pricing</a>
    <a class="btn btn-primary" href="/login">Admin Login</a>
  </div>
</nav>

<div class="page-hero">
  <p class="eyebrow">Trust &amp; Compliance</p>
  <h1>Safety &amp; Compliance</h1>
  <p>How BlueBird Alerts approaches emergency communication, data protection, and operational reliability for schools and districts.</p>
</div>

<div class="disclaimer-banner">
  <strong>&#9888; Important:</strong> BlueBird Alerts is an internal communication tool.
  It does not contact 911 or replace professional emergency services.
  <strong>Always call 911 in a real emergency.</strong>
</div>

<div class="content-wrap">

  <div class="safety-section">
    <h2><span class="section-num">1</span>Purpose &amp; Scope</h2>
    <p>BlueBird Alerts is designed to deliver fast, reliable internal emergency notifications to school staff who have the BlueBird app installed. It is a push-notification and in-app alert system — not an emergency dispatch system.</p>
    <ul>
      <li>Sends real-time push notifications to registered iOS and Android devices</li>
      <li>Provides administrators a single activation point for school-wide alerts</li>
      <li>Supports training drills via a dedicated "Training Mode" that does not trigger real notifications</li>
      <li>Scoped to individual school tenants — each school's data and alerts are fully isolated</li>
    </ul>
    <div class="callout">BlueBird Alerts is intended to <strong>augment</strong> existing emergency protocols, not replace them. Schools should maintain separate emergency response plans independent of this system.</div>
  </div>

  <div class="safety-section">
    <h2><span class="section-num">2</span>Emergency Disclaimer</h2>
    <div class="warn-callout">
      <strong>&#9888; BlueBird Alerts does not contact 911 or emergency services.</strong><br />
      Activating an alert sends push notifications to registered staff devices only. It does not notify police, fire, or medical services. In any real emergency, call 911 immediately.
    </div>
    <p>When activating a live (non-training) alarm, administrators are required to check an EMS acknowledgment confirming that 911 has been contacted or is not required before the alert is sent.</p>
    <ul>
      <li>Live alarm activation requires an explicit EMS acknowledgment checkbox</li>
      <li>Training mode alarms are visually distinct and never trigger real notifications or SMS</li>
      <li>Safety disclaimers are shown on the admin dashboard, login portal, and alarm activation form</li>
      <li>Administrators cannot bypass the EMS acknowledgment during live alarm activation</li>
    </ul>
  </div>

  <div class="safety-section">
    <h2><span class="section-num">3</span>Data Privacy</h2>
    <p>BlueBird Alerts collects only the data required to deliver its core service. No student data is collected or processed.</p>
    <ul>
      <li>User accounts store name, email, phone (optional), and hashed credentials — no student records</li>
      <li>Device tokens are stored and used exclusively for push notification delivery</li>
      <li>Alert history is retained within the platform for audit and drill-report purposes</li>
      <li>Message content sent via push or SMS is logged for audit trail and troubleshooting</li>
      <li>Data is scoped per school tenant — administrators can only access their own school's data</li>
    </ul>
    <div class="callout">No data is sold to third parties. Device tokens are transmitted to Apple (APNs) and Google (FCM) solely for push delivery, under the terms of their respective developer agreements.</div>
  </div>

  <div class="safety-section">
    <h2><span class="section-num">4</span>Role-Based Access Control</h2>
    <p>BlueBird Alerts uses a multi-tier role system to ensure users have access only to what they need.</p>
    <ul>
      <li><strong>Staff</strong> — can receive alerts and acknowledge them on their device; no admin console access</li>
      <li><strong>Building Admin</strong> — can activate and deactivate alarms, manage users, and view reports for their school</li>
      <li><strong>District Admin</strong> — oversight access across all schools in their district</li>
      <li><strong>Super Admin</strong> — platform-level access; manages tenant provisioning and system configuration</li>
    </ul>
    <p>All authenticated active users can trigger emergency alarms. Only Building Admins and above can deactivate an active alarm. TOTP two-factor authentication is strongly encouraged for all administrator accounts.</p>
  </div>

  <div class="safety-section">
    <h2><span class="section-num">5</span>Audit Logging</h2>
    <p>BlueBird Alerts maintains a full audit log of all significant actions within the platform.</p>
    <ul>
      <li>Alarm activations and deactivations — who, when, and message content</li>
      <li>User account changes — creation, role changes, and deactivation</li>
      <li>Admin logins and session events</li>
      <li>Access code generation and redemption</li>
      <li>Push delivery outcomes and acknowledgement events</li>
    </ul>
    <div class="callout">Audit logs are visible to Building Admins and above in the Admin Console under the Activity section. Super Admins have access to platform-wide audit trails.</div>
  </div>

  <div class="safety-section">
    <h2><span class="section-num">6</span>Device Awareness</h2>
    <p>Real-time push delivery depends on staff having the BlueBird app installed and registered. The platform provides device health visibility to administrators at all times.</p>
    <ul>
      <li>Total registered device count is shown in the System Health panel on the admin dashboard</li>
      <li>Recently active devices (seen within 30 days) are tracked separately from stale registrations</li>
      <li>Device coverage — ratio of active users with registered devices — is a key readiness indicator</li>
      <li>Stale or revoked device tokens are automatically pruned from the delivery pool on the next push attempt</li>
    </ul>
    <p>Schools should aim for at least one registered device per active user to ensure full push coverage during an emergency.</p>
  </div>

  <div class="safety-section">
    <h2><span class="section-num">7</span>System Reliability</h2>
    <p>BlueBird Alerts is designed with high availability in mind for critical communication paths.</p>
    <ul>
      <li>Emergency alert delivery is never blocked by billing status or subscription plan limits</li>
      <li>Push delivery uses industry-standard APNs and FCM infrastructure with automatic retry logic</li>
      <li>SMS fallback via Twilio provides a secondary delivery channel when push is unavailable</li>
      <li>Training Mode allows administrators to test the full alert flow without sending real notifications</li>
      <li>The admin console provides real-time alarm state visibility with no polling delay</li>
    </ul>
    <div class="warn-callout">BlueBird Alerts requires an active internet connection on both the server and registered staff devices. It is not a replacement for hardwired PA systems or offline emergency equipment.</div>
  </div>

  <div class="safety-section">
    <h2><span class="section-num">8</span>Training Support</h2>
    <p>Regular drills are essential for ensuring staff familiarity with the alert system before a real emergency occurs.</p>
    <ul>
      <li>Training Mode activates the full alarm flow on staff devices without sending real push or SMS</li>
      <li>The Drill Readiness panel on the dashboard shows push configuration status and device registration counts</li>
      <li>Post-drill PDF reports are automatically generated and available for download</li>
      <li>The system surfaces a "no recent drill" reminder when no alerts have been sent in the past 7 days</li>
      <li>Access codes allow new staff to self-register before a drill without requiring admin action per-user</li>
    </ul>
    <div class="callout">It is recommended to run at least one training drill per semester to verify device registrations, delivery paths, and staff familiarity with the alert flow.</div>
  </div>

</div>

<footer>
  <div class="footer-links">
    <a href="/">Home</a>
    <a href="/#features">Features</a>
    <a href="/#pricing">Pricing</a>
    <a href="/#safety">Safety</a>
    <a href="/login">Admin Login</a>
    <a href="/request-demo">Contact</a>
  </div>
  <p>&copy; 2025 BlueBird Alerts. All rights reserved.</p>
  <p class="footer-disclaimer">BlueBird Alerts is a communication tool and is not a replacement for 911 or professional emergency services. Always call 911 in a real emergency. No student data is collected.</p>
</footer>

</body>
</html>"""


def render_request_demo_page() -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Request a Demo — BlueBird Alerts</title>
  <meta name="description" content="See BlueBird Alerts in action. Request a personalized demo for your school or district." />
  <link rel="icon" href="/favicon.ico?v=1" />
  <link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png?v=1" />
  <link rel="apple-touch-icon" href="/static/apple-touch-icon.png?v=1" />
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --blue:      #1b5fe4;
      --blue-dark: #1048c0;
      --blue-soft: #eff6ff;
      --dark:      #0f172a;
      --text:      #10203f;
      --muted:     #5d7398;
      --border:    rgba(18,52,120,.12);
      --white:     #ffffff;
      --radius:    14px;
      --error:     #dc2626;
      --success:   #16a34a;
    }}
    html {{ scroll-behavior: smooth; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
      color: var(--text);
      background: var(--blue-soft);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }}
    /* ── NAV ── */
    .nav {{
      background: rgba(255,255,255,.94);
      backdrop-filter: saturate(180%) blur(12px);
      border-bottom: 1px solid var(--border);
      padding: 0 24px;
    }}
    .nav-inner {{
      max-width: 900px; margin: 0 auto;
      display: flex; align-items: center; justify-content: space-between;
      height: 60px;
    }}
    .nav-logo {{
      display: flex; align-items: center; gap: 10px;
      font-weight: 700; font-size: 1.05rem; color: var(--dark);
      text-decoration: none;
    }}
    .nav-logo img {{ height: 32px; width: auto; }}
    .btn {{
      display: inline-flex; align-items: center; gap: 6px;
      padding: 9px 20px; border-radius: 8px; font-size: .875rem;
      font-weight: 600; text-decoration: none; cursor: pointer;
      border: none; transition: background .15s, opacity .15s;
    }}
    .btn-ghost {{ background: transparent; color: var(--muted); }}
    .btn-ghost:hover {{ color: var(--text); }}
    /* ── PAGE LAYOUT ── */
    .page {{
      flex: 1; display: flex; align-items: flex-start; justify-content: center;
      padding: 48px 16px 64px;
    }}
    .card {{
      background: var(--white);
      border-radius: var(--radius);
      box-shadow: 0 4px 24px rgba(10,40,100,.10), 0 1px 4px rgba(10,40,100,.06);
      padding: 48px 40px;
      width: 100%; max-width: 560px;
    }}
    .card-eyebrow {{
      font-size: .75rem; font-weight: 700; letter-spacing: .08em;
      color: var(--blue); text-transform: uppercase; margin-bottom: 8px;
    }}
    .card-title {{
      font-size: 1.75rem; font-weight: 800; color: var(--dark);
      line-height: 1.25; margin-bottom: 8px;
    }}
    .card-sub {{
      color: var(--muted); font-size: .925rem; margin-bottom: 32px;
      line-height: 1.6;
    }}
    /* ── FORM ── */
    .field {{ margin-bottom: 18px; }}
    .field label {{
      display: block; font-size: .8rem; font-weight: 600;
      color: var(--text); margin-bottom: 5px;
    }}
    .field label .req {{ color: var(--blue); margin-left: 2px; }}
    .field input, .field select, .field textarea {{
      width: 100%; padding: 11px 14px;
      border: 1.5px solid var(--border);
      border-radius: 8px; font-size: .9rem; color: var(--text);
      background: var(--white); font-family: inherit;
      transition: border-color .15s, box-shadow .15s;
      outline: none; appearance: none;
    }}
    .field input:focus, .field select:focus, .field textarea:focus {{
      border-color: var(--blue);
      box-shadow: 0 0 0 3px rgba(27,95,228,.12);
    }}
    .field textarea {{ resize: vertical; min-height: 90px; }}
    .field-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    .optional-label {{
      font-size: .75rem; font-weight: 500; color: var(--muted);
      font-style: italic; margin-left: 4px;
    }}
    /* ── SUBMIT ── */
    .submit-btn {{
      width: 100%; padding: 14px; margin-top: 8px;
      background: var(--blue); color: var(--white);
      border: none; border-radius: 9px;
      font-size: 1rem; font-weight: 700;
      cursor: pointer; transition: background .15s, opacity .15s;
      display: flex; align-items: center; justify-content: center; gap: 8px;
    }}
    .submit-btn:hover:not(:disabled) {{ background: var(--blue-dark); }}
    .submit-btn:disabled {{ opacity: .6; cursor: not-allowed; }}
    /* ── MESSAGES ── */
    .msg {{
      border-radius: 9px; padding: 14px 16px;
      font-size: .875rem; font-weight: 500; margin-bottom: 20px;
      display: none;
    }}
    .msg.success {{
      background: #f0fdf4; border: 1.5px solid #86efac; color: var(--success);
    }}
    .msg.error {{
      background: #fef2f2; border: 1.5px solid #fca5a5; color: var(--error);
    }}
    .msg.visible {{ display: block; }}
    /* ── TRUST ── */
    .trust-row {{
      display: flex; align-items: center; gap: 20px;
      margin-top: 28px; padding-top: 20px;
      border-top: 1px solid var(--border);
      flex-wrap: wrap;
    }}
    .trust-item {{
      display: flex; align-items: center; gap: 6px;
      font-size: .775rem; color: var(--muted); font-weight: 500;
    }}
    /* ── RESPONSIVE ── */
    @media (max-width: 560px) {{
      .card {{ padding: 32px 20px; }}
      .field-row {{ grid-template-columns: 1fr; gap: 0; }}
      .card-title {{ font-size: 1.45rem; }}
    }}
    /* ── HONEYPOT ── */
    .hp-field {{ display: none; }}
    /* ── DARK MODE ── */
    @media (prefers-color-scheme: dark) {{
      body {{ background: #0c1524; }}
      .nav {{ background: rgba(15,23,42,.94); }}
      .card {{ background: #111827; box-shadow: 0 4px 24px rgba(0,0,0,.35); }}
      .card-title {{ color: #f1f5f9; }}
      .card-sub {{ color: #94a3b8; }}
      .field label {{ color: #e2e8f0; }}
      .field input, .field select, .field textarea {{
        background: #1e293b; border-color: rgba(255,255,255,.1);
        color: #f1f5f9;
      }}
      .field input:focus, .field select:focus, .field textarea:focus {{
        border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59,130,246,.15);
      }}
      .trust-row {{ border-color: rgba(255,255,255,.08); }}
      .trust-item {{ color: #64748b; }}
      .nav-logo {{ color: #f1f5f9; }}
    }}
  </style>
</head>
<body>

<nav class="nav">
  <div class="nav-inner">
    <a href="/" class="nav-logo">
      <img src="{LOGO}" alt="BlueBird Alerts" />
      BlueBird Alerts
    </a>
    <a href="/" class="btn btn-ghost">← Back</a>
  </div>
</nav>

<main class="page">
  <div class="card">
    <div class="card-eyebrow">See it in action</div>
    <h1 class="card-title">Request a Demo</h1>
    <p class="card-sub">Tell us about your school or district and we'll reach out to schedule a personalized demo. Takes less than 60 seconds.</p>

    <div id="success-msg" class="msg success">
      &#10003;&nbsp; Your demo request has been submitted. We'll contact you shortly!
    </div>
    <div id="error-msg" class="msg error"></div>

    <form id="demo-form" novalidate>
      <!-- Honeypot -->
      <div class="hp-field">
        <input type="text" name="website" id="hp-website" autocomplete="off" tabindex="-1" />
      </div>

      <div class="field-row">
        <div class="field">
          <label for="name">Full Name <span class="req">*</span></label>
          <input type="text" id="name" name="name" placeholder="Jane Smith" autocomplete="name" required />
        </div>
        <div class="field">
          <label for="email">Work Email <span class="req">*</span></label>
          <input type="email" id="email" name="email" placeholder="jane@yourdistrict.edu" autocomplete="email" required />
        </div>
      </div>

      <div class="field">
        <label for="organization">Organization / School Name <span class="req">*</span></label>
        <input type="text" id="organization" name="organization" placeholder="Springfield Unified School District" required />
      </div>

      <div class="field-row">
        <div class="field">
          <label for="role">Your Role <span class="req">*</span></label>
          <select id="role" name="role" required>
            <option value="" disabled selected>Select your role</option>
            <option value="Superintendent">Superintendent</option>
            <option value="IT Director">IT Director</option>
            <option value="Principal">Principal</option>
            <option value="Safety Coordinator">Safety Coordinator</option>
            <option value="Other">Other</option>
          </select>
        </div>
        <div class="field">
          <label for="school_count">Number of Schools <span class="req">*</span></label>
          <select id="school_count" name="school_count">
            <option value="" disabled selected>Select range</option>
            <option value="1">1 school</option>
            <option value="2">2–5 schools</option>
            <option value="6">6–15 schools</option>
            <option value="16">16–50 schools</option>
            <option value="51">51+ schools</option>
          </select>
        </div>
      </div>

      <div class="field">
        <label for="message">What are you hoping BlueBird can help with? <span class="req">*</span></label>
        <textarea id="message" name="message" placeholder="We're looking to improve our emergency communication and need something that works across all our schools..." required></textarea>
      </div>

      <div class="field-row">
        <div class="field">
          <label for="phone">Phone <span class="optional-label">(optional)</span></label>
          <input type="tel" id="phone" name="phone" placeholder="(555) 000-0000" autocomplete="tel" />
        </div>
        <div class="field">
          <label for="preferred_time">Preferred Demo Time <span class="optional-label">(optional)</span></label>
          <input type="text" id="preferred_time" name="preferred_time" placeholder="e.g. Weekday mornings" />
        </div>
      </div>

      <button type="submit" class="submit-btn" id="submit-btn">
        <span id="btn-label">Request Demo</span>
      </button>
    </form>

    <div class="trust-row">
      <div class="trust-item">&#128274; No spam, ever</div>
      <div class="trust-item">&#9200; Response within 24 hours</div>
      <div class="trust-item">&#127968; Built for K–12</div>
    </div>
  </div>
</main>

<script>
(function() {{
  var form = document.getElementById('demo-form');
  var btn = document.getElementById('submit-btn');
  var btnLabel = document.getElementById('btn-label');
  var successMsg = document.getElementById('success-msg');
  var errorMsg = document.getElementById('error-msg');

  function showError(msg) {{
    errorMsg.textContent = msg;
    errorMsg.classList.add('visible');
    successMsg.classList.remove('visible');
  }}

  function clearMessages() {{
    errorMsg.classList.remove('visible');
    successMsg.classList.remove('visible');
  }}

  form.addEventListener('submit', async function(e) {{
    e.preventDefault();
    clearMessages();

    var name = document.getElementById('name').value.trim();
    var email = document.getElementById('email').value.trim();
    var organization = document.getElementById('organization').value.trim();
    var role = document.getElementById('role').value.trim();
    var school_count = document.getElementById('school_count').value.trim();
    var message = document.getElementById('message').value.trim();
    var phone = document.getElementById('phone').value.trim();
    var preferred_time = document.getElementById('preferred_time').value.trim();
    var hp = document.getElementById('hp-website').value.trim();

    var errors = [];
    if (!name) errors.push('Full name is required.');
    if (!email || !/^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/.test(email)) errors.push('A valid email address is required.');
    if (!organization) errors.push('Organization name is required.');
    if (!role) errors.push('Please select your role.');
    if (!message) errors.push('Please tell us what you need help with.');
    if (errors.length) {{ showError(errors[0]); return; }}

    btn.disabled = true;
    btnLabel.textContent = 'Sending…';

    var body = new URLSearchParams({{
      name: name,
      email: email,
      organization: organization,
      role: role,
      school_count: school_count,
      message: message,
      phone: phone,
      preferred_time: preferred_time,
      website: hp,
    }});

    try {{
      var resp = await fetch('/public/request-demo', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
        body: body.toString(),
      }});
      var data = await resp.json();
      if (data.ok) {{
        form.reset();
        successMsg.classList.add('visible');
        btn.disabled = false;
        btnLabel.textContent = 'Request Demo';
        form.style.display = 'none';
      }} else {{
        var msg = (data.errors && data.errors[0]) || data.error || 'Something went wrong. Please try again.';
        showError(msg);
        btn.disabled = false;
        btnLabel.textContent = 'Request Demo';
      }}
    }} catch (err) {{
      showError('Network error. Please check your connection and try again.');
      btn.disabled = false;
      btnLabel.textContent = 'Request Demo';
    }}
  }});
}})();
</script>

</body>
</html>"""
