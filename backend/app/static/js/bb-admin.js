/* bb-admin.js — Admin dashboard JS modules.
 *
 * Expects window vars set inline before this script loads:
 *   BB_WS_API_KEY, BB_USER_ID, BB_HOME_TENANT, BB_TENANT_SLUG,
 *   BB_SHOW_DISTRICT_WS, BB_PATH_PREFIX
 *
 * Depends on bb-safe.js (safeRun, bbQs, bbOn) loaded first.
 */
'use strict';

// ── Alarm Form Handlers ───────────────────────────────────────────────────────
try {
  document.addEventListener('DOMContentLoaded', function () {
    var cb = document.getElementById('is_training');
    var warning = document.getElementById('live_alert_warning');
    if (cb && warning) {
      function syncWarning() {
        warning.style.display = cb.checked ? 'none' : 'block';
      }
      cb.addEventListener('change', syncWarning);
      syncWarning();
    }

    var activateForm = document.getElementById('alarm_activate_form');
    if (activateForm) {
      activateForm.addEventListener('submit', function (e) {
        var isTraining = document.getElementById('is_training') && document.getElementById('is_training').checked;
        var msg = isTraining
          ? 'Start a training drill?\n\nDrill alerts will be delivered in training mode (no live SMS delivery).'
          : '⚠ LIVE ALERT\n\nThis will send real emergency notifications to all registered devices for this school.\n\nContinue?';
        if (!confirm(msg)) { e.preventDefault(); }
      });
    }

    document.querySelectorAll('[data-confirm-deactivate]').forEach(function (form) {
      form.addEventListener('submit', function (e) {
        if (!confirm('End the active alarm?\n\nThis will clear the emergency state for all staff devices.')) {
          e.preventDefault();
        }
      });
    });
  });
} catch (e) { console.error('[BB] alarm-form', e); }

