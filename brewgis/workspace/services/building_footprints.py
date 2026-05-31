"""Overture Maps building footprint fetcher.

Downloads building footprints from the Overture Maps release for Sacramento
County, California, and loads them to a PostGIS staging table for downstream
parcel-building-footprint feature extraction.

Usage::

    from brewgis.workspace.services.building_footprints import download_overture_buildings

    result = download_overture_buildings(ignore_cache=False)
    print(f"Loaded {result['row_count']} buildings to {result['table_name']}")

Source: https://overturemaps.org/
License: ODbL (https://overturemaps.org/license/)
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

import geopandas as gpd
import pyarrow.compute as pc
import pyarrow.fs
from django.conf import settings
from pyarrow.parquet import ParquetDataset
from shapely import from_wkb

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = settings.DATA_DOWNLOAD_CACHE_DIR

# Overture Maps release — pin to a known-good version
OVERTURE_RELEASE = "2026-05-20.0"
S3_BUCKET = "overturemaps-us-west-2"
S3_BUILDINGS_PATH = (
    f"{S3_BUCKET}/release/{OVERTURE_RELEASE}/theme=buildings/type=building/"
)

# Sacramento County, CA bounding box (approximate)
SACRAMENTO_BBOX = (-121.87, 38.02, -121.01, 38.74)

# Target PostGIS table name
OUTPUT_TABLE = "overture_buildings"


def _check_overture_buildings_exists() -> bool:
    """Return True if the overture_buildings table already exists and has rows."""
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT EXISTS ( "
                "  SELECT 1 FROM information_schema.tables "
                "  WHERE table_schema = 'public' AND table_name = 'overture_buildings'"
                ")"
            )
        ).scalar()
        if not row:
            return False
        count = conn.execute(
            text("SELECT COUNT(*) FROM public.overture_buildings")
        ).scalar()
        return bool(count) and count > 0


def _build_filter_expr() -> pc.Expression:
    """Build a pyarrow filter expression for the Sacramento County bbox.

    Overture stores an explicit ``bbox`` struct column (xmin, xmax, ymin, ymax)
    per row.  pyarrow pushes this filter down to the row-group level, skipping
    row groups outside the query bbox.
    """
    min_x, min_y, max_x, max_y = SACRAMENTO_BBOX
    return (
        (pc.field("bbox", "xmin") < max_x)
        & (pc.field("bbox", "xmax") > min_x)
        & (pc.field("bbox", "ymin") < max_y)
        & (pc.field("bbox", "ymax") > min_y)
    )


def _download_buildings_parquet(
    cache_path: Path,
    *,
    ignore_cache: bool = False,
) -> list[dict]:
    """Download Overture building footprints for Sacramento County.

    Downloads GeoParquet files from the Overture Maps S3 release, filtered
    by the Sacramento County bounding box.  Caches the result as a parquet
    file on disk for subsequent runs.

    Returns a list of raw dict records from the parquet file.
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if cache_path.exists() and not ignore_cache:
        logger.info("Loading cached Overture buildings from %s", cache_path)
        gdf = gpd.read_parquet(cache_path)
        records = gpd.GeoDataFrame(gdf).to_dict("records") if len(gdf) else []
        logger.info("Loaded %d cached records", len(records))
        return records

    logger.info("Downloading Overture building footprints from S3 (Sacramento bbox)")

    fs = pyarrow.fs.S3FileSystem(anonymous=True, region="us-west-2")

    # ParquetDataset with a filter expression — pyarrow only reads row groups
    # whose bbox overlaps Sacramento County.  The bbox struct column is pushed
    # down to the S3 scan, drastically reducing data transfer (from 256 GB
    # US-wide to ~tens of MB for Sacramento).
    dataset = ParquetDataset(
        S3_BUILDINGS_PATH,
        filesystem=fs,
        filters=_build_filter_expr(),
    )

    table = dataset.read(
        columns=[
            "geometry",
            "height",
            "num_floors",
            "class",
            "sources",
            "id",
        ]
    )

    if table.num_rows == 0:
        logger.warning("No rows found in Overture buildings dataset for Sacramento")
        return []

    # Convert to GeoDataFrame (dropping the bbox struct column)
    # Overture stores geometry as WKB binary — convert to Shapely
    wkb_list = table.column("geometry").to_pylist()
    geometries = from_wkb(wkb_list)
    non_geo = {
        col: table.column(col).to_pylist()
        for col in table.column_names
        if col not in ("geometry", "bbox")
    }
    gdf = gpd.GeoDataFrame(
        non_geo,
        geometry=geometries,
        crs="EPSG:4326",
    )

    logger.info("Downloaded %d building footprints", len(gdf))

    if len(gdf) == 0:
        logger.warning("No building footprints found for Sacramento County bbox")
        return []

    # Cache to disk
    gdf.to_parquet(cache_path)
    logger.info("Cached %d buildings to %s", len(gdf), cache_path)
    return gdf.to_dict("records")


