# ruff: noqa: S608  # table/schema names are controlled values, not user input
# long SQL strings are intentional
"""Base Canvas Pipeline — 11-step ETL as PostGIS SQL operations.

**DEPRECATED**: Steps 3-11 have been ported to dbt models
(``brewgis/dbt_project/models/base_canvas_*.sql``). Only steps 1-2
(DDL + ingestion) are still used for loading parcels into staging tables.

All data transformation logic should be implemented in dbt models,
not Python SQL. This module is kept for backward compatibility.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from django.db import connection

from brewgis.soda import validate_base_canvas
from brewgis.soda import validate_land_use_classification
from brewgis.soda import validate_synthetic_parcels
from brewgis.workspace.services.base_canvas_manager import BaseCanvasManager
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

logger = logging.getLogger(__name__)

# ── Default imputation values ─────────────────────────────────────────
_DEFAULT_INTERSECTION_DENSITY = 12.5
_DEFAULT_BUILT_FORM_KEY = "mixed_use"
_DEFAULT_BLDG_SQFT_PER_DU = 1200.0
_DEFAULT_BLDG_SQFT_PER_EMP = 300.0
_DEFAULT_IRRIGATION_RES_FRAC = 0.25
_DEFAULT_IRRIGATION_COM_FRAC = 0.035

# ── Assessor Use Code → development category (CA Standard codes) ─────
_ASSESSOR_USE_CODE_MAP: dict[str, str] = {
    "10": "urban",
    "11": "urban",
    "12": "urban",
    "13": "urban",
    "14": "urban",
    "15": "urban",
    "16": "urban",
    "17": "urban",
    "18": "urban",
    "20": "industrial",
    "21": "industrial",
    "22": "industrial",
    "23": "industrial",
    "24": "industrial",
    "30": "industrial",
    "31": "industrial",
    "32": "industrial",
    "40": "agricultural",
    "41": "agricultural",
    "42": "agricultural",
    "43": "agricultural",
    "44": "agricultural",
    "45": "agricultural",
    "46": "agricultural",
    "50": "undeveloped",
    "51": "undeveloped",
    "52": "undeveloped",
    "53": "undeveloped",
    "60": "undeveloped",
    "61": "undeveloped",
    "62": "undeveloped",
    "63": "undeveloped",
    "70": "undeveloped",
    "71": "undeveloped",
    "80": "industrial",
    "81": "industrial",
    "82": "industrial",
    "83": "industrial",
    "90": "industrial",
}

# ── SACOG text land-use map ──────────────────────────────────────────
_SACOG_LAND_USE_MAP: dict[str, str] = {
    "Low Density Detached Residential": "urban",
    "Medium Density Detached Residential": "urban",
    "Medium-High Density Detached Residential": "urban",
    "Medium Density Attached Residential": "urban",
    "Medium-High Density Attached Residential": "urban",
    "High Density Attached Residential": "urban",
    "Very High Density Attached Residential": "urban",
    "Mobile Home Park": "urban",
    "Urban Attached Residential": "urban",
    "Urban Mid-Rise Residential": "urban",
    "Blank Place Type": "urban",
    "Rural Residential": "undeveloped",
    "Very Low Density Detached Residential": "undeveloped",
    "Community/Neighborhood Retail": "urban",
    "Community/Neighborhood Commercial": "urban",
    "Community/Neighborhood Commercial/Office": "urban",
    "Regional Retail": "urban",
    "Moderate-Intensity Office": "urban",
    "High-Intensity Office": "urban",
    "CBD Office": "urban",
    "Light Industrial": "industrial",
    "Heavy Industrial": "industrial",
    "Light Industrial-Office": "industrial",
    "Medical Facility": "urban",
    "Hotel": "urban",
    "Public/Quasi-Public": "urban",
    "Civic/Institution": "urban",
    "K-12 School": "urban",
    "Colleges and Universities": "urban",
    "Airport": "urban",
    "Agricultural Processing/Retail Employment": "urban",
    "Residential/Retail Mixed Use Low": "mixed_use",
    "Residential/Retail Mixed Use High": "mixed_use",
    "Agriculture": "undeveloped",
    "Farm Home": "undeveloped",
    "Park and/or Open Space": "undeveloped",
    "Parking Lot": "undeveloped",
    "Parking Structure": "undeveloped",
    "Water": "undeveloped",
    "Road": "undeveloped",
}

# ── Calibration: land_development_category → parameters ──────────────
_CALIBRATION: dict[str, tuple[float, float, float, float, float]] = {
    "urban": (1200.0, 400.0, 0.25, 0.035, 25.0),
    "agricultural": (1200.0, 300.0, 0.34, 0.029, 2.0),
    "industrial": (1200.0, 500.0, 0.25, 0.035, 8.0),
    "undeveloped": (0.0, 0.0, 0.0, 0.0, 1.0),
    "mixed_use": (1500.0, 400.0, 0.25, 0.035, 20.0),
}

# ── Column lists ─────────────────────────────────────────────────────
_DEMOGRAPHIC_COLUMNS = [
    "pop",
    "pop_groupquarter",
    "hh",
    "du",
    "du_detsf",
    "du_detsf_sl",
    "du_detsf_ll",
    "du_attsf",
    "du_mf",
    "du_mf2to4",
    "du_mf5p",
    "median_income",
    "rent_burden_pct",
    "pct_minority",
    "pct_college_educated",
    "cost_burden_pct",
]

_EMPLOYMENT_COLUMNS = [
    "emp",
    "emp_ret",
    "emp_retail_services",
    "emp_restaurant",
    "emp_accommodation",
    "emp_arts_entertainment",
    "emp_other_services",
    "emp_off",
    "emp_office_services",
    "emp_medical_services",
    "emp_pub",
    "emp_public_admin",
    "emp_education",
    "emp_ind",
    "emp_manufacturing",
    "emp_wholesale",
    "emp_transport_warehousing",
    "emp_utilities",
    "emp_construction",
    "emp_ag",
    "emp_agriculture",
    "emp_extraction",
    "emp_military",
]

# Aggregate → sub-columns for reconciliation
_RECONCILIATION_MAP: dict[str, list[str]] = {
    "du_detsf": ["du_detsf_sl", "du_detsf_ll"],
    "du_mf": ["du_mf2to4", "du_mf5p"],
    "du": ["du_detsf", "du_attsf", "du_mf"],
    "emp_ret": [
        "emp_retail_services",
        "emp_restaurant",
        "emp_accommodation",
        "emp_arts_entertainment",
        "emp_other_services",
    ],
    "emp_off": ["emp_office_services", "emp_medical_services"],
    "emp_pub": ["emp_public_admin", "emp_education"],
    "emp_ind": [
        "emp_manufacturing",
        "emp_wholesale",
        "emp_transport_warehousing",
        "emp_utilities",
        "emp_construction",
    ],
    "emp_ag": ["emp_agriculture", "emp_extraction"],
    "emp": [
        "emp_ret",
        "emp_off",
        "emp_pub",
        "emp_ind",
        "emp_ag",
        "emp_military",
    ],
}

# Columns to exclude from imputation
_IMPUTATION_EXCLUDE = frozenset(
    {
        "id",
        "id_source",
        "geometry_key",
        "geometry",
        "built_form_key",
        "land_use",
        "assessor_use_code",
    }
)


def run_pipeline(
    *,
    source_table: str | None = None,
    source_geojson: str | None = None,
    synthetic_n: int | None = None,
    skip_imputation: bool = False,
    truncate: bool = False,
    target_table: str = "public.base_canvas",
    census_schema: str = "census",
    lehd_schema: str = "lehd",
) -> dict[str, Any]:
    """Execute the full 11-step ETL pipeline as SQL operations.

    Exactly one of *source_table*, *source_geojson*, or *synthetic_n*
    must be provided.

    Returns a dict with keys: ``status``, ``rows``, ``elapsed``, ``error``.
    """
    source_count = sum(
        1 for x in [source_table, source_geojson, synthetic_n] if x is not None
    )
    if source_count != 1:
        return {
            "status": "error",
            "error": "Exactly one source must be specified: "
            "source_table, source_geojson, or synthetic_n",
        }

    start = time.time()
    messages: list[str] = []

    def _log(msg: str) -> None:
        messages.append(msg)
        logger.info(msg)

    _log("[1/11] Ensuring target table exists")
    _ensure_target_table(target_table)

    if truncate:
        _log("  Truncating existing data")
        _truncate_table(target_table)

    if source_table:
        _log(f"[2/11] Loading parcels from {source_table}")
        _load_from_table(source_table, target_table)
    elif source_geojson:
        _log(f"[2/11] Loading parcels from {source_geojson}")
        _load_from_geojson(source_geojson, target_table)
    elif synthetic_n is not None:
        _log(f"[2/11] Generating {synthetic_n} synthetic parcels")
        _load_synthetic(synthetic_n, target_table)

    _log("  Parcels loaded")

    _log("[2/11] Ensuring all schema columns exist")
    _ensure_columns(target_table)

    _log("[3/11] Computing area columns from geometry")
    _compute_areas(target_table)

    _log("[4/11] Allocating demographics")
    _allocate_demographics(target_table, census_schema)

    _log("[5/11] Allocating employment")
    _allocate_employment(target_table, lehd_schema)

    _log("[6/11] Estimating building areas")
    _estimate_building_areas(target_table)

    _log("[7/11] Classifying land use")
    _classify_land_use(target_table)
    schema_name, table_name = target_table.split(".")
    result = validate_land_use_classification(schema=schema_name, table=table_name)
    if not result.get("success", False):
        raise RuntimeError(
            "Land use classification validation failed: "
            + "; ".join(result.get("failures", []))
        )

    _log("[8/11] Estimating irrigation")
    _estimate_irrigation(target_table)

    _log("[9/11] Computing intersection density")
    _compute_intersection_density(target_table)

    if not skip_imputation:
        _log("[10/11] Running imputation pass")
        _impute_nulls(target_table)
    else:
        _log("[10/11] Skipping imputation pass")

    _log("[10b/11] Reconciling aggregate columns")
    _reconcile_aggregates(target_table)

    schema_name, table_name = target_table.split(".")
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {_q(schema_name)}.{_q(table_name)}")
        row_count = cursor.fetchone()[0]

    _log("[11/11] Validating base canvas")
    _validate(target_table)

    if synthetic_n is not None:
        _validate_synthetic(target_table)

    elapsed = round(time.time() - start, 1)

    return {
        "status": "success",
        "rows": row_count,
        "elapsed": elapsed,
        "messages": messages,
    }


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _q(name: str) -> str:
    """Quote a PostgreSQL identifier."""
    parts = name.split(".")
    return ".".join(connection.ops.quote_name(p) for p in parts)


def _col_list(cols: list[str]) -> str:
    """Return a comma-separated list of quoted column names."""
    return ", ".join(_q(c) for c in cols)


def _geom_transform_to_6933(schema: str, table: str) -> str:
    """Return a SQL expression that transforms ``geometry`` to EPSG:6933.

    Handles both proper PostGIS ``geometry`` columns and ``TEXT`` columns
    that store raw WKT.  TEXT-sourced geometries are assumed to be in EPSG:4326
    (WGS84) — the standard for census TIGER/Line and LEHD staging tables.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s AND column_name = 'geometry'",
            [schema, table],
        )
        row = cursor.fetchone()
    data_type = row[0] if row else "geometry"
    if data_type in ("text", "character varying"):
        return "ST_Transform(ST_SetSRID(geometry::geometry, 4326), 6933)"
    return "ST_Transform(geometry, 6933)"


