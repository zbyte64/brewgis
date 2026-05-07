#!/bin/bash
# Set up the Fresno Demo workspace end-to-end.
#
# Usage:
#   ./scripts/setup-fresno-demo.sh              # full setup with downloads
#   ./scripts/setup-fresno-demo.sh --skip-download  # use cached data only
#   ./scripts/setup-fresno-demo.sh --force-download # re-download everything
#   ./scripts/setup-fresno-demo.sh --step parcels   # run a single step

set -o errexit
set -o pipefail
set -o nounset

cd "$(dirname "$0")/.."

echo "=== Fresno Demo Workspace Setup ==="

# Determine which compose file to use
if [ -f .env ] && grep -q "USE_DOCKER=no" .env 2>/dev/null; then
    # Host development mode — Django runs directly on host
    echo "Running in host development mode..."
    python manage.py setup_fresno_workspace "$@"
else
    # Docker mode — run inside the Django container
    echo "Running inside Docker container..."
    docker compose -f docker-compose.local.yml run --rm django \
        python manage.py setup_fresno_workspace "$@"
fi

echo "=== Done ==="
