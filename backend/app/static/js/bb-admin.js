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
      if (ackPill) {
        var ackCount = alarm.acknowledgement_count || 0;
        if (alarm.is_active && ackCount > 0) {
          ackPill.style.display = '';
          ackPill.innerHTML = '<strong>Acknowledged</strong>' + ackCount + ' user' + (ackCount !== 1 ? 's' : '');
        } else {
          ackPill.style.display = 'none';
        }
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
    function fmtSeconds(s) {
      if (s === null || s === undefined) return '—';
      if (s < 60) return Math.round(s) + 's';
      return Math.round(s / 60) + 'm ' + (Math.round(s) % 60) + 's';
    }

    function renderBuildingCards(buildings, containerId) {
      var container = document.getElementById(containerId);
      if (!container) return;
      if (!buildings || !buildings.length) {
        container.innerHTML = '<p class="mini-copy">No data available.</p>';
        return;
      }
      container.innerHTML = buildings.map(function (b) {
        var lastAlert = b.last_alert_at ? b.last_alert_at.slice(0, 16).replace('T', ' ') : 'Never';
        return '<div class="um-hcard hc-ok" style="min-width:220px;max-width:280px;">'
          + '<div class="um-hcard-label">' + b.building_name + '</div>'
          + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px 14px;margin-top:8px;font-size:0.82rem;">'
          + '<div><div style="color:var(--muted);font-size:0.72rem;">Emergency Alerts</div><div style="font-weight:700;font-size:1.1rem;">' + (b.emergency_alerts || 0) + '</div></div>'
          + '<div><div style="color:var(--muted);font-size:0.72rem;">Training</div><div style="font-weight:700;font-size:1.1rem;">' + (b.training_alerts || 0) + '</div></div>'
          + '<div><div style="color:var(--muted);font-size:0.72rem;">Help Requests</div><div style="font-weight:700;">' + (b.help_requests || 0) + ' <span style="color:#b45309;font-size:0.75rem;">(' + (b.cancelled_help_requests || 0) + ' cancelled)</span></div></div>'
          + '<div><div style="color:var(--muted);font-size:0.72rem;">Quiet Requests</div><div style="font-weight:700;">' + (b.quiet_period_requests || 0) + '</div></div>'
          + '<div><div style="color:var(--muted);font-size:0.72rem;">Avg Ack Time</div><div style="font-weight:700;">' + fmtSeconds(b.avg_ack_time_seconds) + '</div></div>'
          + '<div><div style="color:var(--muted);font-size:0.72rem;">Last Alert</div><div style="font-weight:700;font-size:0.78rem;">' + lastAlert + '</div></div>'
          + '</div></div>';
      }).join('');
    }

    function loadAnalytics(days, containerId) {
      var container = document.getElementById(containerId);
      if (container) container.innerHTML = '<span class="mini-copy">Loading…</span>';
      fetch(BB_PATH_PREFIX + '/admin/analytics/buildings?days=' + days, { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function (data) {
          renderBuildingCards(data.buildings || [], containerId);
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
            b.className = b.dataset.analyticsDays == days
              ? 'button button-primary' : 'button button-secondary';
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
