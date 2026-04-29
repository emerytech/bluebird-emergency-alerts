#!/usr/bin/env bash
# scripts/install_backup_cron.sh — Install nightly BlueBird backup cron job
#
# Usage (on the production server, as root):
#   sudo bash /srv/bluebird/repo/scripts/install_backup_cron.sh
#
# Installs:
#   /usr/local/bin/bluebird_backup.sh   (wrapper that invokes scripts/backup.sh)
#   /etc/cron.d/bluebird_backup         (cron entry: 2am nightly)
#   /var/log/bluebird_backup.log        (log file, owned by bluebird user)

set -euo pipefail

REPO_DIR="${REPO_DIR:-/srv/bluebird/repo}"
BACKUP_WRAPPER="/usr/local/bin/bluebird_backup.sh"
CRON_FILE="/etc/cron.d/bluebird_backup"
LOG_FILE="/var/log/bluebird_backup.log"
BLUEBIRD_USER="bluebird"

if [[ "$EUID" -ne 0 ]]; then
    echo "ERROR: Run as root (sudo)."
    exit 1
fi

echo "Installing BlueBird nightly backup cron..."

# ── Create wrapper script ─────────────────────────────────────────────────────

cat > "$BACKUP_WRAPPER" << WRAPPER_EOF
#!/usr/bin/env bash
# Nightly backup wrapper — invoked by cron.
set -euo pipefail
LOGFILE="$LOG_FILE"
echo "" >> "\$LOGFILE"
echo "=== BlueBird backup: \$(date '+%Y-%m-%d %H:%M:%S') ===" >> "\$LOGFILE"
bash "$REPO_DIR/scripts/backup.sh" >> "\$LOGFILE" 2>&1
echo "=== Done: \$(date '+%H:%M:%S') ===" >> "\$LOGFILE"

# Prune backups older than 30 days
find /backups/bluebird -maxdepth 1 -type d -name '20*' -mtime +30 -exec rm -rf {} + 2>/dev/null || true
WRAPPER_EOF

chmod +x "$BACKUP_WRAPPER"
echo "  Created: $BACKUP_WRAPPER"

# ── Create log file ───────────────────────────────────────────────────────────

touch "$LOG_FILE"
chown "$BLUEBIRD_USER:$BLUEBIRD_USER" "$LOG_FILE" 2>/dev/null || true
chmod 640 "$LOG_FILE"
echo "  Log: $LOG_FILE"

# ── Install cron entry ────────────────────────────────────────────────────────

cat > "$CRON_FILE" << CRON_EOF
# BlueBird Alerts nightly backup — 2:00 AM daily
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

0 2 * * * root $BACKUP_WRAPPER
CRON_EOF

chmod 644 "$CRON_FILE"
echo "  Cron: $CRON_FILE (runs at 2:00 AM daily as root)"

echo ""
echo "Nightly backup installed. Test with:"
echo "  sudo bash $BACKUP_WRAPPER"
echo "  tail -f $LOG_FILE"
