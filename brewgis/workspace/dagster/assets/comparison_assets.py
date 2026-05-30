"""Dagster assets for the SACOG base canvas comparison pipeline.

Refactors the monolithic ``sacog_comparison`` asset into six independent
assets with clear dependency edges. Aggregation and correlation queries
are delegated to dbt models (``comparison/*``).
"""

import logging
from pathlib import Path

import geopandas as gpd
from dagster import AssetExecutionContext
from dagster import AssetOut
from dagster import MaterializeResult
from dagster import asset
from dagster import multi_asset
from django.conf import settings
from django.db import connection

from brewgis.soda import validate_base_canvas
from brewgis.soda import validate_dbt_table
from brewgis.soda import validate_land_use_classification
from brewgis.workspace.dagster.check_provenance import METADATA_CONTRACT_INLINE_COLUMNS
from brewgis.workspace.dagster.check_provenance import METADATA_CONTRACT_PATH
from brewgis.workspace.dagster.check_provenance import METADATA_CONTRACT_SOURCE
from brewgis.workspace.dagster.configs import SacogComparisonETLConfig
from brewgis.workspace.dagster.configs import SacogLoadParcelsConfig
from brewgis.workspace.dagster.configs import SacogReportConfig
from brewgis.workspace.dagster.resources.dbt_resource import DbtCliResource
from brewgis.workspace.dagster.resources.postgres_resource import PostgresResource
from brewgis.workspace.dlt_pipelines.tiger_bg import run_tiger_bg_pipeline
from brewgis.workspace.dlt_pipelines.tiger_block import run_tiger_block_pipeline
from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services.base_canvas_pipeline import run_pipeline
from brewgis.workspace.services.census_fetcher import _populate_acs_block_group
from brewgis.workspace.services.lehd_fetcher import _populate_wac_block
from brewgis.workspace.services.sacog_demo_db import RestoreError
from brewgis.workspace.services.sacog_demo_db import restore_sacog_demo_db

logger = logging.getLogger(__name__)

CACHE_DIR: Path = settings.DATA_DOWNLOAD_CACHE_DIR
V1_PARCELS = "sac_cnty_region_existing_land_use_parcels"
V1_BASE_CANVAS = "sac_cnty_region_base_canvas"
REPORT_PATH = CACHE_DIR / "sacog_comparison_report.md"

STATE_FIPS = "06"
COUNTY_FIPS = "067"


# ---------------------------------------------------------------------------
# Asset 0: TIGER/Line block group geometry
# ---------------------------------------------------------------------------


@asset(
    group_name="raw_data",
    compute_kind="python",
)
def tiger_bg_asset(
    context: AssetExecutionContext,
) -> MaterializeResult:
    """Fetch TIGER/Line block group polygons from Census and write to ``public.tiger_block_groups``.

    A prerequisite for ``sacog_populate_acs_block_group`` and
    ``sacog_populate_wac_block``, which join ACS/LEHD attribute data with
    block-group geometry.
    """
    context.log.info("Running TIGER/Line BG pipeline for state %s", STATE_FIPS)

    result = run_tiger_bg_pipeline(STATE_FIPS, vintages=["2013", "2023"])
    if not result.get("success"):
        raise RuntimeError(
            f"TIGER/Line BG fetch failed: {result.get('error', 'Unknown error')}"
        )

    row_count = result.get("row_count", 0)
    context.log.info(
        "TIGER/Line BG loaded: %s rows in %s",
        row_count,
        result.get("table_name", "?"),
    )

    return MaterializeResult(metadata={"bg_rows": row_count})


# ---------------------------------------------------------------------------
# Asset 0b: TIGER/Line block geometry (15-digit GEOID)
# ---------------------------------------------------------------------------


@asset(
    group_name="raw_data",
    compute_kind="python",
)
def tiger_block_asset(
    context: AssetExecutionContext,
) -> MaterializeResult:
    """Fetch TIGER/Line block polygons from Census and write to ``public.tiger_blocks``.

    A prerequisite for ``sacog_populate_wac_block``, which joins LEHD attribute
    data with block-level geometry (15-digit GEOID) for finer-grained spatial
    allocation than the block-group-level (12-digit GEOID) approach.
    """
    context.log.info("Running TIGER/Line block pipeline for state %s", STATE_FIPS)

    result = run_tiger_block_pipeline(STATE_FIPS, vintages=["2020"])
    if not result.get("success"):
        raise RuntimeError(
            f"TIGER/Line block fetch failed: {result.get('error', 'Unknown error')}"
        )

    row_count = result.get("row_count", 0)
    context.log.info(
        "TIGER/Line blocks loaded: %s rows in %s",
        row_count,
        result.get("table_name", "?"),
    )

    return MaterializeResult(metadata={"block_rows": row_count})


# ---------------------------------------------------------------------------
# Asset: Ingest Sacramento County Assessor parcel data
# ---------------------------------------------------------------------------


@asset(
    group_name="comparison",
    compute_kind="python",
    metadata={
        METADATA_CONTRACT_SOURCE: "inline",
        METADATA_CONTRACT_INLINE_COLUMNS: [
            "apn",
            "pop_dasym_weight",
            "emp_dasym_weight",
        ],
    },
)
def sacog_ingest_assessor(
    context: AssetExecutionContext,
    dbt_cli: DbtCliResource,
) -> MaterializeResult:
    """Fetch Sacramento County Assessor parcel + building data and compute dasymetric weights.

    1. Fetch parcel geometries from PARCELS/MapServer/8 (~508K parcels)
    2. Fetch building characteristics from ASSESSOR/MapServer/1 (~55K sales)
    3. Run dbt staging models to produce dasymetric_weights table

    The ``dasymetric_weights`` output table contains ``parcel_id``,
    ``pop_dasym_weight``, and ``emp_dasym_weight`` for use by downstream
    base_canvas_demographics and base_canvas_employment models.
    """
    from brewgis.workspace.dlt_pipelines.assessor import run_assessor_parcels_pipeline
    from brewgis.workspace.dlt_pipelines.assessor import run_assessor_sales_pipeline

    # Step 1: Fetch parcel geometries
    context.log.info("Fetching assessor parcel geometries")
    parcels_result = run_assessor_parcels_pipeline()
    if not parcels_result.get("success"):
        raise RuntimeError(
            f"Assessor parcels fetch failed: {parcels_result.get('error')}"
        )
    context.log.info(
        "Assessor parcels loaded: %s rows",
        parcels_result.get("row_count", 0),
    )

    # Step 2: Fetch sales/building data
    context.log.info("Fetching assessor sales/building data")
    sales_result = run_assessor_sales_pipeline()
    if not sales_result.get("success"):
        raise RuntimeError(f"Assessor sales fetch failed: {sales_result.get('error')}")
    context.log.info(
        "Assessor sales loaded: %s rows",
        sales_result.get("row_count", 0),
    )

    # Step 3: Run dbt staging models to compute dasymetric weights
    context.log.info("Materializing assessor dbt staging models")
    staging_result = dbt_cli.run(
        select=[
            "sacog_assessor_parcels",
            "sacog_assessor_sales",
            "assessor_building_medians",
            "parcel_dasymetric_weights",
        ],
        vars_={
            "base_canvas_materialized": "table",
        },
    )
    if not staging_result.success:
        raise RuntimeError(f"dbt assessor staging failed: {staging_result.error}")

    # Verify output exists
    with connection.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM public.dasymetric_weights")
        row_count = cur.fetchone()[0]

    context.log.info(
        "Dasymetric weights computed: %d rows in public.dasymetric_weights",
        row_count,
    )

    return MaterializeResult(
        metadata={
            "parcels_fetched": parcels_result.get("row_count", 0),
            "sales_fetched": sales_result.get("row_count", 0),
            "dasymetric_rows": row_count,
        }
    )