// ── WebSocket Connection ──────────────────────────────────────────────────────
try {
  (function () {
    var wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';

    function makeSingleSchoolWS() {
      if (!BB_WS_API_KEY || !BB_USER_ID || !BB_TENANT_SLUG) return;
      var url = wsProto + '//' + location.host + '/ws/' + BB_TENANT_SLUG + '/alerts'
        + '?user_id=' + BB_USER_ID + '&api_key=' + encodeURIComponent(BB_WS_API_KEY);
      var backoff = 1000;
      function connect() {
        var ws = new WebSocket(url);
        ws.onopen = function () { backoff = 1000; };
        ws.onmessage = function (evt) {
          try { var data = JSON.parse(evt.data); updateSingleSchoolUI(data); } catch (e) {}
        };
        ws.onclose = function (evt) {
          if (evt.code >= 4400 && evt.code < 4500) return;
          setTimeout(connect, backoff);
          backoff = Math.min(backoff * 2, 30000);
        };
      }
      connect();
    }

    function _loadUnacknowledged(alertId) {
      if (!alertId) return;
      var unackList = document.getElementById('js-unack-list');
      var unackCount = document.getElementById('js-unack-count');
      fetch(BB_PATH_PREFIX + '/admin/alerts/' + alertId + '/unacknowledged', { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function (data) {
          var users = data.unacknowledged || [];
          if (unackCount) {
            if (users.length) {
              unackCount.textContent = users.length + ' pending';
              unackCount.style.display = '';
            } else {
              unackCount.style.display = 'none';
            }
          }
          if (!unackList) return;
          if (!users.length) {
            unackList.innerHTML = '<span class="mini-copy" style="color:#16a34a;">All users acknowledged ✓</span>';
            return;
          }
          unackList.innerHTML = users.map(function (u) {
            var statusColor = u.presence_status === 'online' ? '#16a34a' : (u.presence_status === 'idle' ? '#d97706' : '#6b7280');
            var lastSeen = u.last_seen_at ? u.last_seen_at.slice(0, 16).replace('T', ' ') + ' UTC' : 'Never';
            return '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 10px;background:rgba(0,0,0,0.03);border-radius:6px;">'
              + '<div><div style="font-weight:600;">' + u.name + '</div>'
              + '<div style="font-size:0.72rem;color:var(--muted);">' + u.role + ' · Last seen: ' + lastSeen + '</div></div>'
              + '<span style="font-size:0.72rem;font-weight:700;color:' + statusColor + ';">' + u.presence_status + '</span>'
              + '</div>';
          }).join('');
        })
        .catch(function () {
          if (unackList) unackList.innerHTML = '<span class="mini-copy">Could not load user list.</span>';
        });
    }

    function updateSingleSchoolUI(data) {
      var pill = document.getElementById('js-alarm-status-pill');
      var ackPill = document.getElementById('js-ack-pill');
      if (!pill || !data.alarm) return;
      var alarm = data.alarm;
      var cls = 'ok';
      var label = 'Alarm clear';
      var msg = alarm.message || 'No active alarm';
      if (alarm.is_active && alarm.is_training) { cls = 'warn'; label = 'TRAINING ACTIVE'; }
      else if (alarm.is_active) { cls = 'danger'; label = 'ALARM ACTIVE'; }
      pill.className = 'status-pill ' + cls;
      pill.innerHTML = '<strong>' + label + '</strong>' + msg;

      var ackCount = alarm.acknowledgement_count || 0;
      if (ackPill) {
        if (alarm.is_active && ackCount > 0) {
          ackPill.style.display = '';
          ackPill.innerHTML = '<strong>Acknowledged</strong>' + ackCount + ' user' + (ackCount !== 1 ? 's' : '');
        } else {
          ackPill.style.display = 'none';
        }
      }

      // Progress bar
      var progressBar = document.getElementById('js-ack-progress-bar');
      var progressLabel = document.getElementById('js-ack-progress-label');
      var progressPct = document.getElementById('js-ack-progress-pct');
      if (progressBar && alarm.is_active) {
        var totalUsers = (typeof BB_ACTIVE_USERS !== 'undefined' ? BB_ACTIVE_USERS : 0);
        if (totalUsers > 0) {
          var pct = Math.min(Math.round(ackCount / totalUsers * 100), 100);
          var barColor = pct >= 90 ? '#16a34a' : (pct >= 60 ? '#d97706' : '#dc2626');
          progressBar.style.width = pct + '%';
          progressBar.style.background = barColor;
          if (progressLabel) progressLabel.textContent = ackCount + ' / ' + totalUsers + ' acknowledged';
          if (progressPct) { progressPct.textContent = pct + '%'; progressPct.style.color = barColor; }
        }
      }

      // Refresh unacked list on every ack event
      if (alarm.is_active && alarm.current_alert_id) {
        _loadUnacknowledged(alarm.current_alert_id);
      }
    }

    function makeDistrictWS() {
      if (!BB_SHOW_DISTRICT_WS || !BB_WS_API_KEY || !BB_USER_ID || !BB_HOME_TENANT) return;
      var badge = document.getElementById('dist-ws-badge');
      var url = wsProto + '//' + location.host + '/ws/district/alerts'
        + '?user_id=' + BB_USER_ID + '&home_tenant=' + encodeURIComponent(BB_HOME_TENANT)
        + '&api_key=' + encodeURIComponent(BB_WS_API_KEY);
      var backoff = 1000;
      function setBadge(state) {
        if (!badge) return;
        badge.style.display = '';
        if (state === 'live') {
          badge.className = 'status-pill ok';
          badge.innerHTML = '&#x25CF;&nbsp;Live';
        } else if (state === 'reconnecting') {
          badge.className = 'status-pill warn';
          badge.innerHTML = '&#x25CB;&nbsp;Reconnecting';
        } else {
          badge.className = 'status-pill danger';
          badge.innerHTML = '&#x25A0;&nbsp;Offline';
        }
      }
      function connect() {
        setBadge('reconnecting');
        var ws = new WebSocket(url);
        ws.onopen = function () { backoff = 1000; setBadge('live'); };
        ws.onmessage = function (evt) {
          try { var data = JSON.parse(evt.data); updateDistrictRow(data); } catch (e) {}
        };
        ws.onclose = function (evt) {
          setBadge(evt.code >= 4400 && evt.code < 4500 ? 'offline' : 'reconnecting');
          if (evt.code >= 4400 && evt.code < 4500) return;
          setTimeout(connect, backoff);
          backoff = Math.min(backoff * 2, 30000);
        };
      }
      connect();
    }

    function updateDistrictRow(data) {
      if (!data.tenant_slug || !data.alarm) return;
      var slug = data.tenant_slug;
      var alarm = data.alarm;
      var rows = document.querySelectorAll('#district-overview tr[data-tenant-slug="' + slug + '"]');
      rows.forEach(function (row) {
        var statusCell = row.querySelector('.dist-status-cell');
        var ackCell = row.querySelector('.dist-ack-cell');
        var lastCell = row.querySelector('.dist-last-cell');
        if (statusCell) {
          var badge = '';
          if (alarm.is_active && alarm.is_training) badge = '<span class="status-pill warn">TRAINING</span>';
          else if (alarm.is_active) badge = '<span class="status-pill danger">LOCKDOWN</span>';
          else badge = '<span class="status-pill ok">All Clear</span>';
          var note = (alarm.is_active && alarm.message) ? '<div class="mini-copy">' + alarm.message.substring(0, 80) + '</div>' : '';
          statusCell.innerHTML = badge + note;
        }
        if (ackCell) {
          var ackCount = alarm.acknowledgement_count || 0;
          var expectedUsers = parseInt(row.dataset.expectedUsers, 10) || 0;
          if (expectedUsers === 0) {
            ackCell.innerHTML = '<span class="mini-copy">No users</span>';
          } else {
            var rate = Math.round(ackCount / expectedUsers * 100);
            var cls = rate >= 90 ? 'ok' : (rate >= 60 ? 'warn' : 'danger');
            ackCell.innerHTML = '<span class="status-pill ' + cls + '">' + ackCount + '/' + expectedUsers + ' (' + rate + '%)</span>';
          }
        }
        if (lastCell && alarm.activated_at) {
          lastCell.textContent = (alarm.activated_at || '').substring(0, 16).replace('T', ' ');
        }
      });
    }

    document.addEventListener('DOMContentLoaded', function () {
      makeSingleSchoolWS();
      makeDistrictWS();
      // Initial load of unacknowledged users if an alarm is already active
      if (typeof BB_CURRENT_ALERT_ID !== 'undefined' && BB_CURRENT_ALERT_ID) {
        _loadUnacknowledged(BB_CURRENT_ALERT_ID);
      }
    });
  })();
} catch (e) { console.error('[BB] websocket', e); }

// ── Search / Filter ───────────────────────────────────────────────────────────
try {
  document.addEventListener('DOMContentLoaded', function () {
    function makeSearchFilter(inputId, containerSelector, rowSelector) {
      var input = document.getElementById(inputId);
      var container = document.querySelector(containerSelector);
      if (!input || !container) return;
      input.addEventListener('input', function () {
        var q = input.value.trim().toLowerCase();
        container.querySelectorAll(rowSelector).forEach(function (el) {
          el.style.display = (!q || el.textContent.toLowerCase().includes(q)) ? '' : 'none';
        });
      });
    }
    makeSearchFilter('audit-search', '#audit-events', 'tbody tr');
    makeSearchFilter('device-search', '#devices', 'tbody tr');
    makeSearchFilter('drill-search', '#drill-reports', 'tbody tr');
    makeSearchFilter('school-search', '#schools-grid', '.tenant-card');
    var userSearchEl = document.getElementById('user-search');
    if (userSearchEl) {
      userSearchEl.addEventListener('input', function () {
        var q = userSearchEl.value.trim().toLowerCase();
        document.querySelectorAll('.um-row').forEach(function (row) {
          var match = !q || row.textContent.toLowerCase().includes(q);
          row.style.display = match ? '' : 'none';
          var uid = row.dataset.uid;
          var editRow = document.getElementById('um-editcard-' + uid);
          if (editRow && !match) editRow.style.display = 'none';
        });
      });
    }
  });
} catch (e) { console.error('[BB] search-filter', e); }

// ── Enterprise User Management ────────────────────────────────────────────────
try {
  (function () {
    var ROLE_LABELS = {
      'teacher': 'Teacher / Standard', 'staff': 'Staff',
      'law_enforcement': 'Law Enforcement', 'admin': 'Admin',
      'building_admin': 'Building Admin', 'district_admin': 'District Admin',
      'super_admin': 'Super Admin'
    };
    var ROLE_PERMS = {
      'teacher': ['Send help requests', 'View incident feed', 'Submit quiet period request'],
      'staff': ['Send help requests', 'View incident feed', 'Submit quiet period request'],
      'law_enforcement': ['Send help requests', 'Submit quiet period request', 'View assigned incidents', 'Receive school alerts'],
      'admin': ['Manage school users', 'Trigger alerts', 'Approve quiet requests', 'Submit quiet period request'],
      'building_admin': ['Manage school users', 'Trigger alerts', 'Approve quiet requests', 'Submit quiet period request'],
      'district_admin': ['Manage all school users', 'Trigger alerts', 'Approve quiet requests', 'Manage district schools', 'Generate access codes'],
      'super_admin': ['Full platform access']
    };
    var ROLE_BADGE_CLS = {
      'district_admin': 'rb-district_admin', 'admin': 'rb-admin',
      'building_admin': 'rb-building_admin', 'teacher': 'rb-teacher',
      'staff': 'rb-staff', 'law_enforcement': 'rb-law_enforcement', 'super_admin': 'rb-super_admin'
    };
    var panel = document.getElementById('um-panel');
    var overlay = document.getElementById('um-overlay');
    var roleModal = document.getElementById('um-role-modal');
    var pendingRoleForm = null;
    var openEditId = null;

    function roleBadgeHtml(role) {
      return '<span class="role-badge ' + (ROLE_BADGE_CLS[role] || '') + '">' + (ROLE_LABELS[role] || role) + '</span>';
    }

    function openPanel(userData) {
      var role = userData.role || 'teacher';
      var av = document.getElementById('up-avatar');
      if (av) {
        av.className = 'um-panel-avatar ua-' + role;
        var initials = (userData.name || '?').split(' ').map(function (w) { return w[0] || ''; }).join('').slice(0, 2).toUpperCase();
        av.textContent = initials;
      }
      var el = function (id) { return document.getElementById(id); };
      if (el('up-name')) el('up-name').textContent = userData.name || '';
      if (el('up-role-badge')) el('up-role-badge').innerHTML = roleBadgeHtml(role);
      var statusCls = userData.is_archived ? 'offline' : (userData.is_active ? 'ok' : 'danger');
      var statusTxt = userData.is_archived ? 'Archived' : (userData.is_active ? 'Active' : 'Inactive');
      if (el('up-status-pill')) el('up-status-pill').innerHTML = '<span class="status-pill ' + statusCls + '" style="font-size:.76rem;min-height:0;padding:3px 10px;">' + statusTxt + '</span>';
      var metaParts = [];
      if (userData.title) metaParts.push(userData.title);
      if (userData.phone) metaParts.push(userData.phone);
      if (el('up-meta')) el('up-meta').textContent = metaParts.join(' · ') || 'No additional info';
      if (el('up-login')) el('up-login').textContent = userData.login || '—';
      if (el('up-last-login')) el('up-last-login').textContent = userData.last_login || 'Never';
      if (el('up-uid')) el('up-uid').textContent = '#' + userData.id;
      var perms = ROLE_PERMS[role] || [];
      if (el('up-perms')) {
        el('up-perms').innerHTML = perms.map(function (p) {
          return '<div class="um-perm-item"><div class="um-perm-dot"></div><span>' + p + '</span></div>';
        }).join('') || '<span class="mini-copy">No permissions defined</span>';
      }
      if (el('up-actions')) {
        var isSelf = userData.is_self;
        var isArch = !!userData.is_archived;
        var canModify = userData.can_modify !== false;
        var editBtn = '';
        var protectedNote = '';
        if (!isArch) {
          if (canModify) {
            editBtn = '<button class="button button-primary" style="min-height:36px;font-size:0.82rem;" onclick="umToggleEdit(' + userData.id + ');umClosePanel();">Edit User</button>';
          } else {
            protectedNote = '<p class="mini-copy" style="color:#7c3aed;">&#128274; Protected Role — only district admins can modify this account.</p>';
          }
        }
        var selfNote = (!isArch && isSelf && canModify) ? '<p class="mini-copy" style="color:#b45309;">You cannot modify your own account role.</p>' : '';
        var archNote = (isArch && canModify) ? '<p class="mini-copy" style="color:var(--danger);">This user is archived. Use the Archived tab to restore or delete them.</p>' : '';
        el('up-actions').innerHTML = editBtn + protectedNote + selfNote + archNote;
      }
      var tlEl = el('up-timeline');
      if (tlEl) {
        tlEl.innerHTML = '<span style="color:var(--muted);">Loading…</span>';
        fetch(BB_PATH_PREFIX + '/admin/users/' + userData.id + '/audit', { credentials: 'same-origin' })
          .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
          .then(function (events) {
            if (!events || !events.length) {
              tlEl.innerHTML = '<span style="color:var(--muted);">No activity recorded yet.</span>';
              return;
            }
            var EVENT_LABELS = {
              'user_created': 'Created', 'user_archived': 'Archived', 'user_restored': 'Restored',
              'user_deleted': 'Deleted', 'user_updated': 'Updated', 'role_changed': 'Role changed',
              'login': 'Login', 'login_failed': 'Login failed', 'password_changed': 'Password changed',
              'totp_enabled': '2FA enabled', 'totp_disabled': '2FA disabled',
            };
            var html = '<div style="position:relative;padding-left:20px;">';
            events.forEach(function (ev) {
              var label = EVENT_LABELS[ev.event_type] || ev.event_type;
              var ts = (ev.timestamp || '').slice(0, 16).replace('T', ' ');
              var actor = ev.actor_label ? ' by ' + ev.actor_label : '';
              html += '<div style="margin-bottom:10px;position:relative;">'
                + '<div style="position:absolute;left:-18px;top:4px;width:8px;height:8px;border-radius:50%;background:var(--accent);"></div>'
                + '<div style="font-weight:600;font-size:0.78rem;">' + label + '</div>'
                + '<div style="color:var(--muted);font-size:0.72rem;">' + ts + actor + '</div>'
                + '</div>';
            });
            html += '</div>';
            tlEl.innerHTML = html;
          })
          .catch(function () { tlEl.innerHTML = '<span style="color:var(--muted);">Could not load timeline.</span>'; });
      }
      document.querySelectorAll('.um-row').forEach(function (r) { r.classList.remove('um-row-active'); });
      var activeRow = document.querySelector('.um-row[data-uid="' + userData.id + '"]');
      if (activeRow) activeRow.classList.add('um-row-active');
      panel.classList.add('open');
      overlay.classList.add('open');
    }

    window.umClosePanel = function () {
      if (panel) panel.classList.remove('open');
      if (overlay) overlay.classList.remove('open');
      document.querySelectorAll('.um-row').forEach(function (r) { r.classList.remove('um-row-active'); });
    };

    window.umToggleEdit = function (uid) {
      var card = document.getElementById('um-editcard-' + uid);
      if (!card) return;
      if (openEditId && openEditId !== uid) {
        var prev = document.getElementById('um-editcard-' + openEditId);
        if (prev) prev.style.display = 'none';
      }
      var nowOpen = card.style.display !== 'none';
      card.style.display = nowOpen ? 'none' : 'block';
      openEditId = nowOpen ? null : uid;
      if (!nowOpen) card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };

    window.umToggleCreate = function () {
      var wrap = document.getElementById('um-create-wrap');
      if (!wrap) return;
      var nowOpen = wrap.style.display !== 'none';
      wrap.style.display = nowOpen ? 'none' : 'block';
      if (!nowOpen) wrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    document.addEventListener('DOMContentLoaded', function () {
      document.querySelectorAll('.um-row').forEach(function (row) {
        row.addEventListener('click', function (e) {
          if (e.target.closest('button, a, input, select, form')) return;
          try {
            var userData = JSON.parse(row.dataset.user);
            openPanel(userData);
          } catch (err) {}
        });
      });

      if (overlay) overlay.addEventListener('click', window.umClosePanel);
      var closeBtn = document.getElementById('um-panel-close');
      if (closeBtn) closeBtn.addEventListener('click', window.umClosePanel);

      document.querySelectorAll('form[data-role-change]').forEach(function (form) {
        form.addEventListener('submit', function (e) {
          if (form.dataset.skipConfirm) { delete form.dataset.skipConfirm; return; }
          var sel = form.querySelector('select[name="role"]');
          if (!sel) return;
          var oldRole = form.dataset.currentRole || '';
          var newRole = sel.value;
          if (!newRole || newRole === oldRole) return;
          e.preventDefault();
          pendingRoleForm = form;
          var el = function (id) { return document.getElementById(id); };
          if (el('rm-user')) el('rm-user').textContent = form.dataset.userName || 'this user';
          if (el('rm-old-role')) el('rm-old-role').textContent = ROLE_LABELS[oldRole] || oldRole;
          if (el('rm-new-role')) el('rm-new-role').textContent = ROLE_LABELS[newRole] || newRole;
          var warn = el('rm-warning');
          if (warn) {
            if (newRole === 'district_admin') {
              warn.textContent = 'This grants full administrative control over the district. This action is audited.';
              warn.style.display = '';
            } else if (newRole === 'admin' || newRole === 'building_admin') {
              warn.textContent = 'This grants dashboard access and admin capabilities. This action is audited.';
              warn.style.display = '';
            } else {
              warn.style.display = 'none';
            }
          }
          var confirmBtn = el('rm-confirm');
          if (confirmBtn) {
            var isElevation = ['admin', 'building_admin', 'district_admin'].includes(newRole);
            confirmBtn.className = isElevation ? 'button button-danger' : 'button button-primary';
          }
          if (roleModal) roleModal.classList.add('open');
        });
      });

      var rmCancel = document.getElementById('rm-cancel');
      if (rmCancel) rmCancel.addEventListener('click', function () {
        if (roleModal) roleModal.classList.remove('open');
        pendingRoleForm = null;
      });
      var rmConfirm = document.getElementById('rm-confirm');
      if (rmConfirm) rmConfirm.addEventListener('click', function () {
        if (roleModal) roleModal.classList.remove('open');
        if (pendingRoleForm) {
          pendingRoleForm.dataset.skipConfirm = '1';
          pendingRoleForm.submit();
          pendingRoleForm = null;
        }
      });

      var deleteModal = document.getElementById('um-delete-modal');
      var _dmPendingUrl = null;
      window.umOpenDeleteModal = function (url, userName) {
        _dmPendingUrl = url;
        var nameEl = document.getElementById('dm-user-name');
        if (nameEl) nameEl.textContent = userName || 'this user';
        if (deleteModal) deleteModal.classList.add('open');
      };
      var dmCancel = document.getElementById('dm-cancel');
      if (dmCancel) dmCancel.addEventListener('click', function () {
        if (deleteModal) deleteModal.classList.remove('open');
        _dmPendingUrl = null;
      });
      var dmConfirm = document.getElementById('dm-confirm');
      if (dmConfirm) dmConfirm.addEventListener('click', function () {
        if (!_dmPendingUrl) return;
        if (deleteModal) deleteModal.classList.remove('open');
        var f = document.createElement('form');
        f.method = 'post';
        f.action = _dmPendingUrl;
        document.body.appendChild(f);
        f.submit();
      });

      var bulkBar = document.getElementById('um-bulk-bar');
      var bulkCountEl = document.getElementById('um-bulk-count');
      var bulkModal = document.getElementById('um-bulk-modal');
      var _bulkAction = null;

      function getCheckedUids() {
        return Array.from(document.querySelectorAll('.um-bulk-cb:checked')).map(function (cb) { return parseInt(cb.dataset.uid, 10); });
      }
      function updateBulkBar() {
        var uids = getCheckedUids();
        if (bulkBar) bulkBar.style.display = uids.length ? 'flex' : 'none';
        if (bulkCountEl) bulkCountEl.textContent = uids.length + ' user' + (uids.length !== 1 ? 's' : '') + ' selected';
        var selAll = document.getElementById('um-select-all');
        if (selAll) {
          var total = document.querySelectorAll('.um-bulk-cb').length;
          selAll.indeterminate = uids.length > 0 && uids.length < total;
          selAll.checked = total > 0 && uids.length === total;
        }
      }
      document.querySelectorAll('.um-bulk-cb').forEach(function (cb) {
        cb.addEventListener('change', updateBulkBar);
      });
      var selAll = document.getElementById('um-select-all');
      if (selAll) {
        selAll.addEventListener('change', function () {
          document.querySelectorAll('.um-bulk-cb').forEach(function (cb) { cb.checked = selAll.checked; });
          updateBulkBar();
        });
      }
      var bulkClearBtn = document.getElementById('um-bulk-clear-btn');
      if (bulkClearBtn) {
        bulkClearBtn.addEventListener('click', function () {
          document.querySelectorAll('.um-bulk-cb').forEach(function (cb) { cb.checked = false; });
          updateBulkBar();
        });
      }

      function openBulkModal(action, label, warningText) {
        _bulkAction = action;
        var uids = getCheckedUids();
        var titleEl = document.getElementById('bm-title');
        var countEl = document.getElementById('bm-count');
        var pluralEl = document.getElementById('bm-plural');
        var warnEl = document.getElementById('bm-warning');
        var confirmBtn = document.getElementById('bm-confirm');
        if (titleEl) titleEl.textContent = label;
        if (countEl) countEl.textContent = uids.length;
        if (pluralEl) pluralEl.textContent = uids.length !== 1 ? 's' : '';
        if (warnEl) { warnEl.textContent = warningText || ''; warnEl.style.display = warningText ? '' : 'none'; }
        if (confirmBtn) confirmBtn.className = action === 'archive' ? 'button button-danger' : 'button button-primary';
        if (bulkModal) bulkModal.classList.add('open');
      }

      var bulkArchiveBtn = document.getElementById('um-bulk-archive-btn');
      if (bulkArchiveBtn) {
        bulkArchiveBtn.addEventListener('click', function () {
          openBulkModal('archive', 'Bulk Archive Users', 'Archived users will be deactivated and cannot log in.');
        });
      }
      var bmCancel = document.getElementById('bm-cancel');
      if (bmCancel) {
        bmCancel.addEventListener('click', function () {
          if (bulkModal) bulkModal.classList.remove('open');
          _bulkAction = null;
        });
      }
      var bmConfirm = document.getElementById('bm-confirm');
      if (bmConfirm) {
        bmConfirm.addEventListener('click', function () {
          if (bulkModal) bulkModal.classList.remove('open');
          var uids = getCheckedUids();
          if (!uids.length || !_bulkAction) return;
          var endpoint = BB_PATH_PREFIX + '/admin/users/bulk-' + _bulkAction;
          fetch(endpoint, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_ids: uids })
          }).then(function (r) { return r.json(); }).then(function (data) {
            var msg = (data.success_count || 0) + ' user(s) ' + _bulkAction + 'd.';
            if (data.skipped_count) msg += ' ' + data.skipped_count + ' skipped (protected role or not allowed).';
            alert(msg);
            window.location.reload();
          }).catch(function () { alert('Bulk action failed. Please try again.'); });
          _bulkAction = null;
        });
      }
    });

    // View-As modal
    var vaModal = document.getElementById('um-viewas-modal');
    var vaBody = document.getElementById('va-body');
    var vaTitle = document.getElementById('va-title');
    window.umOpenViewAs = function (uid, userName) {
      if (vaTitle) vaTitle.textContent = 'View As: ' + userName + ' — Read Only';
      if (vaBody) vaBody.innerHTML = '<div style="color:var(--muted);text-align:center;padding:24px 0;">Loading…</div>';
      if (vaModal) vaModal.classList.add('open');
      fetch(BB_PATH_PREFIX + '/admin/users/' + uid + '/view-as', { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function (d) {
          if (!vaBody) return;
          var u = d.user || {};
          var ctx = d.tenant_context || {};
          var qp = d.quiet_period_status || {};
          var alarmBanner = ctx.alarm_active
            ? '<div style="background:rgba(220,38,38,0.1);border:1px solid rgba(220,38,38,0.3);border-radius:6px;padding:8px 12px;margin-bottom:10px;">'
              + '<strong style="color:#dc2626;">' + (ctx.alarm_is_training ? '⚠ Training Drill Active' : '⚠ ALARM ACTIVE') + '</strong>'
              + (ctx.alarm_message ? '<br/><span style="font-size:0.8rem;">' + ctx.alarm_message + '</span>' : '')
              + '</div>'
            : '';
          var infoRows = [
            ['Role', u.role || '—'], ['Status', u.is_active ? 'Active' : 'Inactive'],
            ['Username', u.login_name || '—'], ['Title', u.title || '—'],
            ['Phone', u.phone || '—'], ['Last login', (u.last_login_at || '').slice(0, 16).replace('T', ' ') || 'Never'],
            ['School', ctx.school_name || '—'],
          ];
          var infoHtml = '<table style="width:100%;border-collapse:collapse;font-size:0.83rem;margin-bottom:14px;">'
            + infoRows.map(function (r) {
              return '<tr><td style="color:var(--muted);padding:4px 0;width:38%;">' + r[0] + '</td>'
                + '<td style="font-weight:500;padding:4px 0;">' + r[1] + '</td></tr>';
            }).join('') + '</table>';
          var alertsHtml = '';
          if (d.visible_alerts && d.visible_alerts.length) {
            alertsHtml = '<div style="margin-bottom:14px;"><div class="um-panel-sect-label">Recent School Alerts</div><div style="display:grid;gap:6px;">'
              + d.visible_alerts.map(function (a) {
                var tag = a.is_training ? ' <span style="font-size:0.7rem;color:#b45309;">[Training]</span>' : ' <span style="font-size:0.7rem;color:#dc2626;">[Emergency]</span>';
                return '<div style="padding:6px 10px;background:rgba(0,0,0,0.03);border-radius:6px;font-size:0.8rem;">'
                  + tag + ' ' + (a.message || '—')
                  + '<div style="color:var(--muted);font-size:0.72rem;">' + (a.created_at || '').slice(0, 16).replace('T', ' ') + '</div></div>';
              }).join('') + '</div></div>';
          } else {
            alertsHtml = '<div style="margin-bottom:14px;"><div class="um-panel-sect-label">Recent School Alerts</div><span class="mini-copy">No alerts on record.</span></div>';
          }
          var helpsHtml = '';
          if (d.visible_help_requests && d.visible_help_requests.length) {
            helpsHtml = '<div style="margin-bottom:14px;"><div class="um-panel-sect-label">Active Help Requests</div><div style="display:grid;gap:6px;">'
              + d.visible_help_requests.map(function (h) {
                return '<div style="padding:6px 10px;background:rgba(0,0,0,0.03);border-radius:6px;font-size:0.8rem;">'
                  + (h.type || 'request') + ' — ' + (h.status || '—')
                  + '<div style="color:var(--muted);font-size:0.72rem;">' + (h.created_at || '').slice(0, 16).replace('T', ' ') + '</div></div>';
              }).join('') + '</div></div>';
          }
          var qpHtml = '<div style="margin-bottom:6px;"><div class="um-panel-sect-label">Quiet Period Status</div>'
            + '<div style="font-size:0.83rem;">'
            + (qp.active ? '✅ Active quiet period — expires ' + ((qp.expires_at || '').slice(0, 16).replace('T', ' ') || 'unknown')
              : (qp.pending ? '⏳ Pending approval' : '— No active quiet period'))
            + '</div></div>';
          vaBody.innerHTML = alarmBanner + infoHtml + alertsHtml + helpsHtml + qpHtml;
        })
        .catch(function (e) {
          if (vaBody) vaBody.innerHTML = '<div style="color:var(--danger);">Could not load view-as data (code: ' + e + ').</div>';
        });
    };
    var vaClose = document.getElementById('va-close');
    if (vaClose) vaClose.addEventListener('click', function () { if (vaModal) vaModal.classList.remove('open'); });
    if (vaModal) vaModal.addEventListener('click', function (e) { if (e.target === vaModal) vaModal.classList.remove('open'); });
  })();
} catch (e) { console.error('[BB] user-management', e); }

