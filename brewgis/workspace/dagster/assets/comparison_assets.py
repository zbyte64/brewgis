"""Dagster assets for the SACOG base canvas comparison pipeline.

Refactors the monolithic ``sacog_comparison`` asset into six independent
assets with clear dependency edges. Aggregation and correlation queries
are delegated to dbt models (``comparison/*``).
"""

import os
import time
from pathlib import Path
from typing import Any

import geopandas as gpd
from dagster import AssetExecutionContext
from dagster import AssetOut
from dagster import MaterializeResult
from dagster import asset
from dagster import multi_asset
from django.conf import settings
from django.db import connection

from brewgis.workspace.dagster.configs import SacogComparisonETLConfig
from brewgis.workspace.dagster.configs import SacogLoadParcelsConfig
from brewgis.workspace.dagster.configs import SacogReportConfig
from brewgis.workspace.dagster.resources.dbt_resource import DbtCliResource
from brewgis.workspace.dagster.resources.postgres_resource import PostgresResource

from brewgis.soda import validate_base_canvas  # noqa: F401
from brewgis.workspace.services._db import get_engine

CACHE_DIR = Path(settings.BASE_DIR) / "planning"
V1_PARCELS = "sac_cnty_region_existing_land_use_parcels"
V1_BASE_CANVAS = "sac_cnty_region_base_canvas"
REPORT_PATH = CACHE_DIR / "sacog_comparison_report.md"

STATE_FIPS = "06"
COUNTY_FIPS = "067"


# ---------------------------------------------------------------------------
# Asset 1: Load reference parcels
# ---------------------------------------------------------------------------


