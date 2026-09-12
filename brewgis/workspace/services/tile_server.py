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
import time

import docker
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def wait_until_martin_ready(fqtns: list[str], timeout: float = 90.0) -> bool:
    """Block until Martin's catalog reports every table in *fqtns*.

    A restarted Martin container is accepting connections long before it's
    actually usable: it does an expensive startup pass computing bounds for
    every table in the database (logging a warning and moving on for any
    that time out) before it will serve correct tiles for any of them.
    Calling this after :func:`restart_martin` closes that window, at the
    cost of making the caller (an analysis run finishing) wait for it.

    Returns True once ready, False if *timeout* elapses first — logged,
    not raised, since a slow Martin restart shouldn't fail an otherwise
    successful analysis run.
    """
    base_url = settings.TILE_SERVER_MARTIN_URL
    deadline = time.monotonic() + timeout
    remaining = set(fqtns)
    while time.monotonic() < deadline:
        try:
            resp = requests.get(f"{base_url}/catalog", timeout=5)
            if resp.ok:
                tiles = resp.json().get("tiles", {})
                remaining -= set(tiles)
                if not remaining:
                    return True
        except requests.RequestException:
            pass
        time.sleep(1)
    logger.warning(
        "Martin did not report %s as ready within %ss — tiles may render "
        "incorrectly until it finishes starting up",
        sorted(remaining),
        timeout,
    )
    return False


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