def _truncate_table(target_table: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE TABLE {_q(target_table)} RESTART IDENTITY CASCADE")


# ═══════════════════════════════════════════════════════════════════════
# Step 1: Ensure target table exists
# ═══════════════════════════════════════════════════════════════════════


def _ensure_target_table(target_table: str) -> None:
    """Create the target table if it does not exist, with all base canvas columns."""
    col_defs = ["id SERIAL PRIMARY KEY"]
    col_defs.append("geometry geometry(MultiPolygon, 4326)")
    for col in BaseCanvasSchema.COLUMN_NAMES:
        if col in ("id", "geometry"):
            continue
        col_def = BaseCanvasSchema.get(col)
        if col_def is None:
            continue
        col_defs.append(f"{_q(col)} {col_def.pg_type}")

    schema_name, table_name = target_table.split(".")
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {_q(schema_name)}")
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {_q(schema_name)}.{_q(table_name)} (
                {", ".join(col_defs)}
            )
        """)
        # Ensure no NOT NULL constraints (pipeline fills data incrementally)
        for col in BaseCanvasSchema.COLUMN_NAMES:
            if col in ("id", "geometry"):
                continue
            cursor.execute(f"""
                ALTER TABLE {_q(schema_name)}.{_q(table_name)}
                ALTER COLUMN {_q(col)} DROP NOT NULL
            """)


# ═══════════════════════════════════════════════════════════════════════
# Step 2: Load parcels
# ═══════════════════════════════════════════════════════════════════════


def _load_from_table(source_table: str, target_table: str) -> None:
    """Load parcels from an existing PostGIS table, preserving input columns."""
    src_parts = source_table.split(".")
    tgt_parts = target_table.split(".")
    src_schema, src_tbl = src_parts if len(src_parts) > 1 else ("public", src_parts[0])
    tgt_schema, tgt_name = tgt_parts if len(tgt_parts) > 1 else ("public", tgt_parts[0])

    # Dynamically detect input-only columns (land_use, assessor_use_code) in source
    extra_cols = _available_columns(
        ["land_use", "assessor_use_code"], src_schema, src_tbl
    )
    col_list = ", ".join(_q(c) for c in extra_cols) if extra_cols else ""

    with connection.cursor() as cursor:
        if col_list:
            cursor.execute(f"""
                INSERT INTO {_q(tgt_schema)}.{_q(tgt_name)} (geometry, {col_list})
                SELECT ST_Transform(ST_Multi(geometry), 4326), {col_list}
                FROM {_q(src_schema)}.{_q(src_tbl)}
            """)
        else:
            cursor.execute(f"""
                INSERT INTO {_q(tgt_schema)}.{_q(tgt_name)} (geometry)
                SELECT ST_Transform(ST_Multi(geometry), 4326)
                FROM {_q(src_schema)}.{_q(src_tbl)}
            """)


def _load_from_geojson(geojson_path: str, target_table: str) -> None:
    """Load parcels from a GeoJSON file via ST_GeomFromGeoJSON."""
    schema, table = target_table.split(".")

    geojson_data = json.loads(Path(geojson_path).read_text())
    features = geojson_data.get("features", [])

    if not features:
        return

    from django.db import transaction

    with transaction.atomic(), connection.cursor() as cursor:
        for feature in features:
            geom_json = json.dumps(feature.get("geometry", {}))
            cursor.execute(
                f"INSERT INTO {_q(schema)}.{_q(table)} (geometry) "
                "SELECT ST_Multi(ST_GeomFromGeoJSON(%s))",
                [geom_json],
            )


def _load_synthetic(n: int, target_table: str) -> None:
    """Generate synthetic parcels using numpy, inserted via WKT.

    Synthetic parcel generation is the one step that genuinely benefits
    from numpy (controlled random distributions).
    """
    from brewgis.workspace.services.synthetic_parcel_generator import (
        generate_synthetic_parcels,
    )

    gdf = generate_synthetic_parcels(n)
    schema, table = target_table.split(".")

    with connection.cursor() as cursor:
        for i, (_, row) in enumerate(gdf.iterrows()):
            wkt = (
                row.geometry.wkt if hasattr(row.geometry, "wkt") else str(row.geometry)
            )
            cursor.execute(
                f"INSERT INTO {_q(schema)}.{_q(table)} (geography_id, geometry) "
                "VALUES (%s, ST_Multi(ST_GeomFromText(%s, 4326)))",
                [i, wkt],
            )


# ═══════════════════════════════════════════════════════════════════════
# Step 2b: Ensure all schema columns exist
# ═══════════════════════════════════════════════════════════════════════


def _ensure_columns(target_table: str) -> None:
    """Add any missing columns to the target table."""
    schema, table = target_table.split(".")

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s",
            [schema, table],
        )
        existing = {row[0] for row in cursor.fetchall()}

        for col in BaseCanvasSchema.COLUMN_NAMES:
            if col in ("id", "geometry") or col in existing:
                continue
            col_def = BaseCanvasSchema.get(col)
            if col_def is None:
                continue
            cursor.execute(
                f"ALTER TABLE {_q(schema)}.{_q(table)} ADD COLUMN {_q(col)} {col_def.pg_type}"
            )


# ═══════════════════════════════════════════════════════════════════════
# Step 3: Compute areas
# ═══════════════════════════════════════════════════════════════════════


def _compute_areas(target_table: str) -> None:
    """Compute area columns from geometry using EPSG:6933 equal-area projection."""
    with connection.cursor() as cursor:
        cursor.execute(f"""
            UPDATE {_q(target_table)}
            SET
                area_gross = ROUND(
                    (ST_Area(ST_Transform(geometry, 6933)) / 4046.86)::numeric, 4
                ),
                area_parcel = ROUND(
                    (ST_Area(ST_Transform(geometry, 6933)) / 4046.86)::numeric, 4
                ),
                area_dev_condition = ROUND(
                    (ST_Area(ST_Transform(geometry, 6933)) / 4046.86 * 0.7)::numeric, 4
                ),
                area_row = ROUND(
                    (ST_Area(ST_Transform(geometry, 6933)) / 4046.86 * 0.15)::numeric, 4
                )
        """)


# ═══════════════════════════════════════════════════════════════════════
# Steps 4-5: Spatial allocation
# ═══════════════════════════════════════════════════════════════════════


def _table_exists(schema: str, table: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = %s)",
            [schema, table],
        )
        return bool(cursor.fetchone()[0])


def _fill_defaults(target_table: str, columns: list[str], default: float) -> None:
    """Set NULL columns to the default value using COALESCE."""
    with connection.cursor() as cursor:
        for col in columns:
            cursor.execute(
                f"UPDATE {_q(target_table)} SET {_q(col)} = COALESCE({_q(col)}, %s)",
                [default],
            )


def _allocate_demographics(target_table: str, census_schema: str) -> None:
    """Allocate demographic data: spatial allocation from census ACS, or defaults."""
    staging_table = f"{census_schema}.acs_block_group"

    if not _table_exists(census_schema, "acs_block_group"):
        raise RuntimeError(
            f"Census staging table {staging_table} does not exist — "
            "cannot allocate demographics. Run the census dlt pipeline first."
        )
    _allocate_via_spatial_join(target_table, staging_table, _DEMOGRAPHIC_COLUMNS)
    _check_allocation_result(target_table, _DEMOGRAPHIC_COLUMNS, "demographic")
    _fill_defaults(target_table, _DEMOGRAPHIC_COLUMNS, 0.0)


def _allocate_employment(target_table: str, lehd_schema: str) -> None:
    """Allocate employment data: spatial allocation from LEHD, or defaults."""
    staging_table = f"{lehd_schema}.wac_block"

    if not _table_exists(lehd_schema, "wac_block"):
        raise RuntimeError(
            f"LEHD staging table {staging_table} does not exist — "
            "cannot allocate employment. Run the LEHD dlt pipeline first."
        )
    _allocate_via_spatial_join(target_table, staging_table, _EMPLOYMENT_COLUMNS)
    _check_allocation_result(target_table, _EMPLOYMENT_COLUMNS, "employment")
    _calibrate_employment(target_table, staging_table)
    _fill_defaults(target_table, _EMPLOYMENT_COLUMNS, 0.0)


def _calibrate_employment(target_table: str, source_table: str) -> None:
    """Scale allocated employment to match county-level totals."""
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT COALESCE(SUM(emp), 0) FROM {_q(source_table)}")
            county_total = float(cursor.fetchone()[0])

            cursor.execute(f"SELECT COALESCE(SUM(emp), 0) FROM {_q(target_table)}")
            allocated_total = float(cursor.fetchone()[0])

            if allocated_total > 0 and county_total > allocated_total:
                scale = county_total / allocated_total
                for col in _EMPLOYMENT_COLUMNS:
                    cursor.execute(
                        f"UPDATE {_q(target_table)} "
                        f"SET {_q(col)} = {_q(col)} * %s "
                        f"WHERE {_q(col)} > 0",
                        [scale],
                    )
    except Exception:
        logger.warning("  Employment calibration skipped (source unavailable)")


def _allocate_via_spatial_join(
    target_table: str,
    source_table: str,
    columns: list[str],
) -> None:
    """Run area-weighted spatial allocation via a single SQL CTE.

    Replaces the old ``_allocate_via_postgis`` which loaded data into
    temp tables via Python row iteration.  This version operates directly
    on the persisted staging and target tables.
    """
    src_schema, src_table = (
        source_table.split(".") if "." in source_table else ("public", source_table)
    )
    tgt_schema, tgt_table = (
        target_table.split(".") if "." in target_table else ("public", target_table)
    )

    available = _available_columns(columns, src_schema, src_table)
    if not available:
        return

    sum_cols = {c for c in available if c in BaseCanvasSchema.sum_columns()}
    avg_cols = {c for c in available if c in BaseCanvasSchema.avg_columns()}
    unclassified = [c for c in available if c not in sum_cols and c not in avg_cols]
    sum_list = [c for c in available if c in sum_cols] + unclassified
    avg_list = [c for c in available if c in avg_cols]

    if not sum_list and not avg_list:
        return

    # Build aggregation expressions
    sum_exprs: list[str] = []
    for c in sum_list:
        sum_exprs.append(
            f"SUM(COALESCE(s.{_q(c)}, 0) * ST_Area(ST_Intersection(t.geom, s.geom)) "
            f"/ GREATEST(ST_Area(s.geom), 1e-10)) AS {_q(c)}"
        )
    for c in avg_list:
        sum_exprs.append(
            f"SUM(COALESCE(s.{_q(c)}, 0) * ST_Area(ST_Intersection(t.geom, s.geom))) "
            f"/ NULLIF(SUM(ST_Area(ST_Intersection(t.geom, s.geom))), 0) AS {_q(c)}"
        )

    all_available = available
    set_exprs = [
        f"{_q(c)} = COALESCE({_q('t')}.{_q(c)}, sub.{_q(c)})" for c in all_available
    ]

    with connection.cursor() as cursor:
        cursor.execute(f"""
            DROP TABLE IF EXISTS _alloc_src;
            CREATE TEMP TABLE _alloc_src AS
            SELECT
                {_geom_transform_to_6933(src_schema, src_table)} AS geom,
                {_col_list(available)}
            FROM {_q(src_schema)}.{_q(src_table)}
            WHERE geometry IS NOT NULL
        """)
        cursor.execute("CREATE INDEX ON _alloc_src USING GIST (geom)")

        cursor.execute(f"""
            DROP TABLE IF EXISTS _alloc_tgt;
            CREATE TEMP TABLE _alloc_tgt AS
            SELECT id, ST_Transform(geometry, 6933) AS geom
            FROM {_q(tgt_schema)}.{_q(tgt_table)}
            WHERE geometry IS NOT NULL
        """)

        cursor.execute(f"""
            UPDATE {_q(tgt_schema)}.{_q(tgt_table)} t
            SET {", ".join(set_exprs)}
            FROM (
                SELECT
                    t.id,
                    {", ".join(sum_exprs)}
                FROM _alloc_tgt t
                JOIN _alloc_src s ON ST_Intersects(t.geom, s.geom)
                GROUP BY t.id
            ) sub
            WHERE t.id = sub.id
        """)

        # Clamp negatives for currency/percentage/count columns
        metatype_info = BaseCanvasSchema.columns()
        for col in all_available:
            col_def = metatype_info.get(col)
            if col_def and col_def.metatype in ("currency", "percentage", "count"):
                cursor.execute(
                    f"UPDATE {_q(tgt_schema)}.{_q(tgt_table)} "
                    f"SET {_q(col)} = 0.0 WHERE {_q(col)} < 0"
                )


def _available_columns(
    columns: list[str],
    src_schema: str,
    src_table: str,
) -> list[str]:
    """Return the subset of *columns* that exist in *source_table*."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s",
            [src_schema, src_table],
        )
        existing = {row[0] for row in cursor.fetchall()}
    return [c for c in columns if c in existing and c != "geometry"]


