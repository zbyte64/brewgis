"""dlt pipeline for Sacramento County Assessor parcel data.

Reads parcel geometries and building characteristics from ArcGIS REST
services, transforms SRID 2226 → 4326, and writes to PostGIS staging
tables for dbt consumption.

The computational core (``fetch_parcels_arcgis``, ``fetch_sales_arcgis``,
``load_to_postgis``) lives in :mod:`brewgis.workspace.services.assessor_fetcher`.
"""

from __future__ import annotations

import logging

from brewgis.workspace.services.assessor_fetcher import fetch_parcels_arcgis
from brewgis.workspace.services.assessor_fetcher import fetch_sales_arcgis
from brewgis.workspace.services.assessor_fetcher import load_to_postgis

logger = logging.getLogger(__name__)

_PARCEL_TABLE = "sacog_assessor_parcels_raw"
_SALES_TABLE = "sacog_assessor_sales_raw"


def run_assessor_parcels_pipeline(
    *,
    schema: str = "public",
    max_pages: int = 0,
    ignore_cache: bool = False,
) -> dict:
    """Fetch assessor parcel geometries and write to staging table.

    Reads parcel geometries from Sacramento County PARCELS/MapServer/8,
    transforms to EPSG:4326, and writes to ``{schema}.sacog_assessor_parcels``.

    Parameters
    ----------
    schema : str, optional
        Database schema (default ``"public"``).
    max_pages : int, optional
        Limit pages for testing (0 = unlimited).
    ignore_cache : bool, optional
        Re-download even if cache exists.

    Returns
    -------
    dict
        ``{"success": True, "table_name": str, "row_count": int}``
        on success, or ``{"success": False, "error": str}`` on failure.
    """
    parcels = fetch_parcels_arcgis(
        max_pages=max_pages,
        ignore_cache=ignore_cache,
    )

    if parcels.empty:
        return {
            "success": False,
            "error": ("No parcels returned from ArcGIS PARCELS service"),
        }

    result = load_to_postgis(parcels=parcels, schema=schema)
    row_count = result.get(_PARCEL_TABLE, 0)

    logger.info(
        "Assessor parcels pipeline complete: %d rows in %s.%s",
        row_count,
        schema,
        _PARCEL_TABLE,
    )

    return {
        "success": True,
        "table_name": f"{schema}.{_PARCEL_TABLE}",
        "row_count": row_count,
    }


def run_assessor_sales_pipeline(
    *,
    schema: str = "public",
    max_pages: int = 0,
    ignore_cache: bool = False,
) -> dict:
    """Fetch assessor sales/building data and write to staging table.

    Reads sales/building characteristics from Sacramento County
    ASSESSOR/MapServer/1 and writes to ``{schema}.sacog_assessor_sales``.

    Parameters
    ----------
    schema : str, optional
        Database schema (default ``"public"``).
    max_pages : int, optional
        Limit pages for testing (0 = unlimited).
    ignore_cache : bool, optional
        Re-download even if cache exists.

    Returns
    -------
    dict
        ``{"success": True, "table_name": str, "row_count": int}``
        on success, or ``{"success": False, "error": str}`` on failure.
    """
    sales = fetch_sales_arcgis(
        max_pages=max_pages,
        ignore_cache=ignore_cache,
    )

    if sales.empty:
        error_msg = "No sales data returned from ArcGIS ASSESSOR service"
        return {
            "success": False,
            "error": error_msg,
        }

    result = load_to_postgis(sales=sales, schema=schema)
    row_count = result.get(_SALES_TABLE, 0)

    logger.info(
        "Assessor sales pipeline complete: %d rows in %s.%s",
        row_count,
        schema,
        _SALES_TABLE,
    )

    return {
        "success": True,
        "table_name": f"{schema}.{_SALES_TABLE}",
        "row_count": row_count,
    }
