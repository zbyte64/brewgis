"""dlt pipeline for raw OSM Overpass POI extraction.

Extracts raw JSON elements from the Overpass API and loads them into a
PostgreSQL staging table. Domain-specific post-processing (geometry
assignment, category splitting, GeoDataFrame conversion) stays in
:mod:`brewgis.workspace.services.poi_fetcher`.
"""

from __future__ import annotations

import logging

import dlt
import requests

from brewgis.workspace.services.poi_fetcher import OVERPASS_URL
from brewgis.workspace.services.poi_fetcher import (
    POI_CATEGORIES,  # noqa: F401 — re-exported for caller convenience
)
from brewgis.workspace.services.poi_fetcher import _build_overpass_query

logger = logging.getLogger(__name__)

__all__ = [
    "run_poi_pipeline",
]


@dlt.resource(name="poi_raw", write_disposition="replace")
def poi_resource(min_lng, min_lat, max_lng, max_lat, categories=None):  # noqa: ANN001,ANN202
    """Query Overpass API and yield raw POI elements."""
    query = _build_overpass_query(min_lng, min_lat, max_lng, max_lat, categories)
    response = requests.post(
        OVERPASS_URL,
        data={"data": query},
        timeout=70,
    )

    try:
        data = response.json()
    except ValueError:
        response.raise_for_status()  # not JSON — let the caller handle it
        return

    # Overpass returns error-like responses as valid JSON with a "remark" field
    remark = data.get("remark")
    if remark is not None:
        msg = f"Overpass API error: {remark}"
        logger.error(msg)
        raise RuntimeError(msg)

    yield from data.get("elements", [])


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

    try:
        load_info = pipeline.run(
            poi_resource(min_lng, min_lat, max_lng, max_lat, categories)
        )
    except Exception as exc:
        logger.exception("POI pipeline run failed")
        return {"success": False, "error": str(exc)}

    # Count rows loaded via package state
    row_count = 0
    if load_info.packages:
        last_pkg = load_info.packages[-1]
        for table_name, table_meta in last_pkg.tables.items():
            if table_name == "poi_raw":
                row_count = table_meta.get("row_count", 0)
                break

    return {
        "success": True,
        "table_name": f"{schema}.poi_raw",
        "row_count": row_count,
        "load_info": str(load_info),
    }
