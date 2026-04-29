#!/usr/bin/env bash
# scripts/backup.sh — BlueBird Alerts full system backup
#
# Creates a timestamped, verifiable backup of all production assets:
#   - All SQLite databases (platform.db, bluebird.db, schools/*.db)
#   - .env and secrets/
#   - Full code archive with git state
#
# Usage (on the production server):
#   sudo -u bluebird bash /srv/bluebird/repo/scripts/backup.sh
#
# Output:
#   /backups/bluebird/YYYY-MM-DD_HHMMSS/
#   /backups/bluebird/YYYY-MM-DD_HHMMSS/bluebird_full_backup.tar.gz
#
# Restore: see scripts/restore.sh

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────

BLUEBIRD_ROOT="${BLUEBIRD_ROOT:-/srv/bluebird}"
REPO_DIR="$BLUEBIRD_ROOT/repo"
SHARED_DIR="$BLUEBIRD_ROOT/shared"
DATA_DIR="$SHARED_DIR/data"
SECRETS_DIR="$SHARED_DIR/secrets"
ENV_FILE="$SHARED_DIR/.env"

BACKUP_BASE="${BACKUP_BASE:-/backups/bluebird}"
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)
BACKUP_DIR="$BACKUP_BASE/$TIMESTAMP"

SERVICE_NAME="${SERVICE_NAME:-bluebird}"

# ── Colour helpers ────────────────────────────────────────────────────────────

BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; RESET='\033[0m'

log()  { echo -e "${BOLD}[$(date '+%H:%M:%S')]${RESET} $*"; }
ok()   { echo -e "${GREEN}  ✓ $*${RESET}"; }
warn() { echo -e "${YELLOW}  ⚠ $*${RESET}"; }
die()  { echo -e "${RED}  ✗ FATAL: $*${RESET}"; exit 1; }

# ── Preflight checks ──────────────────────────────────────────────────────────

[[ -d "$DATA_DIR" ]]    || die "Data directory not found: $DATA_DIR"
[[ -f "$ENV_FILE" ]]    || warn ".env file not found at $ENV_FILE — skipping config backup"
command -v sqlite3 >/dev/null 2>&1 || die "sqlite3 is required but not installed"

log "═══════════════════════════════════════════════════════════"
log "BlueBird Alerts — Backup starting"
log "Destination : $BACKUP_DIR"
log "═══════════════════════════════════════════════════════════"

# ── Phase 2: Create directory structure ───────────────────────────────────────

log "Phase 2 — Creating backup directory structure ..."
mkdir -p "$BACKUP_DIR"/{code,data,data/schools,config,metadata}
ok "Directories created: $BACKUP_DIR"

# ── Phase 1+2: Write metadata ─────────────────────────────────────────────────

log "Phase 1+2 — Collecting metadata ..."

GIT_COMMIT=""
GIT_STATUS=""
if [[ -d "$REPO_DIR/.git" ]]; then
    GIT_COMMIT=$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo "unknown")
    GIT_STATUS=$(git -C "$REPO_DIR" status --porcelain 2>/dev/null || echo "")
fi

HOSTNAME_VAL=$(hostname -f 2>/dev/null || hostname)

# Find all DB files that exist
DB_LIST=()
[[ -f "$DATA_DIR/platform.db" ]] && DB_LIST+=("platform.db")
[[ -f "$DATA_DIR/bluebird.db" ]] && DB_LIST+=("bluebird.db")
while IFS= read -r -d '' f; do
    DB_LIST+=("schools/$(basename "$f")")
done < <(find "$DATA_DIR/schools" -name "*.db" -print0 2>/dev/null || true)

python3 - <<PYEOF > "$BACKUP_DIR/metadata/metadata.json"
import json, datetime
print(json.dumps({
    "timestamp":        "$TIMESTAMP",
    "timestamp_iso":    datetime.datetime.utcnow().isoformat() + "Z",
    "hostname":         "$HOSTNAME_VAL",
    "git_commit":       "$GIT_COMMIT",
    "git_status":       """$GIT_STATUS""",
    "bluebird_root":    "$BLUEBIRD_ROOT",
    "data_dir":         "$DATA_DIR",
    "databases":        "$DB_LIST".strip("[]").replace("'", "").split(", "),
    "service_name":     "$SERVICE_NAME",
}, indent=2))
PYEOF

ok "Metadata written: $BACKUP_DIR/metadata/metadata.json"
cat "$BACKUP_DIR/metadata/metadata.json"

# ── Phase 3: Code snapshot ────────────────────────────────────────────────────

log "Phase 3 — Archiving code ..."

