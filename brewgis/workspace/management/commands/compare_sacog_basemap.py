"""Compare brewgis base canvas vs SACOG v1 reference — per-column report with aggregate + correlation stats.

The pipeline now uses dbt models for the ETL and comparison stages,
with Soda validation checkpoints to catch data quality issues early.

**DEPRECATED**: Use the Dagster ``sacog_comparison`` job instead:

    dagster job run sacog_comparison

This management command is kept for backward compatibility. New development
should use the Dagster pipeline (``brewgis/workspace/dagster/jobs/comparison_jobs.py``).

"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text
from brewgis.workspace.services.sacog_demo_db import RestoreError
from brewgis.workspace.services.sacog_demo_db import restore_sacog_demo_db

CACHE_DIR = Path(settings.BASE_DIR) / "planning"
REPORT_PATH = CACHE_DIR / "sacog_comparison_report.md"
V1_BASE_CANVAS = "sac_cnty_region_base_canvas"
V1_PARCELS = "sac_cnty_region_existing_land_use_parcels"
logger = logging.getLogger(__name__)
STATE_FIPS = "06"
COUNTY_FIPS = "067"
# Vintage data years matching the SACOG v1 reference (2008-2012 era)
ACS_YEAR = 2013  # ACS 5-year 2009-2013 (earliest with block group API support)
LEHD_YEAR = 2008  # LODES 2008 (employment stats)
NLCD_YEAR = 2011  # NLCD 2011 (closest to 2008-2012)

LOCAL_SRID = 3310


class Command(BaseCommand):
    help = (
        "Create a brewgis base canvas for the SACOG/Sacramento region using the "
        "same parcel geometries as the v1 reference, then produce a comparison report."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--nlcd",
            action="store_true",
            default=False,
            help="Enable NLCD land cover classification and irrigation estimation",
        )
        parser.add_argument(
            "--osm",
            action="store_true",
            default=False,
            help="Enable OSM intersection density estimation",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limit parcel count for fast test runs (0 = all)",
        )
        parser.add_argument(
            "--force-data-fetch",
            action="store_true",
            default=False,
            help="Ignore cached data and re-download",
        )

    def handle(self, **options: Any) -> None:
        # Lazy imports — avoid loading dagster assets at module import time
        # which conflicts with test stubs for pandas/geopandas.
        from brewgis.soda import validate_base_canvas
        from brewgis.soda import validate_land_use_classification
        from brewgis.workspace.analysis.dbt_runner import run_dbt_local
        from brewgis.workspace.analysis.dbt_runner import run_dbt_seed
        from brewgis.workspace.dagster.assets.comparison_assets import REPORT_PATH
        from brewgis.workspace.dagster.assets.comparison_assets import (
            _convert_reference_totals,
        )
        from brewgis.workspace.dagster.assets.comparison_assets import (
            _generate_report_markdown,
        )
        from brewgis.workspace.dagster.assets.comparison_assets import _load_parcels
        from brewgis.workspace.dagster.assets.comparison_assets import (
            _query_table_as_dict,
        )
        from brewgis.workspace.dlt_pipelines.census import run_census_pipeline
        from brewgis.workspace.dlt_pipelines.lehd import run_lehd_pipeline
        from brewgis.workspace.dlt_pipelines.nlcd import run_nlcd_pipeline
        from brewgis.workspace.dlt_pipelines.osm import run_osm_pipeline
        from brewgis.workspace.dlt_pipelines.tiger_bg import run_tiger_bg_pipeline
        from brewgis.workspace.dlt_pipelines.tiger_block import run_tiger_block_pipeline
        from brewgis.workspace.services.census_fetcher import _populate_acs_block_group
        from brewgis.workspace.services.lehd_fetcher import _populate_wac_block

        nlcd = bool(options.get("nlcd", False))
        osm = bool(options.get("osm", False))
        limit = int(options.get("limit", 0))
        force_data_fetch = bool(options.get("force_data_fetch", False))

        # TODO check if base_canvas exists / migrations are up to date

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("  SACOG Base Canvas Comparison: BrewGIS vs v1 Reference")
        self.stdout.write("=" * 70)
        self.stdout.write(f"  NLCD: {'on' if nlcd else 'off'}")
        self.stdout.write(f"  OSM: {'on' if osm else 'off'}")
        self.stdout.write(f"  Parcel limit: {limit or 'all'}")
        self.stdout.write(
            f"  Force re-download: {'yes' if force_data_fetch else 'no (use cached data if available)'}"
        )
        if not settings.CENSUS_API_KEY:
            raise CommandError(
                "  WARNING: CENSUS_API_KEY is not set. Census ACS and CBP API calls will fail. "
                "Set CENSUS_API_KEY in your .env file. Get a free key at "
                "https://api.census.gov/data/key_signup.html"
            )

        # ── Pre-flight: Ensure SACOG v1 reference tables are loaded ────
        self.stdout.write("\n── Pre-flight: Checking SACOG reference tables ──")
        if not self._table_has_rows("public", V1_PARCELS):
            self.stdout.write(
                "  SACOG reference tables not found. Auto-restoring demo database..."
            )
            try:
                restore_sacog_demo_db(log=self.stdout)
            except RestoreError as e:
                raise CommandError(f"Failed to restore SACOG demo database: {e}") from e
            self.stdout.write(
                self.style.SUCCESS("  SACOG reference tables restored successfully")
            )
        else:
            self.stdout.write(
                "  SACOG reference tables already present, skipping restore"
            )

        # ── Phase 1: Load parcels into dbt source table ────────────────
        self.stdout.write("\n── Phase 1: Loading reference parcel geometries ──")
        parcels_gdf = _load_parcels(limit)
        self.stdout.write(f"  Loaded {len(parcels_gdf):,} parcels")

        # Normalize SACOG column names to dbt contract
        # SACOG source uses geography_id; dbt models expect parcel_id and id.
        parcels_gdf["parcel_id"] = parcels_gdf["geography_id"]
        parcels_gdf["id"] = parcels_gdf["geography_id"]
        self.stdout.write(
            f"  Normalized {len(parcels_gdf):,} rows: geography_id → parcel_id, id"
        )

        # Write to dbt source table (sacog_comparison_parcels)
        parcels_gdf.to_postgis(
            "sacog_comparison_parcels",
            get_engine(),
            schema="public",
            if_exists="replace",
            index=False,
            dtype={"geometry": f"geometry(MultiPolygon, {LOCAL_SRID})"},
        )

        self.stdout.write("  Written to public.sacog_comparison_parcels")

        # Populate TIGER/Line block group polygons (needed by ACS reader)
        self.stdout.write("\n── Populating TIGER/Line block group staging table ──")

        tiger_result = run_tiger_bg_pipeline(
            STATE_FIPS, vintages=["2013", "2023"], ignore_cache=force_data_fetch
        )
        if not tiger_result["success"]:
            raise CommandError(
                f"TIGER/Line BG fetch failed: {tiger_result.get('error')}."
            )
        self.stdout.write(
            f"  TIGER/Line BG loaded: {tiger_result.get('row_count', 0)} rows "
            f"in {tiger_result.get('table_name', '?')}"
        )

        # Populate TIGER/Line block polygons (needed by wac_block_raw)
        self.stdout.write("\n── Populating TIGER/Line block staging table ──")

        tiger_block_result = run_tiger_block_pipeline(
            STATE_FIPS, vintages=["2020"], ignore_cache=force_data_fetch
        )
        if not tiger_block_result["success"]:
            raise CommandError(
                f"TIGER/Line block fetch failed: {tiger_block_result.get('error')}."
        )
        self.stdout.write(
            f"  TIGER/Line blocks loaded: {tiger_block_result.get('row_count', 0)} rows "
            f"in {tiger_block_result.get('table_name', '?')}"
        )

        self.stdout.write("\n── Populating Census ACS staging table ──")

        census_result = run_census_pipeline(
            STATE_FIPS, COUNTY_FIPS, ACS_YEAR, ignore_cache=force_data_fetch
        )
        if not census_result["success"]:
            raise CommandError(
                f"Census ACS fetch failed: {census_result.get('error')}."
            )
        self.stdout.write(
            f"  Census ACS loaded: {census_result.get('row_count', 0)} rows "
            f"in {census_result.get('table_name', '?')}"
        )
        # Populate census.acs_block_group from ACS staging + TIGER BG geometry
        self.stdout.write("\n── Populating census.acs_block_group ──")

        acs_bg_count = _populate_acs_block_group(STATE_FIPS, COUNTY_FIPS, ACS_YEAR)
        self.stdout.write(f"  census.acs_block_group populated: {acs_bg_count:,} rows")
        # Populate LEHD staging table before ETL
        self.stdout.write("\n── Populating LEHD LODES staging table ──")

        lehd_result = run_lehd_pipeline(
            STATE_FIPS, COUNTY_FIPS, LEHD_YEAR, ignore_cache=force_data_fetch
        )
        if not lehd_result["success"]:
            raise CommandError(f"LEHD LODES fetch failed: {lehd_result.get('error')}.")
        self.stdout.write(
            f"  LEHD LODES loaded: {lehd_result.get('row_count', 0)} rows "
            f"in {lehd_result.get('table_name', '?')}"
        )
        # Populate lehd.wac_block from LEHD staging + TIGER BG geometry
        self.stdout.write("\n── Populating lehd.wac_block ──")

        lehd_wac_count = _populate_wac_block(STATE_FIPS, COUNTY_FIPS, LEHD_YEAR)
        self.stdout.write(f"  lehd.wac_block populated: {lehd_wac_count:,} rows")
        # ── Phase 1.5: Run NLCD pipeline (optional) ──────────────────────
        nlcd_table = ""
        if nlcd:
            self.stdout.write("\n── Phase 1.5a: Computing NLCD zonal stats ──")

            nlcd_result = run_nlcd_pipeline(
                parcel_table="sacog_comparison_parcels",
                year=NLCD_YEAR,
                ignore_cache=force_data_fetch,
            )
            if not nlcd_result.get("success"):
                raise CommandError(
                    f"NLCD zonal stats failed: {nlcd_result.get('error')}. "
                    "Use --no-nlcd to skip."
                )
            nlcd_table = nlcd_result.get("table_name", "public.nlcd_parcel_stats")
            self.stdout.write(
                f"  NLCD stats loaded: {nlcd_result.get('row_count', 0)} rows "
                f"in {nlcd_table}"
            )

        # ── Phase 1.5b: Run OSM pipeline (optional) ──────────────────────
        osm_table = ""
        if osm:
            self.stdout.write("\n── Phase 1.5b: Computing OSM intersection density ──")

            osm_result = run_osm_pipeline(
                parcel_table="sacog_comparison_parcels",
            )
            if not osm_result.get("success"):
                raise CommandError(
                    f"OSM intersection density failed: {osm_result.get('error')}. "
                    "Use --no-osm to skip."
                )
            osm_table = osm_result.get("table_name", "public.osm_intersection_density")
            self.stdout.write(
                f"  OSM intersection density loaded: {osm_result.get('row_count', 0)} rows "
                f"in {osm_table}"
            )

        # ── Phase 2a: Materialize SACOG parcel shim ────────────────────
        self.stdout.write("\n── Phase 2a: Materializing SACOG parcel shim ──")
        shim_vars: dict[str, Any] = {
            "base_canvas_materialized": "table",
            "projected_srid": LOCAL_SRID,
        }
        shim_result = run_dbt_local(
            select=["sacog_parcel_shim"],
            vars_=shim_vars,
        )
        if not shim_result.success:
            raise CommandError(f"dbt sacog_parcel_shim run failed: {shim_result.error}")
        self.stdout.write(self.style.SUCCESS("  sacog_parcel_shim materialized"))

        # ── Pre-flight: Ensure dbt seed tables are loaded ──────────────
        self.stdout.write("\n── Pre-flight: Checking dbt seed tables ──")
        if not self._table_has_rows("public", "calibration_parameters"):
            self.stdout.write("  dbt seed tables not found. Running dbt seed...")
            seed_result = run_dbt_seed()
            if not seed_result.success:
                raise CommandError(f"dbt seed failed: {seed_result.error}")
            self.stdout.write(
                self.style.SUCCESS("  dbt seed tables loaded successfully")
            )
        else:
            self.stdout.write("  dbt seed tables already present, skipping dbt seed")

        # ── Phase 2b: Run dbt base_canvas models ────────────────────────
        self.stdout.write("\n── Phase 2b: Running dbt base_canvas models ──")
        dbt_vars: dict[str, Any] = {
            "parcel_table": "sacog_parcel_shim",
            "base_canvas_materialized": "table",
            "projected_srid": LOCAL_SRID,
        }
        if nlcd_table:
            dbt_vars["nlcd_parcel_table"] = nlcd_table
        if osm_table:
            dbt_vars["osm_intersection_table"] = osm_table
        result = run_dbt_local(
            select=[
                "base_canvas_geometry",
                "base_canvas_demographics",
                "base_canvas_employment",
                "base_canvas_attributes",
                "base_canvas_imputed",
                "base_canvas_reconciled",
            ],
            vars_=dbt_vars,
        )
        if not result.success:
            raise CommandError(f"dbt base_canvas run failed: {result.error}")
        self.stdout.write(self.style.SUCCESS("  dbt base_canvas models complete"))

        # ── Phase 2.5: Validate land use classification ────────────────
        self.stdout.write("\n── Phase 2.5: Validating land use classification ──")
        soda_result = validate_land_use_classification(
            schema="public", table="base_canvas_attributes"
        )
        if not soda_result.get("success", False):
            self.stdout.write(
                self.style.WARNING("  Land use classification validation issues found")
            )
        else:
            self.stdout.write("  Land use classification validated ✓")

        # ── Phase 3: Run dbt comparison models ─────────────────────────
        self.stdout.write("\n── Phase 3: Running dbt comparison models ──")
        result = run_dbt_local(select=["comparison.*"], vars_=dbt_vars)
        if not result.success:
            raise CommandError(f"dbt comparison run failed: {result.error}")
        self.stdout.write(self.style.SUCCESS("  dbt comparison models complete"))

        # ── Phase 3.5: Validate base canvas ────────────────────────────
        self.stdout.write("\n── Phase 3.5: Validating base canvas ──")
        soda_result = validate_base_canvas(
            schema="public", table="base_canvas_reconciled"
        )
        if not soda_result.get("success", False):
            self.stdout.write(
                self.style.WARNING("  Base canvas validation issues found")
            )
        else:
            self.stdout.write("  Base canvas validated ✓")

        # ── Phase 4: Read results from dbt-materialized tables ─────────
        self.stdout.write("\n── Phase 4: Reading comparison data from dbt ──")
        summary = _query_table_as_dict("sacog_summary")

        # Split summary columns by prefix
        ref_totals = {k[4:]: v for k, v in summary.items() if k.startswith("ref_")}
        brew_totals = {k[5:]: v for k, v in summary.items() if k.startswith("brew_")}
        correlations = {k[5:]: v for k, v in summary.items() if k.startswith("corr_")}
        weighted_means = {k: v for k, v in summary.items() if k.endswith("_wavg")}

        _convert_reference_totals(ref_totals)

        if ref_totals:
            self._print_totals(ref_totals, "Reference v1")
        if brew_totals:
            self._print_totals(brew_totals, "BrewGIS")

        # ── Phase 5: Generate comparison report ────────────────────────
        self.stdout.write("\n── Phase 5: Generating comparison report ──")
        _generate_report_markdown(
            ref_totals,
            brew_totals,
            correlations=correlations,
            weighted_means=weighted_means,
            output_path=REPORT_PATH,
            quick=not (nlcd or osm),
            limit=limit,
        )

        self.stdout.write(self.style.SUCCESS(f"\n✓ Report written to {REPORT_PATH}"))
        self.stdout.write(
            self.style.SUCCESS(
                "  Done — open planning/sacog_comparison_report.md to review"
            )
        )

    # ═══════════════════════════════════════════════════════════════════
    # Internal helpers
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def _table_has_rows(schema: str, table: str) -> bool:
        """Check if a table exists and has at least one row."""
        engine = get_engine()
        with engine.connect() as conn:
            count = conn.execute(
                text(
                    f"SELECT EXISTS ( SELECT 1 FROM information_schema.tables WHERE table_schema = '{schema}' AND table_name = '{table}')"
                )
            ).scalar()
            if count == 0:
                return False
            count = conn.execute(
                text(f"SELECT COUNT(*) FROM {schema}.{table}")  # noqa: S608 — schema/table are hardcoded literals
            ).scalar()
            return bool(count) and count > 0

    def _print_totals(self, totals: dict[str, float], label: str) -> None:
        """Print key aggregate totals."""
        col_map = {
            "acres_gross": ("area_gross", "acres_gross"),
            "acres_parcel": ("area_parcel", "acres_parcel"),
            "pop": ("pop", "pop"),
            "hh": ("hh", "hh"),
            "du": ("du", "du"),
            "emp": ("emp", "emp"),
        }

        self.stdout.write(f"  *** {label} ***")
        for label_name, (v3_col, v1_col) in col_map.items():
            val = totals.get(v3_col) or totals.get(v1_col)
            if val is not None:
                self.stdout.write(f"    {label_name:25s} {val:>14,.0f}")

    def _generate_report(
        self,
        ref: dict[str, float],
        brew: dict[str, float],
        etl_result: dict,
        quick: bool,
        limit: int,
        correlations: dict[str, float] | None = None,
        weighted_means: dict[str, float] | None = None,
    ):
        """Generate the markdown comparison report (thin wrapper for backward compat).

        Legacy method expected by test suite. Delegates to
        ``_generate_report_markdown``.
        """
        # Lazy imports — avoid loading dagster assets at module import time
        import brewgis.workspace.management.commands.compare_sacog_basemap as _cmd_mod
        from brewgis.workspace.dagster.assets.comparison_assets import (
            _generate_report_markdown,
        )

        report_path = _cmd_mod.REPORT_PATH

        _generate_report_markdown(
            ref,
            brew,
            correlations=correlations or {},
            weighted_means=weighted_means or {},
            output_path=report_path,
            quick=quick,
            limit=limit,
        )
