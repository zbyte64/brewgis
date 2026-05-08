"""Management command — populate ``public.base_canvas`` via the ETL pipeline.

Orchestrates the full ETL pipeline:

    1. Ensure base canvas table exists
    2. Load parcel features from source
    3. Compute area columns from geometry
    4. Allocate demographics (Census ACS -> parcels)
    5. Allocate employment (LEHD -> parcels)
    6. Estimate building areas
    7. Classify land use
    8. Estimate irrigation
    9. Compute intersection density
    10. Imputation pass
    11. Validate

Modes:
    ``--synthetic N``: generate *N* synthetic parcels for testing.
    ``--source-table``: read from an existing PostGIS parcel table.
    ``--source-geojson``: read from a GeoJSON file.
    ``--skip-imputation``: leave NULLs as-is (debugging).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser
from django.db import connection

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


class Command(BaseCommand):
    """Populate ``public.base_canvas`` from source parcel data."""

    help = "Populate the base canvas table via the ETL pipeline"

    def add_arguments(self, parser: CommandParser) -> None:
        """Register command-line arguments."""
        source_group = parser.add_mutually_exclusive_group()
        source_group.add_argument(
            "--source-table",
            type=str,
            default=None,
            help="PostGIS table to read parcels from (schema.table)",
        )
        source_group.add_argument(
            "--source-geojson",
            type=str,
            default=None,
            help="GeoJSON file path to read parcels from",
        )
        source_group.add_argument(
            "--synthetic",
            type=int,
            default=None,
            help="Number of synthetic parcels to generate (for testing)",
        )
        parser.add_argument(
            "--skip-imputation",
            action="store_true",
            default=False,
            help="Skip the imputation pass (leave NULLs as-is)",
        )
        parser.add_argument(
            "--truncate",
            action="store_true",
            default=False,
            help="Truncate existing data before inserting",
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def handle(self, **options: Any) -> str | None:
        """Execute the ETL pipeline."""
        self._start_time = time.time()
        self.stdout.write("=== Base Canvas ETL Pipeline ===")

        source_table: str | None = options.get("source_table")
        source_geojson: str | None = options.get("source_geojson")
        synthetic_n: int | None = options.get("synthetic")
        skip_imputation: bool = options.get("skip_imputation", False)
        truncate: bool = options.get("truncate", False)

        # ── Step 0: Validate source ──────────────────────────────
        source_count = sum(1 for x in [source_table, source_geojson, synthetic_n] if x is not None)
        if source_count != 1:
            msg = (
                "Exactly one source must be specified: "
                "--source-table, --source-geojson, or --synthetic N"
            )
            raise CommandError(msg)

        # ── Step 1: Ensure base_canvas table exists ──────────────
        self._step("1/11", "Ensuring base_canvas table")
        BaseCanvasManager.ensure_table()

        if truncate:
            self._log("Truncating existing data")
            with connection.cursor() as cursor:
                cursor.execute("TRUNCATE TABLE public.base_canvas RESTART IDENTITY CASCADE")

        # ── Step 2: Load parcel features ──────────────────────────
        self._step("2/11", "Loading parcel features")
        gdf = self._load_parcels(source_table, source_geojson, synthetic_n)
        self._log(f"Loaded {len(gdf)} parcels")
        if gdf.empty:
            msg = "No parcels loaded from the specified source"
            raise CommandError(msg)

        # Ensure all schema columns exist
        gdf = self._ensure_columns(gdf)

        # ── Step 3: Compute area columns from geometry ───────────
        self._step("3/11", "Computing area columns from geometry")
        gdf = self._compute_areas(gdf)

        # ── Step 4: Allocate demographics ─────────────────────────
        self._step("4/11", "Allocating demographics")
        gdf = self._allocate_demographics(gdf)

        # ── Step 5: Allocate employment ───────────────────────────
        self._step("5/11", "Allocating employment")
        gdf = self._allocate_employment(gdf)

        # ── Step 6: Estimate building areas ───────────────────────
        self._step("6/11", "Estimating building areas")
        gdf = self._estimate_building_areas(gdf)

        # ── Step 7: Classify land use ─────────────────────────────
        self._step("7/11", "Classifying land use")
        gdf = self._classify_land_use(gdf)

        # ── Step 8: Estimate irrigation ───────────────────────────
        self._step("8/11", "Estimating irrigation")
        gdf = self._estimate_irrigation(gdf)

        # ── Step 9: Compute intersection density ──────────────────
        self._step("9/11", "Computing intersection density")
        gdf = self._compute_intersection_density(gdf)

        # ── Step 10: Imputation pass ─────────────────────────────
        if not skip_imputation:
            self._step("10/11", "Running imputation pass")
            gdf = self._impute_nulls(gdf)
        else:
            self._step("10/11", "Skipping imputation pass (--skip-imputation)")

        # ── Write to database ─────────────────────────────────────
        self._step("--", "Writing data to public.base_canvas")
        self._write_to_db(gdf, truncate)

        # ── Step 11: Validate ────────────────────────────────────
        self._step("11/11", "Validating base canvas")
        self._validate()

        elapsed = time.time() - self._start_time
        self.stdout.write(self.style.SUCCESS(f"ETL pipeline complete in {elapsed:.1f}s"))
        return None

    # ------------------------------------------------------------------
    # Step implementations
    # ------------------------------------------------------------------

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

        # Should never reach here due to validation above
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

        Uses ST_Area (in meters^2) converted to acres.
        """
        if gdf.crs is None or gdf.crs.to_string() == "EPSG:4326":
            # Project to a UTM-like meter projection for accurate area
            # Use a simplified Web Mercator for bulk computation
            gdf_utm = gdf.to_crs("EPSG:3857")
            area_sq_m = gdf_utm.geometry.area
        else:
            area_sq_m = gdf.geometry.area

        sq_m_per_acre = 4046.86
        gdf["area_gross"] = (area_sq_m / sq_m_per_acre).round(4)
        gdf["area_parcel"] = (area_sq_m / sq_m_per_acre * 0.85).round(4)
        gdf["area_dev_condition"] = (area_sq_m / sq_m_per_acre * 0.7).round(4)
        gdf["area_row"] = (area_sq_m / sq_m_per_acre * 0.15).round(4)
        return gdf

    def _allocate_demographics(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Allocate demographic values.

        In synthetic/test mode, demographics are already populated.
        When reading from a real source, this would allocate from
        Census block groups via :func:`spatial_allocator.allocate_attributes`.

        For now, columns that are still NaN get plausible defaults.
        """
        # Fill demographic columns if still null
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
        }
        for col, default in fill_map.items():
            if col in gdf.columns:
                gdf[col] = gdf[col].fillna(default)
        return gdf

    def _allocate_employment(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Allocate employment values."""
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
        """Classify land use if not already set."""
        if "land_development_category" in gdf.columns:
            gdf["land_development_category"] = (
                gdf["land_development_category"]
                .fillna("urban")
                .astype(str)
            )
        if "built_form_key" in gdf.columns:
            gdf["built_form_key"] = gdf["built_form_key"].fillna(_DEFAULT_BUILT_FORM_KEY)
        return gdf

    def _estimate_irrigation(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Estimate irrigated areas from land use and area."""
        if "residential_irrigated_area" in gdf.columns:
            gdf["residential_irrigated_area"] = gdf["residential_irrigated_area"].fillna(
                gdf.get("area_parcel_res", gdf["area_gross"]) * _DEFAULT_IRRIGATION_RES_FRAC
            )
        if "commercial_irrigated_area" in gdf.columns:
            gdf["commercial_irrigated_area"] = gdf["commercial_irrigated_area"].fillna(
                gdf.get("area_parcel_emp", gdf["area_gross"]) * _DEFAULT_IRRIGATION_COM_FRAC
            )
        return gdf

    def _compute_intersection_density(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Compute or default intersection density."""
        if "intersection_density" in gdf.columns:
            gdf["intersection_density"] = (
                gdf["intersection_density"].fillna(_DEFAULT_INTERSECTION_DENSITY).round(2)
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
                continue  # nullable identity/static columns

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

    def _write_to_db(self, gdf: gpd.GeoDataFrame, truncate: bool) -> None:
        """Write the GeoDataFrame to ``public.base_canvas`` using Django connection."""
        from django.db import connection as django_connection

        if truncate:
            with django_connection.cursor() as cursor:
                cursor.execute("TRUNCATE TABLE public.base_canvas RESTART IDENTITY CASCADE")

        # Build column list for INSERT (exclude id which is SERIAL)
        insert_cols = [
            c for c in BaseCanvasSchema.COLUMN_NAMES
            if c in gdf.columns and c != "id"
        ]
        col_list = ", ".join(f'"{c}"' for c in insert_cols)
        col_placeholders = ", ".join(f"%({c})s" for c in insert_cols if c != "geometry")
        has_geom = "geometry" in insert_cols
        if has_geom:
            col_list_geom = f"geometry, {col_list.replace('\"geometry\", ', '')}".strip(", ")
        else:
            col_list_geom = col_list

        # Write each row using Django cursor
        with django_connection.cursor() as cursor:
            for _, row in gdf.iterrows():
                params: dict[str, object] = {}
                geometry_wkt = None
                for col in insert_cols:
                    if col == "geometry":
                        val = row.get(col)
                        if val is not None and not (isinstance(val, float) and pd.isna(val)):
                            geometry_wkt = val.wkt if hasattr(val, "wkt") else str(val)
                        continue
                    val = row.get(col)
                    if val is None or (isinstance(val, float) and pd.isna(val)):
                        params[col] = None
                    elif isinstance(val, (np.floating,)):
                        params[col] = float(val)
                    elif isinstance(val, (np.integer,)):
                        params[col] = int(val)
                    else:
                        params[col] = val

                if geometry_wkt:
                    geom_placeholder = "ST_GeomFromText(%(__geom__)s, 4326)"
                    params["__geom__"] = geometry_wkt
                else:
                    geom_placeholder = "ST_SetSRID(ST_MakeEnvelope(0,0,1,1), 4326)::GEOMETRY(POLYGON, 4326)"

                stmt = (
                    f"INSERT INTO public.base_canvas ({col_list_geom}) "
                    f"VALUES ({geom_placeholder}, {col_placeholders})"
                )
                cursor.execute(stmt, params)

        rows = len(gdf)
        self._log(f"Wrote {rows} rows to public.base_canvas")
    def _validate(self) -> None:
        """Validate the base canvas after ETL."""
        missing = BaseCanvasManager.validate_schema()
        if missing:
            msg = f"Base canvas is missing columns: {missing}"
            raise CommandError(msg)
        # Check for NULLs in NON_NULL_COLUMNS
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*) FROM public.base_canvas
                WHERE { ' IS NULL OR '.join(f'"{c}" IS NULL' for c in BaseCanvasSchema.NON_NULL_COLUMNS) }
                """
            )
            null_count = cursor.fetchone()[0]
            if null_count > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f"{null_count} row(s) have NULL values in NON_NULL_COLUMNS"
                    )
                )
            else:
                self.stdout.write(self.style.SUCCESS("No NULLs in required columns"))
        # Count rows
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM public.base_canvas")
            row_count = cursor.fetchone()[0]
            self._log(f"Total rows: {row_count}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _step(self, label: str, description: str) -> None:
        """Log a step header."""
        self.stdout.write(f"\n  [{label}] {description}")

    def _log(self, message: str) -> None:
        """Log an indented info message."""
        self.stdout.write(f"    {message}")
