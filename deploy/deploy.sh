#!/usr/bin/env bash
# deploy/deploy.sh — BlueBird Alerts production deploy
#
# Runs on the server. Creates a timestamped release, switches the
# /srv/bluebird/current symlink atomically, and auto-rolls back if
# the service fails to start.
#
# Usage:
#   bash /srv/bluebird/deploy.sh
#
# First-time setup: see deploy/README in the repo or the inline SETUP
# comment at the bottom of this file.

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────

BLUEBIRD_ROOT="/srv/bluebird"
REPO_DIR="$BLUEBIRD_ROOT/repo"          # git working directory on the server
RELEASES_DIR="$BLUEBIRD_ROOT/releases"
CURRENT_LINK="$BLUEBIRD_ROOT/current"
SHARED_DIR="$BLUEBIRD_ROOT/shared"
LOG_FILE="$SHARED_DIR/logs/deploy.log"
LOCK_FILE="/tmp/bluebird_deploy.lock"
KEEP_RELEASES=5
SERVICE_NAME="bluebird"
BRANCH="main"

# ── Helpers ───────────────────────────────────────────────────────────────────

log() {
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
  echo "$msg"
  echo "$msg" >> "$LOG_FILE"
}

die() { log "ERROR: $*"; exit 1; }

service_running() { systemctl is-active --quiet "$SERVICE_NAME"; }

cleanup_old_releases() {
  local count
  count=$(ls -1d "$RELEASES_DIR"/20*/ 2>/dev/null | wc -l)
  if [[ $count -le $KEEP_RELEASES ]]; then return; fi
  ls -1dt "$RELEASES_DIR"/20*/ | sed 's|/$||' | tail -n "+$((KEEP_RELEASES + 1))" | while read -r old; do
    log "Removing old release: $(basename "$old")"
    rm -rf "$old"
  done
}

# ── Concurrency lock ──────────────────────────────────────────────────────────

exec 200>"$LOCK_FILE"
flock -n 200 || die "Another deploy is already running ($LOCK_FILE). Aborting."
trap 'flock -u 200; rm -f "$LOCK_FILE"' EXIT

# ── Ensure directories exist ──────────────────────────────────────────────────

mkdir -p "$RELEASES_DIR" \
         "$SHARED_DIR/logs" \
         "$SHARED_DIR/data" \
         "$SHARED_DIR/secrets"

# ── Begin ─────────────────────────────────────────────────────────────────────

log "══════════════════════════════════════════════════════════"
log "BlueBird Alerts — deploy started"

# ── Pull latest code ──────────────────────────────────────────────────────────

log "Fetching latest code from origin/$BRANCH ..."
git -C "$REPO_DIR" fetch --prune origin
git -C "$REPO_DIR" reset --hard "origin/$BRANCH"

COMMIT=$(git -C "$REPO_DIR" rev-parse HEAD)
COMMIT_SHORT=$(git -C "$REPO_DIR" rev-parse --short HEAD)
COMMIT_MSG=$(git -C "$REPO_DIR" log --oneline -1)
log "Commit: $COMMIT_SHORT — $COMMIT_MSG"

# ── Create release directory ──────────────────────────────────────────────────

TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
RELEASE_DIR="$RELEASES_DIR/$TIMESTAMP"
log "Release: $RELEASE_DIR"
mkdir -p "$RELEASE_DIR/backend"

# ── Copy backend code (exclude runtime artifacts) ────────────────────────────

rsync -a \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.env' \
  --exclude='data/' \
  --exclude='secrets/' \
  --exclude='venv/' \
  --exclude='.venv/' \
  "$REPO_DIR/backend/" \
  "$RELEASE_DIR/backend/"

# ── Symlink shared persistent resources ──────────────────────────────────────
# .env, data/, and secrets/ live in shared/ and are never overwritten by deploy.

ln -sfn "$SHARED_DIR/.env"    "$RELEASE_DIR/backend/.env"
ln -sfn "$SHARED_DIR/data"    "$RELEASE_DIR/backend/data"
ln -sfn "$SHARED_DIR/secrets" "$RELEASE_DIR/backend/secrets"

# ── Python venv + dependencies ────────────────────────────────────────────────

