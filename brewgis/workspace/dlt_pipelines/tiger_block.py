"""dlt pipeline for TIGER/Line TABBLOCK shapefile downloads.

Downloads 2020 Census TIGER/Line block boundary shapefiles (one ZIP per
state) from the US Census Bureau and loads them into a PostgreSQL staging
table via dlt. The block-level geometries are used for joining LEHD LODES
employment data to spatial units.
"""

from __future__ import annotations

import tempfile

from typing import Any
import dlt
import geopandas as gpd
import requests


__all__ = [
    "tiger_block_source",
    "run_tiger_block_pipeline",
]


@dlt.source(name="tiger_block", max_table_nesting=0)
def tiger_block_source(
    state_fips: str = "06",
    county_fips: str = "067",
) -> list[Any]:
    """dlt source for TIGER/Line TABBLOCK shapefile extraction.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code (included for
            interface consistency with other pipelines; the TIGER/Line
            block file is per-state).

    Returns:
        List with a single :class:`dlt.Resource` yielding block dicts
        with a WKT geometry string.
    """
    return [tiger_block_resource(state_fips)]


@dlt.resource(
    name="tiger_blocks",
    write_disposition="merge",
    primary_key="geoid",
)
def tiger_block_resource(state_fips: str) -> Any:
    """Download TIGER/Line TABBLOCK shapefile ZIP and yield block dicts.

    Downloads the 2020 vintage block boundary file for the given state,
    reprojects to EPSG:4326, builds a 15-digit GEOID from STATEFP10 +
    COUNTYFP10 + TRACTCE10 + BLOCKCE10, and yields each block as a dict
    with a WKT geometry string.
    """
    url = f"https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK/tl_2020_{state_fips}_tabblock10.zip"

    response = requests.get(url, timeout=120)
    response.raise_for_status()

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = f"{tmpdir}/tl_2020_{state_fips}_tabblock10.zip"
        with open(zip_path, "wb") as f:
            f.write(response.content)

        gdf = gpd.read_file(f"zip://{zip_path}")

    if gdf.empty:
        return

    gdf = gdf.to_crs("EPSG:4326")

    for _, row in gdf.iterrows():
        statefp = str(row.get("STATEFP10", "") or row.get("STATEFP", ""))
        countyfp = str(row.get("COUNTYFP10", "") or row.get("COUNTYFP", ""))
        tractce = str(row.get("TRACTCE10", "") or row.get("TRACTCE", ""))
        blockce = str(row.get("BLOCKCE10", "") or row.get("BLOCKCE", ""))

        geoid = f"{statefp}{countyfp}{tractce}{blockce}"

        yield {
            "geoid": geoid,
            "geometry": row.geometry.wkt,
            "state_fips": state_fips,
        }


def run_tiger_block_pipeline(
    state_fips: str,
    schema: str = "public",
) -> dict:
    """Run dlt pipeline to load TIGER/Line TABBLOCK data to a staging table.

    Parameters
    ----------
    state_fips : str
        Two-digit state FIPS code.
    schema : str, optional
        Postgres schema for the staging table (default ``"public"``).

    Returns
    -------
    dict
        ``{"success": True, "table_name": str, "row_count": int,
        "load_info": str}`` on success, or ``{"success": False,
        "error": str}`` on failure.
    """
    pipeline = dlt.pipeline(
        pipeline_name=f"tiger_block_{state_fips}",
        destination="postgres",
        dataset_name=schema,
    )

    try:
        load_info = pipeline.run(
            tiger_block_source(state_fips),
        )

        row_count = 0
        if load_info.packages:  # type: ignore[attr-defined]
            last_pkg = load_info.packages[-1]  # type: ignore[attr-defined]
            for table_name, table_meta in last_pkg.tables.items():
                if table_name == "tiger_blocks":
                    row_count = table_meta.get("row_count", 0)
                    break

        return {
            "success": True,
            "table_name": f"{schema}.tiger_blocks",
            "row_count": row_count,
            "load_info": str(load_info),
        }
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}
