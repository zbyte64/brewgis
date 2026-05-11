"""Base Canvas ETL — orchestrates the 11-step ETL pipeline for ``public.base_canvas``.

This service extracts the full pipeline from the management command into
a reusable service with pluggable data source adapters.  The management
command is a thin CLI wrapper.

Pipeline steps:

    1. Ensure base canvas table exists
    2. Load parcel features from source
    3. Compute area columns from geometry
    4. Allocate demographics (Census ACS -> parcels)
    5. Allocate employment (LEHD -> parcels)
    6. Estimate building areas
    7. Classify land use
    8. Estimate irrigation
    9. Compute intersection density
    10. Imputation pass (3-tier cascade)
    11. Validate
"""

from __future__ import annotations

import logging
import time
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from django.db import connection
from django.db import transaction

from brewgis.workspace.services.base_canvas_adapters import DemographicSource
from brewgis.workspace.services.base_canvas_adapters import EmploymentSource
from brewgis.workspace.services.base_canvas_adapters import IntersectionDensitySource
from brewgis.workspace.services.base_canvas_adapters import IrrigationSource
from brewgis.workspace.services.base_canvas_adapters import LandUseSource
from brewgis.workspace.services.base_canvas_adapters import NullDemographicSource
from brewgis.workspace.services.base_canvas_adapters import NullEmploymentSource
from brewgis.workspace.services.base_canvas_adapters import (
    NullIntersectionDensitySource,
)
from brewgis.workspace.services.base_canvas_adapters import NullIrrigationSource
from brewgis.workspace.services.base_canvas_adapters import NullLandUseSource
from brewgis.workspace.services.base_canvas_manager import BaseCanvasManager
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema
from brewgis.workspace.services.imputation_engine import ImputationEngine
from brewgis.workspace.services.imputation_engine import ImputationRule
from brewgis.workspace.services.synthetic_parcel_generator import (
    generate_synthetic_parcels,
)

logger = logging.getLogger(__name__)

# ── Default imputation values for national defaults ───────────────────
_DEFAULT_INTERSECTION_DENSITY = 12.5  # intersections/km^2
_DEFAULT_BUILT_FORM_KEY = "mixed_use"
_DEFAULT_BLDG_SQFT_PER_DU = 1200.0
_DEFAULT_BLDG_SQFT_PER_EMP = 300.0
_DEFAULT_IRRIGATION_RES_FRAC = 0.1  # 10% of residential area irrigated
_DEFAULT_IRRIGATION_COM_FRAC = 0.05  # 5% of employment area irrigated

# Demographic columns that can be allocated from Census block groups
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

# Employment columns that can be allocated from LEHD blocks
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