def _check_allocation_result(target_table: str, columns: list[str], label: str) -> None:
    """Raise if all target columns are zero after spatial allocation."""
    schema, table = target_table.split(".")
    with connection.cursor() as cursor:
        for col in columns:
            cursor.execute(
                f"SELECT COALESCE(SUM({_q(col)}), 0) FROM {_q(schema)}.{_q(table)}"
            )
            total = float(cursor.fetchone()[0])
            if total > 0:
                return  # at least one column has data
    raise RuntimeError(
        f"Spatial allocation produced all-zero {label} columns in "
        f"{target_table} — no data transferred from the staging table."
    )


# ═══════════════════════════════════════════════════════════════════════
# Step 6: Estimate building areas
# ═══════════════════════════════════════════════════════════════════════


def _build_calib_case(
    extractor: Any,
    default: float,
) -> str:
    """Build a CASE expression from _CALIBRATION for a calibration parameter."""
    parts = ["CASE COALESCE(land_development_category, 'urban')"]
    for cat, values in _CALIBRATION.items():
        parts.append(f"  WHEN '{cat}' THEN {extractor(values)}")
    parts.append(f"  ELSE {default}")
    parts.append("END")
    return "\n".join(parts)


def _estimate_building_areas(target_table: str) -> None:
    """Estimate building areas from dwelling units and employment."""
    du_case = _build_calib_case(lambda v: v[0], _DEFAULT_BLDG_SQFT_PER_DU)
    emp_case = _build_calib_case(lambda v: v[1], _DEFAULT_BLDG_SQFT_PER_EMP)
    q = _q

    with connection.cursor() as cursor:
        # Dwelling unit → building area (only if both columns exist)
        for bldg_col, du_col, factor in [
            ("bldg_area_detsf_sl", "du_detsf_sl", 0.8),
            ("bldg_area_detsf_ll", "du_detsf_ll", 1.2),
            ("bldg_area_attsf", "du_attsf", 0.9),
            ("bldg_area_mf", "du_mf", 0.7),
        ]:
            cursor.execute(f"""
                UPDATE {q(target_table)}
                SET {q(bldg_col)} = COALESCE(
                    {q(bldg_col)},
                    {q(du_col)} * ({du_case}) * {factor}
                )
            """)

        # Employment → building area
        for bldg_col, emp_col in [
            ("bldg_area_retail_services", "emp_retail_services"),
            ("bldg_area_restaurant", "emp_restaurant"),
            ("bldg_area_accommodation", "emp_accommodation"),
            ("bldg_area_arts_entertainment", "emp_arts_entertainment"),
            ("bldg_area_other_services", "emp_other_services"),
            ("bldg_area_office_services", "emp_office_services"),
            ("bldg_area_public_admin", "emp_public_admin"),
            ("bldg_area_education", "emp_education"),
            ("bldg_area_medical_services", "emp_medical_services"),
            ("bldg_area_transport_warehousing", "emp_transport_warehousing"),
            ("bldg_area_wholesale", "emp_wholesale"),
        ]:
            cursor.execute(f"""
                UPDATE {q(target_table)}
                SET {q(bldg_col)} = COALESCE(
                    {q(bldg_col)},
                    {q(emp_col)} * ({emp_case})
                )
            """)


