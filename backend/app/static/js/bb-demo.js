/* bb-demo.js — Demo analytics + guided tour for sandbox tenants.
 *
 * Expects window.BB_CONFIG to be set by the server-rendered page:
 *   window.BB_CONFIG = {
 *     isDemo: true,
 *     demoSlug: "...",
 *     demoAnalyticsUrl: "...",
 *   };
 *
 * Only activates when BB_CONFIG.isDemo === true.
 */
(function () {
  'use strict';

  var cfg = window.BB_CONFIG || {};
  if (!cfg.isDemo) return;

  var _slug = cfg.demoSlug || 'demo';
  var _analyticsUrl = cfg.demoAnalyticsUrl || '';
  var _TOUR_KEY = 'bluebird_tour_done_' + _slug;

  // ── Demo Analytics ──────────────────────────────────────────────────────────

  window.loadDemoAnalytics = function loadDemoAnalytics(days) {
    days = days || 30;
    var body = document.getElementById('demo-analytics-body');
    var chart = document.getElementById('demo-chart-area');
    if (!_analyticsUrl) {
      if (body) body.innerHTML = '<div style="color:var(--muted);padding:16px;font-size:0.85rem;">Analytics URL not configured.</div>';
      return;
    }
    if (body) body.innerHTML = '<div class="signal-card" style="text-align:center;"><p class="mini-copy">Loading…</p></div>';
    if (chart) chart.innerHTML = '';

    fetch(_analyticsUrl + '?days=' + days, { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!body) return;
        var total = d.total_incidents || 0;
        var resp = d.avg_response_seconds;
        var respLabel = resp === null || resp === undefined ? '—'
          : (resp < 60 ? Math.round(resp) + 's' : Math.round(resp / 60) + 'm ' + (Math.round(resp) % 60) + 's');
        var drill = d.drill_compliance_pct !== null && d.drill_compliance_pct !== undefined
          ? Math.round(d.drill_compliance_pct) + '%' : '—';
        var active = d.active_incidents || 0;
        var resolved = d.resolved_incidents || 0;

        var cards = [
          { label: 'Total Incidents', value: total, color: '#1e40af' },
          { label: 'Avg Response Time', value: respLabel, color: '#065f46' },
          { label: 'Drill Compliance', value: drill, color: '#7c3aed' },
          { label: 'Active', value: active, color: '#b45309' },
          { label: 'Resolved', value: resolved, color: '#15803d' },
        ];

        body.innerHTML = cards.map(function (c) {
          return '<div class="signal-card" style="text-align:center;padding:18px 12px;">'
            + '<div style="font-size:1.9rem;font-weight:800;color:' + c.color + ';">' + c.value + '</div>'
            + '<div style="font-size:0.78rem;color:var(--muted);margin-top:4px;">' + c.label + '</div>'
            + '</div>';
        }).join('');

        // Inline SVG bar chart
        var bars = d.alerts_by_day || [];
        if (chart && bars.length > 0) {
          var maxVal = Math.max.apply(null, bars.map(function (b) { return b.count || 0; })) || 1;
          var bw = Math.max(6, Math.min(32, Math.floor(600 / bars.length) - 4));
          var chartW = bars.length * (bw + 4) + 40;
          var chartH = 100;
          var svgBars = bars.map(function (b, i) {
            var h = Math.max(2, Math.round(((b.count || 0) / maxVal) * 72));
            var x = 36 + i * (bw + 4);
            var y = chartH - 22 - h;
            var lbl = (b.day || '').slice(5);
            return '<rect x="' + x + '" y="' + y + '" width="' + bw + '" height="' + h
              + '" rx="2" fill="#3b82f6" fill-opacity="0.7"/>'
              + (bars.length <= 31
                ? '<text x="' + (x + bw / 2) + '" y="' + (chartH - 6) + '" text-anchor="middle" font-size="8" fill="var(--muted)">' + lbl + '</text>'
                : '');
          }).join('');
          var yLabels = '<text x="34" y="22" text-anchor="end" font-size="9" fill="var(--muted)">' + maxVal + '</text>'
            + '<text x="34" y="' + (chartH - 22) + '" text-anchor="end" font-size="9" fill="var(--muted)">0</text>';
          chart.innerHTML = '<div style="margin-bottom:8px;font-size:0.78rem;font-weight:600;color:var(--muted);">Alerts by Day (last ' + days + 'd)</div>'
            + '<svg width="100%" viewBox="0 0 ' + chartW + ' ' + chartH + '" style="display:block;max-width:700px;" xmlns="http://www.w3.org/2000/svg">'
            + yLabels + svgBars + '</svg>';
        }
      })
      .catch(function (e) {
        if (body) body.innerHTML = '<div style="color:var(--danger);padding:16px;font-size:0.85rem;">Could not load demo analytics: ' + e.message + '</div>';
      });
  };

  // ── Guided Tour ──────────────────────────────────────────────────────────────

  var _tourSteps = [
    {
      targetSelector: '#overview',
      title: 'Command Deck',
      text: 'This is your main dashboard. See the current alarm state, user counts, device readiness, and recent alerts at a glance.',
      position: 'bottom'
    },
    {
      targetSelector: '#js-alarm-status-pill',
      title: 'Emergency Alert Status',
      text: 'This shows your current alarm state. Administrators can trigger school-wide emergency alerts that instantly notify all registered devices.',
      position: 'bottom'
    },
    {
      targetSelector: '#user-management',
      title: 'User Management',
      text: 'Manage staff accounts here. Add users, assign roles, and control who can trigger alerts or access the admin panel.',
      position: 'top'
    },
    {
      targetSelector: '#access-codes',
      title: 'Access Codes',
      text: 'Generate one-time access codes for onboarding new staff. Codes can be pre-assigned, emailed, and tracked as claimed or unclaimed.',
      position: 'top'
    },
    {
      targetSelector: '#analytics',
      title: 'Analytics & Reports',
      text: 'Review incident history, response times, drill compliance, and per-building breakdowns. Sandbox data is seeded for realism.',
      position: 'top'
    },
    {
      targetSelector: '#settings',
      title: 'Settings',
      text: 'Configure your school name, APNS credentials, quiet period policies, and branding. Changes take effect immediately.',
      position: 'top'
    }
  ];

  var _tourOverlay = null;
  var _tourHighlight = null;
  var _tourTooltip = null;

  function _tourCreate() {
    if (_tourOverlay) return;
    _tourOverlay = document.createElement('div');
    _tourOverlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9000;pointer-events:none;display:none;';
    document.body.appendChild(_tourOverlay);
    _tourHighlight = document.createElement('div');
    _tourHighlight.style.cssText = 'position:fixed;z-index:9001;border:2px solid #f59e0b;border-radius:6px;box-shadow:0 0 0 4px rgba(245,158,11,0.25);pointer-events:none;display:none;transition:all 0.2s ease;';
    document.body.appendChild(_tourHighlight);
    _tourTooltip = document.createElement('div');
    _tourTooltip.style.cssText = 'position:fixed;z-index:9002;background:#fff;color:#1e293b;border-radius:10px;box-shadow:0 8px 32px rgba(0,0,0,0.22);padding:20px 22px;max-width:340px;min-width:260px;font-size:0.9rem;display:none;';
    document.body.appendChild(_tourTooltip);
  }

  function _tourPosition(target, position) {
    var r = target.getBoundingClientRect();
    _tourHighlight.style.display = 'block';
    _tourHighlight.style.top = (r.top - 6) + 'px';
    _tourHighlight.style.left = (r.left - 6) + 'px';
    _tourHighlight.style.width = (r.width + 12) + 'px';
    _tourHighlight.style.height = (r.height + 12) + 'px';
    var top, left;
    if (position === 'bottom') {
      top = r.bottom + 14;
      left = Math.max(12, Math.min(r.left, window.innerWidth - 352));
    } else {
      top = Math.max(12, r.top - 174);
      left = Math.max(12, Math.min(r.left, window.innerWidth - 352));
    }
    _tourTooltip.style.top = top + 'px';
    _tourTooltip.style.left = left + 'px';
  }

  function _tourEnd(completed) {
    if (_tourOverlay) _tourOverlay.style.display = 'none';
    if (_tourHighlight) _tourHighlight.style.display = 'none';
    if (_tourTooltip) _tourTooltip.style.display = 'none';
    if (completed) {
      try { localStorage.setItem(_TOUR_KEY, '1'); } catch (e) { /* storage unavailable */ }
    }
  }

  function _tourShow(idx) {
    if (idx >= _tourSteps.length) { _tourEnd(true); return; }
    var step = _tourSteps[idx];
    var target = document.querySelector(step.targetSelector);
    if (!target) { _tourShow(idx + 1); return; }
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setTimeout(function () {
      _tourPosition(target, step.position);
      var isLast = (idx === _tourSteps.length - 1);
      var progress = (idx + 1) + ' / ' + _tourSteps.length;
      _tourTooltip.innerHTML =
        '<div style="font-size:0.7rem;color:#b45309;font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">Tour ' + progress + '</div>'
        + '<div style="font-weight:700;font-size:1rem;margin-bottom:8px;">' + step.title + '</div>'
        + '<div style="color:#475569;line-height:1.5;margin-bottom:16px;">' + step.text + '</div>'
        + '<div style="display:flex;gap:8px;justify-content:flex-end;">'
        + (idx > 0 ? '<button id="bb-tour-back" style="padding:5px 14px;border:1px solid #e2e8f0;border-radius:6px;background:#f8fafc;cursor:pointer;font-size:0.82rem;">← Back</button>' : '')
        + (isLast
          ? '<button id="bb-tour-done" style="padding:5px 16px;background:#d97706;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:0.82rem;">Finish Tour ✓</button>'
          : '<button id="bb-tour-next" style="padding:5px 16px;background:#d97706;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:0.82rem;">Next →</button>')
        + '<button id="bb-tour-skip" style="padding:5px 10px;border:none;background:transparent;color:#94a3b8;cursor:pointer;font-size:0.78rem;">Skip</button>'
        + '</div>';
      _tourTooltip.style.display = 'block';
      _tourOverlay.style.display = 'block';
      // Use onclick to avoid listener accumulation across steps
      var nextBtn = document.getElementById('bb-tour-next');
      var backBtn = document.getElementById('bb-tour-back');
      var doneBtn = document.getElementById('bb-tour-done');
      var skipBtn = document.getElementById('bb-tour-skip');
      if (nextBtn) nextBtn.onclick = function () { _tourShow(idx + 1); };
      if (backBtn) backBtn.onclick = function () { _tourShow(idx - 1); };
      if (doneBtn) doneBtn.onclick = function () { _tourEnd(true); };
      if (skipBtn) skipBtn.onclick = function () { _tourEnd(false); };
    }, 220);
  }

  window.startBluebirdTour = function startBluebirdTour() {
    safeRun('tour-create', _tourCreate);
    _tourShow(0);
  };

  // ── Initialization ────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    safeRun('demo-analytics-nav', function () {
      var navItem = document.querySelector('[data-section="demo-analytics"]');
      if (navItem) {
        navItem.onclick = function () {
          setTimeout(function () { window.loadDemoAnalytics(30); }, 80);
        };
      }
      // Auto-load if already on the demo-analytics section
      if (document.querySelector('.nav-item.active[data-section="demo-analytics"]')) {
        window.loadDemoAnalytics(30);
      }
    });

    safeRun('demo-tour-autostart', function () {
      try {
        if (!localStorage.getItem(_TOUR_KEY)) {
          setTimeout(window.startBluebirdTour, 600);
        }
      } catch (e) { /* storage unavailable, skip autostart */ }
    });
  });

})();