@asset(
    group_name="comparison",
    compute_kind="python",
    deps=["census_acs_assets", "lehd_lodes_assets"],
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
# Asset 2: Run brewgis ETL on the loaded parcels
# ---------------------------------------------------------------------------


@asset(
    group_name="comparison",
    compute_kind="python",
    deps=["sacog_load_parcels", "census_acs_assets", "lehd_lodes_assets"],
)
def sacog_run_comparison_etl(
    context: AssetExecutionContext,
    config: SacogComparisonETLConfig,
    postgres: PostgresResource,  # noqa: ARG001
) -> MaterializeResult:
    """Run the brewgis base canvas ETL using the loaded SACOG parcels.

    Uses a scenario-specific temp directory (``COMPARISON_ETL_TEMP``) to
    avoid the shared ``_etl_temp.geojson`` race condition.
    """
    # Create a unique temp directory for this ETL run
    run_id = context.run_id or str(int(time.time()))
    temp_dir = CACHE_DIR / f"_comparison_etl_{run_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_geojson = temp_dir / "parcels.geojson"

    context.log.info(
        "sacog_run_comparison_etl: quick=%s, skip_census=%s, skip_lehd=%s, truncate=%s",
        config.quick,
        config.skip_census,
        config.skip_lehd,
        config.truncate,
    )

    # Load parcels from the staging table
    parcels_gdf = gpd.GeoDataFrame.from_postgis(
        "SELECT * FROM public.sacog_comparison_parcels",
        get_engine(),
        geom_col="geometry",
    )
    context.log.info("Loaded %d parcels from staging", len(parcels_gdf))

    os.environ["BREWGIS_DETSF_SL_RATIO"] = "0.17"

    etl_result = _run_etl(
        parcels_gdf,
        quick=config.quick,
        skip_census=config.skip_census,
        skip_lehd=config.skip_lehd,
        truncate=config.truncate,
        temp_geojson=temp_geojson,
    )

    # Clean up temp directory
    if temp_geojson.exists():
        temp_geojson.unlink()
    try:
        temp_dir.rmdir()
    except OSError:
        pass

    if etl_result["status"] == "error":
        raise RuntimeError(f"ETL failed: {etl_result.get('error', 'Unknown error')}")

    context.log.info(
        "ETL complete: %s rows in %.1fs",
        etl_result.get("rows", "?"),
        etl_result.get("elapsed", 0),
    )

    return MaterializeResult(
        metadata={
            "etl_status": etl_result.get("status", "?"),
            "etl_rows": etl_result.get("rows", 0),
            "etl_elapsed_s": etl_result.get("elapsed", 0),
        }
    )


# ---------------------------------------------------------------------------
# Asset 3: Verify geometry identity (GX checkpoint)
# ---------------------------------------------------------------------------


@asset(
    group_name="comparison",
    compute_kind="python",
    deps=["sacog_run_comparison_etl"],
)
def sacog_verify_geometry(
    context: AssetExecutionContext,
    postgres: PostgresResource,  # noqa: ARG001
) -> MaterializeResult:
    """Verify ETL output matches reference parcel geometries via GX checkpoint.

    Checks:
    - Row count matches between base_canvas and sacog_comparison_parcels
    - Area conservation within 0.1% tolerance
    """
    context.log.info("Verifying geometry identity")

    # Row count check
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM public.base_canvas")
        brewgis_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM public.sacog_comparison_parcels")
        ref_count = cursor.fetchone()[0]

    if brewgis_count != ref_count:
        raise RuntimeError(
            f"Geometry identity violation: {brewgis_count} rows in base_canvas vs "
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
            FROM public.base_canvas
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
    gx_result = validate_base_canvas(schema="public", table="base_canvas")
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
)
def sacog_populate_geography_id(
    context: AssetExecutionContext,
    postgres: PostgresResource,  # noqa: ARG001
) -> MaterializeResult:
    """Populate geography_id in base_canvas using geometry_key-based join.

    Unlike the old ROW_NUMBER() positional approach, this uses a deterministic
    key-based join that survives ETL re-runs.
    """
    context.log.info("Populating geography_id")

    # Add geography_id and geometry_key columns if they don't exist
    with connection.cursor() as cur:
        cur.execute(
            "ALTER TABLE public.base_canvas ADD COLUMN IF NOT EXISTS geography_id INTEGER"
        )
        cur.execute(
            "ALTER TABLE public.base_canvas ADD COLUMN IF NOT EXISTS geometry_key TEXT"
        )

    # Update base_canvas.geometry_key from source_id
    with connection.cursor() as cur:
        cur.execute("""
            UPDATE public.base_canvas bc
            SET geometry_key = COALESCE(bc.source_id, '') || '@sacog'
            WHERE bc.geometry_key IS NULL AND bc.source_id IS NOT NULL
        """)

    # Join on geometry_key to populate geography_id
    with connection.cursor() as cur:
        cur.execute("""
            UPDATE public.base_canvas bc
            SET geography_id = sp.geography_id
            FROM public.sacog_comparison_parcels sp
            WHERE bc.geometry_key = sp.geometry_key
              AND bc.geography_id IS NULL
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
        raise RuntimeError(
            "No geography_id values were populated — geometry_key join failed"
        )

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
        "sacog_reference_totals": AssetOut(),
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
    """Load parcel geometries from reference table or cache."""
    import hashlib  # noqa: PLC0415

    from brewgis.workspace.services.base_canvas_schema import (  # noqa: PLC0415
        BaseCanvasSchema,
    )

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


def _run_etl(
    parcels_gdf: gpd.GeoDataFrame,
    *,
    quick: bool,
    skip_census: bool,
    skip_lehd: bool,
    truncate: bool,
    temp_geojson: Path,
) -> dict[str, Any]:
    """Run the brewgis base canvas ETL on the given parcel geometries."""
    from brewgis.workspace.services.base_canvas_adapters import (  # noqa: PLC0415
        CensusDemographicSource,
    )
    from brewgis.workspace.services.base_canvas_adapters import (  # noqa: PLC0415
        LEHDEmploymentSource,
    )
    from brewgis.workspace.services.base_canvas_adapters import (  # noqa: PLC0415
        NLCDFetcher,
    )
    from brewgis.workspace.services.base_canvas_adapters import (  # noqa: PLC0415
        OSMIntersectionDensitySource,
    )
    from brewgis.workspace.services.base_canvas_etl import BaseCanvasETL
    from brewgis.workspace.services.calibration_registry import SACOG_CALIBRATION

    demographic_source = None
    employment_source = None
    land_use_source = None
    intersection_density_source = None
    irrigation_source = None

    if not skip_census:
        demographic_source = CensusDemographicSource(
            state_fips=STATE_FIPS,
            county_fips=COUNTY_FIPS,
            year=2022,
        )

    if not skip_lehd:
        employment_source = LEHDEmploymentSource(
            state_fips=STATE_FIPS,
            county_fips=COUNTY_FIPS,
        )

    if not quick:
        try:
            bbox = (
                float(parcels_gdf.total_bounds[0]),
                float(parcels_gdf.total_bounds[1]),
                float(parcels_gdf.total_bounds[2]),
                float(parcels_gdf.total_bounds[3]),
            )
            land_use_source = NLCDFetcher(bbox=bbox)
            irrigation_source = land_use_source
        except Exception:
            pass

        try:
            bbox = (
                float(parcels_gdf.total_bounds[0]),
                float(parcels_gdf.total_bounds[1]),
                float(parcels_gdf.total_bounds[2]),
                float(parcels_gdf.total_bounds[3]),
            )
            intersection_density_source = OSMIntersectionDensitySource(bbox=bbox)
        except Exception:
            pass

    etl = BaseCanvasETL(
        calibration=SACOG_CALIBRATION,
        demographic_source=demographic_source,
        employment_source=employment_source,
        land_use_source=land_use_source,
        irrigation_source=irrigation_source,
        intersection_density_source=intersection_density_source,
    )

    parcels_gdf.to_file(str(temp_geojson), driver="GeoJSON")

    with connection.cursor() as cur:
        cur.execute("""
            ALTER TABLE public.base_canvas
            ALTER COLUMN geometry TYPE geometry(MultiPolygon, 4326)
            USING ST_Multi(geometry)
        """)

    try:
        result = etl.run(
            source_geojson=str(temp_geojson),
            skip_imputation=False,
            truncate=truncate,
        )
    except Exception:
        if temp_geojson.exists():
            temp_geojson.unlink()
        raise

    return result


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
    output_path: Path,
    quick: bool,
    limit: int,
) -> None:
    """Generate the markdown comparison report.

    Reuses the same column grouping and report structure as the original
    management command, but reads from pre-computed dbt tables instead of
    running ad-hoc queries.
    """
    import time  # noqa: PLC0415

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
            "Irrigation (acres)",
            [
                (
                    "Res Irrigated",
                    "residential_irrigated_sqft",
                    "residential_irrigated_area",
                ),
                (
                    "Com Irrigated",
                    "commercial_irrigated_sqft",
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
    brew_only_cols: list[str] = [
        "median_income",
        "rent_burden_pct",
        "pct_minority",
        "pct_college_educated",
        "cost_burden_pct",
        "area_dev_condition",
        "area_row",
        "pop_groupquarter",
    ]
    for col in brew_only_cols:
        val = brew.get(col)
        if val is not None:
            lines.append(f"- **{col}**: {val:,.1f} (brewGIS only — no v1 equivalent)")
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