# ---------------------------------------------------------------------------
# Asset 1: Load reference parcels
# ---------------------------------------------------------------------------


@asset(
    group_name="comparison",
    compute_kind="python",
    deps=["census_acs_assets", "lehd_lodes_assets"],
    metadata={
        METADATA_CONTRACT_SOURCE: "inline",
        METADATA_CONTRACT_INLINE_COLUMNS: ["parcel_id", "geometry", "land_use"],
    },
)
def sacog_load_parcels(
    context: AssetExecutionContext,
    config: SacogLoadParcelsConfig,
    postgres: PostgresResource,  # noqa: ARG001
) -> MaterializeResult:
    """Load SACOG reference parcel geometries and land_use into staging.

    Reads from ``sac_cnty_region_existing_land_use_parcels`` (or GeoJSON cache)
    and writes to ``public.sacog_comparison_parcels``. Each row includes a
    ``geometry_key`` (source_id || '@sacog') for deterministic joins.
    """
    context.log.info(
        "sacog_load_parcels: limit=%s, cache_dir=%s",
        config.limit or "all",
        config.cache_dir or "default",
    )

    # Ensure SACOG v1 reference tables exist
    with connection.cursor() as cur:
        cur.execute(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables"
            "  WHERE table_schema = 'public' AND table_name = %s"
            ")",
            [V1_PARCELS],
        )
        if not cur.fetchone()[0]:
            context.log.info(
                "SACOG reference table %s not found — auto-restoring demo database",
                V1_PARCELS,
            )
            try:
                restore_sacog_demo_db()
            except RestoreError as e:
                raise RuntimeError(f"Failed to restore SACOG demo database: {e}") from e
            context.log.info("SACOG reference tables restored successfully")
        else:
            context.log.info("SACOG reference tables already present")

    # Create the staging table if it doesn't exist
    with connection.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.sacog_comparison_parcels (
                geography_id INTEGER,
                source_id TEXT,
                geometry_key TEXT,
                land_use TEXT,
                geometry geometry(MultiPolygon, 4326)
            )
        """)

    # Load parcels
    gdf = _load_parcels(config.limit, config.cache_dir)
    context.log.info("Loaded %d reference parcels", len(gdf))

    # Write to staging table
    gdf.to_postgis(
        "sacog_comparison_parcels",
        get_engine(),
        schema="public",
        if_exists="replace",
        index=False,
        dtype={"geometry": "geometry(MultiPolygon, 4326)"},
    )

    # Ensure geometry_key is populated
    with connection.cursor() as cur:
        cur.execute("""
            UPDATE public.sacog_comparison_parcels
            SET geometry_key = source_id || '@sacog'
            WHERE geometry_key IS NULL
        """)

    with connection.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM public.sacog_comparison_parcels")
        count = cur.fetchone()[0]

    return MaterializeResult(metadata={"parcels_loaded": count})


# ---------------------------------------------------------------------------
# Asset 1b: Populate census.acs_block_group from ACS + TIGER BG
# ---------------------------------------------------------------------------


@asset(
    group_name="comparison",
    compute_kind="python",
    deps=["tiger_bg_asset", "census_acs_assets"],
)
def sacog_populate_acs_block_group(
    context: AssetExecutionContext,
) -> MaterializeResult:
    """Join ACS staging data with TIGER/Line BG geometry and write to ``census.acs_block_group``.

    The downstream ETL (``sacog_run_comparison_etl``) reads demographics from
    ``census.acs_block_group`` via area-weighted spatial allocation.
    """
    context.log.info(
        "Populating census.acs_block_group for %s/%s",
        STATE_FIPS,
        COUNTY_FIPS,
    )

    row_count = _populate_acs_block_group(STATE_FIPS, COUNTY_FIPS)
    context.log.info("census.acs_block_group populated: %d rows", row_count)

    return MaterializeResult(metadata={"acs_bg_rows": row_count})


# ---------------------------------------------------------------------------
# Asset 1c: Populate lehd.wac_block from LEHD + TIGER BG
# ---------------------------------------------------------------------------


@asset(
    group_name="comparison",
    compute_kind="python",
    deps=["tiger_block_asset", "lehd_lodes_assets"],
)
def sacog_populate_wac_block(
    context: AssetExecutionContext,
) -> MaterializeResult:
    """Join LEHD LODES WAC staging data with TIGER/Line block geometry (15-digit GEOID) and write to ``lehd.wac_block``.

    The downstream ETL (``sacog_run_comparison_etl``) reads employment from
    ``lehd.wac_block`` via area-weighted spatial allocation at block resolution.
    """
    context.log.info(
        "Populating lehd.wac_block for %s/%s",
        STATE_FIPS,
        COUNTY_FIPS,
    )

    row_count = _populate_wac_block(STATE_FIPS, COUNTY_FIPS)
    context.log.info("lehd.wac_block populated: %d rows", row_count)

    return MaterializeResult(metadata={"lehd_wac_rows": row_count})


# ---------------------------------------------------------------------------
# Asset 2: Run brewgis ETL on the loaded parcels
# ---------------------------------------------------------------------------


@asset(
    group_name="comparison",
    compute_kind="dbt",
    deps=[
        "sacog_load_parcels",
        "sacog_populate_acs_block_group",
        "sacog_populate_wac_block",
    ],
    metadata={METADATA_CONTRACT_SOURCE: "dbt"},
)
def sacog_run_comparison_etl(
    context: AssetExecutionContext,
    config: SacogComparisonETLConfig,
    dbt_cli: DbtCliResource,
) -> MaterializeResult:
    """Run the brewgis base canvas dbt pipeline using the loaded SACOG parcels.

    Replaces the old Python SQL ETL (``run_pipeline``) with a dbt run across
    the 6 base_canvas models:

      base_canvas_geometry → base_canvas_demographics → base_canvas_employment
        → base_canvas_attributes → base_canvas_imputed → base_canvas_reconciled

    Dependencies:
      - ``sacog_load_parcels`` populates the parcel staging table
      - ``sacog_populate_acs_block_group`` populates ``census.acs_block_group``
      - ``sacog_populate_wac_block`` populates ``lehd.wac_block``

    Optional data sources (controlled by config):
      - NLCD: land cover classification + impervious fraction for irrigation
      - OSM: intersection density from road network
    """
    dbt_vars: dict[str, object] = {
        "parcel_table": "sacog_parcel_shim",
        "base_canvas_materialized": "table",
    }

    # Ensure dbt seed tables are loaded
    with connection.cursor() as cur:
        cur.execute(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables"
            "  WHERE table_schema = 'public' AND table_name = 'calibration_parameters'"
            ")",
        )
        if not cur.fetchone()[0]:
            context.log.info(
                "dbt seed table calibration_parameters not found — running dbt seed"
            )
            seed_result = dbt_cli.seed()
            if not seed_result.success:
                raise RuntimeError(f"dbt seed failed: {seed_result.error}")
            context.log.info("dbt seed completed successfully")
        else:
            context.log.info("dbt seed tables already present")

    # Run NLCD pipeline if enabled
    if config.run_nlcd:
        context.log.info("Running NLCD zonal stats pipeline")
        from brewgis.workspace.dlt_pipelines.nlcd import run_nlcd_pipeline

        nlcd_result = run_nlcd_pipeline(parcel_table="sacog_comparison_parcels")
        if not nlcd_result.get("success"):
            raise RuntimeError(f"NLCD zonal stats failed: {nlcd_result.get('error')}")
        nlcd_table = nlcd_result.get("table_name", "public.nlcd_parcel_stats")
        dbt_vars["nlcd_parcel_table"] = nlcd_table
        context.log.info(
            "NLCD stats loaded: %s rows in %s",
            nlcd_result.get("row_count", 0),
            nlcd_table,
        )

    # Run OSM pipeline if enabled
    if config.run_osm:
        context.log.info("Running OSM intersection density pipeline")
        from brewgis.workspace.dlt_pipelines.osm import run_osm_pipeline

        osm_result = run_osm_pipeline(parcel_table="sacog_comparison_parcels")
        if not osm_result.get("success"):
            raise RuntimeError(
                f"OSM intersection density failed: {osm_result.get('error')}"
            )
        osm_table = osm_result.get("table_name", "public.osm_intersection_density")
        dbt_vars["osm_intersection_table"] = osm_table
        context.log.info(
            "OSM intersection density loaded: %s rows in %s",
            osm_result.get("row_count", 0),
            osm_table,
        )

    # Detect pre-materialized dasymetric_weights table
    # If the assessor asset was already materialized, wire the dbt var
    # so base_canvas_demographics and base_canvas_employment use it.
    dasymetric_weights_table: str | None = None
    if config.run_assessor:
        context.log.info("Running assessor staging pipeline for dasymetric weights")
        from brewgis.workspace.dlt_pipelines.assessor import (
            run_assessor_parcels_pipeline,
        )
        from brewgis.workspace.dlt_pipelines.assessor import run_assessor_sales_pipeline

        run_assessor_parcels_pipeline()
        run_assessor_sales_pipeline()

        # Materialize assessor dbt staging models
        context.log.info("Materializing assessor dbt staging models")
        staging_result = dbt_cli.run(
            select=[
                "sacog_assessor_parcels",
                "sacog_assessor_sales",
                "assessor_building_medians",
                "parcel_dasymetric_weights",
            ],
            vars_={
                "base_canvas_materialized": "table",
            },
        )
        if not staging_result.success:
            raise RuntimeError(f"dbt assessor staging failed: {staging_result.error}")
        dasymetric_weights_table = "public.parcel_dasymetric_weights"
    else:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_schema = 'public' AND table_name = 'dasymetric_weights'"
                ")"
            )
            if cur.fetchone()[0]:
                dasymetric_weights_table = "public.parcel_dasymetric_weights"
                context.log.info("Detected existing dasymetric_weights table")

    if dasymetric_weights_table:
        dbt_vars["dasymetric_weights_table"] = dasymetric_weights_table
        context.log.info("Dasymetric weights enabled: %s", dasymetric_weights_table)

    context.log.info("Running dbt base_canvas models")
    result = dbt_cli.run(
        select=[
            "base_canvas_geometry",
            "base_canvas_demographics",
            "base_canvas_employment",
            "base_canvas_attributes",
            "base_canvas_imputed",
            "base_canvas_reconciled",
        ],
        vars_=dbt_vars,
        full_refresh=False,
    )

    context.log.info("dbt base_canvas run complete: status=%s", result.success)

    # Validate land use classification (fail early if land use is broken)
    context.log.info("Validating land use classification")
    land_use_result = validate_land_use_classification(
        schema="public", table="base_canvas_attributes"
    )
    context.log.info(
        "Land use classification validation: %s",
        land_use_result.get("success", False),
    )

    # Validate via Soda
    soda_result = validate_base_canvas(schema="public", table="base_canvas_reconciled")
    context.log.info("Soda validation result: %s", soda_result.get("success", False))

    return MaterializeResult(
        metadata={
            "dbt_status": "success" if result.success else "failed",
            "models_run": 6,
            "nlcd_enabled": config.run_nlcd,
            "osm_enabled": config.run_osm,
            "land_use_success": land_use_result.get("success", False),
            "soda_success": soda_result.get("success", False),
        }
    )


# ---------------------------------------------------------------------------
# Asset 3: Verify geometry identity (GX checkpoint)
# ---------------------------------------------------------------------------


@asset(
    group_name="comparison",
    compute_kind="python",
    deps=["sacog_run_comparison_etl"],
    metadata={
        METADATA_CONTRACT_SOURCE: "inline",
        METADATA_CONTRACT_INLINE_COLUMNS: [
            "parcel_id",
            "geometry_match",
            "centroid_distance",
        ],
    },
)
def sacog_verify_geometry(
    context: AssetExecutionContext,
    postgres: PostgresResource,  # noqa: ARG001
) -> MaterializeResult:
    """Verify ETL output matches reference parcel geometries.

    Checks:
    - Row count matches between base_canvas_reconciled and sacog_comparison_parcels
    - Area conservation within 0.1% tolerance
    """

    context.log.info("Verifying geometry identity")

    # Row count check
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM public.base_canvas_reconciled")
        brewgis_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM public.sacog_comparison_parcels")
        ref_count = cursor.fetchone()[0]

    if brewgis_count != ref_count:
        raise RuntimeError(
            f"Geometry identity violation: {brewgis_count} rows in base_canvas_reconciled vs "
            f"{ref_count} reference parcels"
        )

    context.log.info("Row count match: %d", brewgis_count)

    # Area conservation check via PostGIS (not geopandas)
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT COALESCE(SUM(ST_Area(ST_Transform(geometry, 6933))), 0) / 4046.86
            FROM public.sacog_comparison_parcels
        """)
        ref_area = float(cursor.fetchone()[0])

        cursor.execute("""
            SELECT COALESCE(SUM(area_gross), 0)
            FROM public.base_canvas_reconciled
        """)
        brewgis_area = float(cursor.fetchone()[0])

    area_diff_pct = abs(ref_area - brewgis_area) / max(ref_area, 1) * 100

    if area_diff_pct > 0.1:
        context.log.warning(
            "Area mismatch: input=%.1f acres, DB=%.1f acres (%.2f%% diff)",
            ref_area,
            brewgis_area,
            area_diff_pct,
        )
    else:
        context.log.info(
            "Area conservation within tolerance: %.2f%% diff", area_diff_pct
        )

    # Run GX checkpoint
    gx_result = validate_base_canvas(schema="public", table="base_canvas_reconciled")
    context.log.info("GX checkpoint result: %s", gx_result.get("success", False))

    return MaterializeResult(
        metadata={
            "row_count": brewgis_count,
            "ref_area_acres": round(ref_area, 2),
            "brew_area_acres": round(brewgis_area, 2),
            "area_diff_pct": round(area_diff_pct, 4),
            "gx_success": gx_result.get("success", False),
        }
    )


