#!/usr/bin/env bash
# deploy/rollback.sh — BlueBird Alerts release rollback
#
# Lists available releases and rolls back to a specific one.
#
# Usage:
#   bash /srv/bluebird/rollback.sh              # list releases
#   bash /srv/bluebird/rollback.sh 2026-04-26_14-00-00

set -euo pipefail

BLUEBIRD_ROOT="/srv/bluebird"
RELEASES_DIR="$BLUEBIRD_ROOT/releases"
CURRENT_LINK="$BLUEBIRD_ROOT/current"
SERVICE_NAME="bluebird"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

current_release() {
  if [[ -L "$CURRENT_LINK" ]]; then
    readlink -f "$CURRENT_LINK"
  else
    echo ""
  fi
}

# ── List mode ─────────────────────────────────────────────────────────────────

if [[ -z "${1:-}" ]]; then
  echo ""
  echo "BlueBird Alerts — available releases"
  echo "──────────────────────────────────────────────────────────"

  CURRENT=$(current_release)
  FOUND=0

  while IFS= read -r dir; do
    [[ -d "$dir" ]] || continue
    FOUND=1
    ts=$(basename "$dir")
    marker=""
    [[ "$dir" == "$CURRENT" ]] && marker="  ← current"

    if [[ -f "$dir/VERSION" ]]; then
      commit=$(grep '^commit_short=' "$dir/VERSION" 2>/dev/null | cut -d= -f2)
      msg=$(grep '^message=' "$dir/VERSION" 2>/dev/null | cut -d= -f2-)
      echo "  $ts  [$commit] $msg$marker"
    else
      echo "  $ts$marker"
    fi
  done < <(ls -1dt "$RELEASES_DIR"/20*/ 2>/dev/null | sed 's|/$||')

  if [[ $FOUND -eq 0 ]]; then
    echo "  No releases found in $RELEASES_DIR"
  fi

  echo ""
  echo "Usage: $0 <timestamp>"
  echo "Example: $0 2026-04-26_14-00-00"
  echo ""
  exit 0
fi

# ── Rollback mode ─────────────────────────────────────────────────────────────

TARGET_TS="${1}"
TARGET_DIR="$RELEASES_DIR/$TARGET_TS"

[[ -d "$TARGET_DIR" ]] || { echo "ERROR: Release not found: $TARGET_DIR"; exit 1; }

CURRENT=$(current_release)
echo ""
echo "BlueBird Alerts — rollback"
echo "──────────────────────────────────────────────────────────"
echo "  Current : $(basename "$CURRENT" 2>/dev/null || echo '(none)')"
echo "  Target  : $TARGET_TS"

if [[ -f "$TARGET_DIR/VERSION" ]]; then
  echo ""
  echo "  Commit  : $(grep '^commit_short=' "$TARGET_DIR/VERSION" | cut -d= -f2)"
  echo "  Message : $(grep '^message=' "$TARGET_DIR/VERSION" | cut -d= -f2-)"
fi

echo ""
read -r -p "Roll back to $TARGET_TS? [y/N] " CONFIRM
[[ "$CONFIRM" == "y" || "$CONFIRM" == "Y" ]] || { echo "Aborted."; exit 0; }

log "Switching symlink to $TARGET_TS ..."
ln -sfn "$TARGET_DIR" "$CURRENT_LINK"

log "Restarting $SERVICE_NAME ..."
systemctl restart "$SERVICE_NAME"
sleep 3

if systemctl is-active --quiet "$SERVICE_NAME"; then
  log "Rollback complete. Active release: $TARGET_TS ✓"
else
  log "ERROR: $SERVICE_NAME did not start after rollback."
  log "Check logs: journalctl -u $SERVICE_NAME -n 50"
  exit 1
fi
