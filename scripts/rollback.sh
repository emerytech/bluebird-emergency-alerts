#!/usr/bin/env bash
# scripts/rollback.sh — BlueBird Alerts rollback utility
#
# Usage:
#   ./scripts/rollback.sh                      # show current HEAD and recent commits
#   ./scripts/rollback.sh <commit-sha>         # reset to that commit (soft by default)
#   ./scripts/rollback.sh <commit-sha> --hard  # hard reset (discards working tree changes)
#   ./scripts/rollback.sh <commit-sha> --backup # snapshot DB files before reset

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="$REPO_ROOT/scripts/.rollback-backups"
TARGET_SHA="${1:-}"
MODE="soft"
DO_BACKUP=false

# Parse flags
for arg in "${@:2}"; do
  case "$arg" in
    --hard)   MODE="hard" ;;
    --backup) DO_BACKUP=true ;;
    *)        echo "Unknown flag: $arg"; exit 1 ;;
  esac
done

# ── Status mode ────────────────────────────────────────────────────────────────
if [[ -z "$TARGET_SHA" ]]; then
  echo "=== Current HEAD ==="
  git -C "$REPO_ROOT" log --oneline -1
  echo ""
  echo "=== Recent commits (last 10) ==="
  git -C "$REPO_ROOT" log --oneline -10
  echo ""
  echo "Usage: $0 <commit-sha> [--hard] [--backup]"
  exit 0
fi

# ── Validate target SHA ────────────────────────────────────────────────────────
if ! git -C "$REPO_ROOT" cat-file -e "${TARGET_SHA}^{commit}" 2>/dev/null; then
  echo "ERROR: '$TARGET_SHA' is not a valid commit in this repo."
  exit 1
fi

RESOLVED_SHA=$(git -C "$REPO_ROOT" rev-parse "$TARGET_SHA")
CURRENT_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD)

echo "=== BlueBird Rollback ==="
echo "Current : $(git -C "$REPO_ROOT" log --oneline -1 "$CURRENT_SHA")"
echo "Target  : $(git -C "$REPO_ROOT" log --oneline -1 "$RESOLVED_SHA")"
echo "Mode    : git reset --$MODE"
echo ""

# ── Optional DB backup ────────────────────────────────────────────────────────
if [[ "$DO_BACKUP" == true ]]; then
  TIMESTAMP=$(date +%Y%m%d_%H%M%S)
  SNAPSHOT_DIR="$BACKUP_DIR/$TIMESTAMP"
  mkdir -p "$SNAPSHOT_DIR"

  DB_FILES=$(find "$REPO_ROOT/backend" -name "*.db" 2>/dev/null || true)
  if [[ -n "$DB_FILES" ]]; then
    echo "Backing up DB files to $SNAPSHOT_DIR ..."
    while IFS= read -r db; do
      cp "$db" "$SNAPSHOT_DIR/$(basename "$db")"
      echo "  Backed up: $db"
    done <<< "$DB_FILES"
  else
    echo "No .db files found — skipping DB backup."
  fi

  # Record the pre-rollback SHA for reference
  echo "$CURRENT_SHA" > "$SNAPSHOT_DIR/pre_rollback_sha.txt"
  git -C "$REPO_ROOT" log --oneline -1 "$CURRENT_SHA" >> "$SNAPSHOT_DIR/pre_rollback_sha.txt"
  echo "Snapshot saved: $SNAPSHOT_DIR"
  echo ""
fi

# ── Confirmation ──────────────────────────────────────────────────────────────
if [[ "$MODE" == "hard" ]]; then
  echo "WARNING: --hard will discard all uncommitted changes in your working tree."
fi

read -r -p "Proceed with rollback? [y/N] " CONFIRM
if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
  echo "Aborted."
  exit 0
fi

# ── Execute reset ─────────────────────────────────────────────────────────────
git -C "$REPO_ROOT" reset "--$MODE" "$RESOLVED_SHA"

echo ""
echo "Rollback complete."
echo "HEAD is now: $(git -C "$REPO_ROOT" log --oneline -1)"

if [[ "$MODE" == "soft" ]]; then
  echo ""
  echo "Staged changes are preserved. Review with: git diff --cached"
  echo "To undo the rollback:  git reset --soft $CURRENT_SHA"
fi
