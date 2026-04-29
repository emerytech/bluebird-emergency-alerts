#!/usr/bin/env bash
# backup_offsite.sh — sync the latest local backup to an offsite rclone remote.
#
# Reads configuration from environment variables (or a .env file if sourced
# by the caller).  Safe to run manually or from cron.
#
# Required env vars:
#   OFFSITE_BACKUP_TARGET  — rclone remote:path  e.g. "b2:my-bucket/bluebird"
#   RCLONE_CONFIG_PATH     — path to rclone.conf  (default: /config/rclone.conf)
#   BACKUP_DIR             — local backup root    (default: /backups/bluebird)
#
# Exit codes:
#   0  success
#   1  configuration error (target not set)
#   2  rclone not found
#   3  sync failure
set -euo pipefail

OFFSITE_TARGET="${OFFSITE_BACKUP_TARGET:-}"
RCLONE_CONF="${RCLONE_CONFIG_PATH:-/config/rclone.conf}"
LOCAL_DIR="${BACKUP_DIR:-/backups/bluebird}"

if [[ -z "$OFFSITE_TARGET" ]]; then
    echo "backup_offsite: OFFSITE_BACKUP_TARGET is not set — skipping offsite sync"
    exit 1
fi

if ! command -v rclone &>/dev/null; then
    echo "backup_offsite: rclone not found in PATH — install rclone first"
    exit 2
fi

echo "backup_offsite: syncing $LOCAL_DIR → $OFFSITE_TARGET"

RCLONE_ARGS=(
    sync
    "$LOCAL_DIR"
    "$OFFSITE_TARGET"
    --transfers=4
    --checksum
    --log-level=INFO
)

if [[ -f "$RCLONE_CONF" ]]; then
    RCLONE_ARGS+=(--config="$RCLONE_CONF")
fi

if rclone "${RCLONE_ARGS[@]}"; then
    echo "backup_offsite: sync complete"
else
    echo "backup_offsite: rclone sync failed (exit $?)"
    exit 3
fi
