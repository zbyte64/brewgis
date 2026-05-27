"""dlt pipeline for TIGER/Line TABBLOCK shapefile downloads.

Downloads TIGER/Line block boundary shapefiles (one ZIP per state) from
the US Census Bureau and loads them into a PostgreSQL staging table via
dlt. Writes with merge disposition keyed on the 15-digit GEOID for upsert
semantics on re-run.

Block boundaries are decennial-only (Census 2020). The 2020 TIGER/Line
release uses the TABBLOCK10 filename convention. TIGER2023 does NOT include
a TABBLOCK directory. When newer releases provide block boundaries they can
be added by extending the vintages list with the appropriate URL.

The block-level geometries are used for joining LEHD LODES employment data
to spatial units at the highest resolution (census block, 15-digit GEOID).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import dlt
from dlt.destinations.impl.postgres.postgres_adapter import postgres_adapter
import geopandas as gpd
from django.conf import settings

CACHE_DIR: Path = settings.DATA_DOWNLOAD_CACHE_DIR

__all__ = [
    "run_tiger_block_pipeline",
    "tiger_block_source",
]


@dlt.source(name="tiger_block", max_table_nesting=0)
def tiger_block_source(
    state_fips: str = "06",
    county_fips: str = "067",
    year: str = "2020",
    ignore_cache: bool = False,
) -> list[Any]:
    """dlt source for TIGER/Line TABBLOCK shapefile extraction.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code (reserved for future use).
        year: TIGER/Line release year (default "2020").
        ignore_cache: Re-download shapefile even if cached.

    Returns:
        List with a single :class:`dlt.Resource` yielding block geometry
        dicts with PostGIS geometry column adapter.
    """
    return [
        postgres_adapter(
            tiger_block_resource(
                state_fips, year=year, ignore_cache=ignore_cache
            ),
            geometry="geometry",
        )
    ]


# TIGER TABBLOCK URL by vintage:
#   2020: https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK/tl_2020_{state_fips}_tabblock10.zip
#   TABBLOCK does NOT exist for 2023 (decennial-only). Add future decennial
#   years here as the URL pattern becomes known.
_TIGER_BLOCK_URLS: dict[str, str] = {
    "2020": "https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK/tl_2020_{state_fips}_tabblock10.zip",
}


@dlt.resource(
    name="tiger_blocks",
    write_disposition="append",
)
def tiger_block_resource(state_fips: str, year: str = "2020", ignore_cache: bool = False) -> Any:
    """Download TIGER/Line TABBLOCK shapefile ZIP and yield block dicts.

    Downloads the block boundary file for the given state and vintage,
    reprojects to EPSG:4326, builds a 15-digit GEOID from STATEFP10 +
    COUNTYFP10 + TRACTCE10 + BLOCKCE10, and yields each block as a dict
    with a WKT geometry string.

    Args:
        state_fips: Two-digit state FIPS code.
        year: TIGER/Line release year (default "2020").
        ignore_cache: Re-download shapefile even if cached.

    Yields:
        Dict with ``geoid`` (15-digit), ``geometry`` (WKT), ``state_fips``,
        and ``vintage``.
    """
    import urllib.request

    url_template = _TIGER_BLOCK_URLS.get(year)
    if url_template is None:
        raise ValueError(
            f"Unsupported TIGER block vintage '{year}'. "
            f"Supported vintages: {list(_TIGER_BLOCK_URLS.keys())}. "
            "Block boundaries are decennial-only; 2020 is the available vintage."
        )
    url = url_template.format(state_fips=state_fips)

    zip_path = CACHE_DIR / f"TIGER{year}" / "TABBLOCK" / f"tl_{year}_{state_fips}_tabblock.zip"
    zip_path.parent.mkdir(exist_ok=True, parents=True)

    if ignore_cache or not zip_path.exists():
        urllib.request.urlretrieve(url, str(zip_path))

    gdf = gpd.read_file("zip://" + str(zip_path))

    if gdf.empty:
        return

    # TIGER/Line ships in NAD83 (EPSG:4269); reproject to WGS84
    if gdf.crs is None:
        gdf.set_crs("EPSG:4269", inplace=True)
    gdf = gdf.to_crs("EPSG:4326")

    statefp_col = next((c for c in ("STATEFP10", "STATEFP") if c in gdf.columns), None)
    countyfp_col = next((c for c in ("COUNTYFP10", "COUNTYFP") if c in gdf.columns), None)
    tractce_col = next((c for c in ("TRACTCE10", "TRACTCE") if c in gdf.columns), None)
    blockce_col = next((c for c in ("BLOCKCE10", "BLOCKCE") if c in gdf.columns), None)

    for _, row in gdf.iterrows():
        statefp = str(row.get(statefp_col, "")).zfill(2)
        countyfp = str(row.get(countyfp_col, "")).zfill(3)
        tractce = str(row.get(tractce_col, "")).zfill(6)
        blockce = str(row.get(blockce_col, "")).zfill(4)

        geoid = f"{statefp}{countyfp}{tractce}{blockce}"

        yield {
            "geoid": geoid,
            "geometry": row.geometry.wkt,
            "state_fips": state_fips,
            "vintage": year,
        }


def run_tiger_block_pipeline(
    state_fips: str,
    schema: str = "public",
    vintages: list[str] | None = None,
    ignore_cache: bool = False,
) -> dict:
    """Run dlt pipeline to load TIGER/Line TABBLOCK data to a staging table.

    Loads one or more TIGER/Line block boundary vintages (e.g. ``"2020"``)
    into the same destination table, distinguished by a ``vintage`` column.
    Existing rows for a given vintage are deleted before re-loading, so
    re-runs are idempotent.

    Parameters
    ----------
    state_fips : str
        Two-digit state FIPS code.
    schema : str, optional
        PostgreSQL schema for the destination table (default ``"public"``).
    vintages : list[str] | None, optional
        List of TIGER/Line release years to load. Each vintage is loaded
        with ``append`` disposition. When ``None``, defaults to ``["2020"]``.
    ignore_cache : bool, optional
        Re-download shapefile even if cached.

    Returns
    -------
    dict
        Keys: ``success``, ``table_name``, ``row_count``, ``load_info``
        (or ``error`` on failure).
    """
    if vintages is None:
        vintages = ["2020"]

    from brewgis.workspace.services._db import get_engine
    from brewgis.workspace.services._db import text as _text

    total_rows = 0
    load_info_strs: list[str] = []

    for idx, vintage in enumerate(vintages):
        # 1. Delete existing rows for this vintage (no-op if table doesn't exist)
        engine = get_engine()
        with engine.connect() as conn:
            table_exists = conn.execute(
                _text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM information_schema.tables"
                    "  WHERE table_schema = :schema AND table_name = 'tiger_blocks'"
                    ")"
                ),
                {"schema": schema},
            ).scalar()
            if table_exists:
                conn.execute(
                    _text(
                        "ALTER TABLE {schema}.tiger_blocks ADD COLUMN IF NOT EXISTS vintage TEXT".format(
                            schema=schema
                        )
                    )
                )
                conn.execute(
                    _text(
                        "DELETE FROM {schema}.tiger_blocks WHERE vintage = :v".format(
                            schema=schema
                        )
                    ),
                    {"v": vintage},
                )
                conn.commit()

        # 2. Load with append
        pipeline = dlt.pipeline(
            pipeline_name=f"tiger_block_{state_fips}_{vintage}",
            destination="postgres",
            dataset_name=schema,
        )
        load_info = pipeline.run(
            tiger_block_source(state_fips, year=vintage, ignore_cache=ignore_cache),
        )
        load_info_strs.append(str(load_info))

        # 3. Count rows from this run
        for step in pipeline.last_trace.steps:
            si = step.step_info
            if si is not None and hasattr(si, "row_counts") and si.row_counts:
                total_rows += si.row_counts.get("tiger_blocks", 0)
                break

        # 4. On first vintage, handle dlt's staging-schema quirk
        if idx == 0:
            engine = get_engine()
            with engine.connect() as conn:
                exists_expected = conn.execute(
                    _text(
                        "SELECT EXISTS ("
                        "  SELECT 1 FROM information_schema.tables"
                        "  WHERE table_schema = :schema AND table_name = 'tiger_blocks'"
                        ")"
                    ),
                    {"schema": schema},
                ).scalar()
                if not exists_expected:
                    staging_schema = f"{schema}_staging"
                    exists_staging = conn.execute(
                        _text(
                            "SELECT EXISTS ("
                            "  SELECT 1 FROM information_schema.tables"
                            "  WHERE table_schema = :staging AND table_name = 'tiger_blocks'"
                            ")"
                        ),
                        {"staging": staging_schema},
                    ).scalar()
                    if exists_staging:
                        conn.execute(
                            _text(
                                "DROP TABLE IF EXISTS {schema}.tiger_blocks CASCADE".format(
                                    schema=schema
                                )
                            )
                        )
                        conn.execute(
                            _text(
                                "ALTER TABLE {staging}.tiger_blocks SET SCHEMA {schema}".format(
                                    staging=staging_schema, schema=schema
                                )
                            )
                        )
                        conn.commit()
                else:
                    conn.execute(
                        _text(
                            "DROP TABLE IF EXISTS {schema}_staging.tiger_blocks CASCADE".format(
                                schema=schema
                            )
                        )
                    )
                    conn.commit()

    if total_rows == 0:
        return {
            "success": False,
            "table_name": f"{schema}.tiger_blocks",
            "row_count": 0,
            "load_info": "; ".join(load_info_strs),
            "error": "TIGER/Line block pipeline completed but loaded 0 rows",
        }

    return {
        "success": True,
        "table_name": f"{schema}.tiger_blocks",
        "row_count": total_rows,
        "load_info": "; ".join(load_info_strs),
    }