def download_overture_buildings(
    *,
    ignore_cache: bool = False,
) -> dict:
    """Download and load Overture building footprints to PostGIS.

    Downloads building footprints from the Overture Maps release for
    Sacramento County, loads them to ``public.overture_buildings``, and
    creates a GiST spatial index.

    Parameters
    ----------
    ignore_cache : bool, optional
        If True, re-download even if cached parquet exists.

    Returns
    -------
    dict
        Mapping with keys ``table_name`` (str) and ``row_count`` (int).
    """
    # Short-circuit if already loaded and cache is acceptable
    has_data = _check_overture_buildings_exists()
    if has_data and not ignore_cache:
        logger.info(
            "overture_buildings already populated; skipping download. "
            "Pass ignore_cache=True to re-download."
        )
        engine = get_engine()
        with engine.connect() as conn:
            row_count = conn.execute(
                text("SELECT COUNT(*) FROM public.overture_buildings")
            ).scalar()
        return {"table_name": OUTPUT_TABLE, "row_count": row_count or 0}

    cache_path = CACHE_DIR / "overture_buildings" / f"{OVERTURE_RELEASE}.parquet"

    records = _download_buildings_parquet(
        cache_path,
        ignore_cache=ignore_cache,
    )

    if not records:
        logger.warning("No building footprint records downloaded")
        return {"table_name": OUTPUT_TABLE, "row_count": 0}

    # Build rows with clean column types for PostGIS
    rows = []
    for r in records:
        geom = r.get("geometry")
        if geom is None:
            continue
        height = r.get("height")
        num_floors = r.get("num_floors")
        cls = r.get("class")
        sources_raw = r.get("sources")
        rid = r.get("id")

        source_str = None
        if sources_raw is not None:
            if isinstance(sources_raw, dict):
                source_str = sources_raw.get("primary") or sources_raw.get("source")
            elif isinstance(sources_raw, list):
                source_str = str(
                    [s.get("source", "") for s in sources_raw if isinstance(s, dict)]
                )

        rows.append(
            {
                "geometry": geom,
                "height": (
                    None
                    if height is None
                    or (isinstance(height, float) and math.isnan(height))
                    else float(height)
                ),
                "levels": (
                    None
                    if num_floors is None
                    or (isinstance(num_floors, float) and math.isnan(num_floors))
                    else int(num_floors)
                ),
                "class": str(cls) if cls is not None else None,
                "source": source_str,
                "id": str(rid) if rid is not None else None,
            }
        )

    if not rows:
        logger.warning("No valid building footprint geometries after filtering")
        return {"table_name": OUTPUT_TABLE, "row_count": 0}

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")

    engine = get_engine()

    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS public.{OUTPUT_TABLE} CASCADE"))

    gdf.to_postgis(
        OUTPUT_TABLE,
        engine,
        schema="public",
        if_exists="replace",
        index=False,
        dtype={"geometry": "geometry(Geometry, 4326)"},
    )

    row_count = len(gdf)
    logger.info("Loaded %d rows to public.%s", row_count, OUTPUT_TABLE)

    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS idx_{OUTPUT_TABLE}_geometry "
                f"ON public.{OUTPUT_TABLE} USING GIST (geometry)"
            )
        )
        conn.execute(text(f"ANALYZE public.{OUTPUT_TABLE}"))

    logger.info("Created GiST index on public.%s.geometry", OUTPUT_TABLE)
    return {"table_name": OUTPUT_TABLE, "row_count": row_count}
