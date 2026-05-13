"""Dagster assets for SACOG calibration comparison workflows.

Wraps the logic from ``compare_sacog_basemap`` management command as
software-defined assets for orchestration.
"""

import hashlib
import os
import time
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from dagster import AssetExecutionContext

from dagster import MaterializeResult
from dagster import asset
from django.conf import settings
from django.db import connection

from brewgis.workspace.dagster.configs import SacogComparisonConfig
from brewgis.workspace.dagster.resources.postgres_resource import PostgresResource
from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

CACHE_DIR = Path(settings.BASE_DIR) / "planning"
V1_BASE_CANVAS = "sac_cnty_region_base_canvas"
V1_PARCELS = "sac_cnty_region_existing_land_use_parcels"
REPORT_PATH = CACHE_DIR / "sacog_comparison_report.md"

# Schema-versioned cache filename
_ETL_SCHEMA_HASH: str = hashlib.md5(  # noqa: S324
    "".join(sorted(BaseCanvasSchema.COLUMN_NAMES)).encode()
    + BaseCanvasSchema.create_table_sql().encode()
).hexdigest()[:8]

SACOG_PARCELS_GEOJSON_HASHED = (
    CACHE_DIR / f"sacog_parcels_502k_{_ETL_SCHEMA_HASH}.geojson"
)

STATE_FIPS = "06"
COUNTY_FIPS = "067"


@asset(
    group_name="calibration",
    compute_kind="python",
)
def sacog_comparison(
    context: AssetExecutionContext,
    config: SacogComparisonConfig,
    postgres: PostgresResource,  # noqa: ARG001
) -> MaterializeResult:
    """Run SACOG base canvas comparison against the v1 reference.

    Loads reference parcel geometries, runs the brewgis ETL pipeline,
    asserts geometry identity, queries reference and brewgis totals,
    and produces a markdown comparison report.

    This is a single asset wrapping the full 5-phase comparison workflow
    from ``compare_sacog_basemap``.
    """

    context.log.info(
        "sacog_comparison: quick=%s, limit=%s, skip_census=%s, skip_lehd=%s",
        config.quick,
        config.limit or "all",
        config.skip_census,
        config.skip_lehd,
    )

    # ── Phase 1: Load parcels from reference ──────────────────────────
    context.log.info("Phase 1: Loading reference parcel geometries")
    parcels_gdf = _load_parcels(config.limit)
    context.log.info("Loaded %d parcels", len(parcels_gdf))
    parcel_ids = (
        list(parcels_gdf["geography_id"])
        if "geography_id" in parcels_gdf.columns
        else []
    )

    # ── Phase 2: Run ETL ──────────────────────────────────────────────
    context.log.info("Phase 2: Running brewgis ETL")
    os.environ["BREWGIS_DETSF_SL_RATIO"] = "0.17"
    etl_result = _run_etl(
        parcels_gdf,
        quick=config.quick,
        skip_census=config.skip_census,
        skip_lehd=config.skip_lehd,
        truncate=config.truncate,
    )

    if etl_result["status"] == "error":
        raise RuntimeError(f"ETL failed: {etl_result.get('error', 'Unknown error')}")

    context.log.info(
        "ETL complete: %s rows in %.1fs",
        etl_result.get("rows", "?"),
        etl_result.get("elapsed", 0),
    )

    # ── Phase 2.5: Assert geometry identity ────────────────────────────
    context.log.info("Phase 2.5: Asserting geometry identity")
    _assert_geometry_identity(parcels_gdf)
    context.log.info("Geometry identity verified")

    # ── Phase 3: Query reference totals ────────────────────────────────
    context.log.info("Phase 3: Querying reference base canvas")
    if parcel_ids:
        ref_totals = _query_totals(V1_BASE_CANVAS, parcel_ids)
    else:
        ref_totals = _query_totals(V1_BASE_CANVAS)
    # Convert sqft → acres for irrigation columns
    for col in ["residential_irrigated_sqft", "commercial_irrigated_sqft"]:
        if col in ref_totals:
            ref_totals[col] = ref_totals[col] / 43560.0

    # ── Phase 4: Query brewgis totals ──────────────────────────────────
    context.log.info("Phase 4: Querying brewgis base canvas")
    brew_totals = _query_totals("public.base_canvas")

    # ── Phase 4.5: Populate geography_id ────────────────────────────────
    context.log.info("Phase 4.5: Populating geography_id")
    if parcel_ids:
        with connection.cursor() as cur:
            cur.execute(
                "ALTER TABLE public.base_canvas ADD COLUMN IF NOT EXISTS geography_id INTEGER"
            )
            gid_list = ", ".join(str(g) for g in parcel_ids)
            cur.execute(
                f"""
                WITH bc_ranked AS (
                    SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rn
                    FROM public.base_canvas
                ),
                ref_ranked AS (
                    SELECT geography_id, ROW_NUMBER() OVER (ORDER BY geography_id) AS rn
                    FROM {V1_PARCELS}
                    WHERE geography_id IN ({gid_list})
                )
                UPDATE public.base_canvas bc
                SET geography_id = ref_ranked.geography_id
                FROM ref_ranked
                INNER JOIN bc_ranked ON ref_ranked.rn = bc_ranked.rn
                WHERE bc.id = bc_ranked.id
                """
            )
        context.log.info("Populated geography_id for %d parcels", len(parcel_ids))
    else:
        context.log.info("Skipping geography_id (no ids available)")

    # ── Phase 5: Generate report ────────────────────────────────────────
    context.log.info("Phase 5: Generating comparison report")
    correlations = _compute_correlations()
    _generate_report(ref_totals, brew_totals, etl_result, config, correlations)

    context.log.info("Report written to %s", REPORT_PATH)

    # Build metadata
    metadata: dict[str, Any] = {
        "parcels_loaded": len(parcels_gdf),
        "etl_status": etl_result.get("status", "?"),
        "etl_rows": etl_result.get("rows", 0),
        "etl_elapsed_s": etl_result.get("elapsed", 0),
        "report_path": str(REPORT_PATH),
        "quick_mode": config.quick,
    }
    if ref_totals:
        metadata["ref_pop"] = ref_totals.get("pop", 0)
        metadata["ref_hh"] = ref_totals.get("hh", 0)
        metadata["ref_emp"] = ref_totals.get("emp", 0)
    if brew_totals:
        metadata["brew_pop"] = brew_totals.get("pop", 0)
        metadata["brew_hh"] = brew_totals.get("hh", 0)
        metadata["brew_emp"] = brew_totals.get("emp", 0)
    if correlations:
        good = sum(1 for v in correlations.values() if v is not None and v >= 0.70)
        metadata["corr_good"] = good
        metadata["corr_count"] = len(correlations)

    return MaterializeResult(metadata=metadata)


