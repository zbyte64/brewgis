"""Tile server maintenance — refreshing Martin after new tables appear.

Martin (unlike tipg) scans the database for tables once at process
startup and has no live-reload API — a newly-created schema/table (e.g.
an analysis run's ``analysis__scenario_<id>`` results) is invisible to it
until the process restarts. This module restarts the Martin container via
the Docker socket so that happens automatically, without a human in the
loop, right after something creates tables Martin needs to know about.
"""

from __future__ import annotations

import logging

import docker
from django.conf import settings

logger = logging.getLogger(__name__)


def restart_martin() -> bool:
    """Restart the Martin container so it re-scans the database for tables.

    No-ops (returns False) if ``MARTIN_CONTAINER_NAME`` isn't configured
    (e.g. the docker socket isn't mounted in this environment) or if the
    restart fails for any reason — this is a best-effort refresh, not
    something that should ever break the caller's own success path.
    """
    container_name = settings.MARTIN_CONTAINER_NAME
    if not container_name:
        return False

    try:
        client = docker.from_env()
        client.containers.get(container_name).restart(timeout=10)
    except Exception:
        logger.exception(
            "Failed to restart Martin container %s to pick up new tables",
            container_name,
        )
        return False

    logger.info("Restarted Martin container %s to pick up new tables", container_name)
    return True
