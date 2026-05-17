"""dlt pipeline for NLCD (National Land Cover Database) zonal statistics.

Reads parcel geometries from a PostGIS table, computes NLCD land cover
zonal statistics per parcel, and writes land_development_category plus
impervious_fraction to a staging table for dbt consumption.

The computational core (``compute_nlcd_zonal_stats``) lives in
:mod:`brewgis.workspace.services.nlcd_fetcher`.
"""

from __future__ import annotations

import logging

import geopandas as gpd

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services.nlcd_fetcher import compute_nlcd_zonal_stats
from brewgis.workspace.services.nlcd_fetcher import download_nlcd_raster

logger = logging.getLogger(__name__)

_TARGET_TABLE = "nlcd_parcel_stats"


def run_nlcd_pipeline(
    parcel_table: str,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    year: int = 2021,
    schema: str = "public",
) -> dict:
    """Compute NLCD zonal statistics for each parcel and write to staging table.

    Reads parcels from *parcel_table* (in the given *schema*), computes
    NLCD zonal statistics (land_development_category, impervious_fraction)
    using the existing ``compute_nlcd_zonal_stats`` function, and writes
    the result to ``{schema}.nlcd_parcel_stats``.

    Parameters
    ----------
    parcel_table : str
        Name of the PostGIS table containing parcel geometries with a
        ``parcel_id`` column.
    bbox : tuple[float, float, float, float] | None, optional
        Bounding box ``(west, south, east, north)`` in EPSG:4326.
        If ``None``, computed from parcel geometries with 5% buffer.
    year : int, optional
        NLCD raster year (default 2021).
    schema : str, optional
        Database schema (default ``"public"``).

    Returns
    -------
    dict
        ``{"success": True, "table_name": str, "row_count": int}``
        on success, or ``{"success": False, "error": str}`` on failure.
    """
    try:
        # ── Read parcels as GeoDataFrame ──────────────────────────────
        sql = (
            f"SELECT parcel_id, geometry FROM {schema}.{parcel_table} "
            f"WHERE geometry IS NOT NULL"
        )
        parcels: gpd.GeoDataFrame = gpd.GeoDataFrame.from_postgis(
            sql, get_engine(), geom_col="geometry"
        )

        if parcels.empty:
            return {
                "success": False,
                "error": f"No parcels found in {schema}.{parcel_table}",
            }

        logger.info(
            "NLCD pipeline: read %d parcels from %s.%s",
            len(parcels),
            schema,
            parcel_table,
        )

        # Ensure geometry is in EPSG:4326 for NLCD
        if parcels.crs is not None and parcels.crs.to_string() != "EPSG:4326":
            parcels = parcels.to_crs("EPSG:4326")

        # ── Compute bbox from parcels if not provided ─────────────────
        if bbox is None:
            bounds = parcels.total_bounds  # [minx, miny, maxx, maxy]
            x_pad = (bounds[2] - bounds[0]) * 0.05
            y_pad = (bounds[3] - bounds[1]) * 0.05
            bbox = (
                bounds[0] - x_pad,
                bounds[1] - y_pad,
                bounds[2] + x_pad,
                bounds[3] + y_pad,
            )
        # ── Download NLCD raster (fail if unavailable) ──────────────────

        source_crs = parcels.crs.to_string() if parcels.crs is not None else None
        raster_path = download_nlcd_raster(bbox, year, source_crs=source_crs)
        if raster_path is None:
            return {
                "success": False,
                "error": (
                    "NLCD raster could not be downloaded — "
                    "check network connectivity or NLCD server availability"
                ),
            }

        # ── Compute zonal stats ───────────────────────────────────────
        result = compute_nlcd_zonal_stats(parcels, bbox, year)

        # ── Write to staging table ────────────────────────────────────
        target_table = f"{schema}.{_TARGET_TABLE}"
        result[
            ["parcel_id", "land_development_category", "impervious_fraction"]
        ].to_sql(
            _TARGET_TABLE,
            get_engine(),
            schema=schema,
            if_exists="replace",
            index=False,
            method="multi",
        )

        row_count = len(result)

        logger.info(
            "NLCD pipeline complete: %d rows written to %s",
            row_count,
            target_table,
        )

        return {
            "success": True,
            "table_name": target_table,
            "row_count": row_count,
        }

    except Exception:
        logger.exception("NLCD pipeline failed")
        return {
            "success": False,
            "error": "NLCD pipeline failed — see logs for details",
        }