log "Installing Python dependencies ..."
python3 -m venv "$RELEASE_DIR/backend/venv" --prompt bluebird
"$RELEASE_DIR/backend/venv/bin/pip" install --quiet --upgrade pip
"$RELEASE_DIR/backend/venv/bin/pip" install --quiet -r "$RELEASE_DIR/backend/requirements.txt"
log "Dependencies installed."

# ── Write VERSION file ────────────────────────────────────────────────────────

cat > "$RELEASE_DIR/VERSION" <<EOF
commit=$COMMIT
commit_short=$COMMIT_SHORT
timestamp=$TIMESTAMP
message=$COMMIT_MSG
branch=$BRANCH
EOF

# ── Pre-flight: import smoke test ─────────────────────────────────────────────
# Catches syntax errors and bad imports before the symlink is switched.

log "Running import smoke test ..."
cd "$RELEASE_DIR/backend"
if ! "$RELEASE_DIR/backend/venv/bin/python" -c "from app.main import app" 2>&1 | tee -a "$LOG_FILE"; then
  log "Smoke test failed — aborting. Symlink not switched."
  rm -rf "$RELEASE_DIR"
  exit 1
fi
cd - > /dev/null
log "Smoke test passed."

# ── Capture previous release for rollback ────────────────────────────────────

PREV_RELEASE=""
if [[ -L "$CURRENT_LINK" ]]; then
  PREV_RELEASE=$(readlink -f "$CURRENT_LINK")
fi

# ── Switch symlink (atomic on Linux) ─────────────────────────────────────────

log "Switching current symlink -> $TIMESTAMP"
ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"

# ── Restart service ───────────────────────────────────────────────────────────

log "Restarting $SERVICE_NAME ..."
sudo systemctl restart "$SERVICE_NAME"

# Wait for service to stabilise.
sleep 4

# ── Verify ────────────────────────────────────────────────────────────────────

if service_running; then
  log "Service is active. ✓"
else
  log "FAILED: service did not start after deploy."

  if [[ -n "$PREV_RELEASE" && -d "$PREV_RELEASE" ]]; then
    log "Auto-rolling back to: $(basename "$PREV_RELEASE") ..."
    ln -sfn "$PREV_RELEASE" "$CURRENT_LINK"
    sudo systemctl restart "$SERVICE_NAME"
    sleep 3
    if service_running; then
      log "Rollback succeeded. Previous release is active."
    else
      log "CRITICAL: rollback also failed — manual intervention required."
    fi
  else
    log "No previous release available for rollback."
  fi

  rm -rf "$RELEASE_DIR"
  exit 1
fi

# ── Cleanup old releases ──────────────────────────────────────────────────────

cleanup_old_releases

log "Deploy complete: $TIMESTAMP (commit $COMMIT_SHORT)"
log "══════════════════════════════════════════════════════════"

# ── FIRST-TIME SETUP (read once, then delete this comment) ───────────────────
#
# 1. On the server, create the bluebird user and directories:
#      sudo useradd -r -s /sbin/nologin bluebird
#      sudo mkdir -p /srv/bluebird/{releases,shared/{data,secrets,logs},repo}
#      sudo chown -R bluebird:bluebird /srv/bluebird
#
# 2. Clone the repo into /srv/bluebird/repo:
#      sudo -u bluebird git clone git@github.com:emerytech/bluebird-emergency-alerts.git /srv/bluebird/repo
#
# 3. Copy .env and secrets into shared/:
#      sudo cp /path/to/.env /srv/bluebird/shared/.env
#      sudo cp /path/to/AuthKey_*.p8 /srv/bluebird/shared/secrets/
#      sudo cp /path/to/firebase-service-account.json /srv/bluebird/shared/secrets/
#
# 4. Copy the systemd service file:
#      sudo cp /srv/bluebird/repo/deploy/bluebird.service /etc/systemd/system/bluebird.service
#      sudo systemctl daemon-reload
#      sudo systemctl enable bluebird
#
# 5. Run the first deploy:
#      sudo bash /srv/bluebird/deploy.sh
#
# 6. (Optional) Install the post-merge git hook so git pull auto-deploys:
#      cp /srv/bluebird/repo/deploy/post-merge /srv/bluebird/repo/.git/hooks/post-merge
#      chmod +x /srv/bluebird/repo/.git/hooks/post-merge
