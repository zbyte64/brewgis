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
from dlt.destinations.impl.postgres.postgres_adapter import postgres_adapter

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
    return [
        postgres_adapter(
            tiger_bg_resource(state_fips, year=year, ignore_cache=ignore_cache),
            geometry="geometry",
        )
    ]


@dlt.resource(
    name="tiger_block_groups",
    write_disposition="append",
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

    for _, row in gdf.iterrows():
        geoid = (
            str(row["STATEFP"]).zfill(2)
            + str(row["COUNTYFP"]).zfill(3)
            + str(row["TRACTCE"]).zfill(6)
            + str(row["BLKGRPCE"]).zfill(1)
        )
        yield {
            "geoid": geoid,
            "geometry": row.geometry.wkt,
            "state_fips": state_fips,
            "vintage": year,
        }


def run_tiger_bg_pipeline(
    state_fips: str,
    schema: str = "public",
    vintages: list[str] | None = None,
    ignore_cache: bool = False,
) -> dict:
    """Run dlt pipeline to extract TIGER/Line BG data to a staging table.

    Loads one or more TIGER/Line block group vintages (e.g. ``"2013"``,
    ``"2023"``) into the same destination table, distinguished by a
    ``vintage`` column. Existing rows for a given vintage are deleted
    before re-loading, so re-runs are idempotent.

    Parameters
    ----------
    state_fips : str
        Two-digit state FIPS code.
    schema : str, optional
        PostgreSQL schema for the destination table (default ``"public"``).
    vintages : list[str] | None, optional
        List of TIGER/Line release years to load. Each vintage is loaded
        with ``append`` disposition. When ``None``, defaults to
        ``["2023"]`` for backward compatibility.
    ignore_cache : bool, optional
        Re-download shapefile even if cached.

    Returns
    -------
    dict
        Keys: ``success``, ``table_name``, ``row_count``, ``load_info``
        (or ``error`` on failure).
    """
    if vintages is None:
        vintages = ["2023"]

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
                    "  WHERE table_schema = :schema AND table_name = 'tiger_block_groups'"
                    ")"
                ),
                {"schema": schema},
            ).scalar()
            if table_exists:
                # Ensure the vintage column exists (safe for tables created before this change)
                conn.execute(
                    _text(
                        f"ALTER TABLE {schema}.tiger_block_groups ADD COLUMN IF NOT EXISTS vintage TEXT"
                    )
                )
                conn.execute(
                    _text(
                        f"DELETE FROM {schema}.tiger_block_groups WHERE vintage = :v"
                    ),
                    {"v": vintage},
                )
                conn.commit()

        # 2. Load with append
        pipeline = dlt.pipeline(
            pipeline_name=f"tiger_bg_{state_fips}_{vintage}",
            destination="postgres",
            dataset_name=schema,
        )
        load_info = pipeline.run(
            tiger_bg_source(state_fips, year=vintage, ignore_cache=ignore_cache),
        )
        load_info_strs.append(str(load_info))

        # 3. Count rows from this run
        for step in pipeline.last_trace.steps:
            si = step.step_info
            if si is not None and hasattr(si, "row_counts") and si.row_counts:
                total_rows += si.row_counts.get("tiger_block_groups", 0)
                break

        # 4. On first vintage, handle dlt's staging-schema quirk:
        #    dlt's merge disposition can leave the table in a staging schema
        #    (e.g. public_staging) when dataset_name="public". If that happened,
        #    move it to the correct schema. If the table isn't found anywhere,
        #    it will be created by the next vintage load — no error needed here.
        if idx == 0:
            engine = get_engine()
            with engine.connect() as conn:
                exists_expected = conn.execute(
                    _text(
                        "SELECT EXISTS ("
                        "  SELECT 1 FROM information_schema.tables"
                        "  WHERE table_schema = :schema AND table_name = 'tiger_block_groups'"
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
                            "  WHERE table_schema = :staging AND table_name = 'tiger_block_groups'"
                            ")"
                        ),
                        {"staging": staging_schema},
                    ).scalar()
                    if exists_staging:
                        conn.execute(
                            _text(
                                f"DROP TABLE IF EXISTS {schema}.tiger_block_groups CASCADE"
                            )
                        )
                        conn.execute(
                            _text(
                                f"ALTER TABLE {staging_schema}.tiger_block_groups SET SCHEMA {schema}"
                            )
                        )
                        conn.commit()
                else:
                    conn.execute(
                        _text(
                            f"DROP TABLE IF EXISTS {schema}_staging.tiger_block_groups CASCADE"
                        )
                    )
                    conn.commit()

    if total_rows == 0:
        return {
            "success": False,
            "table_name": f"{schema}.tiger_block_groups",
            "row_count": 0,
            "load_info": "; ".join(load_info_strs),
            "error": "TIGER/Line BG pipeline completed but loaded 0 rows",
        }

    return {
        "success": True,
        "table_name": f"{schema}.tiger_block_groups",
        "row_count": total_rows,
        "load_info": "; ".join(load_info_strs),
    }
