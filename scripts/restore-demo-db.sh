#!/bin/bash
# Restore the UrbanFootprint SACOG demo database.
#
# Usage:
#   ./scripts/restore-demo-db.sh
#
# This runs inside the Docker Django container, streaming the compressed
# .sql.gz dump through psql after stripping owner references and creating
# any missing PG schemas.
#
# Prerequisites:
#   - Docker stack is running (docker compose -f docker-compose.local.yml up)
#   - planning/urbanfootprint-sacog-source-db.sql.gz exists

set -o errexit
set -o pipefail
set -o nounset

cd "$(dirname "$0")/.."

echo "=== Restoring UrbanFootprint SACOG demo database ==="
docker compose -f docker-compose.local.yml run --rm django \
  python manage.py restore_demo_db
echo "=== Done ==="