# ═══════════════════════════════════════════════════════════════════════
# Step 7: Classify land use
# ═══════════════════════════════════════════════════════════════════════


def _classify_land_use(target_table: str) -> None:
    """Classify land development category using assessor codes or SACOG text."""
    q = _q

    # Build CASE expressions only for columns that actually exist
    schema, table = target_table.split(".")
    with connection.cursor() as c:
        c.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s",
            [schema, table],
        )
        existing_cols = {row[0] for row in c.fetchall()}

    fallbacks = ["'urban'"]

    if "assessor_use_code" in existing_cols:
        assessor_case = "CASE\n"
        for code, category in _ASSESSOR_USE_CODE_MAP.items():
            assessor_case += (
                f"  WHEN LEFT(COALESCE(assessor_use_code, ''), 2) = '{code}' "
                f"THEN '{category}'\n"
            )
        assessor_case += "  ELSE NULL\nEND"
        fallbacks.insert(0, assessor_case)

    if "land_use" in existing_cols:
        sacog_case = "CASE\n"
        for label, category in _SACOG_LAND_USE_MAP.items():
            escaped = label.replace("'", "''")
            sacog_case += (
                f"  WHEN TRIM(COALESCE(land_use, '')) = '{escaped}' THEN '{category}'\n"
            )
        sacog_case += "  ELSE 'urban'\nEND"
        fallbacks.insert(1 if "assessor_use_code" in existing_cols else 0, sacog_case)

    with connection.cursor() as cursor:
        fallback_sql = ", ".join(fallbacks)
        cursor.execute(f"""
            UPDATE {q(target_table)}
            SET
                land_development_category = COALESCE(
                    land_development_category,
                    {fallback_sql}
                ),
                built_form_key = COALESCE(
                    built_form_key, '{_DEFAULT_BUILT_FORM_KEY}'
                )
        """)

    _compute_area_by_use(target_table)


