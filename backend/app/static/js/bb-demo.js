/* bb-demo.js — Demo analytics, guided tour, onboarding walkthrough, push feed.
 *
 * Expects window.BB_CONFIG set by the server:
 *   window.BB_CONFIG = {
 *     isDemo: true,
 *     demoSlug: "...",
 *     demoAnalyticsUrl: "...",
 *     demoPushFeedUrl: "...",
 *   };
 */
(function () {
  'use strict';

  var cfg = window.BB_CONFIG || {};
  if (!cfg.isDemo) return;

  var _slug = cfg.demoSlug || 'demo';
  var _analyticsUrl = cfg.demoAnalyticsUrl || '';
  var _pushFeedUrl = cfg.demoPushFeedUrl || '';
  var _TOUR_KEY = 'bluebird_tour_done_' + _slug;
  var _WALK_KEY = 'bluebird_walk_seen_' + _slug;

  // ── Colour helpers ──────────────────────────────────────────────────────────
  var _CHART_COLORS = {
    panic:   '#dc2626',
    medical: '#d97706',
    assist:  '#2563eb',
    drill:   '#059669',
    bar:     '#3b82f6',
    line:    '#7c3aed',
  };

  function _isDark() {
    return document.documentElement.getAttribute('data-theme') === 'dark';
  }

  function _mutedColor() { return _isDark() ? '#94a3b8' : '#64748b'; }
  function _bgColor()    { return _isDark() ? '#1e2e4a' : '#fff'; }
  function _textColor()  { return _isDark() ? '#e8f0fe' : '#1e293b'; }

  // ── SVG chart primitives ────────────────────────────────────────────────────

  function _svgBar(bars, labelKey, valueKey, color, height) {
    if (!bars || !bars.length) return '';
    height = height || 120;
    var maxVal = Math.max.apply(null, bars.map(function (b) { return b[valueKey] || 0; })) || 1;
    var bw = Math.max(6, Math.min(36, Math.floor(640 / bars.length) - 4));
    var W = bars.length * (bw + 4) + 50;
    var H = height;
    var plotH = H - 28;
    var svgParts = bars.map(function (b, i) {
      var v = b[valueKey] || 0;
      var h = Math.max(2, Math.round((v / maxVal) * (plotH - 10)));
      var x = 42 + i * (bw + 4);
      var y = plotH - h;
      var lbl = String(b[labelKey] || '').slice(-5);
      return '<rect x="' + x + '" y="' + y + '" width="' + bw + '" height="' + h
        + '" rx="2" fill="' + color + '" fill-opacity="0.82"/>'
        + '<title>' + lbl + ': ' + v + '</title>'
        + (bars.length <= 20
          ? '<text x="' + (x + bw / 2) + '" y="' + (H - 4) + '" text-anchor="middle" font-size="8" fill="' + _mutedColor() + '">' + lbl + '</text>'
          : '');
    });
    var yTicks = '<text x="40" y="14" text-anchor="end" font-size="9" fill="' + _mutedColor() + '">' + maxVal + '</text>'
      + '<text x="40" y="' + plotH + '" text-anchor="end" font-size="9" fill="' + _mutedColor() + '">0</text>'
      + '<line x1="42" y1="8" x2="42" y2="' + plotH + '" stroke="' + _mutedColor() + '" stroke-opacity="0.25" stroke-width="1"/>';
    return '<svg width="100%" viewBox="0 0 ' + W + ' ' + H + '" style="display:block;max-width:700px;" xmlns="http://www.w3.org/2000/svg">'
      + yTicks + svgParts.join('') + '</svg>';
  }

  function _svgLine(points, labelKey, valueKey, color, height) {
    if (!points || points.length < 2) return '';
    height = height || 100;
    var maxVal = Math.max.apply(null, points.map(function (p) { return p[valueKey] || 0; })) || 1;
    var W = Math.max(300, points.length * 30 + 50);
    var H = height;
    var plotH = H - 24;
    var step = (W - 50) / (points.length - 1);
    var coords = points.map(function (p, i) {
      var x = 42 + i * step;
      var y = plotH - Math.max(2, Math.round(((p[valueKey] || 0) / maxVal) * (plotH - 10)));
      return { x: x, y: y, label: p[labelKey], val: p[valueKey] };
    });
    var path = 'M ' + coords.map(function (c) { return c.x + ',' + c.y; }).join(' L ');
    var fill = coords.map(function (c) { return c.x + ',' + c.y; }).join(' ')
      + ' ' + coords[coords.length - 1].x + ',' + plotH + ' ' + coords[0].x + ',' + plotH;
    var dots = coords.map(function (c) {
      return '<circle cx="' + c.x + '" cy="' + c.y + '" r="3" fill="' + color + '"><title>' + c.label + ': ' + c.val + '</title></circle>';
    });
    var yLabel = '<text x="40" y="14" text-anchor="end" font-size="9" fill="' + _mutedColor() + '">' + maxVal + '</text>'
      + '<line x1="42" y1="8" x2="42" y2="' + plotH + '" stroke="' + _mutedColor() + '" stroke-opacity="0.2" stroke-width="1"/>';
    return '<svg width="100%" viewBox="0 0 ' + W + ' ' + H + '" style="display:block;max-width:700px;" xmlns="http://www.w3.org/2000/svg">'
      + yLabel
      + '<polygon points="' + fill + '" fill="' + color + '" fill-opacity="0.12"/>'
      + '<polyline points="' + coords.map(function (c) { return c.x + ',' + c.y; }).join(' ') + '" fill="none" stroke="' + color + '" stroke-width="2"/>'
      + dots.join('')
      + '</svg>';
  }

  function _svgDonut(slices, size) {
    size = size || 120;
    var total = slices.reduce(function (s, sl) { return s + (sl.value || 0); }, 0) || 1;
    var cx = size / 2, cy = size / 2, r = size * 0.38, ir = size * 0.22;
    var angle = -Math.PI / 2;
    var paths = slices.map(function (sl) {
      var pct = (sl.value || 0) / total;
      var sweep = pct * 2 * Math.PI;
      var x1 = cx + r * Math.cos(angle), y1 = cy + r * Math.sin(angle);
      var x2 = cx + r * Math.cos(angle + sweep), y2 = cy + r * Math.sin(angle + sweep);
      var ix1 = cx + ir * Math.cos(angle), iy1 = cy + ir * Math.sin(angle);
      var ix2 = cx + ir * Math.cos(angle + sweep), iy2 = cy + ir * Math.sin(angle + sweep);
      var large = sweep > Math.PI ? 1 : 0;
      var d = 'M ' + x1 + ' ' + y1 + ' A ' + r + ' ' + r + ' 0 ' + large + ' 1 ' + x2 + ' ' + y2
        + ' L ' + ix2 + ' ' + iy2 + ' A ' + ir + ' ' + ir + ' 0 ' + large + ' 0 ' + ix1 + ' ' + iy1 + ' Z';
      angle += sweep;
      return '<path d="' + d + '" fill="' + sl.color + '" fill-opacity="0.9"><title>' + sl.label + ': ' + sl.value + '</title></path>';
    });
    var labelEl = '<text x="' + cx + '" y="' + (cy + 5) + '" text-anchor="middle" font-size="11" font-weight="700" fill="' + _textColor() + '">'
      + total + '</text><text x="' + cx + '" y="' + (cy + 17) + '" text-anchor="middle" font-size="8" fill="' + _mutedColor() + '">total</text>';
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 ' + size + ' ' + size + '" xmlns="http://www.w3.org/2000/svg">'
      + paths.join('') + labelEl + '</svg>';
  }

  function _legend(items) {
    return '<div style="display:flex;flex-wrap:wrap;gap:10px 18px;margin-top:8px;">'
      + items.map(function (it) {
        return '<span style="display:flex;align-items:center;gap:5px;font-size:0.78rem;color:' + _mutedColor() + ';">'
          + '<span style="width:10px;height:10px;border-radius:50%;background:' + it.color + ';display:inline-block;"></span>'
          + it.label + ' <strong style="color:' + _textColor() + ';">' + it.value + '</strong></span>';
      }).join('') + '</div>';
  }

  // ── Stat cards ──────────────────────────────────────────────────────────────

  function _statCard(label, value, color, sub) {
    return '<div class="signal-card" style="text-align:center;padding:18px 12px;">'
      + '<div style="font-size:2rem;font-weight:800;color:' + color + ';">' + value + '</div>'
      + '<div style="font-size:0.78rem;color:var(--muted);margin-top:4px;">' + label + '</div>'
      + (sub ? '<div style="font-size:0.68rem;color:var(--muted);margin-top:2px;">' + sub + '</div>' : '')
      + '</div>';
  }

  function _chartCard(title, content) {
    return '<div class="signal-card" style="grid-column:1/-1;padding:18px;">'
      + '<div style="font-size:0.8rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:12px;">' + title + '</div>'
      + content + '</div>';
  }

  function _halfCard(title, content) {
    return '<div class="signal-card" style="grid-column:span 2;padding:18px;min-width:0;">'
      + '<div style="font-size:0.8rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:12px;">' + title + '</div>'
      + content + '</div>';
  }

  // ── Demo Analytics ──────────────────────────────────────────────────────────

  window.loadDemoAnalytics = function loadDemoAnalytics(days) {
    days = days || 30;
    var body = document.getElementById('demo-analytics-body');
    if (!body) return;
    if (!_analyticsUrl) {
      body.innerHTML = '<div style="color:var(--muted);padding:16px;font-size:0.85rem;">Analytics URL not configured.</div>';
      return;
    }
    body.style.gridTemplateColumns = 'repeat(auto-fit,minmax(160px,1fr))';
    body.innerHTML = '<div class="signal-card" style="grid-column:1/-1;text-align:center;padding:24px;"><p class="mini-copy">Loading analytics…</p></div>';

    fetch(_analyticsUrl + '?days=' + days, { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!body) return;

        var total = d.total_incidents || 0;
        var resp = d.avg_response_seconds;
        var respLabel = resp == null ? '—' : (resp < 60 ? resp + 's' : Math.floor(resp / 60) + 'm ' + (resp % 60) + 's');
        var drill = d.drill_compliance_pct != null ? Math.round(d.drill_compliance_pct) + '%' : '—';
        var active = d.active_incidents || 0;
        var resolved = d.resolved_incidents || 0;
        var adopt = d.user_adoption || {};

        // Stat row
        var stats = [
          _statCard('Total Incidents', total, '#1e40af'),
          _statCard('Avg Response', respLabel, '#065f46'),
          _statCard('Drill Compliance', drill, '#7c3aed'),
          _statCard('Active', active, '#b45309'),
          _statCard('Resolved', resolved, '#15803d'),
          _statCard('Total Users', adopt.total || '—', '#1d4ed8', adopt.push_enabled ? adopt.push_enabled + ' push-enabled' : null),
        ];

        // Incident types donut
        var types = d.incident_types || {};
        var donutSlices = [
          { label: 'Panic',   value: types.panic   || 0, color: _CHART_COLORS.panic },
          { label: 'Medical', value: types.medical  || 0, color: _CHART_COLORS.medical },
          { label: 'Assist',  value: types.assist   || 0, color: _CHART_COLORS.assist },
          { label: 'Drill',   value: types.drill    || 0, color: _CHART_COLORS.drill },
        ];
        var donutHtml = '<div style="display:flex;align-items:center;gap:24px;flex-wrap:wrap;">'
          + _svgDonut(donutSlices, 130)
          + _legend(donutSlices)
          + '</div>';

        // Alerts-by-day bar chart
        var bars = d.alerts_by_day || [];
        var barHtml = bars.length
          ? _svgBar(bars, 'day', 'count', _CHART_COLORS.bar, 110)
          : '<p class="mini-copy">No alert data yet.</p>';

        // Response time line chart
        var rtTrend = d.response_time_trend || [];
        var rtHtml = rtTrend.length >= 2
          ? _svgLine(rtTrend, 'day', 'seconds', _CHART_COLORS.line, 100)
          : '<p class="mini-copy">No response time data.</p>';

        // User adoption bar
        var adoptHtml = '';
        if (adopt.total) {
          var adoptBars = [
            { label: 'Total',     count: adopt.total,      color: '#6366f1' },
            { label: 'Active 30d', count: adopt.active_30d, color: '#22c55e' },
            { label: 'Active 7d',  count: adopt.active_7d,  color: '#0ea5e9' },
            { label: 'Push On',   count: adopt.push_enabled, color: '#f59e0b' },
          ];
          adoptHtml = '<div style="display:flex;flex-direction:column;gap:8px;">'
            + adoptBars.map(function (ab) {
              var pct = Math.round(((ab.count || 0) / adopt.total) * 100);
              return '<div><div style="display:flex;justify-content:space-between;font-size:0.75rem;margin-bottom:3px;">'
                + '<span style="color:' + _textColor() + ';">' + ab.label + '</span>'
                + '<span style="color:' + _mutedColor() + ';">' + (ab.count || 0) + ' / ' + adopt.total + '</span></div>'
                + '<div style="height:8px;border-radius:4px;background:' + (_isDark() ? '#2d3e5c' : '#e2e8f0') + ';overflow:hidden;">'
                + '<div style="height:100%;width:' + pct + '%;background:' + ab.color + ';border-radius:4px;transition:width .4s;"></div>'
                + '</div></div>';
            }).join('') + '</div>';
        }

        // Buildings table
        var bldgs = d.building_breakdown || [];
        var bldgHtml = bldgs.length
          ? '<table style="width:100%;border-collapse:collapse;font-size:0.8rem;">'
            + '<thead><tr>' + ['Building','Incidents','Users','Avg Response','Drills'].map(function (h) {
              return '<th style="padding:5px 8px;text-align:left;color:' + _mutedColor() + ';font-weight:600;border-bottom:1px solid var(--border);">' + h + '</th>';
            }).join('') + '</tr></thead><tbody>'
            + bldgs.map(function (b) {
              var r = b.avg_response_s;
              var rl = r < 60 ? r + 's' : Math.floor(r/60) + 'm';
              return '<tr>'
                + '<td style="padding:5px 8px;color:' + _textColor() + ';font-weight:600;">' + b.name + '</td>'
                + '<td style="padding:5px 8px;color:' + _textColor() + ';">' + b.incidents + '</td>'
                + '<td style="padding:5px 8px;color:' + _textColor() + ';">' + b.users + '</td>'
                + '<td style="padding:5px 8px;color:' + _textColor() + ';">' + rl + '</td>'
                + '<td style="padding:5px 8px;"><span style="color:' + (b.drill_pct >= 85 ? '#15803d' : '#b45309') + ';font-weight:700;">' + b.drill_pct + '%</span></td>'
                + '</tr>';
            }).join('') + '</tbody></table>'
          : '';

        body.innerHTML = stats.join('')
          + _chartCard('Alerts by Day (last ' + days + 'd)', barHtml)
          + _halfCard('Incident Type Breakdown', donutHtml)
          + _halfCard('Response Time Trend (seconds)', rtHtml)
          + (adoptHtml ? _halfCard('User Adoption', adoptHtml) : '')
          + (bldgHtml ? _chartCard('Per-Building Summary', bldgHtml) : '');
      })
      .catch(function (e) {
        if (body) body.innerHTML = '<div class="signal-card" style="grid-column:1/-1;color:var(--danger);padding:16px;font-size:0.85rem;">Could not load demo analytics: ' + e.message + '</div>';
      });
  };

  // ── Live Push Feed ──────────────────────────────────────────────────────────

  var _pushInterval = null;

  window.startPushFeedPoller = function startPushFeedPoller(containerId) {
    var el = document.getElementById(containerId);
    if (!el || !_pushFeedUrl) return;

    function _poll() {
      fetch(_pushFeedUrl + '?limit=15', { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var events = d.events || [];
          if (!events.length) {
            el.innerHTML = '<div style="padding:12px;color:var(--muted);font-size:0.82rem;text-align:center;">Waiting for live events…</div>';
            return;
          }
          el.innerHTML = events.map(function (ev) {
            var typeColor = ev.incident_type === 'panic' ? '#dc2626'
              : ev.incident_type === 'medical' ? '#d97706'
              : ev.incident_type === 'drill' ? '#059669' : '#2563eb';
            var label = (ev.incident_type || ev.type || 'event').replace(/_/g, ' ');
            var ts = (ev.timestamp || '').slice(11, 16);
            return '<div style="display:flex;align-items:center;gap:10px;padding:8px 12px;border-bottom:1px solid var(--border);">'
              + '<span style="width:8px;height:8px;border-radius:50%;background:' + typeColor + ';flex-shrink:0;"></span>'
              + '<div style="flex:1;min-width:0;">'
              + '<div style="font-size:0.82rem;font-weight:600;color:var(--text-primary);">' + _esc(label) + '</div>'
              + (ev.reported_by ? '<div style="font-size:0.72rem;color:var(--muted);">by ' + _esc(ev.reported_by) + '</div>' : '')
              + '</div>'
              + '<span style="font-size:0.7rem;color:var(--muted);white-space:nowrap;">' + ts + '</span>'
              + '</div>';
          }).join('');
        })
        .catch(function () {});
    }
    _poll();
    if (_pushInterval) clearInterval(_pushInterval);
    _pushInterval = setInterval(_poll, 12000);
  };

  function _esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ── Guided Tour ──────────────────────────────────────────────────────────────

  var _tourSteps = [
    {
      sel: '.app-header',
      title: 'BlueBird Command Center',
      text: 'Welcome to the BlueBird Alerts admin console. This is your real-time command center for school safety.',
      pos: 'bottom',
    },
    {
      sel: '#js-alarm-status-pill',
      title: 'Emergency Alert Status',
      text: 'This pill shows the current alarm state. When a lockdown is triggered, it turns red and all registered devices receive an immediate push notification.',
      pos: 'bottom',
    },
    {
      sel: '#overview',
      title: 'Dashboard Overview',
      text: 'The dashboard gives you a live count of users, connected devices, and recent alerts. All data updates in real time via WebSocket.',
      pos: 'bottom',
    },
    {
      sel: '#user-management',
      title: 'User Management',
      text: 'Manage all staff accounts here. Admins can add users, assign roles (teacher / building admin / district admin), deactivate accounts, and archive former staff.',
      pos: 'top',
    },
    {
      sel: '.um-tabs',
      title: 'Three-Tab User View',
      text: 'Users are split across Active, Inactive, and Archived tabs. The Codes tab manages access code onboarding — one-click QR code generation for new staff.',
      pos: 'bottom',
    },
    {
      sel: '#analytics',
      title: 'Analytics & Reports',
      text: 'Drill compliance, incident response times, per-building breakdowns, and user adoption trends — all pre-seeded with realistic data for this demo.',
      pos: 'top',
    },
    {
      sel: '#demo-analytics',
      title: '📊 Demo Analytics',
      text: 'This sandbox has enhanced demo analytics showing incident trends, response time graphs, building comparisons, and user adoption funnels.',
      pos: 'top',
    },
    {
      sel: '#audit-logs',
      title: 'Audit Log',
      text: 'Every login, alert trigger, user change, and access code use is recorded in the audit log. Searchable, filterable, and paginated.',
      pos: 'top',
    },
    {
      sel: '#quiet-periods',
      title: 'Quiet Periods',
      text: 'Teachers can request a quiet period (e.g., testing, assembly). Building admins can approve or deny requests — all tracked with audit events.',
      pos: 'top',
    },
    {
      sel: '#settings',
      title: 'Settings',
      text: 'Configure push credentials, school name, branding, and feature labels. All changes are tenant-isolated and take effect immediately.',
      pos: 'top',
    },
  ];

  var _tourOverlay = null;
  var _tourHL = null;
  var _tourTip = null;

  function _tourCreate() {
    if (_tourOverlay) return;
    _tourOverlay = document.createElement('div');
    _tourOverlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9000;pointer-events:none;display:none;';
    document.body.appendChild(_tourOverlay);
    _tourHL = document.createElement('div');
    _tourHL.style.cssText = 'position:fixed;z-index:9001;border:2px solid #f59e0b;border-radius:6px;box-shadow:0 0 0 5px rgba(245,158,11,0.2);pointer-events:none;display:none;transition:all 0.18s ease;';
    document.body.appendChild(_tourHL);
    _tourTip = document.createElement('div');
    _tourTip.style.cssText = 'position:fixed;z-index:9002;background:' + _bgColor() + ';color:' + _textColor() + ';border-radius:12px;box-shadow:0 10px 40px rgba(0,0,0,0.22);padding:22px 24px;max-width:360px;min-width:280px;font-size:0.9rem;display:none;';
    document.body.appendChild(_tourTip);
  }

  function _tourPos(target, pos) {
    var r = target.getBoundingClientRect();
    _tourHL.style.cssText += ';display:block;top:' + (r.top - 7) + 'px;left:' + (r.left - 7) + 'px;width:' + (r.width + 14) + 'px;height:' + (r.height + 14) + 'px;';
    var top, left;
    if (pos === 'bottom') {
      top = r.bottom + 16;
      left = Math.max(12, Math.min(r.left, window.innerWidth - 376));
    } else {
      top = Math.max(12, r.top - 200);
      left = Math.max(12, Math.min(r.left, window.innerWidth - 376));
    }
    _tourTip.style.top = top + 'px';
    _tourTip.style.left = left + 'px';
  }

  function _tourEnd(done) {
    if (_tourOverlay) _tourOverlay.style.display = 'none';
    if (_tourHL)      _tourHL.style.display = 'none';
    if (_tourTip)     _tourTip.style.display = 'none';
    if (done) { try { localStorage.setItem(_TOUR_KEY, '1'); } catch (e) {} }
  }

  function _tourShow(idx) {
    if (idx >= _tourSteps.length) { _tourEnd(true); return; }
    var step = _tourSteps[idx];
    var target = step.sel ? document.querySelector(step.sel) : null;
    if (!target) { _tourShow(idx + 1); return; }
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setTimeout(function () {
      _tourPos(target, step.pos);
      var isLast = idx === _tourSteps.length - 1;
      var prog = (idx + 1) + ' / ' + _tourSteps.length;
      // Progress bar
      var pct = Math.round(((idx + 1) / _tourSteps.length) * 100);
      var progBar = '<div style="height:4px;background:' + (_isDark() ? '#2d3e5c' : '#e2e8f0') + ';border-radius:2px;margin-bottom:14px;overflow:hidden;">'
        + '<div style="height:100%;width:' + pct + '%;background:#f59e0b;border-radius:2px;transition:width .25s;"></div></div>';
      _tourTip.innerHTML = progBar
        + '<div style="font-size:0.68rem;color:#b45309;font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px;">Step ' + prog + '</div>'
        + '<div style="font-weight:700;font-size:1rem;margin-bottom:8px;">' + step.title + '</div>'
        + '<div style="color:' + (_isDark() ? '#94a3b8' : '#475569') + ';line-height:1.55;margin-bottom:16px;font-size:0.87rem;">' + step.text + '</div>'
        + '<div style="display:flex;gap:8px;justify-content:flex-end;align-items:center;">'
        + (idx > 0 ? '<button id="bb-tb" style="padding:5px 13px;border:1px solid var(--border);border-radius:6px;background:transparent;cursor:pointer;font-size:0.82rem;color:' + _textColor() + ';">← Back</button>' : '')
        + (isLast
          ? '<button id="bb-td" style="padding:6px 18px;background:#d97706;color:#fff;border:none;border-radius:7px;cursor:pointer;font-size:0.85rem;font-weight:600;">Finish ✓</button>'
          : '<button id="bb-tn" style="padding:6px 18px;background:#d97706;color:#fff;border:none;border-radius:7px;cursor:pointer;font-size:0.85rem;font-weight:600;">Next →</button>')
        + '<button id="bb-ts" style="padding:5px 10px;border:none;background:transparent;color:#94a3b8;cursor:pointer;font-size:0.78rem;">Skip</button>'
        + '</div>';
      _tourTip.style.display = 'block';
      _tourOverlay.style.display = 'block';
      var tn = document.getElementById('bb-tn');
      var tb = document.getElementById('bb-tb');
      var td = document.getElementById('bb-td');
      var ts = document.getElementById('bb-ts');
      if (tn) tn.onclick = function () { _tourShow(idx + 1); };
      if (tb) tb.onclick = function () { _tourShow(idx - 1); };
      if (td) td.onclick = function () { _tourEnd(true); };
      if (ts) ts.onclick = function () { _tourEnd(false); };
    }, 220);
  }

  window.startBluebirdTour = function () {
    _tourCreate();
    _tourShow(0);
  };

  // ── Onboarding Walkthrough Modal ────────────────────────────────────────────

  var _FEATURES = [
    {
      icon: '🚨',
      title: 'One-Touch Emergency Alerts',
      desc: 'Staff tap one button on their phone to trigger a school-wide lockdown. All registered devices receive an immediate push notification with alarm sound — no app-open required.',
    },
    {
      icon: '👥',
      title: 'Role-Based Access Control',
      desc: 'Teachers, building admins, and district admins each have scoped permissions. District admins oversee multiple schools; building admins manage their own. No role can escalate beyond its own level.',
    },
    {
      icon: '🔐',
      title: 'Access Code Onboarding',
      desc: 'Generate QR codes or printable packets to onboard staff. Codes can be pre-assigned, time-limited, and tracked. Staff self-register — no IT involvement required.',
    },
    {
      icon: '📊',
      title: 'Analytics & Drill Reports',
      desc: 'Track response times, drill compliance rates, incident types, and per-building breakdowns. Exportable as PDF reports for compliance documentation.',
    },
    {
      icon: '🔇',
      title: 'Quiet Period Requests',
      desc: 'Teachers can request a quiet period for testing or assemblies. Admins approve or deny — all activity is logged in the audit trail with timestamps.',
    },
    {
      icon: '🏫',
      title: 'Multi-Tenant District Support',
      desc: 'District admins see all schools in one view. Each school is fully isolated — no data crosses tenant boundaries. Add, remove, or clone schools from the district dashboard.',
    },
  ];

  window.showDemoWalkthrough = function () {
    var existing = document.getElementById('bb-walkthrough-modal');
    if (existing) { existing.remove(); return; }
    try { localStorage.setItem(_WALK_KEY, '1'); } catch (e) {}
    var modal = document.createElement('div');
    modal.id = 'bb-walkthrough-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.55);z-index:9500;display:flex;align-items:center;justify-content:center;padding:20px;';
    var cards = _FEATURES.map(function (f) {
      return '<div style="display:flex;gap:14px;padding:14px 0;border-bottom:1px solid var(--border);">'
        + '<span style="font-size:1.8rem;line-height:1;flex-shrink:0;">' + f.icon + '</span>'
        + '<div><div style="font-weight:700;font-size:0.95rem;color:' + _textColor() + ';margin-bottom:4px;">' + f.title + '</div>'
        + '<div style="font-size:0.83rem;color:' + (_isDark() ? '#94a3b8' : '#475569') + ';line-height:1.5;">' + f.desc + '</div></div>'
        + '</div>';
    }).join('');
    modal.innerHTML = '<div style="background:' + _bgColor() + ';border-radius:16px;max-width:580px;width:100%;max-height:88vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,0.3);">'
      + '<div style="padding:24px 24px 0;">'
      + '<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;">'
      + '<div>'
      + '<div style="font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#1b5fe4;margin-bottom:4px;">DEMO SANDBOX</div>'
      + '<h2 style="margin:0;font-size:1.35rem;color:' + _textColor() + ';">What BlueBird Alerts Does</h2>'
      + '<p style="font-size:0.83rem;color:' + (_isDark() ? '#94a3b8' : '#64748b') + ';margin-top:6px;">Production-grade emergency alert platform built for K-12 school safety.</p>'
      + '</div>'
      + '<button id="bb-walk-close" style="border:none;background:transparent;font-size:1.4rem;cursor:pointer;color:' + _mutedColor() + ';padding:0 0 0 12px;line-height:1;">×</button>'
      + '</div></div>'
      + '<div style="padding:0 24px 24px;">' + cards
      + '<div style="display:flex;gap:10px;margin-top:20px;">'
      + '<button id="bb-walk-tour" style="flex:1;padding:10px 0;background:#1b5fe4;color:#fff;border:none;border-radius:8px;font-size:0.9rem;font-weight:600;cursor:pointer;">Start Guided Tour →</button>'
      + '<button id="bb-walk-ok" style="padding:10px 20px;background:transparent;border:1px solid var(--border);border-radius:8px;font-size:0.9rem;cursor:pointer;color:' + _textColor() + ';">Got It</button>'
      + '</div></div></div>';
    document.body.appendChild(modal);
    function _close() { modal.remove(); }
    document.getElementById('bb-walk-close').onclick = _close;
    document.getElementById('bb-walk-ok').onclick = _close;
    document.getElementById('bb-walk-tour').onclick = function () {
      _close();
      setTimeout(window.startBluebirdTour, 200);
    };
    modal.addEventListener('click', function (e) { if (e.target === modal) _close(); });
  };

  // ── Initialization ────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    safeRun('demo-analytics-auto', function () {
      if (document.getElementById('demo-analytics-body')) {
        var sect = document.querySelector('#demo-analytics');
        if (sect && !sect.hidden && sect.style.display !== 'none') {
          window.loadDemoAnalytics(30);
        }
      }
    });

    safeRun('demo-push-feed-auto', function () {
      var el = document.getElementById('demo-push-feed');
      if (el && _pushFeedUrl) {
        window.startPushFeedPoller('demo-push-feed');
      }
    });

    safeRun('demo-tour-autostart', function () {
      try {
        if (!localStorage.getItem(_TOUR_KEY)) {
          // Show walkthrough first, then offer tour
          if (!localStorage.getItem(_WALK_KEY)) {
            setTimeout(window.showDemoWalkthrough, 800);
          } else {
            setTimeout(window.startBluebirdTour, 600);
          }
        }
      } catch (e) {}
    });
  });

})();
