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

import deal
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
from brewgis.workspace.services.calibration_registry import NATIONAL_DEFAULT
from brewgis.workspace.services.calibration_registry import CalibrationPreset
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
_DEFAULT_IRRIGATION_RES_FRAC = (
    0.25  # 25% of residential area irrigated (SACOG urban calibration)
)
_DEFAULT_IRRIGATION_COM_FRAC = (
    0.035  # 3.5% of employment area irrigated (SACOG urban calibration)
)

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
        calibration: CalibrationPreset | None = None,
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
        self._calibration = calibration or NATIONAL_DEFAULT
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

            # Step 10b: Reconcile aggregate columns
            self._step("10b/11", "Reconciling aggregate columns from sub-columns")
            gdf = self._reconcile_aggregates(gdf)
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

    @deal.post(
        lambda result: (
            (result["area_gross"] >= 0).all()
            and (result["area_parcel"] >= 0).all()
            and (result["area_dev_condition"] >= 0).all()
            and (result["area_row"] >= 0).all()
        )
    )
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
        gdf["area_parcel"] = (area_sq_m / sq_m_per_acre).round(4)
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
            # Employment calibration: scale allocated values to match
            # county-level totals from the source data.
            try:
                src_gdf = self._employment_source.fetch_block_data()
                if not src_gdf.empty and "emp" in src_gdf.columns:
                    county_total = float(src_gdf["emp"].sum())
                    allocated_total = float(gdf["emp"].sum())
                    if allocated_total > 0 and county_total > allocated_total:
                        scale_factor = county_total / allocated_total
                        emp_cols = [c for c in _EMPLOYMENT_COLUMNS if c in gdf.columns]
                        for col in emp_cols:
                            mask = gdf[col].notna() & (gdf[col] != 0)
                            gdf.loc[mask, col] = gdf.loc[mask, col] * scale_factor
                        scaled_total = float(gdf["emp"].sum())
                        self._log(
                            f"Employment calibration: {allocated_total:,.0f} → "
                            f"{scaled_total:,.0f} (×{scale_factor:.3f})"
                        )
            except Exception:
                self._log("Employment calibration skipped (source unavailable)")
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

        For columns with ``aggregation_hint="sum"`` (default): spreads source
        polygon totals across target parcels proportionally by overlap area.
        For columns with ``aggregation_hint="avg"`` (rates, percentages, medians):
        computes area-weighted averages of source values per target parcel.
        """
        # ── Split columns by aggregation hint ─────────────────────────
        # Only include columns that are actually available in the source
        schema_sum_cols = set(BaseCanvasSchema.sum_columns())
        schema_avg_cols = set(BaseCanvasSchema.avg_columns())
        sum_cols = [c for c in available_cols if c in schema_sum_cols]
        avg_cols = [c for c in available_cols if c in schema_avg_cols]
        # Fallback: if a column isn't classified in schema, default to sum
        unclassified = [
            c
            for c in available_cols
            if c not in schema_sum_cols and c not in schema_avg_cols
        ]
        sum_cols.extend(unclassified)

        # ── Extract actual SRID from each GeoDataFrame ─────────────
        target_srid = gdf.crs.to_epsg() if gdf.crs is not None else 4326
        source_srid = src_gdf.crs.to_epsg() if src_gdf.crs is not None else 4326

        with connection.cursor() as cursor:
            # ── Create temp tables (drop first to allow reuse) ──────
            all_cols = sum_cols + avg_cols
            col_defs = ", ".join(f'"{c}" DOUBLE PRECISION' for c in all_cols)
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
            src_geom_expr = (
                f"ST_Transform(ST_SetSRID(ST_GeomFromText(%s), {source_srid}), 6933)"
            )
            tgt_geom_expr = (
                f"ST_Transform(ST_SetSRID(ST_GeomFromText(%s), {target_srid}), 6933)"
            )
            col_names = ", ".join(f'"{c}"' for c in all_cols)
            val_placeholders = ", ".join(["%s"] * len(all_cols))

            for _, row in src_gdf.iterrows():
                params = [row.geometry.wkt] + [
                    None if pd.isna(row[c]) else float(row[c]) for c in all_cols
                ]
                cursor.execute(
                    f"INSERT INTO _etl_src (geometry, {col_names}) "
                    f"VALUES ({src_geom_expr}, {val_placeholders})",
                    params,
                )

            # ── Insert target geometries with index tracking ────────
            idx_map: dict[int, int] = {}
            for rid, (orig_idx, row) in enumerate(
                gdf[["geometry"]].iterrows(), start=1
            ):
                cursor.execute(
                    "INSERT INTO _etl_tgt (idx, geometry) "
                    "VALUES (%s, " + tgt_geom_expr + ")",
                    [orig_idx, row.geometry.wkt],
                )
                idx_map[rid] = orig_idx

            # ── Intersection CTE — compute weights for all columns ──
            # Sum cols: weight = overlap_area / source_area (spread totals)
            # Avg cols: intersect_area directly (for weighted average denominator)
            raw_exprs: list[str] = []
            for c in sum_cols:
                raw_exprs.append(f's."{c}" AS "{c}_raw"')
            for c in avg_cols:
                raw_exprs.append(f's."{c}" AS "{c}_raw"')
            col_raw_exprs = ", ".join(raw_exprs)

            intersect_area_expr = "ST_Area(ST_Intersection(t.geometry, s.geometry))"
            source_area_expr = "GREATEST(ST_Area(s.geometry), 1e-10)"

            cursor.execute(f"""
                DROP TABLE IF EXISTS _etl_intersections;
                CREATE TEMP TABLE _etl_intersections AS
                SELECT
                    t.rid AS target_rid,
                    {col_raw_exprs},
                    {intersect_area_expr} AS intersect_area,
                    {intersect_area_expr} / {source_area_expr} AS weight
                FROM _etl_tgt t
                JOIN _etl_src s ON ST_Intersects(t.geometry, s.geometry)
            """)

            # ── Aggregate: sum columns use area-weighted sums ─────────
            sum_exprs: list[str] = []
            for c in sum_cols:
                sum_exprs.append(f'SUM(COALESCE("{c}_raw", 0) * weight) AS "{c}"')
            for c in avg_cols:
                sum_exprs.append(
                    f'SUM(COALESCE("{c}_raw", 0) * intersect_area)'
                    f' / NULLIF(SUM(intersect_area), 0) AS "{c}"'
                )

            cursor.execute(f"""
                SELECT target_rid, {", ".join(sum_exprs)}
                FROM _etl_intersections
                GROUP BY target_rid
            """)
            rows = cursor.fetchall()
            if not rows:
                no_overlaps_msg = "No spatial overlaps"
                raise RuntimeError(no_overlaps_msg)

            # ── Apply results back to GeoDataFrame ──────────────────
            col_values: dict[str, dict[int, float]] = {col: {} for col in all_cols}
            for row in rows:
                target_rid = row[0]
                orig_idx = idx_map[target_rid]
                for i, col in enumerate(all_cols):
                    val = row[i + 1]
                    if val is not None:
                        col_values[col][orig_idx] = val

            for col in all_cols:
                if col_values[col]:
                    gdf[col] = gdf[col].fillna(pd.Series(col_values[col]))
        # Clamp negative values for currency/percentage/count columns
        clamp_metatypes = {"currency", "percentage", "count"}
        for col_def in BaseCanvasSchema.columns().values():
            if (
                col_def.metatype in clamp_metatypes
                and col_def.name in gdf.columns
                and col_def.aggregation_hint != "avg"
            ):
                neg_count = int((gdf[col_def.name] < 0).sum())
                if neg_count > 0:
                    gdf.loc[gdf[col_def.name] < 0, col_def.name] = 0.0
                    logger.warning(
                        'Clamped %d negative values in "%s" to 0.0',
                        neg_count,
                        col_def.name,
                    )

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
        if "land_development_category" in gdf.columns:
            cat = gdf["land_development_category"].fillna("urban")
            default_sqft_per_du = cat.map(
                {
                    cat_name: cal.sqft_per_du
                    for cat_name, cal in self._calibration.categories.items()
                }
            ).fillna(_DEFAULT_BLDG_SQFT_PER_DU)
            default_sqft_per_emp = cat.map(
                {
                    cat_name: cal.sqft_per_emp
                    for cat_name, cal in self._calibration.categories.items()
                }
            ).fillna(_DEFAULT_BLDG_SQFT_PER_EMP)
        else:
            default_sqft_per_du = pd.Series(_DEFAULT_BLDG_SQFT_PER_DU, index=gdf.index)
            default_sqft_per_emp = pd.Series(
                _DEFAULT_BLDG_SQFT_PER_EMP, index=gdf.index
            )
        for bldg_col, du_col, factor in du_cols:
            if bldg_col in gdf.columns and du_col in gdf.columns:
                gdf[bldg_col] = gdf[bldg_col].fillna(
                    gdf[du_col] * default_sqft_per_du * factor
                )

        emp_bldg_map: dict[str, str] = {
            "bldg_area_retail_services": "emp_retail_services",
            "bldg_area_restaurant": "emp_restaurant",
            "bldg_area_accommodation": "emp_accommodation",
            "bldg_area_arts_entertainment": "emp_arts_entertainment",
            "bldg_area_other_services": "emp_other_services",
            "bldg_area_office_services": "emp_office_services",
            "bldg_area_public_admin": "emp_public_admin",
            "bldg_area_education": "emp_education",
            "bldg_area_medical_services": "emp_medical_services",
            "bldg_area_transport_warehousing": "emp_transport_warehousing",
            "bldg_area_wholesale": "emp_wholesale",
        }
        for bldg_col, emp_col in emp_bldg_map.items():
            if bldg_col in gdf.columns and emp_col in gdf.columns:
                gdf[bldg_col] = gdf[bldg_col].fillna(
                    gdf[emp_col] * default_sqft_per_emp
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
            self._log("Using default land use classification (trying assessor codes)")
            if (
                isinstance(self._land_use_source, NullLandUseSource)
                or self._land_use_source is not None
            ):
                gdf = self._land_use_source.classify_parcels(gdf)

        if "land_development_category" in gdf.columns:
            gdf["land_development_category"] = (
                gdf["land_development_category"].fillna("urban").astype(str)
            )

        if "built_form_key" in gdf.columns:
            gdf["built_form_key"] = gdf["built_form_key"].fillna(
                _DEFAULT_BUILT_FORM_KEY
            )
        gdf = self._compute_area_by_use(gdf)
        return gdf

    def _compute_area_by_use(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Derive area-by-use columns from land_development_category."""
        category_map = {
            "urban": "area_parcel_res",
            "agricultural": "area_parcel_emp_ag",
            "industrial": "area_parcel_emp",
            "mixed_use": "area_parcel_mixed_use",
            "undeveloped": "area_parcel_no_use",
        }

        if "land_development_category" not in gdf.columns:
            return gdf

        if "area_parcel" not in gdf.columns:
            area_col = "area_gross"
        else:
            area_col = "area_parcel"

        categories = gdf["land_development_category"].fillna("undeveloped")

        for cat, target_col in category_map.items():
            if target_col in gdf.columns:
                mask = categories == cat
                gdf[target_col] = gdf[target_col].fillna(
                    gdf.loc[mask, area_col] if mask.any() else 0.0
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
            cat = gdf.get("land_development_category", None)
            res_area = gdf["area_parcel_res"].fillna(gdf["area_gross"])
            if cat is not None:
                cat = cat.fillna("urban")
                for c, cat_cal in self._calibration.categories.items():
                    mask = cat == c
                    gdf.loc[mask, "residential_irrigated_area"] = gdf.loc[
                        mask, "residential_irrigated_area"
                    ].fillna(res_area.loc[mask] * cat_cal.irrigation_res_frac)
            # Fallback: fill remaining NaN (unmatched categories) with default fractions
            gdf["residential_irrigated_area"] = gdf[
                "residential_irrigated_area"
            ].fillna(res_area * _DEFAULT_IRRIGATION_RES_FRAC)
        else:
            gdf["residential_irrigated_area"] = gdf[
                "residential_irrigated_area"
            ].fillna(res_area * _DEFAULT_IRRIGATION_RES_FRAC)
        if "commercial_irrigated_area" in gdf.columns:
            cat = gdf.get("land_development_category", None)
            emp_area = gdf["area_parcel_emp"].fillna(gdf["area_gross"])
            if cat is not None:
                cat = cat.fillna("urban")
                for c, cat_cal in self._calibration.categories.items():
                    mask = cat == c
                    gdf.loc[mask, "commercial_irrigated_area"] = gdf.loc[
                        mask, "commercial_irrigated_area"
                    ].fillna(emp_area.loc[mask] * cat_cal.irrigation_com_frac)
            # Fallback: fill remaining NaN (unmatched categories) with default fractions
            gdf["commercial_irrigated_area"] = gdf["commercial_irrigated_area"].fillna(
                emp_area * _DEFAULT_IRRIGATION_COM_FRAC
            )
        else:
            gdf["commercial_irrigated_area"] = gdf["commercial_irrigated_area"].fillna(
                emp_area * _DEFAULT_IRRIGATION_COM_FRAC
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
            # Apply per-category defaults if land_development_category is available
            if "land_development_category" in gdf.columns:
                cat = gdf["land_development_category"].fillna("urban")
                cat_defaults = cat.map(
                    {
                        cat_name: cal.intersection_density
                        for cat_name, cal in self._calibration.categories.items()
                    }
                ).fillna(_DEFAULT_INTERSECTION_DENSITY)
                gdf["intersection_density"] = gdf["intersection_density"].fillna(
                    cat_defaults
                )
            else:
                gdf["intersection_density"] = gdf["intersection_density"].fillna(
                    _DEFAULT_INTERSECTION_DENSITY
                )
            gdf["intersection_density"] = gdf["intersection_density"].round(2)
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

    def _reconcile_aggregates(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Recompute aggregate columns from sub-columns using available data.

        Overwrites each aggregate with the sum of its sub-columns whenever at
        least one sub-column has positive data.  Falls back to the original
        aggregate value when no sub-column data is available.  Logs a warning
        when sub-columns are missing so the caller can investigate.
        """
        # ── Dwelling unit aggregates ────────────────────────────────────
        self._reconcile_one(gdf, "du_detsf", ["du_detsf_sl", "du_detsf_ll"])
        self._reconcile_one(gdf, "du_mf", ["du_mf2to4", "du_mf5p"])
        self._reconcile_one(gdf, "du", ["du_detsf", "du_attsf", "du_mf"])

        # ── Employment aggregates ───────────────────────────────────────
        self._reconcile_one(
            gdf,
            "emp_ret",
            [
                "emp_retail_services",
                "emp_restaurant",
                "emp_accommodation",
                "emp_arts_entertainment",
                "emp_other_services",
            ],
        )
        self._reconcile_one(
            gdf, "emp_off", ["emp_office_services", "emp_medical_services"]
        )
        self._reconcile_one(gdf, "emp_pub", ["emp_public_admin", "emp_education"])
        self._reconcile_one(
            gdf,
            "emp_ind",
            [
                "emp_manufacturing",
                "emp_wholesale",
                "emp_transport_warehousing",
                "emp_utilities",
                "emp_construction",
            ],
        )
        self._reconcile_one(gdf, "emp_ag", ["emp_agriculture", "emp_extraction"])
        self._reconcile_one(
            gdf,
            "emp",
            [
                "emp_ret",
                "emp_off",
                "emp_pub",
                "emp_ind",
                "emp_ag",
                "emp_military",
            ],
        )
        return gdf

    @staticmethod
    def _reconcile_one(
        gdf: gpd.GeoDataFrame,
        aggregate_col: str,
        sub_cols: list[str],
    ) -> None:
        """Reconcile *aggregate_col* from *sub_cols*, tolerating missing columns.

        Uses only the sub-columns that exist in *gdf*.  Logs a warning when
        sub-columns are absent so the caller can investigate incomplete data
        sources.  Overwrites the aggregate only on rows where at least one
        available sub-column has a positive value.
        """
        if aggregate_col not in gdf.columns:
            return
        available = [c for c in sub_cols if c in gdf.columns]
        if not available:
            return
        missing = [c for c in sub_cols if c not in gdf.columns]
        if missing:
            logger.warning(
                "Reconciling %s: missing sub-columns %s",
                aggregate_col,
                missing,
            )
        sub_sum = gdf[available].sum(axis=1, min_count=1)
        # min_count=1 means NaN if ALL values are NaN; otherwise sum available
        valid_mask = sub_sum.notna() & (sub_sum > 0)
        cnt = int(valid_mask.sum())
        if cnt > 0:
            gdf.loc[valid_mask, aggregate_col] = sub_sum

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
        row_placeholder = (
            "("
            + ", ".join(
                "ST_GeomFromText(%s, 4326)" if c == "geometry" else "%s"
                for c in insert_cols
            )
            + ")"
        )
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
        # Irrigation unit sanity check: irrigated area should not exceed parcel area
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) FROM public.base_canvas
                WHERE residential_irrigated_area > area_parcel
                   OR commercial_irrigated_area > area_parcel
            """)
            overflow = cursor.fetchone()[0]
            if overflow > 0:
                self._log(
                    f"WARNING: {overflow} row(s) have irrigated area exceeding parcel area"
                )
            else:
                self._log("Irrigation units OK — no area overflow")

        # Equity column sanity check: must be non-negative
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) FROM public.base_canvas
                WHERE median_income < 0
                   OR rent_burden_pct < 0
                   OR pct_minority < 0
                   OR pct_college_educated < 0
                   OR cost_burden_pct < 0
            """)
            neg_equity = cursor.fetchone()[0]
            if neg_equity > 0:
                self._log(
                    f"WARNING: {neg_equity} row(s) have negative equity column values"
                )
            else:
                self._log("Equity columns OK — all non-negative")

    # ── Helpers ─────────────────────────────────────────────────────────

    def _step(self, label: str, description: str) -> None:
        """Log a step header."""
        self._messages.append(f"[{label}] {description}")

    def _log(self, message: str) -> None:
        """Log an indented info message."""
        self._messages.append(f"  {message}")