def _compute_area_by_use(target_table: str) -> None:
    """Derive area-by-use columns from land_development_category."""
    q = _q

    area_col = "COALESCE(area_parcel, area_gross, 0)"
    use_mappings = [
        ("urban", "area_parcel_res"),
        ("agricultural", "area_parcel_emp_ag"),
        ("industrial", "area_parcel_emp"),
        ("mixed_use", "area_parcel_mixed_use"),
        ("undeveloped", "area_parcel_no_use"),
    ]

    updates: list[str] = []
    for cat, use_col in use_mappings:
        updates.append(
            f"{q(use_col)} = CASE WHEN land_development_category = '{cat}' "
            f"THEN COALESCE({q(use_col)}, {area_col}) ELSE {q(use_col)} END"
        )

    if updates:
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE {q(target_table)} SET {', '.join(updates)}")


# ═══════════════════════════════════════════════════════════════════════
# Step 8: Estimate irrigation
# ═══════════════════════════════════════════════════════════════════════


def _estimate_irrigation(target_table: str) -> None:
    """Estimate irrigated areas from land use and calibration."""
    q = _q

    res_case = _build_calib_case(
        lambda v: v[2],
        _DEFAULT_IRRIGATION_RES_FRAC,
    )
    com_case = _build_calib_case(
        lambda v: v[3],
        _DEFAULT_IRRIGATION_COM_FRAC,
    )

    with connection.cursor() as cursor:
        cursor.execute(f"""
            UPDATE {q(target_table)}
            SET
                residential_irrigated_area = COALESCE(
                    residential_irrigated_area,
                    COALESCE(area_parcel_res, area_gross, 0) * ({res_case})
                ),
                commercial_irrigated_area = COALESCE(
                    commercial_irrigated_area,
                    COALESCE(area_parcel_emp, area_gross, 0) * ({com_case})
                )
        """)