// ── Analytics + District Reports ──────────────────────────────────────────────
try {
  (function () {

    // ── Helpers ──────────────────────────────────────────────────────────────

    function fmtSeconds(s) {
      if (s === null || s === undefined) return '—';
      if (s < 60) return Math.round(s) + 's';
      return Math.round(s / 60) + 'm ' + (Math.round(s) % 60) + 's';
    }

    function _esc(s) {
      return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function _statChip(label, val, color) {
      return '<div style="background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 16px;min-width:90px;">'
        + '<div style="font-size:0.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.04em;margin-bottom:3px;">' + label + '</div>'
        + '<div style="font-size:1.5rem;font-weight:700;color:' + color + ';line-height:1;">' + val + '</div>'
        + '</div>';
    }

    // ── SVG Primitives ───────────────────────────────────────────────────────

    /* Sparkline: compact 72×22 trend line for table rows. */
    function _svgSparkline(counts) {
      var n = counts.length;
      if (!n) return '<span style="color:var(--muted);font-size:0.7rem;">—</span>';
      var max = Math.max.apply(null, counts) || 1;
      var W = 72, H = 22, pad = 2;
      var step = n > 1 ? (W - pad * 2) / (n - 1) : 0;
      var pts = counts.map(function (v, i) {
        return (pad + i * step).toFixed(1) + ',' + (pad + (H - pad * 2) * (1 - v / max)).toFixed(1);
      }).join(' ');
      var hasActivity = max > 0;
      return '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" style="display:block;overflow:visible;">'
        + (hasActivity
          ? '<polyline points="' + pts + '" fill="none" stroke="#3b82f6" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
          : '<line x1="' + pad + '" y1="' + (H / 2) + '" x2="' + (W - pad) + '" y2="' + (H / 2) + '" stroke="var(--border)" stroke-width="1"/>')
        + '</svg>';
    }

    /* Area chart: full-width SVG with date labels, for the district trend. */
    function _svgAreaChart(trend) {
      var counts = trend.map(function (t) { return t.c || 0; });
      var dates  = trend.map(function (t) { return t.d || ''; });
      var n = counts.length;
      if (!n) return '';
      var max = Math.max.apply(null, counts) || 1;
      var W = 600, H = 120, pL = 30, pR = 8, pT = 10, pB = 22;
      var iW = W - pL - pR, iH = H - pT - pB;
      function px(i) { return pL + (n > 1 ? iW * i / (n - 1) : iW / 2); }
      function py(v) { return pT + iH * (1 - v / max); }
      var linePts = counts.map(function (v, i) { return px(i).toFixed(1) + ',' + py(v).toFixed(1); }).join(' ');
      var area = 'M' + px(0).toFixed(1) + ',' + (pT + iH).toFixed(1)
        + ' ' + counts.map(function (v, i) { return 'L' + px(i).toFixed(1) + ',' + py(v).toFixed(1); }).join(' ')
        + ' L' + px(n - 1).toFixed(1) + ',' + (pT + iH).toFixed(1) + ' Z';
      var grid = [0, 0.5, 1].map(function (f) {
        var y = (pT + iH * f).toFixed(1);
        return '<line x1="' + pL + '" y1="' + y + '" x2="' + (W - pR) + '" y2="' + y + '" stroke="var(--border)" stroke-width="0.5"/>';
      }).join('');
      var yLbl = '<text x="0" y="' + (pT + 4) + '" font-size="9" fill="var(--muted)" dominant-baseline="middle">' + max + '</text>';
      var xLbls = [0, Math.floor((n - 1) / 2), n - 1].filter(function (i) { return i < n; }).map(function (i) {
        var d = dates[i] ? dates[i].slice(5) : '';
        return '<text x="' + px(i).toFixed(1) + '" y="' + (H - 2) + '" text-anchor="middle" font-size="9" fill="var(--muted)">' + d + '</text>';
      }).join('');
      return '<svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;height:120px;display:block;" preserveAspectRatio="none">'
        + grid + yLbl
        + '<path d="' + area + '" fill="rgba(59,130,246,0.1)"/>'
        + '<polyline points="' + linePts + '" fill="none" stroke="#3b82f6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        + xLbls + '</svg>';
    }

    // ── Per-building panel (Analytics section) ───────────────────────────────

    function _buildingDetailCard(b) {
      var lastAlert = b.last_alert_at ? b.last_alert_at.slice(0, 16).replace('T', ' ') : 'Never';
      var drillPct = b.drill_rate != null ? Math.round(b.drill_rate * 100) : null;
      var drillBar = drillPct != null
        ? '<div style="margin-top:10px;">'
            + '<div style="display:flex;justify-content:space-between;font-size:0.68rem;color:var(--muted);margin-bottom:3px;"><span>Drill Rate</span><span>' + drillPct + '%</span></div>'
            + '<div style="background:var(--border);border-radius:3px;height:4px;"><div style="background:#3b82f6;width:' + drillPct + '%;height:100%;border-radius:3px;"></div></div>'
            + '</div>'
        : '';
      var userBadge = b.active_users ? '<div style="font-size:0.7rem;color:var(--muted);margin-top:6px;">' + b.active_users + ' active users</div>' : '';
      return '<div class="signal-card" style="padding:14px 16px;min-width:220px;">'
        + '<div style="font-weight:700;font-size:0.88rem;margin-bottom:10px;">' + _esc(b.building_name) + '</div>'
        + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:0.8rem;">'
        + '<div><div style="color:var(--muted);font-size:0.68rem;">Emergency</div><div style="font-weight:700;color:#dc2626;font-size:1.1rem;">' + (b.emergency_alerts || 0) + '</div></div>'
        + '<div><div style="color:var(--muted);font-size:0.68rem;">Training</div><div style="font-weight:700;color:#2563eb;font-size:1.1rem;">' + (b.training_alerts || 0) + '</div></div>'
        + '<div><div style="color:var(--muted);font-size:0.68rem;">Help Requests</div><div style="font-weight:600;">' + (b.help_requests || 0) + ' <span style="color:#b45309;font-size:0.72rem;">(' + (b.cancelled_help_requests || 0) + '✗)</span></div></div>'
        + '<div><div style="color:var(--muted);font-size:0.68rem;">Quiet Requests</div><div style="font-weight:600;">' + (b.quiet_period_requests || 0) + '</div></div>'
        + '<div><div style="color:var(--muted);font-size:0.68rem;">Avg Ack</div><div style="font-weight:600;">' + fmtSeconds(b.avg_ack_time_seconds) + '</div></div>'
        + '<div><div style="color:var(--muted);font-size:0.68rem;">Last Alert</div><div style="font-size:0.75rem;">' + lastAlert + '</div></div>'
        + '</div>'
        + drillBar + userBadge
        + '</div>';
    }

    function renderBuildingPanel(buildings, containerId) {
      var container = document.getElementById(containerId);
      if (!container) return;
      if (!buildings || !buildings.length) {
        container.innerHTML = '<p class="mini-copy">No data available for this period.</p>';
        return;
      }

      var totEmerg = buildings.reduce(function (s, b) { return s + (b.emergency_alerts || 0); }, 0);
      var totTrain = buildings.reduce(function (s, b) { return s + (b.training_alerts || 0); }, 0);
      var totHelp  = buildings.reduce(function (s, b) { return s + (b.help_requests || 0); }, 0);

      /* Summary chips */
      var summary = '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px;">'
        + _statChip('Emergency', totEmerg, '#dc2626')
        + _statChip('Training', totTrain, '#2563eb')
        + _statChip('Help Requests', totHelp, '#d97706')
        + _statChip('Buildings', buildings.length, 'var(--accent)')
        + '</div>';

      /* Comparison table with sparklines */
      var sorted = buildings.slice().sort(function (a, b) { return (b.emergency_alerts || 0) - (a.emergency_alerts || 0); });
      var tableRows = sorted.map(function (b) {
        var spark = b.alert_trend ? _svgSparkline(b.alert_trend.map(function (t) { return t.c; })) : '';
        return '<tr style="border-bottom:1px solid var(--border);">'
          + '<td style="padding:8px 6px;font-weight:600;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + _esc(b.building_name) + '</td>'
          + '<td style="padding:8px 6px;text-align:right;color:#dc2626;font-weight:700;">' + (b.emergency_alerts || 0) + '</td>'
          + '<td style="padding:8px 6px;text-align:right;color:#2563eb;">' + (b.training_alerts || 0) + '</td>'
          + '<td style="padding:8px 6px;text-align:right;">' + (b.help_requests || 0) + '</td>'
          + '<td style="padding:8px 6px;text-align:right;font-size:0.78rem;white-space:nowrap;">' + fmtSeconds(b.avg_ack_time_seconds) + '</td>'
          + '<td style="padding:8px 6px;">' + spark + '</td>'
          + '</tr>';
      }).join('');
      var table = '<div style="overflow-x:auto;margin-bottom:20px;">'
        + '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;">'
        + '<thead><tr style="border-bottom:2px solid var(--border);">'
        + '<th style="padding:6px;text-align:left;color:var(--muted);font-weight:600;font-size:0.74rem;">Building</th>'
        + '<th style="padding:6px;text-align:right;color:var(--muted);font-weight:600;font-size:0.74rem;">Emergency</th>'
        + '<th style="padding:6px;text-align:right;color:var(--muted);font-weight:600;font-size:0.74rem;">Training</th>'
        + '<th style="padding:6px;text-align:right;color:var(--muted);font-weight:600;font-size:0.74rem;">Help</th>'
        + '<th style="padding:6px;text-align:right;color:var(--muted);font-weight:600;font-size:0.74rem;">Avg Ack</th>'
        + '<th style="padding:6px;color:var(--muted);font-weight:600;font-size:0.74rem;">30-day Trend</th>'
        + '</thead><tbody>' + tableRows + '</tbody></table></div>';

      /* Detail cards */
      var cards = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;">'
        + sorted.map(_buildingDetailCard).join('') + '</div>';

      container.innerHTML = summary + table + cards;
    }

    // ── District dashboard (District Reports section) ────────────────────────

    function renderDistrictPanel(buildings, containerId, days) {
      var container = document.getElementById(containerId);
      if (!container) return;
      if (!buildings || !buildings.length) {
        container.innerHTML = '<p class="mini-copy">No district data available.</p>';
        return;
      }

      var totEmerg   = buildings.reduce(function (s, b) { return s + (b.emergency_alerts || 0); }, 0);
      var totTrain   = buildings.reduce(function (s, b) { return s + (b.training_alerts || 0); }, 0);
      var totHelp    = buildings.reduce(function (s, b) { return s + (b.help_requests || 0); }, 0);
      var totQP      = buildings.reduce(function (s, b) { return s + (b.quiet_period_requests || 0); }, 0);
      var totOnline  = buildings.reduce(function (s, b) { return s + (b.devices_online || 0); }, 0);
      var totDevices = buildings.reduce(function (s, b) { return s + (b.device_count || 0); }, 0);
      var ackRates   = buildings.filter(function (b) { return b.ack_rate != null; }).map(function (b) { return b.ack_rate; });
      var avgAckRate = ackRates.length ? Math.round(ackRates.reduce(function (s, r) { return s + r; }, 0) / ackRates.length) : null;

      var summary = '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px;">'
        + _statChip('Total Alerts', totEmerg + totTrain, '#1d4ed8')
        + _statChip('Emergency', totEmerg, '#dc2626')
        + _statChip('Training', totTrain, '#2563eb')
        + _statChip('Help Requests', totHelp, '#d97706')
        + _statChip('Quiet Requests', totQP, '#7c3aed')
        + _statChip('Buildings', buildings.length, 'var(--accent)')
        + (avgAckRate != null ? _statChip('Avg Ack Rate', avgAckRate + '%', avgAckRate >= 80 ? '#16a34a' : avgAckRate >= 50 ? '#d97706' : '#dc2626') : '')
        + (totDevices > 0 ? _statChip('Online Devices', totOnline + ' / ' + totDevices, '#0ea5e9') : '')
        + '</div>';

      /* Aggregate daily trend across all buildings */
      var trendMap = {};
      buildings.forEach(function (b) {
        if (!b.alert_trend) return;
        b.alert_trend.forEach(function (t) {
          trendMap[t.d] = (trendMap[t.d] || 0) + (t.c || 0);
        });
      });
      var trendDates = Object.keys(trendMap).sort();
      var trendData = trendDates.map(function (d) { return { d: d, c: trendMap[d] }; });

      var chartSection = '';
      if (trendData.length >= 3) {
        chartSection = '<div style="background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px 16px;margin-bottom:20px;">'
          + '<p style="font-size:0.72rem;color:var(--muted);margin:0 0 8px;text-transform:uppercase;letter-spacing:0.04em;">Daily Alert Trend — Last ' + days + ' days</p>'
          + _svgAreaChart(trendData)
          + '<div style="display:flex;gap:16px;margin-top:8px;font-size:0.72rem;color:var(--muted);">'
          + '<span style="display:flex;align-items:center;gap:4px;"><span style="display:inline-block;width:10px;height:2px;background:#3b82f6;border-radius:1px;"></span>All alerts</span>'
          + '</div></div>';
      }

      /* Building comparison table — alerts, ack rate, device coverage */
      var sortedB = buildings.slice().sort(function (a, b) { return (b.emergency_alerts || 0) - (a.emergency_alerts || 0); });
      var maxE = Math.max.apply(null, sortedB.map(function (b) { return b.emergency_alerts || 0; })) || 1;

      var tableRows = sortedB.map(function (b) {
        var ePct = Math.max(Math.round(((b.emergency_alerts || 0) / maxE) * 100), (b.emergency_alerts ? 2 : 0));
        var tPct = Math.max(Math.round(((b.training_alerts || 0) / maxE) * 100), (b.training_alerts ? 2 : 0));
        var ackCell = b.ack_rate != null
          ? '<span style="font-weight:700;color:' + (b.ack_rate >= 80 ? '#16a34a' : b.ack_rate >= 50 ? '#d97706' : '#dc2626') + ';">' + b.ack_rate + '%</span>'
          : '<span style="color:var(--muted);">—</span>';
        var devTotal = b.device_count || 0;
        var devOnline = b.devices_online || 0;
        var devCell = devTotal > 0
          ? devOnline + '<span style="color:var(--muted);font-size:0.7rem;"> / ' + devTotal + '</span>'
          : '<span style="color:var(--muted);">—</span>';
        return '<tr style="border-bottom:1px solid var(--border);">'
          + '<td style="padding:8px 6px;font-weight:600;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + _esc(b.building_name) + '</td>'
          + '<td style="padding:8px 6px;">'
          + '<div style="display:flex;gap:2px;align-items:center;height:8px;min-width:80px;">'
          + '<div style="background:#dc2626;height:100%;width:' + ePct + '%;border-radius:2px;"></div>'
          + '<div style="background:#3b82f6;height:100%;width:' + tPct + '%;border-radius:2px;opacity:0.7;"></div>'
          + '</div></td>'
          + '<td style="padding:8px 6px;text-align:right;font-size:0.78rem;color:var(--muted);">' + (b.emergency_alerts || 0) + 'E / ' + (b.training_alerts || 0) + 'T</td>'
          + '<td style="padding:8px 6px;text-align:right;font-size:0.8rem;">' + ackCell + '</td>'
          + '<td style="padding:8px 6px;text-align:right;font-size:0.78rem;">' + devCell + '</td>'
          + '<td style="padding:8px 6px;text-align:right;font-size:0.76rem;color:var(--muted);">' + fmtSeconds(b.avg_ack_time_seconds) + '</td>'
          + '</tr>';
      }).join('');

      var rank = '<div style="margin-bottom:16px;">'
        + '<p style="font-size:0.72rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.04em;margin:0 0 10px;">Building Comparison</p>'
        + '<div style="overflow-x:auto;">'
        + '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;">'
        + '<thead><tr style="border-bottom:2px solid var(--border);">'
        + '<th style="padding:6px;text-align:left;color:var(--muted);font-size:0.72rem;font-weight:600;">Building</th>'
        + '<th style="padding:6px;color:var(--muted);font-size:0.72rem;font-weight:600;">Alert Mix</th>'
        + '<th style="padding:6px;text-align:right;color:var(--muted);font-size:0.72rem;font-weight:600;">Counts</th>'
        + '<th style="padding:6px;text-align:right;color:var(--muted);font-size:0.72rem;font-weight:600;">Ack Rate</th>'
        + '<th style="padding:6px;text-align:right;color:var(--muted);font-size:0.72rem;font-weight:600;">Online / Devices</th>'
        + '<th style="padding:6px;text-align:right;color:var(--muted);font-size:0.72rem;font-weight:600;">Avg Ack Time</th>'
        + '</tr></thead><tbody>' + tableRows + '</tbody>'
        + '</table></div></div>';

      container.innerHTML = summary + chartSection + rank;
    }

    // ── Data loading ─────────────────────────────────────────────────────────

    function loadAnalytics(days, containerId) {
      var container = document.getElementById(containerId);
      if (container) container.innerHTML = '<span class="mini-copy">Loading analytics…</span>';
      fetch(BB_PATH_PREFIX + '/admin/analytics/buildings?days=' + days, { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function (data) {
          var buildings = data.buildings || [];
          if (containerId === 'dr-cards') {
            renderDistrictPanel(buildings, containerId, days);
          } else {
            renderBuildingPanel(buildings, containerId);
          }
        })
        .catch(function () {
          var el = document.getElementById(containerId);
          if (el) el.innerHTML = '<span class="mini-copy" style="color:var(--danger);">Could not load analytics.</span>';
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
      var analyticsSection = document.getElementById('analytics');
      if (analyticsSection && analyticsSection.style.display !== 'none') {
        loadAnalytics(30, 'analytics-cards');
      }
      var drSection = document.getElementById('district-reports');
      if (drSection && drSection.style.display !== 'none') {
        loadAnalytics(30, 'dr-cards');
      }

      document.querySelectorAll('[data-analytics-days]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var days = parseInt(btn.dataset.analyticsDays, 10);
          var target = btn.dataset.analyticsTarget;
          document.querySelectorAll('[data-analytics-target="' + target + '"]').forEach(function (b) {
            b.className = b.dataset.analyticsDays == days ? 'button button-primary' : 'button button-secondary';
            b.style.minHeight = '28px';
            b.style.fontSize = '0.78rem';
            b.style.padding = '0 10px';
          });
          loadAnalytics(days, target === 'analytics-cards' ? 'analytics-cards' : 'dr-cards');
        });
      });
    });

  })();
} catch (e) { console.error('[BB] analytics', e); }

