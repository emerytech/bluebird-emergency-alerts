#!/usr/bin/env bash
# update.sh — pull latest image(s) and restart the stack in place.
#
# Usage:
#   ./deploy/update.sh [--profile worker] [--profile backup]
#
# The script accepts zero or more --profile flags which are forwarded to
# docker compose so optional service groups (worker, beat, backup) are
# included if they were part of the running stack.
#
# Behavior:
#   1. Pull the latest backend image (rebuild from source via --build)
#   2. Restart only services whose image changed (rolling update)
#   3. Print a short status summary
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/docker-compose.prod.yml"

PROFILES=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)
            PROFILES+=(--profile "$2")
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

DC=(docker compose -f "$COMPOSE_FILE" "${PROFILES[@]}")

echo "=== BlueBird Alerts — update ==="
echo "Repo: $REPO_ROOT"
echo ""

echo "--- Pulling latest code ---"
git -C "$REPO_ROOT" pull --ff-only

echo ""
echo "--- Building updated image ---"
"${DC[@]}" build --pull backend

echo ""
echo "--- Restarting stack (zero-downtime where possible) ---"
"${DC[@]}" up -d --no-deps backend

echo ""
echo "--- Service status ---"
"${DC[@]}" ps

echo ""
echo "=== Update complete ==="
