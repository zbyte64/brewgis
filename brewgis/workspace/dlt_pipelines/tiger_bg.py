"""dlt pipeline for TIGER/Line block group (BG) shapefile extraction.

Downloads TIGER/Line BG shapefile ZIP files from the US Census Bureau and
loads them into a PostgreSQL staging table via dlt. Writes with merge
disposition keyed on the 12-digit GEOID for upsert semantics on re-run.

Domain-specific post-processing (geometry, column mapping) stays in
downstream transforms.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import dlt
import geopandas as gpd
from django.conf import settings

CACHE_DIR: Path = settings.DATA_DOWNLOAD_CACHE_DIR

__all__ = [
    "run_tiger_bg_pipeline",
    "tiger_bg_source",
]


@dlt.source(name="tiger_bg", max_table_nesting=0)
def tiger_bg_source(
    state_fips: str = "06",
    county_fips: str = "067",
    year: str = "2023",
    ignore_cache: bool = False,
) -> list[Any]:
    """dlt source for TIGER/Line block group shapefile extraction.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code (reserved for future use).
        year: TIGER/Line release year (default "2023").

    Returns:
        List with a single :class:`dlt.Resource` yielding block-group
        geometry dicts.
    """
    return [tiger_bg_resource(state_fips, year=year, ignore_cache=ignore_cache)]


@dlt.resource(
    name="tiger_block_groups",
    write_disposition="merge",
    primary_key="geoid",
)
def tiger_bg_resource(state_fips: str, year: str = "2023", ignore_cache=False) -> Any:
    """Download TIGER/Line BG shapefile ZIP and yield one dict per row.

    Downloads the state-level block-group shapefile from the Census
    TIGER/Line feed, reads it with GeoPandas, reprojects to
    EPSG:4326, builds the 12-digit GEOID from component FIPS codes,
    and yields a flat dict with WKT geometry for dlt compatibility.
    """
    import urllib.request

    url = (
        f"ftp://ftp2.census.gov/geo/tiger/TIGER{year}/BG/tl_{year}_{state_fips}_bg.zip"
    )
    zip_path = CACHE_DIR / f"TIGER{year}" / "BG" / f"tl_{year}_{state_fips}_bg.zip"

    if ignore_cache or not zip_path.exists():
        urllib.request.urlretrieve(url, zip_path)

        gdf = gpd.read_file(f"zip://{zip_path}")

        if gdf.empty:
            return

        # TIGER/Line ships in NAD83 (EPSG:4269); reproject to WGS84
        if gdf.crs is None:
            gdf.set_crs("EPSG:4269", inplace=True)
        gdf = gdf.to_crs("EPSG:4326")

        for _, row in gdf.iterrows():
            geoid = (
                str(row["STATEFP"]).zfill(2)
                + str(row["COUNTYFP"]).zfill(3)
                + str(row["TRACTCE"]).zfill(6)
                + str(row["BLKGRPCE"]).zfill(1)
            )
            wkt_geom = row.geometry.wkt
            yield {
                "geoid": geoid,
                "geometry": wkt_geom,
                "state_fips": state_fips,
            }


def run_tiger_bg_pipeline(
    state_fips: str,
    schema: str = "public",
    year: str = "2023",
    ignore_cache: bool = False,
) -> dict:
    """Run dlt pipeline to extract TIGER/Line BG data to a staging table.

    Parameters
    ----------
    state_fips : str
        Two-digit state FIPS code.
    schema : str, optional
        PostgreSQL schema for the destination table (default ``"public"``).
    year : str, optional
        TIGER/Line release year (default ``"2023"``).

    Returns
    -------
    dict
        Keys: ``success``, ``table_name``, ``row_count``, ``load_info``
        (or ``error`` on failure).
    """
    pipeline = dlt.pipeline(
        pipeline_name=f"tiger_bg_{state_fips}",
        destination="postgres",
        dataset_name=schema,
    )

    load_info = pipeline.run(
        tiger_bg_source(state_fips, year=year, ignore_cache=ignore_cache),
    )

    row_count = 0
    for step in pipeline.last_trace.steps:
        si = step.step_info
        if si is not None and hasattr(si, "row_counts") and si.row_counts:
            row_count = si.row_counts.get("tiger_block_groups", 0)
            break

    return {
        "success": True,
        "table_name": f"{schema}.tiger_block_groups",
        "row_count": row_count,
        "load_info": str(load_info),
    }
