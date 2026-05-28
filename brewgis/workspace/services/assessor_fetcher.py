"""Sacramento County Assessor parcel data fetcher.

Downloads parcel geometries from ArcGIS REST services (PARCELS/MapServer/8)
and building characteristics from ASSESSOR/MapServer/1 (Sales by Property Type),
transforms SRID 2226 → 4326, caches to disk, and loads to PostGIS staging tables.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path  # noqa: TC003
from typing import Any

import geopandas as gpd
import requests
from django.conf import settings
from shapely.geometry import shape

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text

logger = logging.getLogger(__name__)

CACHE_DIR: Path = settings.DATA_DOWNLOAD_CACHE_DIR

# ── ArcGIS REST API Endpoints ──────────────────────────────────────

# Sacramento County GIS: Active GIS Parcel Base — 508K parcels
PARCELS_MAP_SERVER = (
    "https://mapservices.gis.saccounty.net/arcgis/rest/services/PARCELS/MapServer/8/query"
)
# Sacramento County GIS: Sales by Property Type — 55K sold parcels
SALES_MAP_SERVER = (
    "https://mapservices.gis.saccounty.net/arcgis/rest/services/ASSESSOR/MapServer/1/query"
)

_PAGE_SIZE = 2000
_REQUEST_TIMEOUT = 300  # seconds

# Columns to fetch from each layer
_PARCEL_FIELDS = [
    "PARCEL_NUMBER",
    "LANDUSE",
    "ZONE_",
    "LOTSIZE",
    "JURISDICTION",
]
_SALES_FIELDS = [
    "PARCEL_NUMBER",
    "TOTAL_LIVING_AREA",
    "BUILDING_SF",
    "EFFECTIVE_YEAR_BUILT",
    "NUMBER_OF_STORIES",
    "NUMBER_OF_BEDROOMS",
    "NUMBER_OF_BATHS",
    "GROUND_FLOOR_GROSS",
    "LAND_USE_CODE",
    "Property_Type",
    "INDICATED_SALES_PRICE",
    "LOT_SIZE_ACRES",
    "Units",
]


def _arcgis_query_paginated(
    url: str,
    fields: list[str],
    *,
    where: str = "1=1",
    max_pages: int = 0,
    out_sr: int = 4326,
) -> list[dict[str, Any]]:
    """Paginate an ArcGIS REST MapServer query and return combined features.

    Parameters
    ----------
    url : str
        Full ArcGIS REST query endpoint URL.
    fields : list[str]
        Column names to fetch (uses ``outFields``).
    where : str, optional
        SQL-like where clause (default ``"1=1"`` fetches all rows).
    max_pages : int, optional
        Maximum pages to fetch (0 = unlimited).  Used for testing.
    out_sr : int, optional
        Output spatial reference (default 4326 = WGS84).

    Returns
    -------
    list[dict]
        List of feature attribute dicts.
    """
    all_features: list[dict[str, Any]] = []
    offset = 0
    page = 0

    params: dict[str, Any] = {
        "where": where,
        "outFields": ",".join(fields),
        "returnGeometry": "true",
        "outSR": str(out_sr),
        "f": "geojson",
        "resultOffset": offset,
        "resultRecordCount": _PAGE_SIZE,
    }

    while True:
        if max_pages and page >= max_pages:
            break

        params["resultOffset"] = offset
        response = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        features = data.get("features", [])
        if not features:
            break

        for feat in features:
            props = feat.get("properties", {})
            geo = feat.get("geometry")
            if geo:
                props["geometry"] = json.dumps(geo)
            all_features.append(props)

        offset += _PAGE_SIZE
        page += 1
        logger.info(
            "Fetched page %d from %s (%d records so far)",
            page,
            url,
            len(all_features),
        )

        # ArcGIS returns fewer than pageSize on the last page
        if len(features) < _PAGE_SIZE:
            break

    logger.info(
        "ArcGIS pagination complete: %d total records from %s",
        len(all_features),
        url,
    )
    return all_features


def _arcgis_features_to_gdf(features: list[dict[str, Any]]) -> gpd.GeoDataFrame:
    """Convert ArcGIS GeoJSON-style feature list to a GeoDataFrame.

    The ``geometry`` column is parsed from the JSON string stored in
    each feature dict (produced by ``_arcgis_query_paginated``).

    Parameters
    ----------
    features : list[dict]
        Feature dicts with a ``geometry`` JSON string key.

    Returns
    -------
    gpd.GeoDataFrame
        With CRS EPSG:4326.  The ``geometry`` key is consumed as the
        geometry column.
    """
    records: list[dict[str, Any]] = []
    geometries: list[Any] = []

    for feat in features:
        geo_json = feat.pop("geometry", None)
        if geo_json:
            try:
                parsed = json.loads(geo_json) if isinstance(geo_json, str) else geo_json
                geometries.append(shape(parsed))
            except (ValueError, TypeError, KeyError) as exc:
                logger.warning("Failed to parse geometry: %s", exc)
                geometries.append(None)
        else:
            geometries.append(None)
        records.append(feat)

    return gpd.GeoDataFrame(records, geometry=geometries, crs="EPSG:4326")


def fetch_parcels_arcgis(
    *,
    max_pages: int = 0,
    cache_name: str = "sacog_assessor_parcels",
    ignore_cache: bool = False,
) -> gpd.GeoDataFrame:
    """Fetch Sacramento County parcel geometries from PARCELS/MapServer/8.

    Paginates all ~508K parcels, converts SRID 2226 (CA Albers) to 4326,
    and caches to ``{CACHE_DIR}/{cache_name}.parquet``.

    Parameters
    ----------
    max_pages : int, optional
        Limit pages for testing (0 = unlimited).
    cache_name : str, optional
        Cache file name (without extension).
    ignore_cache : bool, optional
        Re-download even if cache exists.

    Returns
    -------
    gpd.GeoDataFrame
        Parcel data in EPSG:4326 with columns: parcel_id, geometry,
        assessor_use_code, lotsize, jurisdiction, landuse.
    """
    cache_path = CACHE_DIR / f"{cache_name}.parquet"

    if cache_path.exists() and not ignore_cache:
        logger.info("Loading cached parcels from %s", cache_path)
        gdf = gpd.read_parquet(cache_path)
        if not gdf.empty:
            return gdf

    logger.info(
        "Fetching parcels from ArcGIS PARCELS/MapServer/8 (max_pages=%s)",
        max_pages or "all",
    )
    features = _arcgis_query_paginated(
        PARCELS_MAP_SERVER,
        _PARCEL_FIELDS,
        max_pages=max_pages,
    )

    gdf = _arcgis_features_to_gdf(features)

    # The geometry from ArcGIS PARCELS/MapServer/8 comes in SRID 2226 (CA Albers)
    # but we requested outSR=4326 so it's already transformed.
    # Ensure CRS is set correctly.
    if gdf.crs is None:
        gdf.set_crs("EPSG:4326", inplace=True)

    # Rename columns to staging conventions
    gdf = gdf.rename(
        columns={
            "PARCEL_NUMBER": "parcel_id",
            "LANDUSE": "landuse",
            "ZONE_": "zone",
            "LOTSIZE": "lotsize",
            "JURISDICTION": "jurisdiction",
        }
    )

    # Ensure parcel_id is a string
    gdf["parcel_id"] = gdf["parcel_id"].astype(str)

    # Cache
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(cache_path)
    logger.info("Cached %d parcels to %s", len(gdf), cache_path)
    return gdf


def fetch_sales_arcgis(
    *,
    max_pages: int = 0,
    cache_name: str = "sacog_assessor_sales",
    ignore_cache: bool = False,
) -> gpd.GeoDataFrame:
    """Fetch Sacramento County sales/building data from ASSESSOR/MapServer/1.

    Paginates all ~55K sold parcels with building characteristics.

    Parameters
    ----------
    max_pages : int, optional
        Limit pages for testing (0 = unlimited).
    cache_name : str, optional
        Cache file name (without extension).
    ignore_cache : bool, optional
        Re-download even if cache exists.

    Returns
    -------
    gpd.GeoDataFrame
        Sales data in EPSG:4326 with columns: parcel_id, living_area,
        building_sf, year_built, stories, bedrooms, baths,
        ground_floor_gross, land_use_code, property_type, sales_price,
        lot_size_acres, units.
    """
    cache_path = CACHE_DIR / f"{cache_name}.parquet"

    if cache_path.exists() and not ignore_cache:
        logger.info("Loading cached sales from %s", cache_path)
        gdf = gpd.read_parquet(cache_path)
        if not gdf.empty:
            return gdf

    logger.info(
        "Fetching sales from ArcGIS ASSESSOR/MapServer/1 (max_pages=%s)",
        max_pages or "all",
    )
    features = _arcgis_query_paginated(
        SALES_MAP_SERVER,
        _SALES_FIELDS,
        max_pages=max_pages,
    )

    gdf = _arcgis_features_to_gdf(features)

    if gdf.crs is None:
        gdf.set_crs("EPSG:4326", inplace=True)

    # Rename columns to staging conventions
    gdf = gdf.rename(
        columns={
            "PARCEL_NUMBER": "parcel_id",
            "TOTAL_LIVING_AREA": "living_area",
            "BUILDING_SF": "building_sf",
            "EFFECTIVE_YEAR_BUILT": "year_built",
            "NUMBER_OF_STORIES": "stories",
            "NUMBER_OF_BEDROOMS": "bedrooms",
            "NUMBER_OF_BATHS": "baths",
            "GROUND_FLOOR_GROSS": "ground_floor_gross",
            "LAND_USE_CODE": "land_use_code",
            "Property_Type": "property_type",
            "INDICATED_SALES_PRICE": "sales_price",
            "LOT_SIZE_ACRES": "lot_size_acres",
            "Units": "units",
        }
    )

    gdf["parcel_id"] = gdf["parcel_id"].astype(str)

    # Cache
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(cache_path)
    logger.info("Cached %d sales records to %s", len(gdf), cache_path)
    return gdf


def load_to_postgis(
    parcels: gpd.GeoDataFrame | None = None,
    sales: gpd.GeoDataFrame | None = None,
    schema: str = "public",
    *,
    if_exists: str = "replace",
) -> dict[str, int]:
    """Write assessor parcel and/or sales data to PostGIS staging tables.

    Creates tables:
        ``{schema}.sacog_assessor_parcels`` — parcel geometries + land use
        ``{schema}.sacog_assessor_sales`` — building characteristics

    Parameters
    ----------
    parcels : gpd.GeoDataFrame | None
        Parcel data from ``fetch_parcels_arcgis()``.
    sales : gpd.GeoDataFrame | None
        Sales data from ``fetch_sales_arcgis()``.
    schema : str, optional
        Database schema (default ``"public"``).
    if_exists : str, optional
        SQL write mode (default ``"replace"``).

    Returns
    -------
    dict[str, int]
        Mapping of table name to row count for tables written.
    """
    engine = get_engine()
    result: dict[str, int] = {}

    # When replacing, drop with CASCADE first to handle dependent views
    def _drop_cascade(table: str) -> None:
        if if_exists == "replace":
            with engine.connect() as conn:
                conn.execute(
                    text(f"DROP TABLE IF EXISTS {schema}.{table} CASCADE")
                )
                conn.commit()

    if parcels is not None and not parcels.empty:
        _drop_cascade("sacog_assessor_parcels_raw")
        parcels.to_postgis(
            "sacog_assessor_parcels_raw",
            engine,
            schema=schema,
            if_exists="append",
            index=False,
            dtype={"geometry": "geometry(Geometry, 4326)"},
        )
        row_count = len(parcels)
        logger.info(
            "Loaded %d rows to %s.sacog_assessor_parcels",
            row_count,
            schema,
        )
        result["sacog_assessor_parcels_raw"] = row_count

    if sales is not None and not sales.empty:
        _drop_cascade("sacog_assessor_sales_raw")
        sales.to_postgis(
            "sacog_assessor_sales_raw",
            engine,
            schema=schema,
            if_exists="append",
            index=False,
        )
        row_count = len(sales)
        logger.info(
            "Loaded %d rows to %s.sacog_assessor_sales",
            row_count,
            schema,
        )
        result["sacog_assessor_sales_raw"] = row_count

    return result