// ── Alert Accountability Panel ────────────────────────────────────────────────
try {
  (function () {
    var _pollTimer = null;
    var _activeTab = 'not-acked';
    var _lastMsgCount = 0;

    function _apiHeaders() {
      var h = { 'Content-Type': 'application/json' };
      if (typeof BB_WS_API_KEY !== 'undefined' && BB_WS_API_KEY) h['X-API-Key'] = BB_WS_API_KEY;
      return h;
    }

    function _fmtRole(role) {
      if (!role) return '';
      return role.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
    }

    function _fmtTs(ts) {
      if (!ts) return '';
      try {
        var d = new Date(ts);
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      } catch (e) { return ts.substring(11, 16) || ts; }
    }

    function _presenceDot(status) {
      var color = status === 'online' ? '#16a34a' : status === 'recent' ? '#d97706' : '#9ca3af';
      return '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + color + ';margin-right:4px;flex-shrink:0;"></span>';
    }

    function updateAccountabilityUI(data) {
      var acked = data.acknowledged || [];
      var unacked = data.not_acknowledged || [];
      var msgs = data.messages || [];
      var count = acked.length;
      var expected = data.expected_user_count || 0;
      var pct = data.acknowledgement_percentage || 0;

      var barColor = pct >= 90 ? '#16a34a' : pct >= 60 ? '#d97706' : '#dc2626';
      var labelEl = document.getElementById('js-ack-progress-label');
      var pctEl = document.getElementById('js-ack-progress-pct');
      var barEl = document.getElementById('js-ack-progress-bar');
      if (labelEl) labelEl.textContent = count + ' / ' + expected + ' acknowledged';
      if (pctEl) { pctEl.textContent = pct + '%'; pctEl.style.color = barColor; }
      if (barEl) { barEl.style.width = pct + '%'; barEl.style.background = barColor; }

      // Not-yet tab
      var unackEl = document.getElementById('js-unack-list');
      if (unackEl) {
        if (unacked.length === 0) {
          unackEl.innerHTML = '<span class="mini-copy" style="color:#16a34a;">All users acknowledged!</span>';
        } else {
          unackEl.innerHTML = unacked.map(function(u) {
            return '<div style="display:flex;align-items:center;gap:6px;padding:5px 8px;border-radius:7px;background:rgba(220,38,38,0.04);border:1px solid rgba(220,38,38,0.10);">'
              + _presenceDot(u.presence_status)
              + '<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500;">' + (u.name || 'User #' + u.user_id) + '</span>'
              + '<span style="font-size:0.72rem;color:var(--muted);">' + _fmtRole(u.role) + '</span>'
              + (u.has_device ? '' : '<span style="font-size:0.7rem;color:#9ca3af;margin-left:2px;">no device</span>')
              + '</div>';
          }).join('');
        }
      }

      // Acknowledged tab
      var ackedEl = document.getElementById('js-acked-list');
      if (ackedEl) {
        if (acked.length === 0) {
          ackedEl.innerHTML = '<span class="mini-copy">No acknowledgements yet.</span>';
        } else {
          ackedEl.innerHTML = acked.map(function(u) {
            return '<div style="display:flex;align-items:center;gap:6px;padding:5px 8px;border-radius:7px;background:rgba(22,163,74,0.04);border:1px solid rgba(22,163,74,0.12);">'
              + _presenceDot(u.presence_status)
              + '<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500;">' + (u.name || 'User #' + u.user_id) + '</span>'
              + '<span style="font-size:0.72rem;color:var(--muted);">' + _fmtRole(u.role) + '</span>'
              + '<span style="font-size:0.72rem;color:#16a34a;margin-left:auto;">' + _fmtTs(u.acknowledged_at) + '</span>'
              + '</div>';
          }).join('');
        }
      }

      // Messages tab
      var msgsEl = document.getElementById('js-messages-list');
      if (msgsEl) {
        if (msgs.length === 0) {
          msgsEl.innerHTML = '<span class="mini-copy">No messages yet.</span>';
        } else {
          msgsEl.innerHTML = msgs.map(function(m) {
            var isBroadcast = m.is_broadcast;
            var fromLabel = m.sender_label || (m.sender_role ? _fmtRole(m.sender_role) : 'User #' + m.sender_id);
            var bg = isBroadcast ? 'rgba(14,165,233,0.06)' : 'rgba(0,0,0,0.03)';
            var border = isBroadcast ? '1px solid rgba(14,165,233,0.20)' : '1px solid rgba(0,0,0,0.08)';
            return '<div style="padding:6px 9px;border-radius:7px;background:' + bg + ';border:' + border + ';">'
              + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;">'
              + '<span style="font-weight:600;font-size:0.78rem;">' + fromLabel + (isBroadcast ? ' <span style="font-size:0.68rem;color:#0ea5e9;">[broadcast]</span>' : '') + '</span>'
              + '<span style="font-size:0.7rem;color:var(--muted);">' + _fmtTs(m.timestamp) + '</span>'
              + '</div>'
              + '<div style="font-size:0.82rem;">' + m.message + '</div>'
              + '</div>';
          }).join('');
          msgsEl.scrollTop = msgsEl.scrollHeight;
        }
      }

      // Badge on messages tab if new messages
      var badge = document.getElementById('acc-msg-badge');
      if (badge) {
        if (msgs.length > _lastMsgCount && _activeTab !== 'messages') {
          badge.style.display = '';
          badge.textContent = msgs.length;
        }
        if (_activeTab === 'messages') {
          badge.style.display = 'none';
          _lastMsgCount = msgs.length;
        }
      }
    }

    function loadAccountability() {
      var alertId = (typeof BB_CURRENT_ALERT_ID !== 'undefined') ? BB_CURRENT_ALERT_ID : null;
      var panel = document.getElementById('accountability-panel');
      if (!alertId || !panel) return;
      fetch(BB_PATH_PREFIX + '/admin/alerts/' + alertId + '/full-accountability', {
        credentials: 'same-origin',
        headers: _apiHeaders(),
      })
        .then(function(r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(updateAccountabilityUI)
        .catch(function() { /* silently fail — non-critical */ });
    }

    window.switchAccTab = function(tabName, btn) {
      _activeTab = tabName;
      ['not-acked', 'acked', 'messages'].forEach(function(name) {
        var el = document.getElementById('acc-tab-' + name);
        if (el) el.style.display = name === tabName ? '' : 'none';
      });
      document.querySelectorAll('.acc-tab').forEach(function(b) {
        var isActive = b.dataset.tab === tabName;
        b.style.borderBottomColor = isActive ? '#dc2626' : 'transparent';
        b.style.color = isActive ? '#dc2626' : 'var(--muted)';
      });
      if (tabName === 'messages') {
        var badge = document.getElementById('acc-msg-badge');
        if (badge) badge.style.display = 'none';
        _lastMsgCount = document.querySelectorAll('#js-messages-list > div').length;
      }
    };

    window.adminRemindAll = function() {
      var alertId = (typeof BB_CURRENT_ALERT_ID !== 'undefined') ? BB_CURRENT_ALERT_ID : null;
      if (!alertId) return;
      var btn = document.getElementById('remind-all-btn');
      var fb = document.getElementById('remind-feedback');
      if (btn) { btn.disabled = true; btn.textContent = 'Sending…'; }
      fetch(BB_PATH_PREFIX + '/admin/alerts/' + alertId + '/remind-all', {
        method: 'POST',
        credentials: 'same-origin',
        headers: _apiHeaders(),
        body: JSON.stringify({}),
      })
        .then(function(r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function(data) {
          if (fb) {
            fb.style.display = '';
            fb.style.background = 'rgba(22,163,74,0.10)';
            fb.style.border = '1px solid rgba(22,163,74,0.25)';
            fb.style.color = '#15803d';
            fb.textContent = 'Reminders sent to ' + (data.reminded_count || 0) + ' user(s). ' +
              (data.skipped_no_device ? data.skipped_no_device + ' skipped (no device).' : '');
            setTimeout(function() { if (fb) fb.style.display = 'none'; }, 5000);
          }
        })
        .catch(function() {
          if (fb) {
            fb.style.display = '';
            fb.style.background = 'rgba(220,38,38,0.08)';
            fb.style.border = '1px solid rgba(220,38,38,0.22)';
            fb.style.color = '#dc2626';
            fb.textContent = 'Failed to send reminders. Please try again.';
            setTimeout(function() { if (fb) fb.style.display = 'none'; }, 5000);
          }
        })
        .finally(function() {
          if (btn) { btn.disabled = false; btn.textContent = 'Send Reminders'; }
        });
    };

    window.sendBroadcast = function() {
      var alertId = (typeof BB_CURRENT_ALERT_ID !== 'undefined') ? BB_CURRENT_ALERT_ID : null;
      if (!alertId) return;
      var input = document.getElementById('broadcast-input');
      if (!input) return;
      var msg = (input.value || '').trim();
      if (!msg) return;
      var sendBtn = input.nextElementSibling;
      if (sendBtn) sendBtn.disabled = true;
      fetch(BB_PATH_PREFIX + '/admin/alerts/' + alertId + '/broadcast', {
        method: 'POST',
        credentials: 'same-origin',
        headers: _apiHeaders(),
        body: JSON.stringify({ message: msg }),
      })
        .then(function(r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function() {
          input.value = '';
          loadAccountability();
          if (_activeTab !== 'messages') {
            var messagesBtn = document.querySelector('.acc-tab[data-tab="messages"]');
            if (messagesBtn) window.switchAccTab('messages', messagesBtn);
          }
        })
        .catch(function() {
          alert('Failed to send broadcast. Please try again.');
        })
        .finally(function() {
          if (sendBtn) sendBtn.disabled = false;
        });
    };

    document.addEventListener('DOMContentLoaded', function() {
      var panel = document.getElementById('accountability-panel');
      if (!panel) return;
      loadAccountability();
      _pollTimer = setInterval(loadAccountability, 10000);
    });
  })();
} catch (e) { console.error('[BB] accountability', e); }

// ── District Management ────────────────────────────────────────────────────────
try {
  (function() {
    // ── Modal helpers ──────────────────────────────────────────────────────────
    window.bbCloseModal = function(id) {
      var el = document.getElementById(id);
      if (el) el.style.display = 'none';
    };
    function bbOpenModal(id) {
      var el = document.getElementById(id);
      if (el) el.style.display = 'flex';
    }
    function bbShowBanner(id, msg, isError) {
      var el = document.getElementById(id);
      if (!el) return;
      el.textContent = msg;
      el.className = 'bb-banner ' + (isError ? 'err' : 'ok');
      el.style.display = 'block';
    }
    function bbClearBanner(id) {
      var el = document.getElementById(id);
      if (el) { el.style.display = 'none'; el.textContent = ''; }
    }
    function bbSetBtnLoading(btn, loading) {
      if (!btn) return;
      btn.disabled = loading;
      btn._origText = btn._origText || btn.textContent;
      btn.textContent = loading ? 'Saving…' : btn._origText;
    }
    function slugify(s) {
      return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    }

    // ── Create District ────────────────────────────────────────────────────────
    window.bbOpenCreateDistrictModal = function() {
      bbClearBanner('bb-create-district-banner');
      var nameEl = document.getElementById('bb-create-district-name');
      var slugEl = document.getElementById('bb-create-district-slug');
      if (nameEl) nameEl.value = '';
      if (slugEl) slugEl.value = '';

      // Auto-slug from name
      if (nameEl && slugEl) {
        nameEl.oninput = function() {
          if (!slugEl._userEdited) slugEl.value = slugify(nameEl.value);
        };
        slugEl.oninput = function() { slugEl._userEdited = true; };
        slugEl._userEdited = false;
      }

      // Populate org select
      var orgSel = document.getElementById('bb-create-district-org');
      if (orgSel) {
        orgSel.innerHTML = '<option value="">Loading…</option>';
        fetch('/super-admin/organizations')
          .then(function(r) { return r.json(); })
          .then(function(data) {
            var orgs = data.organizations || [];
            if (!orgs.length) {
              orgSel.innerHTML = '<option value="">No organizations found</option>';
              document.getElementById('bb-create-org-field').style.display = 'none';
              return;
            }
            orgSel.innerHTML = orgs.map(function(o) {
              return '<option value="' + o.id + '">' + o.name + '</option>';
            }).join('');
            if (orgs.length === 1) {
              document.getElementById('bb-create-org-field').style.display = 'none';
            } else {
              document.getElementById('bb-create-org-field').style.display = '';
            }
          })
          .catch(function() {
            orgSel.innerHTML = '<option value="">Could not load organizations</option>';
          });
      }
      bbOpenModal('bb-create-district-modal');
    };

    window.bbSubmitCreateDistrict = function() {
      var name = (document.getElementById('bb-create-district-name') || {}).value || '';
      var slug = (document.getElementById('bb-create-district-slug') || {}).value || '';
      var orgSel = document.getElementById('bb-create-district-org');
      var orgId = orgSel ? orgSel.value : '';
      if (!name.trim()) { bbShowBanner('bb-create-district-banner', 'District name is required.', true); return; }
      if (!slug.trim()) { bbShowBanner('bb-create-district-banner', 'Slug is required.', true); return; }
      var btn = document.getElementById('bb-create-district-btn');
      bbSetBtnLoading(btn, true);
      bbClearBanner('bb-create-district-banner');
      var body = new URLSearchParams({ name: name.trim(), slug: slug.trim(), organization_id: orgId || '1' });
      fetch('/super-admin/districts/create', { method: 'POST', body: body })
        .then(function(r) { return r.ok ? r.json() : r.json().then(function(e) { throw new Error(e.detail || 'Failed'); }); })
        .then(function(data) {
          bbShowBanner('bb-create-district-banner', 'District "' + data.name + '" created. Reloading…', false);
          setTimeout(function() { window.location.reload(); }, 1200);
        })
        .catch(function(e) {
          bbShowBanner('bb-create-district-banner', e.message || 'Failed to create district.', true);
          bbSetBtnLoading(btn, false);
        });
    };

    // ── Edit District ──────────────────────────────────────────────────────────
    var _editSlug = '';
    window.bbOpenEditDistrictModal = function(slug, name) {
      _editSlug = slug;
      bbClearBanner('bb-edit-district-banner');
      var nameEl = document.getElementById('bb-edit-district-name');
      var slugEl = document.getElementById('bb-edit-district-slug');
      if (nameEl) nameEl.value = name;
      if (slugEl) slugEl.value = slug;
      var btn = document.getElementById('bb-edit-district-btn');
      bbSetBtnLoading(btn, false);
      bbOpenModal('bb-edit-district-modal');
    };

    window.bbSubmitEditDistrict = function() {
      var name = (document.getElementById('bb-edit-district-name') || {}).value || '';
      var newSlug = (document.getElementById('bb-edit-district-slug') || {}).value || '';
      if (!name.trim()) { bbShowBanner('bb-edit-district-banner', 'Name is required.', true); return; }
      var btn = document.getElementById('bb-edit-district-btn');
      bbSetBtnLoading(btn, true);
      bbClearBanner('bb-edit-district-banner');
      var body = new URLSearchParams({ name: name.trim(), new_slug: newSlug.trim() });
      fetch('/super-admin/districts/' + encodeURIComponent(_editSlug) + '/update', { method: 'POST', body: body })
        .then(function(r) { return r.ok ? r.json() : r.json().then(function(e) { throw new Error(e.detail || 'Failed'); }); })
        .then(function(data) {
          bbShowBanner('bb-edit-district-banner', 'Saved. Reloading…', false);
          setTimeout(function() { window.location.reload(); }, 1000);
        })
        .catch(function(e) {
          bbShowBanner('bb-edit-district-banner', e.message || 'Failed to save.', true);
          bbSetBtnLoading(btn, false);
        });
    };

    // ── Manage Schools (dual-list) ─────────────────────────────────────────────
    var _manageSlug = '', _manageDistrictId = 0;

    function bbRenderSchoolLists() {
      var all = window._bbAllSchools || [];
      var assigned = all.filter(function(s) { return s.district_id === _manageDistrictId; });
      var available = all.filter(function(s) { return s.district_id === null || s.district_id === undefined; });

      var aList = document.getElementById('bb-assigned-list');
      var vList = document.getElementById('bb-available-list');

      function schoolItem(s, btnCls, btnLabel, onclick) {
        return '<div class="bb-school-item">' +
          '<div><div class="bb-school-item-name">' + s.name + '</div>' +
          '<div class="bb-school-item-slug">' + s.slug + '</div></div>' +
          '<button class="bb-school-btn ' + btnCls + '" onclick="' + onclick + '">' + btnLabel + '</button>' +
          '</div>';
      }

      if (aList) {
        aList.innerHTML = assigned.length
          ? assigned.map(function(s) {
              return schoolItem(s, 'remove', 'Remove', 'bbRemoveSchoolFromDistrict(' + JSON.stringify(s.slug) + ')');
            }).join('')
          : '<div class="bb-empty-state">No schools assigned yet.</div>';
      }
      if (vList) {
        vList.innerHTML = available.length
          ? available.map(function(s) {
              return schoolItem(s, 'add', 'Assign', 'bbAssignSchoolToDistrict(' + JSON.stringify(s.slug) + ',' + _manageDistrictId + ')');
            }).join('')
          : '<div class="bb-empty-state">All unassigned schools are in this district.</div>';
      }
    }

    window.bbOpenManageSchoolsModal = function(slug, name, districtId) {
      _manageSlug = slug;
      _manageDistrictId = districtId;
      bbClearBanner('bb-manage-schools-banner');
      var titleEl = document.getElementById('bb-manage-schools-title');
      if (titleEl) titleEl.textContent = 'Manage Schools — ' + name;
      bbRenderSchoolLists();
      bbOpenModal('bb-manage-schools-modal');
    };

    window.bbAssignSchoolToDistrict = function(schoolSlug, districtId) {
      var body = new URLSearchParams({ district_id: districtId });
      fetch('/super-admin/schools/' + encodeURIComponent(schoolSlug) + '/assign-district', { method: 'POST', body: body })
        .then(function(r) { return r.ok ? r.json() : r.json().then(function(e) { throw new Error(e.detail || 'Failed'); }); })
        .then(function() {
          // Update local state
          var all = window._bbAllSchools || [];
          for (var i = 0; i < all.length; i++) {
            if (all[i].slug === schoolSlug) { all[i].district_id = districtId; break; }
          }
          bbRenderSchoolLists();
          bbShowBanner('bb-manage-schools-banner', 'School assigned.', false);
        })
        .catch(function(e) { bbShowBanner('bb-manage-schools-banner', e.message || 'Failed to assign.', true); });
    };

    window.bbRemoveSchoolFromDistrict = function(schoolSlug) {
      fetch('/super-admin/schools/' + encodeURIComponent(schoolSlug) + '/remove-district', { method: 'POST' })
        .then(function(r) { return r.ok ? r.json() : r.json().then(function(e) { throw new Error(e.detail || 'Failed'); }); })
        .then(function() {
          var all = window._bbAllSchools || [];
          for (var i = 0; i < all.length; i++) {
            if (all[i].slug === schoolSlug) { all[i].district_id = null; break; }
          }
          bbRenderSchoolLists();
          bbShowBanner('bb-manage-schools-banner', 'School removed from district.', false);
        })
        .catch(function(e) { bbShowBanner('bb-manage-schools-banner', e.message || 'Failed to remove.', true); });
    };

    // ── License form AJAX (Phase 13 — inline save, no page reload) ────────────
    document.addEventListener('DOMContentLoaded', function() {
      document.addEventListener('submit', function(ev) {
        var form = ev.target;
        if (!form.closest('.district-billing-expand')) return;
        ev.preventDefault();
        var btn = form.querySelector('button[type="submit"]');
        var origLabel = btn ? btn.textContent : '';
        if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }

        var data = new URLSearchParams(new FormData(form));
        fetch(form.action, { method: form.method || 'POST', body: data })
          .then(function(r) {
            // Backend redirects with 303 — treat any non-500 as success
            if (r.status >= 500) throw new Error('Server error');
            return r;
          })
          .then(function() {
            // Show inline success chip next to button
            var chip = document.createElement('span');
            chip.className = 'status-pill ok';
            chip.style.cssText = 'font-size:0.7rem;padding:2px 8px;margin-left:6px;';
            chip.textContent = 'Saved';
            if (btn) { btn.after(chip); setTimeout(function() { chip.remove(); }, 3000); }
          })
          .catch(function() {
            var chip = document.createElement('span');
            chip.className = 'status-pill danger';
            chip.style.cssText = 'font-size:0.7rem;padding:2px 8px;margin-left:6px;';
            chip.textContent = 'Failed';
            if (btn) { btn.after(chip); setTimeout(function() { chip.remove(); }, 3000); }
          })
          .finally(function() {
            if (btn) { btn.disabled = false; btn.textContent = origLabel; }
          });
      });
    });

  })();
} catch (e) { console.error('[BB] district-mgmt', e); }
