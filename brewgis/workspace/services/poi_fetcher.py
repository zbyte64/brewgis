"""Points of Interest import — the Overpass fetch is a SQLMesh model.

The Overpass query, its response parsing, and the POI classification live in
SQLMesh (``models/osm/poi.sql`` fetches from DuckDB, ``models/osm/poi_bridge.sql``
bridges to PostGIS, ``macros/overpass_fetch.py`` holds the tag taxonomy).  Like
every other web import, the fetch is cached by DuckDB rather than repeated per
request.  This module only drives the plan that materializes the bridge and
copies the result into the workspace's own schema.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan
from brewgis.workspace.services.fetch_clone import PROD_ENVIRONMENT
from brewgis.workspace.services.fetch_clone import clone_to_postgres
from brewgis.workspace.services.fetch_clone import model_source_ref

logger = logging.getLogger(__name__)

# SQLMesh models behind a POI import: the DuckDB fetch VIEW and the PostGIS
# bridge whose rows the clone copies. Selecting both keeps the fetch view and
# the bridge planned together, whichever of them changed.
POI_MODELS: tuple[str, ...] = ("duckdb.osm.poi", "brewgis.osm.poi")

# Namespace and table the bridge materializes under, which the clone reads from.
_POI_BRIDGE_REGION = "osm"
_POI_BRIDGE_TABLE = "poi"


def _poi_table_name(
    min_lng: float,
    min_lat: float,
    max_lng: float,
    max_lat: float,
    categories: list[str] | None,
) -> str:
    """Build a deterministic, valid Postgres table name for a POI request.

    Re-running the same bounding box/category fetch replaces its own table
    rather than growing a new one on every request.
    """
    cat_label = ",".join(categories) if categories else "all"
    raw = f"poi_{min_lng}_{min_lat}_{max_lng}_{max_lat}_{cat_label}"
    slug = re.sub(r"[^a-z0-9_]+", "_", raw.lower()).strip("_")
    return slug[:63]  # Postgres identifier length limit


def run_poi_pipeline(
    min_lng: float,
    min_lat: float,
    max_lng: float,
    max_lat: float,
    categories: list[str] | None,
    *,
    schema: str,
) -> dict[str, Any]:
    """Fetch POIs from Overpass via SQLMesh and copy them into *schema*.

    Args:
        min_lng: Western bound.
        min_lat: Southern bound.
        max_lng: Eastern bound.
        max_lat: Northern bound.
        categories: List of category names to include. None or empty = all.
        schema: Workspace schema to write the resulting table into.

    Returns:
        Dict with ``table_name`` (unqualified, within *schema*) and
        ``row_count``.
    """
    run_sqlmesh_plan(
        environment=PROD_ENVIRONMENT,
        select=list(POI_MODELS),
        skip_tests=True,
        variables={
            "poi_min_lng": min_lng,
            "poi_min_lat": min_lat,
            "poi_max_lng": max_lng,
            "poi_max_lat": max_lat,
            "poi_categories": ",".join(categories) if categories else "",
        },
    )

    table_name = _poi_table_name(min_lng, min_lat, max_lng, max_lat, categories)
    row_count = clone_to_postgres(
        source_ref=model_source_ref(region=_POI_BRIDGE_REGION, table=_POI_BRIDGE_TABLE),
        dest_schema=schema,
        dest_table=table_name,
    )

    logger.info("Wrote %d POI records to %s.%s", row_count, schema, table_name)
    return {"table_name": table_name, "row_count": row_count}