# ---------------------------------------------------------------------------
# Asset 4: Populate geography_id using deterministic key-based join
# ---------------------------------------------------------------------------


@asset(
    group_name="comparison",
    compute_kind="python",
    deps=["sacog_verify_geometry"],
    metadata={
        METADATA_CONTRACT_SOURCE: "inline",
        METADATA_CONTRACT_INLINE_COLUMNS: ["parcel_id", "geography_id"],
    },
)
def sacog_populate_geography_id(
    context: AssetExecutionContext,
    postgres: PostgresResource,  # noqa: ARG001
) -> MaterializeResult:
    """Create ``public.base_canvas`` view wrapping ``base_canvas_reconciled`` with geography_id.

    The dbt base_canvas models produce a ``base_canvas_reconciled`` view without
    geography_id.  This asset creates a backward-compatible ``public.base_canvas``
    view that adds geography_id via a join with the parcels staging table.
    """
    context.log.info("Creating public.base_canvas view with geography_id")

    with connection.cursor() as cur:
        cur.execute("""
            CREATE OR REPLACE VIEW public.base_canvas AS
            SELECT
                bcr.*,
                sp.geography_id
            FROM public.base_canvas_reconciled bcr
            LEFT JOIN public.sacog_comparison_parcels sp
                ON bcr.parcel_id = sp.parcel_id
        """)

    # Verify population
    with connection.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM public.base_canvas WHERE geography_id IS NOT NULL"
        )
        populated = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM public.base_canvas")
        total = cur.fetchone()[0]

    context.log.info("geography_id populated: %d / %d rows", populated, total)

    if populated == 0:
        raise RuntimeError("No geography_id values were populated — join failed")

    return MaterializeResult(
        metadata={
            "geography_id_populated": populated,
            "total_rows": total,
            "populated_pct": round(populated / total * 100, 1) if total else 0,
        }
    )


