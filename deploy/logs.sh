#!/usr/bin/env bash
# logs.sh — tail logs from one or all BlueBird Alerts services.
#
# Usage:
#   ./deploy/logs.sh                        # all services, last 50 lines + follow
#   ./deploy/logs.sh backend                # backend only
#   ./deploy/logs.sh worker                 # Celery worker
#   ./deploy/logs.sh beat                   # Celery beat
#   ./deploy/logs.sh nginx                  # nginx
#   ./deploy/logs.sh -n 200 worker          # last 200 lines from worker
#   ./deploy/logs.sh --no-follow backend    # print and exit (no -f)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/docker-compose.prod.yml"

TAIL=50
FOLLOW=true
SERVICE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -n|--lines)
            TAIL="$2"
            shift 2
            ;;
        --no-follow)
            FOLLOW=false
            shift
            ;;
        -*)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
        *)
            SERVICE="$1"
            shift
            ;;
    esac
done

FOLLOW_FLAG=()
if $FOLLOW; then
    FOLLOW_FLAG=(-f)
fi

docker compose -f "$COMPOSE_FILE" logs \
    "${FOLLOW_FLAG[@]}" \
    --tail="$TAIL" \
    --timestamps \
    $SERVICE