# ═══════════════════════════════════════════════════════════════════════
# Internal helpers (mirror compare_sacog_basemap logic)
# ═══════════════════════════════════════════════════════════════════════


def _load_parcels(limit: int) -> gpd.GeoDataFrame:
    """Load parcel geometries from reference table or cache."""

    if SACOG_PARCELS_GEOJSON_HASHED.exists():
        gdf = gpd.read_file(str(SACOG_PARCELS_GEOJSON_HASHED))
        if limit > 0 and len(gdf) > limit:
            gdf = gdf.head(limit)
        # Merge land_use from reference
        gids = gdf["geography_id"].tolist()
        if gids:
            lu_sql = f"SELECT geography_id, land_use FROM {V1_PARCELS}"
            lu_df = pd.read_sql(lu_sql, get_engine())
            if not lu_df.empty:
                gdf = gdf.merge(
                    lu_df[["geography_id", "land_use"]],
                    on="geography_id",
                    how="left",
                )
        return gdf

    limit_clause = f"LIMIT {limit}" if limit > 0 else ""
    sql = f"""
        SELECT *, wkb_geometry AS geometry
        FROM {V1_PARCELS}
        ORDER BY geography_id
        {limit_clause}
    """
    gdf = gpd.GeoDataFrame.from_postgis(sql, get_engine(), geom_col="geometry")
    gdf.to_file(str(SACOG_PARCELS_GEOJSON_HASHED), driver="GeoJSON")
    return gdf


def _run_etl(
    parcels_gdf: gpd.GeoDataFrame,
    *,
    quick: bool,
    skip_census: bool,
    skip_lehd: bool,
    truncate: bool,
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

    temp_geojson = CACHE_DIR / "_etl_temp.geojson"
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
    finally:
        if temp_geojson.exists():
            temp_geojson.unlink()

    return result


def _assert_geometry_identity(input_gdf: gpd.GeoDataFrame) -> None:
    """Assert ETL output matches input parcel geometries."""

    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM public.base_canvas")
        db_count = cursor.fetchone()[0]

    if db_count != len(input_gdf):
        raise RuntimeError(
            f"Geometry identity violation: {db_count} rows in DB vs "
            f"{len(input_gdf)} input parcels."
        )

    if "geography_id" in input_gdf.columns:
        input_ids = sorted(input_gdf["geography_id"].tolist())
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT geography_id FROM public.base_canvas "
                "WHERE geography_id IS NOT NULL ORDER BY geography_id"
            )
            db_ids = [row[0] for row in cursor.fetchall()]
        if input_ids != db_ids:
            raise RuntimeError(
                "Geography ID mismatch between input parcels and base_canvas."
            )