# ═══════════════════════════════════════════════════════════════════════
# Step 9: Compute intersection density
# ═══════════════════════════════════════════════════════════════════════


def _compute_intersection_density(target_table: str) -> None:
    """Compute or default intersection density."""
    q = _q

    density_case = _build_calib_case(
        lambda v: v[4],
        _DEFAULT_INTERSECTION_DENSITY,
    )

    with connection.cursor() as cursor:
        cursor.execute(f"""
            UPDATE {q(target_table)}
            SET intersection_density = ROUND(
                COALESCE(
                    intersection_density,
                    ({density_case})
                )::numeric, 2
            )
        """)


# ═══════════════════════════════════════════════════════════════════════
# Step 10: Imputation
# ═══════════════════════════════════════════════════════════════════════


def _impute_nulls(target_table: str) -> None:
    """Impute NULL values: set remaining NULLs to their schema defaults.

    Uses a COALESCE-to-default per column.  The old pandas version
    iterated ~70 columns in a Python for-loop through
    ``ImputationEngine.national_rule()`` — this does the same in SQL.
    """
    q = _q
    with connection.cursor() as cursor:
        for col in BaseCanvasSchema.COLUMN_NAMES:
            if col in _IMPUTATION_EXCLUDE:
                continue

            column_def = BaseCanvasSchema.get(col)
            if column_def is None:
                continue

            # String columns like land_development_category and built_form_key
            # have their own fill logic — skip them.
            if col in ("land_development_category", "built_form_key"):
                continue

            # Use schema default, falling back to 0.0 for None/non-numeric
            default = column_def.default_value
            if default is None or not isinstance(default, (int, float)):
                default = 0.0

            cursor.execute(
                f"UPDATE {q(target_table)} "
                f"SET {q(col)} = COALESCE({q(col)}, %s) "
                f"WHERE {q(col)} IS NULL",
                [float(default)],
            )


