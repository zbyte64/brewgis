"""dlt pipeline for VIDA Google-Microsoft-OSM Combined Building Footprints.

Downloads S2-partitioned GeoParquet files from the VIDA dataset on Source
Cooperative S3 and loads ALL rows into a PostGIS staging table.  Spatial
filtering and deduplication against Overture buildings is owned by the
``buildings_combined`` dbt model downstream.

Usage::

    from brewgis.workspace.dlt_pipelines.vida_buildings import run_vida_buildings_pipeline

    result = run_vida_buildings_pipeline()
    print(f"Loaded {result['row_count']} buildings to {result['table_name']}")

Source: https://source.coop/repositories/vida/google-microsoft-osm-open-buildings/
License: ODbL (https://opendatacommons.org/licenses/odbl/)
"""

from __future__ import annotations

import logging
from typing import Any

import dlt
import pyarrow.fs
import pyarrow.parquet
from dlt.destinations.impl.postgres.postgres_adapter import postgres_adapter
from shapely import from_wkb

logger = logging.getLogger(__name__)

# VIDA release — pin to a known-good version
VIDA_RELEASE_DIR = "v2.0"
S3_BUCKET = "us-west-2.opendata.source.coop"
S3_S2_PARTITION_DIR = (
    f"{S3_BUCKET}/vida/google-microsoft-osm-open-buildings"
    "/geoparquet/by_country_s2/country_iso=USA"
)

# Target PostGIS table name
OUTPUT_TABLE = "vida_combined_buildings"

__all__ = [
    "run_vida_buildings_pipeline",
    "vida_buildings_source",
]


@dlt.source(name="vida_buildings", max_table_nesting=0)
def vida_buildings_source() -> list[Any]:
    """dlt source for VIDA combined building footprints.

    Lists S2-partitioned parquet files for the USA, reads each file via
    pyarrow, and yields every row as a dict.  Downloads ALL rows from
    whatever S2 files exist — no spatial filtering at the pipeline level.
    That's owned by the downstream ``buildings_combined`` dbt model.

    Returns:
        List with a single :class:`dlt.Resource` wrapped via
        :func:`postgres_adapter` for PostGIS geometry handling.
    """
    return [
        postgres_adapter(
            vida_buildings_resource(),
            geometry="geometry",
        )
    ]


@dlt.resource(
    name=OUTPUT_TABLE,
    write_disposition="replace",
)
def vida_buildings_resource() -> Any:
    """Yield VIDA building footprint rows from all S2 parquet files.

    Lists the S2 sub-partitioned files for the USA, reads each file via
    pyarrow, and yields every row as a dict with WKT geometry.

    Yields dicts with keys: ``geometry`` (WKT), ``confidence``,
    ``bf_source``, ``area_in_meters``.
    """
    fs = pyarrow.fs.S3FileSystem(
        anonymous=True,
        region="us-west-2",
        connect_timeout=30,
        request_timeout=300,
    )

    # List S2 partition files
    try:
        selector = pyarrow.fs.FileSelector(S3_S2_PARTITION_DIR, recursive=False)
        all_infos = fs.get_file_info(selector)
    except (OSError, pyarrow.ArrowException):
        logger.exception("Failed to list S2 partition directory")
        raise

    s2_files = [info.path for info in all_infos if info.path.endswith(".parquet")]
    if not s2_files:
        msg = "No S2 partition files found for USA"
        logger.error(msg)
        raise RuntimeError(msg)

    logger.info("Found %d S2 partition files for USA", len(s2_files))

    total_rows_yielded = 0
    for file_path in s2_files:
        file_basename = file_path.rsplit("/", 1)[-1]
        try:
            # Use ParquetFile (not read_table) — it opens a single file and
            # does NOT auto-detect Hive partitions from the ``country_iso=USA``
            # directory component, which would conflict with the parquet
            # file's internal ``country_iso`` dictionary column.
            pf = pyarrow.parquet.ParquetFile(file_path, filesystem=fs)
            table = pf.read(
                columns=[
                    "geometry",
                    "confidence",
                    "bf_source",
                    "area_in_meters",
                ],
                use_threads=False,
            )
        except (OSError, pyarrow.ArrowException) as exc:
            logger.warning(
                "Failed to read S2 file %s: %s; skipping", file_basename, exc
            )
            continue

        if table.num_rows == 0:
            continue

        # Convert WKB geometry to Shapely, then yield WKT for PostGIS
        wkb_list = table.column("geometry").to_pylist()
        geometries = from_wkb(wkb_list)
        confidence_col = table.column("confidence").to_pylist()
        bf_source_col = table.column("bf_source").to_pylist()
        area_col = table.column("area_in_meters").to_pylist()

        for i in range(table.num_rows):
            geom = geometries[i]
            if geom is None or geom.is_empty:
                continue
            yield {
                "geometry": geom.wkt,
                "confidence": (
                    float(confidence_col[i]) if confidence_col[i] is not None else None
                ),
                "bf_source": (
                    str(bf_source_col[i]) if bf_source_col[i] is not None else None
                ),
                "area_in_meters": (
                    float(area_col[i]) if area_col[i] is not None else None
                ),
            }

        total_rows_yielded += table.num_rows
        logger.info(
            "Yielded %s: %d rows (%d total)",
            file_basename,
            table.num_rows,
            total_rows_yielded,
        )

    logger.info("Yielded %d total VIDA building footprint rows", total_rows_yielded)