# ---------------------------------------------------------------------------
# Asset 5: dbt comparison models (multi-asset)
# ---------------------------------------------------------------------------


_COMPARISON_DBT_SELECT = "comparison.*"


@multi_asset(
    group_name="comparison",
    compute_kind="dbt",
    deps=["sacog_populate_geography_id"],
    outs={
        "sacog_reference_totals": AssetOut(
            metadata={
                METADATA_CONTRACT_SOURCE: "dbt",
                METADATA_CONTRACT_PATH: "sacog_reference_totals",
            },
        ),
        "sacog_brewgis_totals": AssetOut(),
        "sacog_correlations": AssetOut(),
        "sacog_weighted_means": AssetOut(),
        "sacog_summary": AssetOut(),
    },
)
def sacog_dbt_comparison(
    context: AssetExecutionContext,
    dbt_cli: DbtCliResource,
) -> MaterializeResult:
    """Materialize all dbt comparison models (``comparison.*``).

    Dependencies on ``sacog_populate_geography_id`` are handled by
    dbt itself via ``{{ ref() }}`` within the models.
    """
    context.log.info("Running dbt comparison models: %s", _COMPARISON_DBT_SELECT)

    result = dbt_cli.run(
        select=[_COMPARISON_DBT_SELECT],
        full_refresh=False,
    )

    context.log.info("dbt comparison run complete: status=%s", result.success)

    # Run Soda validation on each comparison output table (warning-only)
    comparison_tables = [
        "sacog_reference_totals",
        "sacog_brewgis_totals",
        "sacog_correlations",
        "sacog_weighted_means",
        "sacog_summary",
    ]
    schema = "public"
    for tbl in comparison_tables:
        result = validate_dbt_table(schema=schema, table=tbl)
        if not result.get("success", False):
            msg = (
                f"Comparison dbt table {tbl} validation failed: "
                f"{'; '.join(result.get('failures', []))}"
            )
            raise RuntimeError(msg)
        context.log.info("  Soda validation passed for %s.%s", schema, tbl)

    return MaterializeResult(
        metadata={
            "dbt_status": "success" if result.success else "failed",
            "dbt_elapsed_s": 0,
        }
    )


