#!/bin/bash
# Fix file ownership after Docker container operations.
#
# Docker containers often run as root, creating files (migrations, staticfiles)
# owned by root. This script re-owns them to match the host user.
#
# Usage:
#   docker compose -f docker-compose.local.yml run --rm django bash /app/scripts/fix-perms.sh
#
# Or from inside the container:
#   /app/scripts/fix-perms.sh

set -o errexit
set -o pipefail

# Default to UID:GID of the host user (passed via env or default 1000:1000)
HOST_UID="${UID:-1000}"
HOST_GID="${GID:-1000}"

echo "Fixing ownership to ${HOST_UID}:${HOST_GID}..."

# Re-own common files that Docker creates as root
chown -R "${HOST_UID}:${HOST_GID}" /app/brewgis/workspace/migrations/ 2>/dev/null || true
chown -R "${HOST_UID}:${HOST_GID}" /app/staticfiles/ 2>/dev/null || true
chown -R "${HOST_UID}:${HOST_GID}" /app/.venv/ 2>/dev/null || true

# Catch any other root-owned files in /app
find /app -user root -not -path '*/\.*' -exec chown "${HOST_UID}:${HOST_GID}" {} + 2>/dev/null || true

echo "Done."
