"""NLCD bbox computation for DuckDB raster models.

The NLCD DuckDB models (``brewgis.nlcd.nlcd_parcel_stats`` and
``brewgis.nlcd.nlcd_tree_canopy_parcel_stats``) now fetch rasters
directly from the MRLC WCS endpoint via httpfs.  The bbox is computed
inline in the SQL ``pre_statements`` block.

This module retains ``_compute_bbox`` for any other code that needs
the parcel extent in EPSG:4326.
"""

from __future__ import annotations

import logging

from django.conf import settings
from sqlalchemy import text as sql_text

from brewgis.workspace.services._db import get_engine

logger = logging.getLogger(__name__)

CACHE_DIR = settings.DATA_DOWNLOAD_CACHE_DIR


def _compute_bbox(parcel_source: str, schema: str) -> tuple | None:
    """Compute a bounding box from a parcel table's geometry extent.

    Args:
        parcel_source: Table name (without schema).
        schema: Database schema.

    Returns:
        ``(west, south, east, north)`` in EPSG:4326, or None if the
        table has no geometry.
    """
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            sql_text(
                f"WITH extent_info AS ("
                f"  SELECT "
                f"    ST_Extent(geometry) AS e, "
                f"    MAX(ST_SRID(geometry)) AS srid "
                f"  FROM {schema}.{parcel_source} "
                f"  WHERE geometry IS NOT NULL "
                f") "
                f"SELECT "
                f"  ST_XMin(ST_Transform("
                f"    ST_SetSRID(ST_MakePoint(ST_XMin(e), ST_YMin(e)), srid), 4326"
                f"  )), "
                f"  ST_YMin(ST_Transform("
                f"    ST_SetSRID(ST_MakePoint(ST_XMin(e), ST_YMin(e)), srid), 4326"
                f"  )), "
                f"  ST_XMax(ST_Transform("
                f"    ST_SetSRID(ST_MakePoint(ST_XMax(e), ST_YMax(e)), srid), 4326"
                f"  )), "
                f"  ST_YMax(ST_Transform("
                f"    ST_SetSRID(ST_MakePoint(ST_XMax(e), ST_YMax(e)), srid), 4326"
                f"  )) "
                f"FROM extent_info"
            )
        ).one()

    if row[0] is None:
        return None

    west, south, east, north = row
    x_pad = (east - west) * 0.05
    y_pad = (north - south) * 0.05
    return (
        west - x_pad,
        south - y_pad,
        east + x_pad,
        north + y_pad,
    )