# ---------------------------------------------------------------------------
# Asset 6: Generate report from dbt-materialized tables
# ---------------------------------------------------------------------------


@asset(
    group_name="comparison",
    compute_kind="python",
    deps=[
        "sacog_reference_totals",
        "sacog_brewgis_totals",
        "sacog_correlations",
        "sacog_weighted_means",
    ],
)
def sacog_generate_report(
    context: AssetExecutionContext,
    config: SacogReportConfig,
    postgres: PostgresResource,  # noqa: ARG001
) -> MaterializeResult:
    """Generate the markdown comparison report from dbt-materialized tables.

    Reads pre-computed totals, correlations, and weighted means from the
    dbt comparison models, then formats the SACOG comparison report.
    """
    context.log.info("Generating comparison report")

    # Read from dbt-materialized tables
    ref_totals = _query_table_as_dict("sacog_reference_totals")
    brew_totals = _query_table_as_dict("sacog_brewgis_totals")
    correlations = _query_table_as_dict("sacog_correlations")
    weighted_means = _query_table_as_dict("sacog_weighted_means")

    # Rename reference columns from acres_* → area_* for comparison table
    # and convert sqft → acres for irrigation columns
    _convert_reference_totals(ref_totals)

    context.log.info(
        "Read %d ref columns, %d brew columns, %d correlations",
        len(ref_totals),
        len(brew_totals),
        len(correlations),
    )

    output_path = Path(config.output_path or REPORT_PATH)

    # Build the report
    _generate_report_markdown(
        ref_totals,
        brew_totals,
        correlations=correlations,
        weighted_means=weighted_means,
        output_path=output_path,
        quick=False,
        limit=0,
    )

    context.log.info("Report written to %s", output_path)

    return MaterializeResult(
        metadata={
            "report_path": str(output_path),
            "ref_columns": len(ref_totals),
            "brew_columns": len(brew_totals),
        }
    )


# ═══════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════


def _load_parcels(limit: int, cache_dir: str | None = None) -> gpd.GeoDataFrame:
    """Load parcel geometries from reference table or cache. Uses SACOG V1 parcels are a startining point."""
    import hashlib

    from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

    _etl_schema_hash: str = hashlib.md5(  # noqa: S324
        "".join(sorted(BaseCanvasSchema.COLUMN_NAMES)).encode()
        + BaseCanvasSchema.create_table_sql().encode()
    ).hexdigest()[:8]

    cache_base = Path(cache_dir) if cache_dir else CACHE_DIR
    cache_path = cache_base / f"sacog_parcels_502k_{_etl_schema_hash}.geojson"

    if cache_path.exists():
        gdf = gpd.read_file(str(cache_path))
        if limit > 0 and len(gdf) > limit:
            gdf = gdf.head(limit)
    else:
        limit_clause = f"LIMIT {limit}" if limit > 0 else ""
        sql = f"""
            SELECT *, wkb_geometry AS geometry
            FROM {V1_PARCELS}
            ORDER BY geography_id
            {limit_clause}
        """
        gdf = gpd.GeoDataFrame.from_postgis(sql, get_engine(), geom_col="geometry")
        gdf.to_file(str(cache_path), driver="GeoJSON")

    return gdf


def _query_table_as_dict(table_name: str) -> dict[str, float]:
    """Read a single-row dbt materialized table and return as a dict."""
    with connection.cursor() as cur:
        cur.execute(f"SELECT * FROM public.{table_name}")
        columns = [desc[0] for desc in cur.description]
        row = cur.fetchone()

    result: dict[str, float] = {}
    if row:
        for col, val in zip(columns, row, strict=False):
            if val is not None:
                try:
                    result[col] = float(val)
                except (ValueError, TypeError):
                    pass
    return result


# DEPRECATED: Kept for backward compatibility with the management command.
# Use dbt base_canvas models or run_pipeline directly instead.
def _run_etl(
    parcels_gdf,
    *,
    quick: bool = False,
    force_data_fetch: bool = False,
    truncate: bool = False,
) -> dict:
    """Run the brewgis base canvas ETL on the given parcel geometries.

    DEPRECATED: Kept for backward compatibility. The management command
    ``compare_sacog_basemap`` and its tests still call this function.
    New code should use the dbt base_canvas models or ``run_pipeline`` directly.

    Args:
        parcels_gdf: Parcel geometries to process.
        quick: Skip optional heavy post-processing steps.
        force_data_fetch: Ignore cached data and re-download.
        truncate: Truncate existing base_canvas before inserting.
    """
    import time

    from django.db import connection

    temp_table = f"_temp_etl_parcels_{int(time.time() * 1_000_000)}"
    engine = get_engine()
    parcels_gdf.to_postgis(temp_table, engine, if_exists="replace")
    try:
        result = run_pipeline(
            source_table=temp_table,
            truncate=truncate,
        )
    finally:
        with connection.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {temp_table}")
    return result


def _convert_reference_totals(ref: dict[str, float]) -> None:
    """Convert reference column names (acres_* → area_*) and units for comparability."""
    # Rename acres_* → area_*
    acres_columns = [k for k in ref if k.startswith("acres_")]
    for col in acres_columns:
        area_col = col.replace("acres_", "area_", 1)
        if area_col not in ref:
            ref[area_col] = ref[col]

    # Convert sqft → acres for irrigation
    for sqft_col in ["residential_irrigated_sqft", "commercial_irrigated_sqft"]:
        area_col = sqft_col.replace("_sqft", "_area")
        if sqft_col in ref:
            ref[area_col] = ref[sqft_col] / 43560.0