if [[ -d "$REPO_DIR" ]]; then
    tar -czf "$BACKUP_DIR/code/bluebird_code.tar.gz" \
        -C "$REPO_DIR" \
        --exclude='.git' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='.venv' \
        --exclude='venv' \
        --exclude='backend/data' \
        --exclude='backend/secrets' \
        . 2>/dev/null
    ok "Code archive: $(du -sh "$BACKUP_DIR/code/bluebird_code.tar.gz" | cut -f1)"

    # Save uncommitted changes patch
    git -C "$REPO_DIR" diff HEAD > "$BACKUP_DIR/code/uncommitted.patch" 2>/dev/null || true
    echo "$GIT_COMMIT" > "$BACKUP_DIR/code/git_commit.txt"
    git -C "$REPO_DIR" log --oneline -10 > "$BACKUP_DIR/code/git_log.txt" 2>/dev/null || true
    ok "Git state saved (commit: ${GIT_COMMIT:0:12})"
else
    warn "Repo directory not found ($REPO_DIR) — skipping code snapshot"
fi

# ── Phase 4: Database backup ──────────────────────────────────────────────────

log "Phase 4 — Backing up databases ..."

backup_db() {
    local src="$1"
    local dest="$2"
    local label="$3"

    if [[ ! -f "$src" ]]; then
        warn "DB not found — skipping: $src"
        return
    fi

    # sqlite3 .backup is crash-safe and works even with WAL mode
    sqlite3 "$src" ".backup '$dest'"

    local size
    size=$(du -sh "$dest" | cut -f1)
    ok "  $label → $(basename "$dest") ($size)"

    # Verify backup integrity
    local check
    check=$(sqlite3 "$dest" "PRAGMA integrity_check;" 2>&1)
    if [[ "$check" == "ok" ]]; then
        ok "  Integrity: ok"
    else
        warn "  Integrity check FAILED for $dest: $check"
    fi
}

backup_db "$DATA_DIR/platform.db"  "$BACKUP_DIR/data/platform.db"  "platform.db"
backup_db "$DATA_DIR/bluebird.db"  "$BACKUP_DIR/data/bluebird.db"  "bluebird.db"

# Per-tenant school DBs
if [[ -d "$DATA_DIR/schools" ]]; then
    find "$DATA_DIR/schools" -name "*.db" | sort | while read -r src; do
        slug=$(basename "$src" .db)
        dest="$BACKUP_DIR/data/schools/${slug}.db"
        backup_db "$src" "$dest" "schools/${slug}.db"
    done
else
    warn "No schools/ directory found — no per-tenant DBs backed up"
fi

# ── Phase 5: Config & secrets ─────────────────────────────────────────────────

log "Phase 5 — Backing up config and secrets ..."

if [[ -f "$ENV_FILE" ]]; then
    cp -p "$ENV_FILE" "$BACKUP_DIR/config/.env"
    ok ".env backed up ($(wc -l < "$BACKUP_DIR/config/.env") lines)"
fi

if [[ -d "$SECRETS_DIR" ]] && [[ -n "$(ls -A "$SECRETS_DIR" 2>/dev/null)" ]]; then
    cp -rp "$SECRETS_DIR/." "$BACKUP_DIR/config/secrets/"
    ok "Secrets backed up: $(ls "$BACKUP_DIR/config/secrets/" | tr '\n' ' ')"
else
    warn "Secrets directory empty or not found — skipping"
fi

# ── Phase 6: Full archive ─────────────────────────────────────────────────────

log "Phase 6 — Creating full portable archive ..."

tar -czf "$BACKUP_DIR/bluebird_full_backup.tar.gz" \
    -C "$BACKUP_DIR" \
    code/ data/ config/ metadata/

FULL_SIZE=$(du -sh "$BACKUP_DIR/bluebird_full_backup.tar.gz" | cut -f1)
ok "Full archive: $BACKUP_DIR/bluebird_full_backup.tar.gz ($FULL_SIZE)"

# ── Phase 7: Integrity checks ─────────────────────────────────────────────────

log "Phase 7 — Integrity checks and checksums ..."

# List top-level archive contents
log "  Contents of full backup:"
tar -tzf "$BACKUP_DIR/bluebird_full_backup.tar.gz" | grep -v '/$' | sort | sed 's/^/    /'

# List code archive
log "  Contents of code archive:"
tar -tzf "$BACKUP_DIR/code/bluebird_code.tar.gz" 2>/dev/null | wc -l | xargs printf "    %s files\n"

