"""NLCD (National Land Cover Database) raster downloading.

Downloads an NLCD GeoTIFF subset to a well-known cache path.  The
DuckDB staging models ``brewgis.nlcd.nlcd_parcel_stats`` (VIEW,
duckdb gateway) read the cached file directly via ``RT_ReadCells``
and compute per-parcel zonal statistics.

The ``raster2pgsql`` / PostGIS raster step has been removed — all
raster processing now happens inside DuckDB's ``raster`` extension.

Callers **must** ensure the GeoTIFF is cached at the well-known path
(``/app/planning/nlcd/nlcd_land_cover.tif``) before the SQLMesh plan
runs.  This module provides convenience functions for that download.
"""

from __future__ import annotations

import logging

from django.conf import settings
from sqlalchemy import text as sql_text

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services.nlcd_fetcher import download_nlcd_raster
from brewgis.workspace.services.nlcd_fetcher import download_nlcd_tree_canopy_raster

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


def run_nlcd_pipeline(
    parcel_source: str,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    year: int = 2021,
    schema: str = "public",
    ignore_cache: bool = False,
) -> dict:
    """Download NLCD land cover GeoTIFF to the DuckDB well-known cache path.

    Steps:
    1. Optionally derives a bbox from *parcel_source* ``ST_Extent``.
    2. Downloads a GeoTIFF subset (via WCS) to
       ``DEFAULT_LAND_COVER_PATH``.

    The DuckDB model ``brewgis.nlcd.nlcd_parcel_stats`` reads this
    cached file and computes per-parcel zonal statistics.

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
        ``{"raster_path": str}``
    """
    # ── Derive bbox from parcel table if not provided ──────────────
    if bbox is None:
        bbox_raw = _compute_bbox(parcel_source, schema)
        if bbox_raw is None:
            _msg = (
                f"No geometries found in {schema}.{parcel_source} — "
                "cannot compute NLCD download bbox"
            )
            raise ValueError(_msg)
        bbox = bbox_raw

    # ── Download NLCD raster subset to well-known cache path ──────

    raster_path = download_nlcd_raster(
        bbox,
        year,
        refresh_cache=ignore_cache,
        source_crs="EPSG:4326",
    )

    msg_suffix = " (re-downloaded)" if ignore_cache else ""
    logger.info("NLCD land cover raster cached at %s%s", raster_path, msg_suffix)

    return {"raster_path": raster_path}


def run_nlcd_tree_canopy_pipeline(
    parcel_source: str,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    year: int = 2016,
    schema: str = "public",
    ignore_cache: bool = False,
) -> dict:
    """Download NLCD Tree Canopy Cover GeoTIFF to the well-known cache path.

    Parameters
    ----------
    parcel_source : str
        Name of the PostGIS table containing parcel geometries.
        Used only to derive the bbox when *bbox* is not provided.
    bbox : tuple[float, float, float, float] | None, optional
        Bounding box ``(west, south, east, north)`` in EPSG:4326.
    year : int, optional
        NLCD tree canopy year (default 2016). Valid: 2011, 2016, 2019.
    schema : str, optional
        Database schema (default ``"public"``).
    ignore_cache : bool, optional
        If True, bypass cached downloads.

    Returns
    -------
    dict
        ``{"raster_path": str}``
    """
    if bbox is None:
        bbox_raw = _compute_bbox(parcel_source, schema)
        if bbox_raw is None:
            _msg = (
                f"No geometries found in {schema}.{parcel_source} — "
                "cannot compute NLCD download bbox"
            )
            raise ValueError(_msg)
        bbox = bbox_raw

    raster_path = download_nlcd_tree_canopy_raster(
        bbox,
        year,
        refresh_cache=ignore_cache,
        source_crs="EPSG:4326",
    )

    msg_suffix = " (re-downloaded)" if ignore_cache else ""
    logger.info("NLCD tree canopy raster cached at %s%s", raster_path, msg_suffix)

    return {"raster_path": raster_path}
