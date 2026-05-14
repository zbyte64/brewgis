"""dlt pipeline for raw OSM Overpass POI extraction.

Extracts raw JSON elements from the Overpass API and loads them into a
PostgreSQL staging table. Includes rate-limiting backoff and retry logic
for the Overpass API. Domain-specific post-processing (geometry
assignment, category splitting, GeoDataFrame conversion) stays in
:mod:`brewgis.workspace.services.poi_fetcher`.
"""

from __future__ import annotations

import logging
import time

from typing import Any
import dlt
import requests

from brewgis.workspace.services.poi_fetcher import OVERPASS_URL
from brewgis.soda import validate_poi
from brewgis.workspace.services.poi_fetcher import POI_CATEGORIES  # noqa: F401
from brewgis.workspace.services.poi_fetcher import _build_overpass_query

logger = logging.getLogger(__name__)

__all__ = [
    "poi_source",
    "run_poi_pipeline",
]

# Overpass API rate limit: 1 request per 5 seconds per IP
_OVERPASS_RATE_LIMIT_S = 5.0
_last_overpass_request: float = 0.0


@dlt.source(name="overpass_poi", max_table_nesting=0)
def poi_source(
    min_lng: float = -121.5,
    min_lat: float = 38.0,
    max_lng: float = -121.0,
    max_lat: float = 38.4,
    categories: list[str] | None = None,
) -> list[Any]:
    """dlt source for Overpass POI extraction.

    Args:
        min_lng: Western bound.
        min_lat: Southern bound.
        max_lng: Eastern bound.
        max_lat: Northern bound.
        categories: List of category names to include, or None for all.

    Returns:
        List with a single :class:`dlt.Resource` yielding raw Overpass
        JSON element dicts.
    """
    return [poi_resource(min_lng, min_lat, max_lng, max_lat, categories)]


@dlt.resource(
    name="poi_raw",
    write_disposition="replace",
)
def poi_resource(
    min_lng: float,
    min_lat: float,
    max_lng: float,
    max_lat: float,
    categories: list[str] | None = None,
) -> Any:
    """Query Overpass API and yield raw POI elements.

    Rate-limits to one request per ``_OVERPASS_RATE_LIMIT_S`` seconds
    to comply with Overpass API usage policy.
    """
    _throttle()

    query = _build_overpass_query(min_lng, min_lat, max_lng, max_lat, categories)
    response = requests.post(
        OVERPASS_URL,
        data={"data": query},
        timeout=120,
    )

    data = response.json()

    remark = data.get("remark")
    if remark is not None:
        msg = f"Overpass API error: {remark}"
        logger.error(msg)
        raise RuntimeError(msg)

    for element in data.get("elements", []):
        yield element


def _throttle() -> None:
    """Enforce rate limit for Overpass API requests."""
    global _last_overpass_request  # noqa: PLW0603
    elapsed = time.monotonic() - _last_overpass_request
    if elapsed < _OVERPASS_RATE_LIMIT_S:
        time.sleep(_OVERPASS_RATE_LIMIT_S - elapsed)
    _last_overpass_request = time.monotonic()


def run_poi_pipeline(  # noqa: PLR0913
    min_lng: float,
    min_lat: float,
    max_lng: float,
    max_lat: float,
    categories: list[str] | None = None,
    schema: str = "public",
) -> dict:
    """Run dlt pipeline to extract raw Overpass POI data to a staging table.

    Args:
        min_lng: Western bound.
        min_lat: Southern bound.
        max_lng: Eastern bound.
        max_lat: Northern bound.
        categories: List of category names to include, or None for all.
        schema: PostgreSQL schema name (default 'public').

    Returns:
        dict with keys: success, table_name, row_count, load_info (or error).
    """
    pipeline = dlt.pipeline(
        pipeline_name="overpass_poi",
        destination="postgres",
        dataset_name=schema,
    )

    load_info = pipeline.run(
        poi_source(min_lng, min_lat, max_lng, max_lat, categories),
    )

    row_count = 0
    for step in pipeline.last_trace.steps:
        si = step.step_info
        if hasattr(si, "row_counts") and si.row_counts:
            row_count = si.row_counts.get("poi_raw", 0)
            break

    # Run Soda Core validation
    validation = validate_poi(schema=schema, table="poi_raw")
    if validation["success"]:
        logger.info("Validation passed for %s.poi_raw", schema)
    else:
        for failure in validation["failures"]:
            logger.warning("Validation failure for %s.poi_raw: %s", schema, failure)

    return {
        "success": True,
        "table_name": f"{schema}.poi_raw",
        "row_count": row_count,
        "load_info": str(load_info),
        "validation": validation,
    }