def _generate_report_markdown(
    ref: dict[str, float],
    brew: dict[str, float],
    *,
    correlations: dict[str, float] | None = None,
    weighted_means: dict[str, float] | None = None,
    config: dict | None = None,
    diagnostics: dict | None = None,
    output_path: Path,
    quick: bool,
    limit: int,
) -> None:
    """Generate the markdown comparison report.

    Reuses the same column grouping and report structure as the original
    management command, but reads from pre-computed dbt tables instead.

    Args:
        config: Optional dict of configuration flags used in the run.
        diagnostics: Optional dict of calibration diagnostics (coverage stats).
    """
    import time

    lines: list[str] = []

    # Column groups for comparison table (label, v1_col, v3_col)
    # v1_col is for reference, v3_col is for brewgis
    col_groups: list[tuple[str, list[tuple[str, str, str]]]] = [
        (
            "Area (acres)",
            [
                ("Gross Area", "acres_gross", "area_gross"),
                ("Parcel Area", "acres_parcel", "area_parcel"),
                ("Res Parcel Area *", "acres_parcel_res", "area_parcel_res"),
                ("Emp Parcel Area *", "acres_parcel_emp", "area_parcel_emp"),
                (
                    "Mixed Use Area *",
                    "acres_parcel_mixed_use",
                    "area_parcel_mixed_use",
                ),
                ("No Use Area *", "acres_parcel_no_use", "area_parcel_no_use"),
            ],
        ),
        (
            "Residential & Housing",
            [
                ("Population", "pop", "pop"),
                ("Households", "hh", "hh"),
                ("Dwelling Units", "du", "du"),
                ("DU Detached SF", "du_detsf", "du_detsf"),
                ("DU Detached SF SL", "du_detsf_sl", "du_detsf_sl"),
                ("DU Detached SF LL", "du_detsf_ll", "du_detsf_ll"),
                ("DU Attached SF", "du_attsf", "du_attsf"),
                ("DU Multi-Family", "du_mf", "du_mf"),
                ("DU MF 2-4", "du_mf2to4", "du_mf2to4"),
                ("DU MF 5+", "du_mf5p", "du_mf5p"),
            ],
        ),
        (
            "Employment",
            [
                ("Total Emp", "emp", "emp"),
                ("Retail Emp", "emp_ret", "emp_ret"),
                ("Office Emp", "emp_off", "emp_off"),
                ("Public Emp", "emp_pub", "emp_pub"),
                ("Industrial Emp", "emp_ind", "emp_ind"),
                ("Agriculture Emp", "emp_ag", "emp_ag"),
                ("Military Emp", "emp_military", "emp_military"),
            ],
        ),
        (
            "Employment (Detailed)",
            [
                ("Retail Services", "emp_retail_services", "emp_retail_services"),
                ("Restaurant", "emp_restaurant", "emp_restaurant"),
                ("Accommodation", "emp_accommodation", "emp_accommodation"),
                (
                    "Arts & Entertain.",
                    "emp_arts_entertainment",
                    "emp_arts_entertainment",
                ),
                ("Other Services", "emp_other_services", "emp_other_services"),
                ("Office Services", "emp_office_services", "emp_office_services"),
                ("Medical Services", "emp_medical_services", "emp_medical_services"),
                ("Public Admin", "emp_public_admin", "emp_public_admin"),
                ("Education", "emp_education", "emp_education"),
                ("Manufacturing", "emp_manufacturing", "emp_manufacturing"),
                ("Wholesale", "emp_wholesale", "emp_wholesale"),
                (
                    "Transport/Ware.",
                    "emp_transport_warehousing",
                    "emp_transport_warehousing",
                ),
                ("Utilities", "emp_utilities", "emp_utilities"),
                ("Construction", "emp_construction", "emp_construction"),
                ("Agriculture", "emp_agriculture", "emp_agriculture"),
                ("Extraction", "emp_extraction", "emp_extraction"),
            ],
        ),
        (
            "Building Area (sqft)",
            [
                ("Bldg Det SF SL", "bldg_sqft_detsf_sl", "bldg_area_detsf_sl"),
                ("Bldg Det SF LL", "bldg_sqft_detsf_ll", "bldg_area_detsf_ll"),
                ("Bldg Att SF", "bldg_sqft_attsf", "bldg_area_attsf"),
                ("Bldg MF", "bldg_sqft_mf", "bldg_area_mf"),
                (
                    "Bldg Retail Svc",
                    "bldg_sqft_retail_services",
                    "bldg_area_retail_services",
                ),
                (
                    "Bldg Restaurant",
                    "bldg_sqft_restaurant",
                    "bldg_area_restaurant",
                ),
                (
                    "Bldg Accommodation",
                    "bldg_sqft_accommodation",
                    "bldg_area_accommodation",
                ),
                (
                    "Bldg Arts/Entertain",
                    "bldg_sqft_arts_entertainment",
                    "bldg_area_arts_entertainment",
                ),
                (
                    "Bldg Other Svc",
                    "bldg_sqft_other_services",
                    "bldg_area_other_services",
                ),
                (
                    "Bldg Office Svc",
                    "bldg_sqft_office_services",
                    "bldg_area_office_services",
                ),
                (
                    "Bldg Public Admin",
                    "bldg_sqft_public_admin",
                    "bldg_area_public_admin",
                ),
                ("Bldg Education", "bldg_sqft_education", "bldg_area_education"),
                (
                    "Bldg Medical Svc",
                    "bldg_sqft_medical_services",
                    "bldg_area_medical_services",
                ),
                (
                    "Bldg Trans/Ware",
                    "bldg_sqft_transport_warehousing",
                    "bldg_area_transport_warehousing",
                ),
                (
                    "Bldg Wholesale",
                    "bldg_sqft_wholesale",
                    "bldg_area_wholesale",
                ),
            ],
        ),
        (
            "Intersection Density (per sq mi)",
            [
                (
                    "Intersection Density",
                    "intersection_density_sqmi",
                    "intersection_density",
                ),
            ],
        ),
        (
            "Irrigation (acres)",
            [
                (
                    "Res Irrigated",
                    "residential_irrigated_area",
                    "residential_irrigated_area",
                ),
                (
                    "Com Irrigated",
                    "commercial_irrigated_area",
                    "commercial_irrigated_area",
                ),
            ],
        ),
    ]

    lines.append("# SACOG Base Canvas Comparison Report")
    lines.append("")
    lines.append(f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("**Region:** Sacramento County, CA (SACOG)")
    lines.append(f"**Reference:** `{V1_BASE_CANVAS}` (2015 vintage, 2008-2012 data)")
    lines.append(f"**Quick mode:** {quick}")
    lines.append(f"**Parcel limit:** {limit or 'all (502,874)'}")
    lines.append("")

    # ── Configuration section ─────────────────────────────────────
    if config:
        lines.append("## Configuration")
        lines.append("")
        lines.append("| Flag | Value |")
        lines.append("|------|-------|")
        for key, value in sorted(config.items()):
            val_str = str(value).lower() if isinstance(value, bool) else str(value)
            lines.append(f"| `--{key}` | {val_str} |")
        lines.append("")

    # ── Calibration Diagnostics section ───────────────────────────
    if diagnostics:
        dasym = diagnostics.get("dasymetric", {})
        assessor = diagnostics.get("assessor", {})
        lines.append("## Calibration Diagnostics")
        lines.append("")
        lines.append("### Assessor Data Coverage")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        total_parcels = dasym.get("total_parcels", 0)
        assessor_parcels = dasym.get("assessor_parcels", 0)
        pct = (assessor_parcels / total_parcels * 100) if total_parcels > 0 else 0
        lines.append(f"| Total parcels | {total_parcels:,} |")
        lines.append(f"| Parcels with du_subtype | {assessor_parcels:,} ({pct:.1f}%) |")
        lines.append(
            f"| Parcels with pop_dasym_weight | {dasym.get('pop_weight_parcels', 0):,} |"
        )
        if "du_subtype_breakdown" in dasym:
            lines.append("")
            lines.append("**DU Sub-type Breakdown:**")
            lines.append("")
            lines.append("| Sub-type | Count |")
            lines.append("|----------|-------|")
            for st, count in sorted(dasym.get("du_subtype_breakdown", {}).items()):
                label = st if st else "NULL (no assessor data)"
                lines.append(f"| {label} | {count:,} |")
        lc = assessor.get("land_development_category", {})
        if lc:
            lines.append("")
            lines.append(
                "**Land Development Category Distribution (from assessor use codes):**"
            )
            lines.append("")
            lines.append("| Category | Count |")
            lines.append("|----------|-------|")
            for cat, count in sorted(lc.items()):
                lines.append(f"| {cat} | {count:,} |")
        emp = diagnostics.get("employment", {})
        if emp:
            lines.append("")
            lines.append("### Employment Pipeline")
            lines.append("")
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            lines.append(
                f"| WAC blocks with geometry | {emp.get('wac_blocks_with_geom', 0):,} |"
            )
            lines.append(f"| Total WAC blocks | {emp.get('total_wac_blocks', 0):,} |")
            match_tier1 = emp.get("match_tier1", 0)
            match_tier2 = emp.get("match_tier2", 0)
            match_tier3 = emp.get("match_tier3", 0)
            total_matched = match_tier1 + match_tier2 + match_tier3
            lines.append(
                f"| Tier 1 matches (exact block) | {match_tier1:,} ({match_tier1 / total_matched * 100:.1f}%)"
                if total_matched > 0
                else f"| Tier 1 matches (exact block) | {match_tier1:,}"
            )
            lines.append(
                f"| Tier 2 matches (block group) | {match_tier2:,}"
                if total_matched == 0
                else f"| Tier 2 matches (block group) | {match_tier2:,} ({match_tier2 / total_matched * 100:.1f}%)"
            )
        lines.append("")
    lines.append("")

    # ── Summary comparison table ──────────────────────────────────
    lines.append("## 1. Aggregate Comparison")
    lines.append("")
    lines.append(
        "| Column | Reference (v1) | BrewGIS | Diff | % Diff | Corr (R) | Status |"
    )
    lines.append("|--------|--------:|------:|-----:|------:|---------:|:-------|")

    matched_count = 0
    for group_label, col_list in col_groups:
        lines.append(f"\n### {group_label}\n")

        for label, v1_col, v3_col in col_list:
            ref_val = ref.get(v1_col)
            brew_val = brew.get(v3_col)

            if ref_val is None and brew_val is None:
                continue

            ref_str = f"{ref_val:>14,.1f}" if ref_val is not None else f"{'N/A':>14}"
            brew_str = f"{brew_val:>14,.1f}" if brew_val is not None else f"{'N/A':>14}"

            if ref_val and brew_val and ref_val != 0:
                diff = brew_val - ref_val
                pct = (diff / ref_val) * 100
                diff_str = f"{diff:>+11,.1f}"
                pct_str = f"{pct:>+7.1f}%"
                matched_count += 1
            elif ref_val is not None and brew_val is not None:
                diff_str = f"{'0.0':>11}"
                pct_str = f"{'0.0%':>7}"
            else:
                diff_str = f"{'N/A':>11}"
                pct_str = f"{'N/A':>7}"

            corr_val = correlations.get(v3_col) if correlations else None
            corr_str = f"{corr_val:.3f}" if corr_val is not None else "N/A"

            if corr_val is None:
                status = "N/A"
            elif corr_val >= 0.70:
                status = "GOOD"
            elif corr_val >= 0.50:
                status = "OK"
            elif corr_val >= 0.30:
                status = "WARN"
            elif corr_val >= 0.10:
                status = "POOR"
            else:
                status = "FAIL"

            lines.append(
                f"| {label:25s} | {ref_str} | {brew_str} | {diff_str} | {pct_str} "
                f"| {corr_str:>9s} | {status:>7s} |"
            )

    lines.append(f"\n**Columns matched:** {matched_count}")

    # ── Correlation quality summary ─────────────────────────────────
    if correlations:
        corr_vals = [v for v in correlations.values() if v is not None]
        if corr_vals:
            good = sum(1 for v in corr_vals if v >= 0.70)
            ok = sum(1 for v in corr_vals if 0.50 <= v < 0.70)
            warn = sum(1 for v in corr_vals if 0.30 <= v < 0.50)
            poor = sum(1 for v in corr_vals if 0.10 <= v < 0.30)
            fail = sum(1 for v in corr_vals if v < 0.10)
            lines.append(
                f"\n**Correlation quality:** {good} GOOD, {ok} OK, {warn} WARN, "
                f"{poor} POOR, {fail} FAIL (based on {len(corr_vals)} columns)"
            )

    # ── Data sources ───────────────────────────────────────────────
    lines.append("\n## 2. Data Sources Used")
    lines.append("")
    lines.append("| Data Domain | Reference (v1) | BrewGIS |")
    lines.append("|-------------|-----------------|---------|")
    lines.append(
        "| Parcel geometries | SACOG Assessor | Same (extracted from reference) |"
    )
    lines.append(
        "| Demographics | SACOG 2008 + ACS blockgroup rates "
        "| Census ACS 2022 blockgroup area-weighted |"
    )
    lines.append(
        "| Employment | SACOG 2008 + LEHD disaggregation "
        "| LEHD LODES WAC block area-weighted |"
    )
    lines.append(
        "| Dwelling units | SACOG parcel DU + TAZ controls "
        "| Inferred from ACS HH/occupancy |"
    )
    lines.append(
        "| Land use | SACOG use code crosswalk | "
        + ("NLCD 2021" if not quick else "Default (Null source)")
        + " |"
    )
    lines.append(
        "| Intersection density | CA walkable intersection points | "
        + ("OSM road network" if not quick else "Default (12.5)")
        + " |"
    )
    lines.append(
        "| Building area | Derived from DU/emp + sqft factors "
        "| Same (default 1200sqft/DU, 300sqft/emp) |"
    )
    lines.append(
        "| Irrigation | Parcel area-based fractions | "
        + ("NLCD impervious" if not quick else "Default (25%/3.5%)")
        + " |"
    )
    lines.append("")

    # ── Interpretation ─────────────────────────────────────────────
    lines.append("## 3. Interpretation")
    lines.append("")
    lines.append(
        "**Column-to-column alignment** indicates whether the brewgis automated "
        "pipeline produces values comparable to the manually-assembled SACOG v1 dataset."
    )
    lines.append("")
    lines.append(
        "**Correlation interpretation (per-column Pearson R):** "
        "R \u2265 0.70 = GOOD, \u2265 0.50 = OK, \u2265 0.30 = WARN, "
        "\u2265 0.10 = POOR, < 0.10 = FAIL."
    )
    lines.append("")

    # ── BrewGIS-only columns ──────────────────────────────────────
    lines.append("## 4. Columns Not in Reference (BrewGIS-only)")
    lines.append("")
    brew_only_cols: list[tuple[str, bool]] = [
        ("median_income", True),
        ("rent_burden_pct", True),
        ("pct_minority", True),
        ("pct_college_educated", True),
        ("cost_burden_pct", True),
        ("area_dev_condition", False),
        ("area_row", False),
        ("pop_groupquarter", False),
    ]
    for col, is_rate in brew_only_cols:
        val = brew.get(col)
        if val is not None:
            if is_rate and weighted_means:
                wavg_key = f"{col}_wavg"
                wavg = weighted_means.get(wavg_key)
                line = f"- **{col}**: {val:,.1f} (brewGIS only — no v1 equivalent)"
                if wavg is not None:
                    if col == "median_income":
                        line += f" — area-weighted avg: ${wavg:,.0f}"
                    else:
                        line += f" — area-weighted avg: {wavg:.1f}%"
                lines.append(line)
            else:
                lines.append(
                    f"- **{col}**: {val:,.1f} (brewGIS only — no v1 equivalent)"
                )
    lines.append("")
    lines.append(
        "> **Note:** median_income and percentage columns "
        "(rent_burden_pct, pct_minority, etc.) "
        "are density/rate measures. Their raw summed values are not meaningful "
        "— they should be compared as area-weighted averages, not totals."
    )
    lines.append("")

    # ── Equity column validation ──────────────────────────────────
    lines.append("## 5. Equity Column Validation (vs ACS County Estimates)")
    lines.append("")
    lines.append(
        "These BrewGIS-only equity columns cannot be compared against the "
        "v1 reference. Instead, they are validated against published ACS "
        "5-year county-level estimates for Sacramento County, CA."
    )
    lines.append("")
    lines.append(
        "| Column | BrewGIS (area-weighted) | ACS County Estimate | Diff | Notes |"
    )
    lines.append(
        "|--------|------------------------:|--------------------:|-----:|-------|"
    )

    acs_estimates: dict[str, dict[str, float | str]] = {
        "median_income": {
            "value": 75430.0,
            "source": "ACS B19013 (2022), median $",
        },
        "rent_burden_pct": {
            "value": 42.0,
            "source": "ACS B25070 (2022), % >30% gross rent",
        },
        "pct_minority": {
            "value": 55.2,
            "source": "ACS B03002 (2022), % non-White",
        },
        "pct_college_educated": {
            "value": 34.8,
            "source": "ACS B15003 (2022), % Bachelor's+",
        },
        "cost_burden_pct": {
            "value": 42.0,
            "source": "ACS B25070+B25091 (2022), % >30% income",
        },
    }

    for col, info in acs_estimates.items():
        acs_val = info["value"]
        note = info["source"]
        brew_wavg = (
            (weighted_means.get(f"{col}_wavg") or weighted_means.get(col))
            if weighted_means
            else None
        )

        if brew_wavg is None:
            continue

        if col == "median_income":
            brew_str = f"${brew_wavg:,.0f}"
            acs_str = f"${acs_val:,.0f}"
            diff_val = brew_wavg - acs_val  # type: ignore[operator]
            diff_str = f"${diff_val:+,.0f}"
        else:
            brew_str = f"{brew_wavg:.1f}%"
            acs_str = f"{acs_val:.1f}%"
            diff_val = brew_wavg - acs_val  # type: ignore[operator]
            diff_str = f"{diff_val:+.1f}pp"

        lines.append(f"| {col} | {brew_str} | {acs_str} | {diff_str} | {note} |")

    lines.append("")

    # ── Notes ──────────────────────────────────────────────────────
    lines.append("## 6. Notes")
    lines.append("")
    lines.append(
        f"- This report compares aggregate totals across all "
        f"{limit or '502,874'} parcels."
    )
    lines.append(
        "- The reference `sac_cnty_region_base_canvas` was created from the "
        "UrbanFootprint v1 SACOG demo database (2015 export)."
    )
    lines.append(
        "- BrewGIS epoch: Early 2026 — data sourced from national APIs "
        "(Census ACS 2022, LEHD, NLCD 2021)."
    )
    lines.append(
        "- NLCD and OSM were "
        + ("**enabled**" if not quick else "**disabled**")
        + " for this run."
    )
    lines.append(
        "- The reference does not contain equity columns "
        "(median_income, rent_burden_pct, pct_minority, "
        "pct_college_educated, cost_burden_pct) — "
        "these are brewGIS-only additions."
    )
    lines.append(
        "- Irrigation values: The v1 reference stores irrigation in square feet. "
        "BrewGIS stores in acres. This report applies sqft\u2192acres conversion "
        "(\u00f7 43,560) to v1 values for comparability."
    )

    output_path.write_text("\n".join(lines), encoding="utf-8")