def run_vida_buildings_pipeline(
    schema: str = "public",
) -> dict:
    """Run dlt pipeline to load VIDA combined building footprints to PostGIS.

    Downloads all USA S2-partitioned GeoParquet files and loads every row
    into ``public.vida_combined_buildings`` (``OUTPUT_TABLE``).  The table
    is replaced on each run (``write_disposition="replace"``).

    Parameters
    ----------
    schema : str, optional
        PostgreSQL schema for the destination table (default ``"public"``).

    Returns
    -------
    dict
        Keys: ``table_name`` (str), ``row_count`` (int), ``load_info`` (str).
    """
    pipeline = dlt.pipeline(
        pipeline_name="vida_buildings",
        destination="postgres",
        dataset_name=schema,
    )

    load_info = pipeline.run(vida_buildings_source())

    total_rows = 0
    for step in pipeline.last_trace.steps:
        si = step.step_info
        if si is not None and hasattr(si, "row_counts") and si.row_counts:
            total_rows += si.row_counts.get(OUTPUT_TABLE, 0)
            break

    # Handle dlt's staging-schema quirk: dlt may create the table in
    # public_staging instead of public.
    from brewgis.workspace.services._db import get_engine
    from brewgis.workspace.services._db import text as _text

    engine = get_engine()
    with engine.connect() as conn:
        exists_expected = conn.execute(
            _text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_schema = :schema AND table_name = :tbl"
                ")"
            ),
            {"schema": schema, "tbl": OUTPUT_TABLE},
        ).scalar()
        if not exists_expected:
            staging_schema = f"{schema}_staging"
            exists_staging = conn.execute(
                _text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM information_schema.tables"
                    "  WHERE table_schema = :staging AND table_name = :tbl"
                    ")"
                ),
                {"staging": staging_schema, "tbl": OUTPUT_TABLE},
            ).scalar()
            if exists_staging:
                conn.execute(
                    _text(f"DROP TABLE IF EXISTS {schema}.{OUTPUT_TABLE} CASCADE")
                )
                conn.execute(
                    _text(
                        f"ALTER TABLE {staging_schema}.{OUTPUT_TABLE} SET SCHEMA {schema}"
                    )
                )
                conn.commit()
        else:
            conn.execute(
                _text(f"DROP TABLE IF EXISTS {schema}_staging.{OUTPUT_TABLE} CASCADE")
            )
            conn.commit()

    return {
        "table_name": f"{schema}.{OUTPUT_TABLE}",
        "row_count": total_rows,
        "load_info": str(load_info),
    }