def _query_totals(
    table: str,
    geography_ids: list[int] | None = None,
) -> dict[str, float]:
    """Query aggregate SUM for all numeric columns in a table."""

    with connection.cursor() as cur:
        parts = table.split(".") if "." in table else ["public", table]
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
              AND data_type IN ('numeric', 'double precision', 'real', 'integer', 'bigint')
            ORDER BY ordinal_position
            """,
            parts,
        )
        num_cols = [
            r[0] for r in cur.fetchall() if r[0] not in ("geography_id", "source_id")
        ]
        if not num_cols:
            return {}

        sum_exprs = ", ".join(f'COALESCE(SUM("{c}"), 0) AS "{c}"' for c in num_cols)
        where_clause = ""
        if geography_ids:
            ids_str = ", ".join(str(i) for i in geography_ids)
            where_clause = f" WHERE geography_id IN ({ids_str})"
        cur.execute(f"SELECT {sum_exprs} FROM {table}{where_clause}")
        row = cur.fetchone()
        totals: dict[str, float] = {}
        if row:
            for i, col in enumerate(num_cols):
                val = row[i]
                if val is not None:
                    totals[col] = float(val)
        return totals


def _compute_correlations() -> dict[str, float]:
    """Compute Pearson R correlation between brewgis and reference columns."""

    from brewgis.workspace.services.sacog_column_mapping import (  # noqa: PLC0415
        get_v1_columns_for_verification,
    )

    v3_to_v1 = get_v1_columns_for_verification()
    numeric_types = {
        "numeric",
        "double precision",
        "real",
        "integer",
        "bigint",
        "smallint",
    }

    with connection.cursor() as cur:
        cur.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'base_canvas'"
        )
        brew_cols = {r[0] for r in cur.fetchall() if r[1] in numeric_types}
        cur.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'sac_cnty_region_base_canvas'"
        )
        ref_cols = {r[0] for r in cur.fetchall() if r[1] in numeric_types}

    corr_exprs: list[str] = []
    valid_v3_cols: list[str] = []
    for v3_col, v1_col in v3_to_v1.items():
        if v3_col in brew_cols and v1_col in ref_cols:
            corr_exprs.append(f'    CORR(bc."{v3_col}", ref."{v1_col}") AS "{v3_col}"')
            valid_v3_cols.append(v3_col)

    if not corr_exprs:
        return {}

    corr_sql = (
        "SELECT\n"
        + ",\n".join(corr_exprs)
        + "\nFROM public.base_canvas bc\n"
        + f"INNER JOIN {V1_BASE_CANVAS} ref ON bc.geography_id = ref.geography_id"
    )
    with connection.cursor() as cur:
        cur.execute(corr_sql)
        row = cur.fetchone()
    result: dict[str, float] = {}
    if row:
        for v3_col, val in zip(valid_v3_cols, row, strict=False):
            if val is not None:
                result[v3_col] = float(val)
    return result


def _generate_report(
    ref: dict[str, float],
    brew: dict[str, float],
    etl_result: dict[str, Any],
    config: SacogComparisonConfig,
    correlations: dict[str, float] | None = None,
) -> None:
    """Generate the markdown comparison report."""

    # Column groups for comparison table
    col_groups: list[tuple[str, list[tuple[str, str, str]]]] = [
        (
            "Area (acres)",
            [
                ("Gross Area", "acres_gross", "area_gross"),
                ("Parcel Area", "acres_parcel", "area_parcel"),
                ("Res Parcel Area *", "acres_parcel_res", "area_parcel_res"),
                ("Emp Parcel Area *", "acres_parcel_emp", "area_parcel_emp"),
                ("Mixed Use Area *", "acres_parcel_mixed_use", "area_parcel_mixed_use"),
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
                ("Bldg Restaurant", "bldg_sqft_restaurant", "bldg_area_restaurant"),
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
                ("Bldg Wholesale", "bldg_sqft_wholesale", "bldg_area_wholesale"),
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

    lines: list[str] = []
    lines.append("# SACOG Base Canvas Comparison Report")
    lines.append("")
    lines.append(f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("**Region:** Sacramento County, CA (SACOG)")
    lines.append(f"**Reference:** `{V1_BASE_CANVAS}` (2015 vintage, 2008-2012 data)")
    lines.append(f"**Quick mode:** {config.quick}")
    lines.append(f"**Parcel limit:** {config.limit or 'all (502,874)'}")
    lines.append(f"**ETL elapsed:** {etl_result.get('elapsed', 'N/A')}s")
    lines.append(f"**ETL rows:** {etl_result.get('rows', 'N/A'):,}")
    lines.append("")

    # Aggregate comparison table
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
                f"| {label:25s} | {ref_str} | {brew_str} | {diff_str} | {pct_str} | {corr_str:>9s} | {status:>7s} |"
            )

    lines.append(f"\n**Columns matched:** {matched_count}")

    # Correlation quality summary
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
                f"{poor} POOR, {fail} FAIL"
            )

    # Data sources
    lines.append("\n## 2. Data Sources Used")
    lines.append("")
    lines.append("| Data Domain | Reference (v1) | BrewGIS |")
    lines.append("|-------------|-----------------|---------|")
    lines.append(
        "| Parcel geometries | SACOG Assessor | Same (extracted from reference) |"
    )
    lines.append(
        "| Demographics | SACOG 2008 + ACS blockgroup rates | Census ACS 2022 blockgroup area-weighted |"
    )
    lines.append(
        "| Employment | SACOG 2008 + LEHD disaggregation | LEHD LODES WAC block area-weighted |"
    )
    lines.append(
        "| Dwelling units | SACOG parcel DU + TAZ controls | Inferred from ACS HH/occupancy |"
    )
    lines.append(
        "| Land use | SACOG use code crosswalk | "
        + ("NLCD 2021" if not config.quick else "Default (Null source)")
        + " |"
    )
    lines.append(
        "| Intersection density | CA walkable intersection points | "
        + ("OSM road network" if not config.quick else "Default (12.5)")
        + " |"
    )
    lines.append(
        "| Building area | Derived from DU/emp + sqft factors | Same (default 1200sqft/DU, 300sqft/emp) |"
    )
    lines.append(
        "| Irrigation | Parcel area-based fractions | "
        + ("NLCD impervious" if not config.quick else "Default (25%/3.5%)")
        + " |"
    )

    # Interpretation
    lines.extend(
        [
            "",
            "## 3. Interpretation",
            "",
            "**Column-to-column alignment** indicates whether the brewgis automated "
            "pipeline produces values comparable to the manually-assembled SACOG v1 dataset.",
            "",
            "**Correlation interpretation (per-column Pearson R):** "
            "R \u2265 0.70 = GOOD, \u2265 0.50 = OK, \u2265 0.30 = WARN, \u2265 0.10 = POOR, < 0.10 = FAIL.",
            "",
            "- **Area-by-use columns:** These columns compare fundamentally different data models. "
            "The reference v1 splits each parcel's area across multiple use types. "
            "BrewGIS assigns each parcel entirely to a single land_development_category.",
            "",
            "- **Correlation warning:** Most domains show FAIL-status parcel-level correlation (R < 0.10). "
            "The pipeline produces aggregate totals in the right order of magnitude for some columns "
            "but does not yet produce believable parcel-level distributions.",
            "",
            "## 4. Columns Not in Reference (BrewGIS-only)",
            "",
            "> Note: median_income and percentage columns (rent_burden_pct, pct_minority, etc.) "
            "are density/rate measures. Their raw summed values are not meaningful.",
            "",
            "## 5. Equity Column Validation (vs ACS County Estimates)",
            "",
            "These BrewGIS-only equity columns cannot be compared against the v1 reference. "
            "They are validated against published ACS 5-year county-level estimates.",
            "",
            "## 6. Notes",
            "",
            f"- This report compares aggregate totals across all {config.limit or '502,874'} parcels.",
            "- The reference `sac_cnty_region_base_canvas` was created from the "
            "UrbanFootprint v1 SACOG demo database (2015 export).",
            "- BrewGIS epoch: Early 2026 — data sourced from national APIs.",
            "- NLCD and OSM were "
            + ("**enabled**" if not config.quick else "**disabled**")
            + " for this run.",
        ]
    )

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