# SHA-256 checksums of all backup files
(
    cd "$BACKUP_DIR"
    find . -type f ! -name "checksums.txt" -print0 \
        | sort -z \
        | xargs -0 sha256sum \
        > metadata/checksums.txt
)
ok "Checksums written: $BACKUP_DIR/metadata/checksums.txt"

# Verify the full archive can be extracted (dry run)
log "  Verifying full archive integrity (dry run) ..."
if tar -tzf "$BACKUP_DIR/bluebird_full_backup.tar.gz" > /dev/null 2>&1; then
    ok "Full archive verified: no corruption detected"
else
    warn "Full archive verification FAILED — archive may be corrupt"
fi

# ── Phase 9: Restore script ───────────────────────────────────────────────────

log "Phase 9 — Writing restore script ..."

RESTORE_SCRIPT="$BACKUP_DIR/metadata/restore.sh"
cat > "$RESTORE_SCRIPT" << 'RESTORE_EOF'
#!/usr/bin/env bash
# restore.sh — BlueBird Alerts restore script
# Auto-generated by backup.sh. Run on the production server.
#
# Usage:
#   sudo bash /backups/bluebird/YYYY-MM-DD_HHMMSS/metadata/restore.sh
#
# Flags:
#   --code-only    Restore code only (do not touch data/config)
#   --data-only    Restore data only (skip code)
#   --dry-run      Show what would happen without making changes

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_ROOT="$(dirname "$SCRIPT_DIR")"  # parent of metadata/

BLUEBIRD_ROOT="${BLUEBIRD_ROOT:-/srv/bluebird}"
SHARED_DIR="$BLUEBIRD_ROOT/shared"
DATA_DIR="$SHARED_DIR/data"
SERVICE_NAME="${SERVICE_NAME:-bluebird}"

DRY_RUN=false
RESTORE_CODE=true
RESTORE_DATA=true

for arg in "$@"; do
    case "$arg" in
        --dry-run)   DRY_RUN=true ;;
        --code-only) RESTORE_DATA=false ;;
        --data-only) RESTORE_CODE=false ;;
        *) echo "Unknown flag: $arg"; exit 1 ;;
    esac
done

BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; RESET='\033[0m'
log()  { echo -e "${BOLD}[$(date '+%H:%M:%S')]${RESET} $*"; }
ok()   { echo -e "${GREEN}  ✓ $*${RESET}"; }
warn() { echo -e "${YELLOW}  ⚠ $*${RESET}"; }
die()  { echo -e "${RED}  ✗ FATAL: $*${RESET}"; exit 1; }
run()  { if $DRY_RUN; then echo "  [DRY-RUN] $*"; else eval "$@"; fi; }

log "═══════════════════════════════════════════════════════════"
log "BlueBird Alerts — Restore"
log "Backup  : $BACKUP_ROOT"
if $DRY_RUN; then warn "DRY-RUN mode — no changes will be made"; fi
log "═══════════════════════════════════════════════════════════"

# ── Verify backup integrity ───────────────────────────────────────────────────

log "Verifying backup checksums ..."
CHECKSUM_FILE="$BACKUP_ROOT/metadata/checksums.txt"
if [[ -f "$CHECKSUM_FILE" ]]; then
    if (cd "$BACKUP_ROOT" && sha256sum --check --quiet "$CHECKSUM_FILE" 2>/dev/null); then
        ok "All checksums verified"
    else
        warn "Some checksums did not match — backup may be partially corrupted"
        read -r -p "Continue anyway? [y/N] " CONFIRM
        [[ "$CONFIRM" =~ ^[yY]$ ]] || { echo "Aborted."; exit 0; }
    fi
else
    warn "No checksums.txt found — skipping verification"
fi

# ── Pre-restore safety snapshot ───────────────────────────────────────────────

SAFETY_TS=$(date +%Y%m%d_%H%M%S)
SAFETY_DIR="/backups/bluebird/pre_restore_${SAFETY_TS}"

log "Creating pre-restore safety snapshot at $SAFETY_DIR ..."
run "mkdir -p $SAFETY_DIR"