class BaseCanvasETL:
    """Orchestrate the full 11-step ETL pipeline for ``public.base_canvas``.

    Args:
        demographic_source: Source for Census ACS demographic data.
            Default: ``NullDemographicSource`` (fillna 0.0).
        employment_source: Source for LEHD employment data.
            Default: ``NullEmploymentSource`` (fillna 0.0).
        land_use_source: Source for land use classification.
            Default: ``NullLandUseSource`` (all ``"urban"``).
        intersection_density_source: Source for intersection density.
            Default: ``NullIntersectionDensitySource`` (12.5).
        irrigation_source: Source for irrigation estimation.
            Default: ``NullIrrigationSource`` (hardcoded fractions).
        verbosity: Logging verbosity level (0=silent, 1=normal, 2=verbose).
    """

    def __init__(
        self,
        *,
        demographic_source: DemographicSource | None = None,
        employment_source: EmploymentSource | None = None,
        land_use_source: LandUseSource | None = None,
        intersection_density_source: IntersectionDensitySource | None = None,
        irrigation_source: IrrigationSource | None = None,
        verbosity: int = 1,
    ) -> None:
        self._demographic_source = demographic_source or NullDemographicSource()
        self._employment_source = employment_source or NullEmploymentSource()
        self._land_use_source = land_use_source or NullLandUseSource()
        self._intersection_density_source = (
            intersection_density_source or NullIntersectionDensitySource()
        )
        self._irrigation_source = irrigation_source or NullIrrigationSource()
        self._verbosity = verbosity
        self._messages: list[str] = []
        self._start_time: float = 0.0

    # ── Public API ──────────────────────────────────────────────────────

    def run(
        self,
        *,
        source_table: str | None = None,
        source_geojson: str | None = None,
        synthetic_n: int | None = None,
        skip_imputation: bool = False,
        truncate: bool = False,
    ) -> dict[str, Any]:
        """Execute the full 11-step ETL pipeline.

        Exactly one of *source_table*, *source_geojson*, or *synthetic_n*
        must be provided.

        Returns a result dict with keys:
            * ``status`` — ``"success"`` or ``"error"``
            * ``rows`` — number of rows written
            * ``elapsed`` — wall-clock seconds
            * ``error`` — error message (if status is ``"error"``)
        """
        self._messages = []
        self._start_time = time.time()

        source_count = sum(
            1 for x in [source_table, source_geojson, synthetic_n] if x is not None
        )
        if source_count != 1:
            return {
                "status": "error",
                "error": "Exactly one source must be specified: "
                "--source-table, --source-geojson, or --synthetic N",
            }

        try:
            # Step 1
            self._step("1/11", "Ensuring base_canvas table")
            BaseCanvasManager.ensure_table()

            if truncate:
                self._log("Truncating existing data")
                with connection.cursor() as cursor:
                    cursor.execute(
                        "TRUNCATE TABLE public.base_canvas RESTART IDENTITY CASCADE"
                    )

            # Step 2
            self._step("2/11", "Loading parcel features")
            gdf = self._load_parcels(source_table, source_geojson, synthetic_n)
            self._log(f"Loaded {len(gdf)} parcels")
            if gdf.empty:
                return {
                    "status": "error",
                    "error": "No parcels loaded from the specified source",
                }

            gdf = self._ensure_columns(gdf)

            # Step 3
            self._step("3/11", "Computing area columns from geometry")
            gdf = self._compute_areas(gdf)

            # Step 4
            self._step("4/11", "Allocating demographics")
            gdf = self._allocate_demographics(gdf)

            # Step 5
            self._step("5/11", "Allocating employment")
            gdf = self._allocate_employment(gdf)

            # Step 6
            self._step("6/11", "Estimating building areas")
            gdf = self._estimate_building_areas(gdf)

            # Step 7
            self._step("7/11", "Classifying land use")
            gdf = self._classify_land_use(gdf)

            # Step 8
            self._step("8/11", "Estimating irrigation")
            gdf = self._estimate_irrigation(gdf)

            # Step 9
            self._step("9/11", "Computing intersection density")
            gdf = self._compute_intersection_density(gdf)

            # Step 10
            if not skip_imputation:
                self._step("10/11", "Running imputation pass")
                gdf = self._impute_nulls(gdf)
            else:
                self._step("10/11", "Skipping imputation pass (--skip-imputation)")

            # Write to database
            self._step("--", "Writing data to public.base_canvas")
            row_count = self._write_to_db(gdf, truncate)

            # Step 11
            self._step("11/11", "Validating base canvas")
            self._validate()

            elapsed = time.time() - self._start_time

            return {
                "status": "success",
                "rows": row_count,
                "elapsed": round(elapsed, 1),
                "messages": list(self._messages),
            }

        except Exception as exc:
            elapsed = time.time() - self._start_time
            logger.exception("ETL pipeline failed")
            return {
                "status": "error",
                "error": str(exc),
                "elapsed": round(elapsed, 1),
                "messages": list(self._messages),
            }

    # ── Step implementations ────────────────────────────────────────────

    def _load_parcels(
        self,
        source_table: str | None,
        source_geojson: str | None,
        synthetic_n: int | None,
    ) -> gpd.GeoDataFrame:
        """Load parcel features from the specified source."""
        if source_table:
            self._log(f"Reading from PostGIS table: {source_table}")
            parts = source_table.split(".", 1)
            schema_name = parts[0] if len(parts) > 1 else "public"
            table_name = parts[-1]
            return gpd.GeoDataFrame.from_postgis(
                f'SELECT *, ST_AsText(geometry) AS geometry_wkt FROM "{schema_name}"."{table_name}"',
                connection,
                geom_col="geometry",
            )

        if source_geojson:
            self._log(f"Reading from GeoJSON: {source_geojson}")
            return gpd.read_file(source_geojson)

        if synthetic_n is not None:
            self._log(f"Generating {synthetic_n} synthetic parcels")
            return generate_synthetic_parcels(synthetic_n)

        return gpd.GeoDataFrame()

    def _ensure_columns(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Ensure all base canvas columns exist; add missing ones with NaN."""
        for col in BaseCanvasSchema.COLUMN_NAMES:
            if col in ("id", "geometry"):
                continue
            if col not in gdf.columns:
                gdf[col] = np.nan
        return gdf

    def _compute_areas(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Compute area columns from parcel geometry.

        Uses EPSG:6933 equal-area projection for accurate geodesic area.
        """
        gdf_eq = (
            gdf.to_crs("EPSG:6933")
            if gdf.crs is None or gdf.crs.to_string() != "EPSG:6933"
            else gdf
        )
        area_sq_m = gdf_eq.geometry.area

        sq_m_per_acre = 4046.86
        gdf["area_gross"] = (area_sq_m / sq_m_per_acre).round(4)
        gdf["area_parcel"] = (area_sq_m / sq_m_per_acre * 0.85).round(4)
        gdf["area_dev_condition"] = (area_sq_m / sq_m_per_acre * 0.7).round(4)
        gdf["area_row"] = (area_sq_m / sq_m_per_acre * 0.15).round(4)
        return gdf

    def _allocate_demographics(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Allocate demographic values from the configured source.

        If the configured ``DemographicSource`` has real data, use spatial
        allocation.  Otherwise fill demographic columns with 0.0.
        """
        if self._demographic_source.available:
            self._log("Using real demographic source")
            gdf = self._allocate_from_source(
                gdf,
                self._demographic_source,
                _DEMOGRAPHIC_COLUMNS,
            )
        else:
            self._log("Using default demographic values (fillna 0.0)")
            fill_map: dict[str, float] = {
                "pop": 0.0,
                "pop_groupquarter": 0.0,
                "hh": 0.0,
                "du": 0.0,
                "du_detsf": 0.0,
                "du_detsf_sl": 0.0,
                "du_detsf_ll": 0.0,
                "du_attsf": 0.0,
                "du_mf": 0.0,
                "du_mf2to4": 0.0,
                "du_mf5p": 0.0,
                "median_income": 0.0,
                "rent_burden_pct": 0.0,
                "pct_minority": 0.0,
                "pct_college_educated": 0.0,
                "cost_burden_pct": 0.0,
            }
            for col, default in fill_map.items():
                if col in gdf.columns:
                    gdf[col] = gdf[col].fillna(default)
        return gdf

    def _allocate_employment(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Allocate employment values from the configured source."""
        if self._employment_source.available:
            self._log("Using real employment source")
            gdf = self._allocate_from_source(
                gdf,
                self._employment_source,
                _EMPLOYMENT_COLUMNS,
            )
        else:
            self._log("Using default employment values (fillna 0.0)")
            fill_map: dict[str, float] = {
                "emp": 0.0,
                "emp_ret": 0.0,
                "emp_retail_services": 0.0,
                "emp_restaurant": 0.0,
                "emp_accommodation": 0.0,
                "emp_arts_entertainment": 0.0,
                "emp_other_services": 0.0,
                "emp_off": 0.0,
                "emp_office_services": 0.0,
                "emp_medical_services": 0.0,
                "emp_pub": 0.0,
                "emp_public_admin": 0.0,
                "emp_education": 0.0,
                "emp_ind": 0.0,
                "emp_manufacturing": 0.0,
                "emp_wholesale": 0.0,
                "emp_transport_warehousing": 0.0,
                "emp_utilities": 0.0,
                "emp_construction": 0.0,
                "emp_ag": 0.0,
                "emp_agriculture": 0.0,
                "emp_extraction": 0.0,
                "emp_military": 0.0,
            }
            for col, default in fill_map.items():
                if col in gdf.columns:
                    gdf[col] = gdf[col].fillna(default)
        return gdf

    def _allocate_via_postgis(
        self,
        gdf: gpd.GeoDataFrame,
        src_gdf: gpd.GeoDataFrame,
        available_cols: list[str],
    ) -> None:
        """Run PostGIS area-weighted allocation, modifying gdf in place.

        Creates temp tables for source and target, runs a single batch SQL
        query for area-weighted allocation, and writes results back to gdf.
        Raises RuntimeError if no spatial overlaps are found.
        """
        with connection.cursor() as cursor:
            # ── Create temp tables (drop first to allow reuse) ──────
            col_defs = ", ".join(f'"{c}" DOUBLE PRECISION' for c in available_cols)
            cursor.execute(f"""
                DROP TABLE IF EXISTS _etl_src;
                CREATE TEMP TABLE _etl_src (
                    rid SERIAL PRIMARY KEY,
                    geometry geometry,
                    {col_defs}
                )
            """)
            cursor.execute("""
                DROP TABLE IF EXISTS _etl_tgt;
                CREATE TEMP TABLE _etl_tgt (
                    rid SERIAL PRIMARY KEY,
                    idx BIGINT,
                    geometry geometry
                )
            """)

            # ── Insert source geometries (4326 -> 6933 in SQL) ─────
            geom_expr = "ST_Transform(ST_SetSRID(ST_GeomFromText(%s), 4326), 6933)"
            col_names = ", ".join(f'"{c}"' for c in available_cols)
            val_placeholders = ", ".join(["%s"] * len(available_cols))

            for _, row in src_gdf.iterrows():
                params = [row.geometry.wkt] + [
                    None if pd.isna(row[c]) else float(row[c]) for c in available_cols
                ]
                cursor.execute(
                    f"INSERT INTO _etl_src (geometry, {col_names}) "
                    f"VALUES ({geom_expr}, {val_placeholders})",
                    params,
                )

            # ── Insert target geometries with index tracking ────────
            idx_map: dict[int, int] = {}
            for rid, (orig_idx, row) in enumerate(
                gdf[["geometry"]].iterrows(), start=1
            ):
                cursor.execute(
                    "INSERT INTO _etl_tgt (idx, geometry) "
                    "VALUES (%s, " + geom_expr + ")",
                    [orig_idx, row.geometry.wkt],
                )
                idx_map[rid] = orig_idx

            # ── Batch SQL query for all columns ─────────────────────
            col_raw_exprs = ", ".join(f's."{c}" AS "{c}_raw"' for c in available_cols)
            col_sum_exprs = ", ".join(
                f'SUM(COALESCE("{c}_raw", 0) * weight) AS "{c}"' for c in available_cols
            )
            cursor.execute(f"""
                WITH intersections AS (
                    SELECT
                        t.rid AS target_rid,
                        {col_raw_exprs},
                        ST_Area(ST_Intersection(t.geometry, s.geometry))
                            / GREATEST(ST_Area(s.geometry), 1e-10) AS weight
                    FROM _etl_tgt t
                    JOIN _etl_src s ON ST_Intersects(t.geometry, s.geometry)
                )
                SELECT target_rid, {col_sum_exprs}
                FROM intersections
                GROUP BY target_rid
            """)

            rows = cursor.fetchall()
            if not rows:
                no_overlaps_msg = "No spatial overlaps"
                raise RuntimeError(no_overlaps_msg)

            # ── Apply results back to GeoDataFrame ──────────────────
            col_values: dict[str, dict[int, float]] = {
                col: {} for col in available_cols
            }
            for row in rows:
                target_rid = row[0]
                orig_idx = idx_map[target_rid]
                for i, col in enumerate(available_cols):
                    val = row[i + 1]
                    if val is not None:
                        col_values[col][orig_idx] = val

            for col in available_cols:
                if col_values[col]:
                    gdf[col] = gdf[col].fillna(pd.Series(col_values[col]))

    def _allocate_from_source(
        self,
        gdf: gpd.GeoDataFrame,
        source: DemographicSource | EmploymentSource,
        columns: list[str],
    ) -> gpd.GeoDataFrame:
        """Allocate attributes from source polygons to parcels via
        area-weighted geospatial overlay."""
        if hasattr(source, "fetch_block_group_data"):
            src_gdf = source.fetch_block_group_data()
        else:
            src_gdf = source.fetch_block_data()

        available_cols = [c for c in columns if c in src_gdf.columns]
        available_cols = [c for c in available_cols if c != "geometry"]
        if not available_cols or src_gdf.empty:
            self._log("Source returned no data; falling back to fillna 0.0")
            for col in columns:
                if col in gdf.columns:
                    gdf[col] = gdf[col].fillna(0.0)
            return gdf

        try:
            with transaction.atomic():
                self._allocate_via_postgis(gdf, src_gdf, available_cols)

                cnt = (
                    int((gdf[available_cols[0]] > 0).sum())
                    if available_cols[0] in gdf.columns
                    else 0
                )
                self._log(
                    f"Area-weighted alloc: {cnt}/{len(gdf)} matched, "
                    f"{len(available_cols)} cols"
                )
                col_sums = {c: float(gdf[c].sum()) for c in available_cols[:4]}
                self._log(f"Alloc sums: {col_sums}")
        except Exception as exc:
            self._log(f"Allocation failed: {exc}; falling back")
            for col in columns:
                if col in gdf.columns:
                    gdf[col] = gdf[col].fillna(0.0)
        return gdf

    def _estimate_building_areas(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Estimate building areas from dwelling units and employment."""
        du_cols = [
            ("bldg_area_detsf_sl", "du_detsf_sl", 0.8),
            ("bldg_area_detsf_ll", "du_detsf_ll", 1.2),
            ("bldg_area_attsf", "du_attsf", 0.9),
            ("bldg_area_mf", "du_mf", 0.7),
        ]
        for bldg_col, du_col, factor in du_cols:
            if bldg_col in gdf.columns and du_col in gdf.columns:
                gdf[bldg_col] = gdf[bldg_col].fillna(
                    gdf[du_col] * _DEFAULT_BLDG_SQFT_PER_DU * factor
                )

        emp_bldg_map: dict[str, str] = {
            "bldg_area_retail_services": "emp_ret",
            "bldg_area_restaurant": "emp_ret",
            "bldg_area_accommodation": "emp_ret",
            "bldg_area_arts_entertainment": "emp_ret",
            "bldg_area_other_services": "emp_ret",
            "bldg_area_office_services": "emp_off",
            "bldg_area_public_admin": "emp_pub",
            "bldg_area_education": "emp_pub",
            "bldg_area_medical_services": "emp_off",
            "bldg_area_transport_warehousing": "emp_ind",
            "bldg_area_wholesale": "emp_ind",
        }
        for bldg_col, emp_col in emp_bldg_map.items():
            if bldg_col in gdf.columns and emp_col in gdf.columns:
                gdf[bldg_col] = gdf[bldg_col].fillna(
                    gdf[emp_col] * _DEFAULT_BLDG_SQFT_PER_EMP
                )
        return gdf

    def _classify_land_use(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Classify land use if not already set.

        Delegates to the configured land-use source which may use:
        - Assessor use codes from parcel attributes (CA Standard codes)
        - NLCD land cover zonal statistics
        - Default fallback to ``"urban"``
        """
        if self._land_use_source.available:
            self._log("Using real land-use source")
            gdf = self._land_use_source.classify_parcels(gdf)
        else:
            self._log("Using default land use classification (fillna urban)")

        if "land_development_category" in gdf.columns:
            gdf["land_development_category"] = (
                gdf["land_development_category"].fillna("urban").astype(str)
            )

        if "built_form_key" in gdf.columns:
            gdf["built_form_key"] = gdf["built_form_key"].fillna(
                _DEFAULT_BUILT_FORM_KEY
            )
        return gdf

    def _estimate_irrigation(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Estimate irrigated areas from land use and area."""
        if self._irrigation_source.available:
            self._log("Using real irrigation source")
            gdf = self._irrigation_source.estimate_irrigation(gdf)
        else:
            self._log("Using default irrigation estimates")

        if "residential_irrigated_area" in gdf.columns:
            gdf["residential_irrigated_area"] = gdf[
                "residential_irrigated_area"
            ].fillna(
                gdf.get("area_parcel_res", gdf["area_gross"])
                * _DEFAULT_IRRIGATION_RES_FRAC
            )
        if "commercial_irrigated_area" in gdf.columns:
            gdf["commercial_irrigated_area"] = gdf["commercial_irrigated_area"].fillna(
                gdf.get("area_parcel_emp", gdf["area_gross"])
                * _DEFAULT_IRRIGATION_COM_FRAC
            )
        return gdf

    def _compute_intersection_density(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Compute or default intersection density."""
        if self._intersection_density_source.available:
            self._log("Using real intersection density source")
            gdf = self._intersection_density_source.compute_density(gdf)
        else:
            self._log("Using default intersection density")

        if "intersection_density" in gdf.columns:
            gdf["intersection_density"] = (
                gdf["intersection_density"]
                .fillna(_DEFAULT_INTERSECTION_DENSITY)
                .round(2)
            )
        return gdf

    def _impute_nulls(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Run the full imputation cascade on all numeric columns.

        Uses the ImputationEngine with sensible defaults.
        """
        engine = ImputationEngine()
        rules: list[ImputationRule] = []

        for col in BaseCanvasSchema.COLUMN_NAMES:
            if col in ("id", "id_source", "geometry_key", "geometry", "built_form_key"):
                continue

            column_def = BaseCanvasSchema.get(col)
            default = column_def.default_value if column_def is not None else 0.0
            if default is None:
                default = 0.0
            if not isinstance(default, (int, float)):
                default = 0.0

            rules.append(
                ImputationRule(
                    target_column=col,
                    strategy=ImputationEngine.national_rule(col, default).strategy,
                    fallback_value=default,
                )
            )

        engine.apply(gdf, rules)
        return gdf

    def _write_to_db(self, gdf: gpd.GeoDataFrame, truncate: bool) -> int:
        """Write the GeoDataFrame to ``public.base_canvas`` using a multi-row INSERT.
        Bulk INSERT using a single ``cursor.execute`` with a multi-row VALUES clause,
        batched in pages of 5000 rows to keep the query size manageable.
        Works with both psycopg2 and psycopg v3 (psycopg[c]) backends.
        """
        if truncate:
            with connection.cursor() as cursor:
                cursor.execute(
                    "TRUNCATE TABLE public.base_canvas RESTART IDENTITY CASCADE"
                )

        insert_cols = [
            c for c in BaseCanvasSchema.COLUMN_NAMES if c in gdf.columns and c != "id"
        ]
        col_names = ", ".join(f'"{c}"' for c in insert_cols)

        rows: list[tuple[object, ...]] = []

        for _, row in gdf.iterrows():
            vals: list[object] = []
            for col in insert_cols:
                if col == "geometry":
                    val = row.get(col)
                    if val is not None and not (
                        isinstance(val, float) and pd.isna(val)
                    ):
                        wkt = val.wkt if hasattr(val, "wkt") else str(val)
                    else:
                        wkt = None
                    vals.append(wkt)
                else:
                    val = row.get(col)
                    if val is None or (isinstance(val, float) and pd.isna(val)):
                        vals.append(None)
                    elif isinstance(val, (np.floating,)):
                        vals.append(float(val))
                    elif isinstance(val, (np.integer,)):
                        vals.append(int(val))
                    else:
                        vals.append(val)
            rows.append(tuple(vals))
        # Build a single-row placeholder: ( %s, %s, ST_GeomFromText(%s, 4326), ... )
        row_placeholder = "(" + ", ".join(
            "ST_GeomFromText(%s, 4326)" if c == "geometry" else "%s"
            for c in insert_cols
        ) + ")"
        sql_base = f"INSERT INTO public.base_canvas ({col_names}) VALUES "
        page_size = 5000
        with connection.cursor() as cursor:
            for i in range(0, len(rows), page_size):
                batch = rows[i : i + page_size]
                values_clause = ", ".join(row_placeholder for _ in batch)
                flat_values = [val for row in batch for val in row]
                cursor.execute(sql_base + values_clause, flat_values)

        rows_written = len(gdf)
        self._log(f"Wrote {rows_written} rows to public.base_canvas")
        return rows_written
    def _validate(self) -> None:
        """Validate the base canvas after ETL."""
        missing = BaseCanvasManager.validate_schema()
        if missing:
            msg = f"Base canvas is missing columns: {missing}"
            raise RuntimeError(msg)

        with connection.cursor() as cursor:
            non_null_checks = " OR ".join(
                f'"{c}" IS NULL' for c in BaseCanvasSchema.NON_NULL_COLUMNS
            )
            cursor.execute(
                f"SELECT COUNT(*) FROM public.base_canvas WHERE {non_null_checks}"
            )
            null_count = cursor.fetchone()[0]
            if null_count > 0:
                self._log(
                    f"WARNING: {null_count} row(s) have NULL values in NON_NULL_COLUMNS"
                )
            else:
                self._log("No NULLs in required columns")

        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM public.base_canvas")
            row_count = cursor.fetchone()[0]
            self._log(f"Total rows: {row_count}")

    # ── Helpers ─────────────────────────────────────────────────────────

    def _step(self, label: str, description: str) -> None:
        """Log a step header."""
        self._messages.append(f"[{label}] {description}")

    def _log(self, message: str) -> None:
        """Log an indented info message."""
        self._messages.append(f"  {message}")
