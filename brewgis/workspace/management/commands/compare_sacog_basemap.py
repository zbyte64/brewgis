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

CACHE_DIR = Path(settings.BASE_DIR) / "planning"
REPORT_PATH = CACHE_DIR / "sacog_comparison_report.md"
V1_BASE_CANVAS = "sac_cnty_region_base_canvas"
V1_PARCELS = "sac_cnty_region_existing_land_use_parcels"
logger = logging.getLogger(__name__)
STATE_FIPS = "06"
COUNTY_FIPS = "067"


class Command(BaseCommand):
    help = (
        "Create a brewgis base canvas for the SACOG/Sacramento region using the "
        "same parcel geometries as the v1 reference, then produce a comparison report."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--quick",
            action="store_true",
            default=False,
            help="Skip NLCD/OSM (use default null sources); only Census + LEHD for demographics",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limit parcel count for fast test runs (0 = all)",
        )
        parser.add_argument(
            "--skip-census",
            action="store_true",
            default=False,
            help="Skip Census ACS demographic fetching",
        )
        parser.add_argument(
            "--skip-lehd",
            action="store_true",
            default=False,
            help="Skip LEHD employment fetching",
        )
        parser.add_argument(
            "--skip-data-fetch",
            action="store_true",
            default=False,
            help="Skip all data fetching (Census ACS + LEHD)",
        )
        parser.add_argument(
            "--truncate",
            action="store_true",
            default=False,
            help="Ignored in dbt mode — kept for backward compatibility",
        )

    def handle(self, **options: Any) -> None:
        # Lazy imports — avoid loading dagster assets at module import time
        # which conflicts with test stubs for pandas/geopandas.
        from brewgis.soda import validate_base_canvas
        from brewgis.soda import validate_land_use_classification
        from brewgis.workspace.analysis.dbt_runner import run_dbt_local
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
        from brewgis.workspace.services._db import get_engine

        quick = bool(options.get("quick", False))
        limit = int(options.get("limit", 0))
        skip_data_fetch = bool(options.get("skip_data_fetch", False))
        skip_census = skip_data_fetch or bool(options.get("skip_census", False))
        skip_lehd = skip_data_fetch or bool(options.get("skip_lehd", False))

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("  SACOG Base Canvas Comparison: BrewGIS vs v1 Reference")
        self.stdout.write("=" * 70)
        self.stdout.write(f"  Quick mode: {quick}")
        self.stdout.write(f"  Parcel limit: {limit or 'all'}")
        self.stdout.write(f"  Census: {'skip' if skip_census else 'on'}")
        self.stdout.write(f"  LEHD: {'skip' if skip_lehd else 'on'}")
        if not settings.CENSUS_API_KEY:
            self.stdout.write(
                self.style.WARNING(
                    "  WARNING: CENSUS_API_KEY is not set. Census ACS and CBP API calls will fail. "
                    "Set CENSUS_API_KEY in your .env file. Get a free key at "
                    "https://api.census.gov/data/key_signup.html"
                )
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
            dtype={"geometry": "geometry(MultiPolygon, 4326)"},
        )

        self.stdout.write("  Written to public.sacog_comparison_parcels")

        # Populate TIGER/Line block group polygons (needed by ACS reader)
        if not skip_census:
            self.stdout.write("\n── Populating TIGER/Line block group staging table ──")
            from brewgis.workspace.dlt_pipelines.tiger_bg import run_tiger_bg_pipeline

            tiger_result = run_tiger_bg_pipeline(STATE_FIPS)
            if not tiger_result["success"]:
                raise CommandError(
                    f"TIGER/Line BG fetch failed: {tiger_result.get('error')}. "
                    "Use --skip-census or --skip-data-fetch to skip."
                )
            self.stdout.write(
                f"  TIGER/Line BG loaded: {tiger_result.get('row_count', 0)} rows "
                f"in {tiger_result.get('table_name', '?')}"
            )
        # Populate ACS staging table before ETL
        if not skip_census:
            self.stdout.write("\n── Populating Census ACS staging table ──")
            from brewgis.workspace.dlt_pipelines.census import run_census_pipeline

            census_result = run_census_pipeline(STATE_FIPS, COUNTY_FIPS, 2022)
            if not census_result["success"]:
                raise CommandError(
                    f"Census ACS fetch failed: {census_result.get('error')}. "
                    "Use --skip-census or --skip-data-fetch to skip."
                )
            self.stdout.write(
                f"  Census ACS loaded: {census_result.get('row_count', 0)} rows "
                f"in {census_result.get('table_name', '?')}"
            )
            # Populate census.acs_block_group from ACS staging + TIGER BG geometry
            self.stdout.write("\n── Populating census.acs_block_group ──")
            from brewgis.workspace.services.census_fetcher import (
                _populate_acs_block_group,
            )

            acs_bg_count = _populate_acs_block_group(STATE_FIPS, COUNTY_FIPS, 2022)
            self.stdout.write(
                f"  census.acs_block_group populated: {acs_bg_count:,} rows"
            )

        # Populate LEHD staging table before ETL
        if not skip_lehd:
            self.stdout.write("\n── Populating LEHD LODES staging table ──")
            from brewgis.workspace.dlt_pipelines.lehd import run_lehd_pipeline

            lehd_result = run_lehd_pipeline(STATE_FIPS, COUNTY_FIPS, 2021)
            if not lehd_result["success"]:
                raise CommandError(
                    f"LEHD LODES fetch failed: {lehd_result.get('error')}. "
                    "Use --skip-lehd or --skip-data-fetch to skip."
                )
            self.stdout.write(
                f"  LEHD LODES loaded: {lehd_result.get('row_count', 0)} rows "
                f"in {lehd_result.get('table_name', '?')}"
            )
            # Populate lehd.wac_block from LEHD staging + TIGER BG geometry
            self.stdout.write("\n── Populating lehd.wac_block ──")
            from brewgis.workspace.services.lehd_fetcher import _populate_wac_block

            lehd_wac_count = _populate_wac_block(STATE_FIPS, COUNTY_FIPS, 2021)
            self.stdout.write(f"  lehd.wac_block populated: {lehd_wac_count:,} rows")

        # ── Phase 2a: Materialize SACOG parcel shim ────────────────────
        self.stdout.write("\n── Phase 2a: Materializing SACOG parcel shim ──")
        shim_vars: dict[str, Any] = {
            "base_canvas_materialized": "table",
        }
        shim_result = run_dbt_local(
            select=["sacog_parcel_shim"],
            vars_=shim_vars,
        )
        if not shim_result.success:
            raise CommandError(f"dbt sacog_parcel_shim run failed: {shim_result.error}")
        self.stdout.write(self.style.SUCCESS("  sacog_parcel_shim materialized"))

        # ── Phase 2b: Run dbt base_canvas models ────────────────────────
        self.stdout.write("\n── Phase 2b: Running dbt base_canvas models ──")
        dbt_vars: dict[str, Any] = {
            "parcel_table": "sacog_parcel_shim",
            "base_canvas_materialized": "table",
            "projected_srid": 6933,
        }
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
            quick=quick,
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