if [[ -d "$DATA_DIR" ]]; then
    for db in "$DATA_DIR"/*.db "$DATA_DIR"/schools/*.db 2>/dev/null; do
        [[ -f "$db" ]] || continue
        rel="${db#$DATA_DIR/}"
        run "mkdir -p $SAFETY_DIR/$(dirname "$rel")"
        run "sqlite3 \"$db\" \".backup '$SAFETY_DIR/$rel'\""
        ok "Snapshot: $rel"
    done
fi
ok "Safety snapshot written to $SAFETY_DIR"

# ── Stop service ──────────────────────────────────────────────────────────────

log "Stopping $SERVICE_NAME ..."
read -r -p "  Stop service $SERVICE_NAME now? [y/N] " CONFIRM
if [[ "$CONFIRM" =~ ^[yY]$ ]]; then
    run "systemctl stop $SERVICE_NAME"
    ok "Service stopped"
else
    warn "Service not stopped — DB restore may fail if service holds locks"
fi

# ── Restore data (databases + config) ────────────────────────────────────────

if $RESTORE_DATA; then
    log "Restoring databases ..."

    restore_db() {
        local src="$1"
        local dest="$2"
        if [[ ! -f "$src" ]]; then
            warn "Backup DB not found: $src — skipping"
            return
        fi
        run "mkdir -p $(dirname "$dest")"
        run "sqlite3 \"$src\" \".backup '$dest'\""
        ok "Restored: $(basename "$dest")"
    }

    restore_db "$BACKUP_ROOT/data/platform.db"  "$DATA_DIR/platform.db"
    restore_db "$BACKUP_ROOT/data/bluebird.db"  "$DATA_DIR/bluebird.db"

    if [[ -d "$BACKUP_ROOT/data/schools" ]]; then
        for src in "$BACKUP_ROOT/data/schools/"*.db; do
            [[ -f "$src" ]] || continue
            slug=$(basename "$src" .db)
            restore_db "$src" "$DATA_DIR/schools/${slug}.db"
        done
    fi

    log "Restoring config ..."
    if [[ -f "$BACKUP_ROOT/config/.env" ]]; then
        run "cp -p $BACKUP_ROOT/config/.env $SHARED_DIR/.env"
        ok ".env restored"
    fi
    if [[ -d "$BACKUP_ROOT/config/secrets" ]]; then
        run "cp -rp $BACKUP_ROOT/config/secrets/. $SHARED_DIR/secrets/"
        ok "Secrets restored"
    fi
fi

# ── Restore code ──────────────────────────────────────────────────────────────

if $RESTORE_CODE; then
    CODE_ARCHIVE="$BACKUP_ROOT/code/bluebird_code.tar.gz"
    if [[ -f "$CODE_ARCHIVE" ]]; then
        REPO_DIR="$BLUEBIRD_ROOT/repo"
        log "Restoring code to $REPO_DIR ..."
        warn "This will overwrite $REPO_DIR — current state was saved above."
        read -r -p "  Restore code? [y/N] " CONFIRM
        if [[ "$CONFIRM" =~ ^[yY]$ ]]; then
            run "tar -xzf $CODE_ARCHIVE -C $REPO_DIR"
            ok "Code restored"
        else
            warn "Code restore skipped"
        fi
    else
        warn "No code archive found — skipping code restore"
    fi
fi

# ── Restart service ───────────────────────────────────────────────────────────

log "Restarting $SERVICE_NAME ..."
read -r -p "  Start service now? [y/N] " CONFIRM
if [[ "$CONFIRM" =~ ^[yY]$ ]]; then
    run "systemctl start $SERVICE_NAME"
    sleep 3
    if $DRY_RUN || systemctl is-active --quiet "$SERVICE_NAME"; then
        ok "Service is running"
    else
        die "Service failed to start — check: journalctl -u $SERVICE_NAME -n 50"
    fi
fi

log "═══════════════════════════════════════════════════════════"
log "Restore complete."
log "If something looks wrong: sudo bash $SAFETY_DIR/... to re-restore"
log "═══════════════════════════════════════════════════════════"
RESTORE_EOF

chmod +x "$RESTORE_SCRIPT"
ok "Restore script: $RESTORE_SCRIPT"

# ── Final summary ─────────────────────────────────────────────────────────────

log "═══════════════════════════════════════════════════════════"
log "Backup complete: $TIMESTAMP"
log ""
log "  Location : $BACKUP_DIR"
log "  Full archive : $BACKUP_DIR/bluebird_full_backup.tar.gz ($FULL_SIZE)"
log "  Databases:"
find "$BACKUP_DIR/data" -name "*.db" | sort | while read -r f; do
    printf "    %-40s %s\n" "$(basename "$f")" "$(du -sh "$f" | cut -f1)"
done
log "  Checksums: $BACKUP_DIR/metadata/checksums.txt"
log "  Restore : $RESTORE_SCRIPT"
log ""

# Check if we should set up nightly automation
if [[ ! -f /etc/cron.d/bluebird_backup ]]; then
    log "  To enable nightly backups, run:"
    log "    sudo bash /srv/bluebird/repo/scripts/install_backup_cron.sh"
fi

log "═══════════════════════════════════════════════════════════"
