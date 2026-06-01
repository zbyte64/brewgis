"""dlt pipeline for NLCD (National Land Cover Database) raster loading.

Downloads a NLCD GeoTIFF subset and loads it into a PostGIS raster
table using ST_FromGDALRaster. Zonal statistics computation moves to
a dbt model (nlcd_parcel_stats).
"""

from __future__ import annotations

import logging

from django.conf import settings
from sqlalchemy import text as sql_text

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services.nlcd_fetcher import download_nlcd_raster
from brewgis.workspace.services.raster_loader import load_raster_to_postgis

logger = logging.getLogger(__name__)

CACHE_DIR = settings.DATA_DOWNLOAD_CACHE_DIR

_TARGET_RASTER_TABLE = "nlcd_raster"


def _compute_bbox(parcel_source: str, schema: str) -> tuple | None:
    """Compute a bounding box from a parcel table's geometry extent.

    Returns ``(west, south, east, north)`` in EPSG:4326 with 5%
    padding, or ``None`` if the table has no geometries.
    """
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            sql_text(
                f"WITH extent_info AS ("  # noqa: S608
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


def run_nlcd_pipeline(
    parcel_source: str,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    year: int = 2021,
    schema: str = "public",
    ignore_cache: bool = False,
) -> dict:
    """Download NLCD raster and load into a PostGIS raster table.

    Steps:
    1. Downloads an NLCD GeoTIFF subset covering the *parcel_source*
       bounding box.
    2. Loads the GeoTIFF into a PostGIS raster table via
       ST_FromGDALRaster / ST_Tile / AddRasterConstraints.

    Parameters
    ----------
    parcel_source : str
        Name of the PostGIS table containing parcel geometries.
        Used only to derive the bounding box when *bbox* is not
        provided (reads ``ST_Extent(geometry)``).
    bbox : tuple[float, float, float, float] | None, optional
        Bounding box ``(west, south, east, north)`` in EPSG:4326.
        When ``None``, computed from ``ST_Extent(geometry)`` on the
        parcel source table with 5% buffer.
    year : int, optional
        NLCD raster year (default 2021).
    schema : str, optional
        Database schema (default ``"public"``).
    ignore_cache : bool, optional
        If True, bypass cached downloads.

    Returns
    -------
    dict
        ``{"success": True, "raster_table": str, "schema": str}``
        on success, or ``{"success": False, "error": str}`` on failure.
    """
    # ── Derive bbox from parcel table if not provided ──────────────
    if bbox is None:
        bbox = _compute_bbox(parcel_source, schema)
        assert bbox is not None, f"No geometries found in {schema}.{parcel_source}"

    # ── Download NLCD raster subset ───────────────────────────────
    # download_nlcd_raster expects (west, south, east, north) in
    # EPSG:4326; NLCD WCS handles reprojection to EPSG:5070
    raster_path = download_nlcd_raster(
        bbox,
        year,
        refresh_cache=ignore_cache,
        source_crs="EPSG:4326",
    )

    assert raster_path is not None, "NLCD raster download returned no data"

    # ── Load GeoTIFF into PostGIS raster table ────────────────────

    result = load_raster_to_postgis(
        raster_path,
        _TARGET_RASTER_TABLE,
        schema=schema,
        srid=5070,
    )

    if not result.get("success"):
        return result

    logger.info(
        "NLCD pipeline complete: raster loaded to %s.%s (%d tiles)",
        schema,
        _TARGET_RASTER_TABLE,
        result.get("row_count", 0),
    )

    return {
        "success": True,
        "raster_table": _TARGET_RASTER_TABLE,
        "schema": schema,
    }
