"""Tile server maintenance — keeping Martin in sync with the database.

Two distinct kinds of change need Martin to notice, handled by the functions
below:

- A new schema/table (e.g. an analysis run's ``analysis__scenario_<id>``
  results) is invisible to Martin — unlike tipg, which reads the database
  per request — until Martin runs catalog discovery again.
  :func:`restart_martin` restarts the container via the Docker socket so
  that happens immediately, without a human in the loop. Martin does also
  re-run discovery on its own at ``postgres.reload_interval`` (10 minutes
  by default, verified on the pinned 1.16.1 image: it re-ran discovery at
  an exact 600 s cadence) — the restart exists for the minutes between
  writes, not because the reload is missing. Note the reload only notices
  *catalog* changes, which matters for the next point.
- An existing view's *rows* changing (e.g. a paint operation, which
  ``CREATE OR REPLACE``s a scenario's canvas view without touching its
  schema) doesn't need a restart, but Martin's tile cache doesn't look at
  the request's query string, so a tile it already served for that source
  stays stale until something purges it. A reload does not help here: it
  compares table/column metadata, and identical rows-with-different-values
  look unchanged, so the cached bytes survive every reload (verified: a
  rewritten table served a byte-identical tile across four reloads).
  :func:`purge_martin_cache` calls Martin's ``DELETE /cache/{source_id}``
  (maplibre/martin#3194) to drop just that source's cached tiles, and is
  the only one of the three mechanisms that reacts to a data change on its
  own terms — a reload flushes a source's cache only incidentally, when
  the source's metadata changed enough to rebuild it.
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

    Slower than the reload Martin already does at ``postgres.reload_interval``
    (10 minutes by default) — a restart re-derives every source, bounds
    included, which took ~25 s against this stack's ~1500 sources — but it
    happens now rather than up to ten minutes from now, which is what a user
    who just created a view is waiting for. It also drops every cached tile as
    a side effect, which a *reload* only does for sources whose metadata
    changed.

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


def martin_source_ids() -> set[str] | None:
    """The source ids Martin currently publishes, or None when it can't be read.

    Martin scans the database for tables once, at process startup, so a view
    created since that scan is missing here until it restarts.
    """
    try:
        resp = requests.get(f"{settings.TILE_SERVER_MARTIN_URL}/catalog", timeout=5)
        resp.raise_for_status()
    except requests.RequestException:
        logger.exception("Failed to read Martin's catalog")
        return None
    return set(resp.json().get("tiles", {}))


def purge_martin_cache(source_id: str) -> bool:
    """Drop *source_id*'s cached tiles via Martin's ``DELETE /cache/{source_id}``.

    *source_id* is Martin's ``{schema}.{table}`` source identifier (see
    ``source_id_format`` in ``compose/local/martin/config.yaml``) — for a
    scenario canvas view, its ``schema.view_name``.

    Requires ``endpoints.purge_cache: true`` in Martin's own config; a
    Martin version predating maplibre/martin#3194 (<1.15.0) doesn't have
    this route at all. Either way this is best-effort like
    :func:`restart_martin` — logged, not raised, so a purge failure can't
    fail the paint operation that triggered it.
    """
    base_url = settings.TILE_SERVER_MARTIN_URL
    try:
        resp = requests.delete(f"{base_url}/cache/{source_id}", timeout=5)
    except requests.RequestException:
        logger.exception("Failed to purge Martin cache for source %s", source_id)
        return False

    if resp.status_code == requests.codes.not_found:
        # Martin hasn't discovered this source yet (e.g. right after its
        # view was first created) — nothing cached to purge.
        logger.debug("Martin has no source %s yet, nothing to purge", source_id)
        return False

    if not resp.ok:
        logger.warning(
            "Unexpected %s purging Martin cache for source %s: %s",
            resp.status_code,
            source_id,
            resp.text,
        )
        return False

    logger.info("Purged Martin cache for source %s", source_id)
    return True


def ensure_martin_source(source_id: str) -> bool:
    """Make Martin render *source_id* from the database's current rows.

    Both failures described in this module's docstring, resolved for a single
    source: one Martin already publishes is purged, while one it has never seen
    (a view created since its startup scan) needs the restart — which re-scans
    the database and drops every cached tile along with it. Best-effort like its
    siblings, so a tile server problem can never fail the data change that
    triggered it.

    Returns whether Martin was actually told to refresh.
    """
    published = martin_source_ids()
    if published is None:
        # Unreachable Martin: restarting a container we can't read the catalog
        # of would be guessing, and the purge endpoint is equally unavailable.
        return False
    if source_id in published:
        return purge_martin_cache(source_id)
    if not restart_martin():
        return False
    return wait_until_martin_ready([source_id])