# ═══════════════════════════════════════════════════════════════════════
# Step 10b: Reconcile aggregates
# ═══════════════════════════════════════════════════════════════════════


def _reconcile_aggregates(target_table: str) -> None:
    """Recompute aggregate columns from sub-columns.

    Replaces the old ``_reconcile_aggregates`` / ``_reconcile_one``
    pandas methods.
    """
    q = _q
    with connection.cursor() as cursor:
        for aggregate_col, sub_cols in _RECONCILIATION_MAP.items():
            # Check which sub-columns exist
            available = []
            for sc in sub_cols:
                cursor.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema || '.' || table_name = %s "
                    "AND column_name = %s",
                    [target_table, sc],
                )
                if cursor.fetchone():
                    available.append(sc)

            if not available:
                continue

            sub_sum = "+".join(f"COALESCE({q(c)}, 0)" for c in available)
            cursor.execute(
                f"UPDATE {q(target_table)} "
                f"SET {q(aggregate_col)} = {sub_sum} "
                f"WHERE {sub_sum} > 0"
            )


# ═══════════════════════════════════════════════════════════════════════
# Step 11: Validate
# ═══════════════════════════════════════════════════════════════════════


def _validate(target_table: str) -> None:
    """Validate the base canvas after ETL using Soda Core."""
    missing = BaseCanvasManager.validate_schema(target_table)
    if missing:
        msg = f"Base canvas is missing columns: {missing}"
        raise RuntimeError(msg)

    schema, table = target_table.split(".")
    result = validate_base_canvas(schema=schema, table=table)
    if not result["success"]:
        for failure in result["failures"]:
            logger.warning("  GX FAIL: %s", failure)
        msg = (
            f"GX validation failed for {target_table}: "
            f"{len(result['failures'])} expectation(s) failed"
        )
        raise RuntimeError(msg)
    logger.info("  GX validation passed")


def _validate_synthetic(target_table: str) -> None:
    """Post-validate synthetic parcels (raises on failure)."""
    schema_name, table_name = target_table.split(".")
    gx_result = validate_synthetic_parcels(schema=schema_name, table=table_name)
    if gx_result["success"]:
        logger.info("  GX synthetic_parcels validation passed")
    else:
        msg = "; ".join(gx_result["failures"][:5])
        raise RuntimeError(
            f"GX synthetic_parcels validation failed for {target_table}: {msg}"
        )
