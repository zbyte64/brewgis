"""Set up the Fresno Demo workspace end-to-end using the current SQLMesh pipeline.

Uses the same methodology as compare_sacog_basemap: dlt data ingestion + SQLMesh
models for ETL + Dagster for analysis.  Fresno parcels lack assessor data, so
all assessor-derived columns are NULL / 0; regressor predictions come from
SACOG-trained LightGBM models applied via inference-only Python SQLMesh models.

Usage:
    python manage.py setup_fresno_workspace
    python manage.py setup_fresno_workspace --overture --nlcd --osm
    python manage.py setup_fresno_workspace --skip-download
    python manage.py setup_fresno_workspace --force-data-fetch --force-data-reload
"""

from __future__ import annotations

import contextlib
import json
import logging
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import geopandas as gpd
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser
from django.db import connection
from django.utils import timezone
from sqlalchemy import text

from brewgis.workspace.analysis.data_export import export_building_types
from brewgis.workspace.analysis.pipeline import run_modules_sync
from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan
from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import Layer
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace
from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services.poi_fetcher import fetch_pois
from brewgis.workspace.symbology.auto import auto_generate_symbology

# ═══════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════

logger = logging.getLogger(__name__)

WORKSPACE_NAME = "Fresno Demo"
WORKSPACE_SCHEMA = "fresno_demo"

# State FIPS / County FIPS for Fresno County, CA
STATE_FIPS = "06"
COUNTY_FIPS = "019"

# CA Teale Albers (projected SRID for area computations)
LOCAL_SRID = 3310

# Fresno-Clovis urban area bounding box
BBOX = (-119.95, 36.60, -119.55, 36.90)
MIN_LNG, MIN_LAT, MAX_LNG, MAX_LAT = BBOX

# Base scenario config
BASE_YEAR = 2022
LEHD_YEAR = 2021  # LEHD LODES lags 1-2 years behind ACS
HORIZON_YEAR = 2050

# Pipeline vars — used by the analysis pipeline (not base canvas SQLMesh)
PIPELINE_VARS: dict[str, Any] = {
    "source_schema": WORKSPACE_SCHEMA,
    "base_table_schema": WORKSPACE_SCHEMA,
    "base_table_name": "base_canvas_reconciled",
    "parcel_table": "parcels",
    "base_canvas_table": "base_canvas_reconciled",
    "scenario_slug": "fresno_baseline",
    "constraints": [
        {"table": "floodplains", "discount_pct": 100, "geom_col": "geom"},
        {"table": "wetlands", "discount_pct": 100, "geom_col": "geom"},
        {"table": "steep_slopes", "discount_pct": 75, "geom_col": "geom"},
        {"table": "farmland", "discount_pct": 50, "geom_col": "geom"},
    ],
    "target_schema": None,
    "scenario_id": None,
    "built_forms_schema": WORKSPACE_SCHEMA,
    "built_forms_table": "built_forms",
    "base_year": BASE_YEAR,
    "horizon_year": HORIZON_YEAR,
}

CACHE_DIR = Path(settings.BASE_DIR) / "planning" / "fresno_demo"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

FIXTURE_PATH = (
    Path(settings.BASE_DIR)
    / "brewgis"
    / "workspace"
    / "built_forms"
    / "fixtures"
    / "default_library.json"
)

POI_CATEGORIES: list[str] = [
    "schools",
    "hospitals",
    "parks",
    "retail",
    "restaurants",
    "transit",
    "public_facilities",
    "places_of_worship",
]


class Command(BaseCommand):
    help = "Set up the Fresno Demo workspace end-to-end using SQLMesh pipeline."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--skip-download",
            action="store_true",
            help="Skip data downloads; use cached files only.",
        )
        parser.add_argument(
            "--nlcd",
            action="store_true",
            default=False,
            help="Enable NLCD land cover + NLCD Tree Canopy (zonal stats per parcel).",
        )
        parser.add_argument(
            "--osm",
            action="store_true",
            default=False,
            help="Enable OSM intersection density computation.",
        )
        parser.add_argument(
            "--overture",
            action="store_true",
            default=True,
            dest="overture",
            help="Enable Overture buildings/transport, ResNet features, and regressors.",
        )
        parser.add_argument(
            "--no-overture",
            action="store_false",
            dest="overture",
            help="Disable Overture buildings/transport, ResNet features, and regressors.",
        )
        parser.add_argument(
            "--force-data-fetch",
            action="store_true",
            default=False,
            help="Re-download all data even if cached.",
        )
        parser.add_argument(
            "--force-data-reload",
            action="store_true",
            default=False,
            help="Re-run all SQLMesh models even if unchanged.",
        )
        parser.add_argument(
            "--cbp-employment",
            type=str,
            default="",
            help="JSON string or file path for CBP county employment overrides. "
            "E.g. '{\"cbp_county_emp_agriculture\": 5000}'. "
            "Defaults to 0 for all sectors (uses LEHD allocation without CBP control totals).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be done without doing it.",
        )

    def handle(self, **options: Any) -> None:
        self.dry_run = bool(options.get("dry_run", False))
        overture = bool(options.get("overture", True))
        nlcd = bool(options.get("nlcd", False))
        osm = bool(options.get("osm", False))
        force_data_fetch = bool(options.get("force_data_fetch", False))
        force_data_reload = bool(options.get("force_data_reload", False))
        cbp_employment_str = str(options.get("cbp_employment", "") or "")

        # Parse CBP employment overrides
        cbp_vars: dict[str, object] = {}
        if cbp_employment_str:
            cbp_path = Path(cbp_employment_str)
            if cbp_path.exists():
                with cbp_path.open() as f:
                    cbp_vars = json.load(f)
            else:
                cbp_vars = json.loads(cbp_employment_str)

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("  Fresno Demo Workspace Setup")
        self.stdout.write("=" * 70)
        self.stdout.write(f"  Overture: {'on' if overture else 'off'}")
        self.stdout.write(f"  NLCD: {'on' if nlcd else 'off'}")
        self.stdout.write(f"  OSM: {'on' if osm else 'off'}")
        self.stdout.write(
            f"  Force re-download: {'yes' if force_data_fetch else 'no (use cached data if available)'}"
        )
        self.stdout.write(
            f"  Force data reload: {'yes' if force_data_reload else 'no (use cached data if available)'}"
        )

        # ── Pre-flight: Ensure migrations are up to date ─────────────
        self.stdout.write("\n── Pre-flight: Checking migrations ──")
        call_command("migrate", "--run-syncdb", verbosity=0)
        self.stdout.write("  Migrations up to date")

        if not settings.CENSUS_API_KEY:
            raise CommandError(
                "  WARNING: CENSUS_API_KEY is not set. Census ACS and CBP API calls will fail. "
                "Set CENSUS_API_KEY in your .env file. Get a free key at "
                "https://api.census.gov/data/key_signup.html"
            )

        # ── Step 1: Download data ──────────────────────────────────────
        if not options.get("skip_download"):
            self._run_step("Download data", self._download_data, options)
        else:
            self.stdout.write("  [SKIP] Download data")

        # ── Step 2: Create workspace + load built form fixtures ────────
        workspace = self._run_step("Create workspace", self._create_workspace)

        # ── Step 3: Ingest parcels (GeoJSON → fresno_demo.fresno_parcels) ──
        self._run_step("Ingest parcels", self._ingest_parcels)

        # ── Step 4: Populate TIGER/Line BG staging ──────────────────────
        self._run_step(
            "Populate TIGER/Line block group staging",
            self._populate_tiger_bg,
            force_data_fetch,
            force_data_reload,
        )

        # ── Step 5: Populate TIGER/Line block staging ───────────────────
        self._run_step(
            "Populate TIGER/Line block staging",
            self._populate_tiger_blocks,
            force_data_fetch,
            force_data_reload,
        )

        # ── Step 6: Populate Census ACS staging + acs_block_group ───────
        self._run_step(
            "Census ACS data (dlt → acs_block_group)",
            self._populate_census,
            force_data_fetch,
            force_data_reload,
        )

        # ── Step 7: Populate Census 2020 block staging ──────────────────
        self._run_step(
            "Census 2020 block data",
            self._populate_census_2020,
            force_data_fetch,
            force_data_reload,
        )

        # ── Step 8: Populate Census PDB ────────────────────────────────
        self._run_step(
            "Census PDB data",
            self._populate_pdb,
            force_data_fetch,
            force_data_reload,
        )

        # ── Step 9: Populate LEHD staging + wac_block ──────────────────
        self._run_step(
            "LEHD employment data (dlt → wac_block)",
            self._populate_lehd,
            force_data_fetch,
            force_data_reload,
        )

        # ── Step 10: NLCD + tree canopy (opt-in) ───────────────────────
        if nlcd:
            self._run_step(
                "NLCD land cover + tree canopy",
                self._populate_nlcd,
                force_data_fetch,
                force_data_reload,
            )
        else:
            self.stdout.write("  [SKIP] NLCD (not enabled)")

        # ── Step 11: OSM intersection density (opt-in) ────────────────
        if osm:
            self._run_step(
                "OSM intersection density",
                self._populate_osm,
                force_data_fetch,
                force_data_reload,
            )
        else:
            self.stdout.write("  [SKIP] OSM (not enabled)")

        # ── Step 12: Consolidated SQLMesh plan ─────────────────────────
        self._run_step(
            "SQLMesh plan (models + ResNet + regressors)",
            self._run_sqlmesh_plan,
            overture,
            nlcd,
            osm,
            force_data_reload,
            cbp_vars,
        )

        # ── Step 13: Create analysis compat view ───────────────────────
        self._run_step(
            "Create analysis compat view",
            self._create_analysis_view,
        )

        # ── Step 14: Import POIs (skipped — pre-existing requests import bug)
        self.stdout.write(
            "  [SKIP] Import POIs (pre-existing import bug in poi pipeline)"
        )

        # ── Step 15: Ingest constraint layers ──────────────────────────
        self._run_step("Ingest constraint layers", self._ingest_constraints)

        # ── Step 16: Export building types ─────────────────────────────
        self._run_step("Export building types", self._export_built_forms)

        # ── Step 17: Create base scenario ──────────────────────────────
        self._run_step("Create base scenario", self._create_base_scenario)

        # ── Step 18: Run analysis pipeline ─────────────────────────────
        self._run_step("Run analysis pipeline", self._run_analysis)

        self.stdout.write(self.style.SUCCESS("\nFresno demo workspace setup complete!"))

    # -- helpers ----------------------------------------------------------

    def _run_step(self, label: str, fn: Any, *args: Any) -> Any:
        self.stdout.write(f"\n{'─' * 60}")
        self.stdout.write(f"Step: {label}")
        self.stdout.write(f"{'─' * 60}")
        if self.dry_run:
            self.stdout.write(f"  [DRY RUN] Would execute: {fn.__name__}")
            return None
        try:
            result = fn(*args)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"  [FAIL] {label}: {exc}"))
            raise
        else:
            self.stdout.write(f"  [{self.style.SUCCESS('OK')}] {label}")
            return result

    def _get_workspace(self) -> Workspace:
        workspace, _ = Workspace.objects.get_or_create(
            name=WORKSPACE_NAME,
            defaults={"db_schema": WORKSPACE_SCHEMA},
        )
        return workspace

    @staticmethod
    def _create_db_schema(schema: str) -> None:
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    @staticmethod
    def _table_exists(schema: str, table: str) -> bool:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = %s AND table_name = %s)",
                [schema, table],
            )
            return cursor.fetchone()[0]  # type: ignore[no-any-return]

    @staticmethod
    def _table_has_rows(schema: str, table: str) -> bool:
        """Check if a table exists and has at least one row."""
        engine = get_engine()
        with engine.connect() as conn:
            count = conn.execute(
                text(
                    f"SELECT EXISTS ( SELECT 1 FROM information_schema.tables "
                    f"WHERE table_schema = '{schema}' AND table_name = '{table}')"
                )
            ).scalar()
            if not count:
                return False
            count = conn.execute(
                text(f"SELECT COUNT(*) FROM {schema}.{table}")
            ).scalar()
            return bool(count) and count > 0

    def _read_geojson(self, filename: str) -> gpd.GeoDataFrame:
        filepath = CACHE_DIR / filename
        if not filepath.exists():
            self.stdout.write(f"  Cache miss: {filepath}. Run download step first.")
            sys.exit(1)
        self.stdout.write(f"  Reading {filepath}...")
        df: gpd.GeoDataFrame = gpd.read_file(str(filepath))
        self.stdout.write(f"  Loaded {len(df)} features")
        return df

    def _write_to_postgis(self, df: gpd.GeoDataFrame, table: str, schema: str) -> None:
        if df.geometry.name != "geom":
            df = df.rename_geometry("geom")
        if "geometry" in df.columns and "geom" in df.columns:
            df = df.drop(columns=["geometry"])
        df.columns = [c.lower() for c in df.columns]
        engine = get_engine()
        df.to_postgis(
            table, engine, schema=schema, if_exists="replace", chunksize=50000
        )

    def _register_layer(
        self,
        key: str,
        name: str,
        workspace: Workspace,
        geometry_type: str = "fill",
        layer_source: str = "Fresno Demo",
    ) -> Layer:
        layer, created = Layer.objects.get_or_create(
            key=key,
            workspace=workspace,
            defaults={
                "name": name,
                "db_table": key,
                "geometry_type": geometry_type,
                "layer_source": layer_source,
            },
        )
        if created:
            with contextlib.suppress(Exception):
                auto_generate_symbology(layer)
        return layer

    # -- Step implementations --------------------------------------------

    def _download_data(self, options: Any) -> None:
        args = []
        if options.get("force_data_fetch") or options.get("force_data_reload"):
            args.append("--force")
        call_command("download_fresno_demo", *args)

    def _create_workspace(self) -> Workspace:
        self._create_db_schema(WORKSPACE_SCHEMA)
        workspace = self._get_workspace()
        self.stdout.write(
            f"  Workspace: {workspace.name} (schema: {workspace.db_schema})"
        )

        if BuildingType.objects.count() == 0 and FIXTURE_PATH.exists():
            call_command("loaddata", str(FIXTURE_PATH))
            self.stdout.write(
                f"  Loaded built form fixture: {BuildingType.objects.count()} BuildingTypes"
            )
        else:
            self.stdout.write(
                f"  Built forms already loaded ({BuildingType.objects.count()} BuildingTypes)"
            )

        return workspace

    def _ingest_parcels(self) -> int:
        """Ingest parcels from GeoJSON directly to fresno_demo.fresno_parcels.

        The fresno_parcel_shim SQLMesh model reads from this table and maps
        columns to the standard parcel contract.
        """
        workspace = self._get_workspace()
        df = self._read_geojson("fresno_parcels.geojson")

        # Normalize parcel ID column
        if "parcel_id" not in df.columns:
            if "apn" in df.columns:
                df["parcel_id"] = df["apn"]
            elif "geography_id" in df.columns:
                df["parcel_id"] = df["geography_id"]
            else:
                df["parcel_id"] = df.index.astype(str)

        self.stdout.write(
            f"  Normalized parcel_id column ({df['parcel_id'].nunique()} unique)"
        )

        # Write directly to the target table
        engine = get_engine()
        df.to_postgis(
            "fresno_parcels",
            engine,
            schema=WORKSPACE_SCHEMA,
            if_exists="replace",
            chunksize=50000,
        )

        count = len(df)
        self.stdout.write(
            f"  Wrote {count} parcels to {WORKSPACE_SCHEMA}.fresno_parcels"
        )

        # Register layer
        self._register_layer(
            "fresno_parcels", "Fresno County Parcels", workspace, "fill"
        )

        return count

    def _ingest_city_boundary(self) -> int:
        filepath = CACHE_DIR / "fresno_city_boundary.geojson"
        if not filepath.exists():
            self.stdout.write("  [SKIP] City boundary not cached; skipping")
            return 0
        workspace = self._get_workspace()
        df = gpd.read_file(str(filepath))
        self._write_to_postgis(df, "fresno_city_boundary", WORKSPACE_SCHEMA)
        self._register_layer(
            "fresno_city_boundary",
            "Fresno City Boundary",
            workspace,
            "fill",
        )
        count = len(df)
        self.stdout.write(f"  Ingested city boundary ({count} features)")
        return count

    # -- Data loading helpers ---------------------------------------------

    def _populate_tiger_bg(
        self,
        force_data_fetch: bool,
        force_data_reload: bool,  # noqa: ARG002
    ) -> None:
        from brewgis.workspace.dlt_pipelines.tiger_bg import run_tiger_bg_pipeline

        if not (
            force_data_fetch or not self._table_has_rows("public", "tiger_block_groups")
        ):
            self.stdout.write("  TIGER/Line BG already loaded, skipping")
            return

        tiger_result = run_tiger_bg_pipeline(
            STATE_FIPS, vintages=["2023"], ignore_cache=force_data_fetch
        )
        self.stdout.write(
            f"  TIGER/Line BG loaded: {tiger_result.get('row_count', 0)} rows "
            f"in {tiger_result.get('table_name', '?')}"
        )

    def _populate_tiger_blocks(
        self,
        force_data_fetch: bool,
        force_data_reload: bool,  # noqa: ARG002
    ) -> None:
        from brewgis.workspace.dlt_pipelines.tiger_block import run_tiger_block_pipeline

        if not (force_data_fetch or not self._table_has_rows("public", "tiger_blocks")):
            self.stdout.write("  TIGER/Line blocks already loaded, skipping")
            return

        tiger_block_result = run_tiger_block_pipeline(
            STATE_FIPS, vintages=["2020"], ignore_cache=force_data_fetch
        )
        self.stdout.write(
            f"  TIGER/Line blocks loaded: {tiger_block_result.get('row_count', 0)} rows "
            f"in {tiger_block_result.get('table_name', '?')}"
        )

    def _populate_census(
        self,
        force_data_fetch: bool,
        force_data_reload: bool,  # noqa: ARG002
    ) -> None:
        from brewgis.workspace.dlt_pipelines.census import run_census_pipeline
        from brewgis.workspace.services.census_fetcher import _populate_acs_block_group

        # Census ACS raw data — hard fail on fetch error
        if force_data_fetch or not self._table_has_rows("public", "acs_raw"):
            census_result = run_census_pipeline(
                STATE_FIPS, [COUNTY_FIPS], BASE_YEAR, ignore_cache=force_data_fetch
            )
            self.stdout.write(
                f"  Census ACS loaded: {census_result.get('row_count', 0)} rows"
            )
        else:
            self.stdout.write("  ACS raw already loaded, skipping")

        # Materialize acs_block_group via SQLMesh — hard fail on error
        if force_data_fetch or not self._table_has_rows(
            "staging__brewgis_prod", "acs_block_group"
        ):
            acs_bg_count = _populate_acs_block_group(
                STATE_FIPS, [COUNTY_FIPS], BASE_YEAR
            )
            self.stdout.write(f"  ACS block group populated: {acs_bg_count:,} rows")
        else:
            self.stdout.write("  ACS block group already populated, skipping")

    def _populate_census_2020(
        self,
        force_data_fetch: bool,
        force_data_reload: bool,  # noqa: ARG002
    ) -> None:
        from brewgis.workspace.dlt_pipelines.census_2020 import run_census_2020_pipeline

        if not (
            force_data_fetch
            or not self._table_has_rows("public", "census_2020_block_raw")
        ):
            self.stdout.write("  Census 2020 blocks already loaded, skipping")
            return

        result = run_census_2020_pipeline(
            STATE_FIPS, [COUNTY_FIPS], ignore_cache=force_data_fetch
        )
        self.stdout.write(
            f"  Census 2020 blocks loaded: {result.get('row_count', 0)} rows "
            f"in {result.get('table_name', '?')}"
        )

    def _populate_pdb(
        self,
        force_data_fetch: bool,
        force_data_reload: bool,  # noqa: ARG002
    ) -> None:
        from brewgis.workspace.dlt_pipelines.pdb import run_pdb_pipeline

        if force_data_fetch or not self._table_has_rows("public", "pdb_raw"):
            result = run_pdb_pipeline(
                STATE_FIPS, COUNTY_FIPS, ignore_cache=force_data_fetch
            )
            self.stdout.write(
                f"  Census PDB loaded: {result.get('row_count', 0)} rows "
                f"in {result.get('table_name', '?')}"
            )
        else:
            self.stdout.write("  Census PDB already loaded, skipping")

    def _populate_lehd(
        self,
        force_data_fetch: bool,
        force_data_reload: bool,
    ) -> None:
        from brewgis.workspace.dlt_pipelines.lehd import run_lehd_pipeline
        from brewgis.workspace.services.lehd_fetcher import _populate_wac_block

        # LEHD LODES raw data — hard fail on fetch error
        if force_data_fetch or not self._table_has_rows("public", "lodes_raw"):
            lehd_result = run_lehd_pipeline(
                STATE_FIPS, COUNTY_FIPS, LEHD_YEAR, ignore_cache=force_data_fetch
            )
            self.stdout.write(
                f"  LEHD LODES loaded: {lehd_result.get('row_count', 0)} rows"
            )
        else:
            self.stdout.write("  LEHD LODES already loaded, skipping")

        # Materialize lehd.wac_block — hard fail on error
        lehd_wac_count = _populate_wac_block(
            STATE_FIPS, COUNTY_FIPS, LEHD_YEAR, force_reload=force_data_reload
        )
        self.stdout.write(f"  LEHD wac_block populated: {lehd_wac_count:,} rows")

    def _populate_nlcd(
        self,
        force_data_fetch: bool,
        force_data_reload: bool,  # noqa: ARG002
    ) -> None:
        from brewgis.workspace.dlt_pipelines.nlcd import run_nlcd_pipeline
        from brewgis.workspace.dlt_pipelines.nlcd import run_nlcd_tree_canopy_pipeline

        self.stdout.write("\n  -- NLCD land cover --")
        if not (force_data_fetch or not self._table_has_rows("public", "nlcd_raster")):
            self.stdout.write("  NLCD raster already loaded, skipping")
        else:
            nlcd_result = run_nlcd_pipeline(
                parcel_source="fresno_parcels",
                year=2021,
                ignore_cache=force_data_fetch,
            )
            self.stdout.write(
                f"  NLCD raster loaded: {nlcd_result.get('row_count', 0)} tiles "
                f"in public.{nlcd_result.get('raster_table', 'nlcd_raster')}"
            )

        self.stdout.write("\n  -- NLCD tree canopy --")
        if not (
            force_data_fetch
            or not self._table_has_rows("public", "nlcd_tree_canopy_raster")
        ):
            self.stdout.write("  NLCD tree canopy already loaded, skipping")
        else:
            nlcd_tc_result = run_nlcd_tree_canopy_pipeline(
                parcel_source="fresno_parcels",
                year=2021,
                ignore_cache=force_data_fetch,
            )
            self.stdout.write(
                f"  NLCD tree canopy loaded: {nlcd_tc_result.get('row_count', 0)} tiles "
                f"in public.{nlcd_tc_result.get('raster_table', 'nlcd_tree_canopy_raster')}"
            )

    def _populate_osm(
        self,
        force_data_fetch: bool,
        force_data_reload: bool,  # noqa: ARG002
    ) -> None:
        from brewgis.workspace.dlt_pipelines.osm import run_osm_pipeline

        if not (
            force_data_fetch
            or not self._table_has_rows("public", "osm_intersection_density")
        ):
            self.stdout.write("  OSM intersection density already loaded, skipping")
            return

        osm_result = run_osm_pipeline(
            parcel_table="fresno_parcels",
            schema=WORKSPACE_SCHEMA,
        )
        self.stdout.write(
            f"  OSM intersection density loaded: {osm_result.get('row_count', 0)} rows "
            f"in {osm_result.get('table_name', '?')}"
        )

    # -- SQLMesh plan runner -----------------------------------------------

    def _run_sqlmesh_plan(
        self,
        overture: bool,
        nlcd: bool,
        osm: bool,
        force_data_reload: bool,
        cbp_vars: dict[str, object],
    ) -> None:
        """Run the consolidated SQLMesh plan with Fresno-specific selectors and variables."""

        # Core Fresno models + regressors (no DuckDB dependency)
        model_selectors: list[str] = [
            "+brewgis.fresno.parcel_shim",
            "+brewgis.fresno.dasymetric_weights",
            "+brewgis.fresno.dasymetric_intersections",
            "+brewgis.fresno.du_estimation",
            "+brewgis.fresno.du_regressor",
            "+brewgis.fresno.sqft_regressor",
            "+brewgis.fresno.emp_ratios_regressor",
            "+brewgis.fresno.comparison_dasymetric",
            "+brewgis.staging.census_2020_block",
            "+brewgis.base_canvas.base_canvas_reconciled",
        ]
        if overture:
            # DuckDB-dependent: Overture building/transport staging + ResNet
            model_selectors.extend(
                [
                    "+brewgis.fresno.parcel_resnet_features",
                    "+brewgis.staging.overture_buildings",
                    "+brewgis.staging.vida_combined_buildings",
                    "+brewgis.assessor.buildings_combined",
                    "+brewgis.assessor.parcel_building_footprints",
                    "+brewgis.assessor.authoritative_residential_area",
                ]
            )
        if nlcd:
            model_selectors.extend(
                [
                    "+brewgis.nlcd.parcels_wm",
                    "+brewgis.nlcd.nlcd_parcel_stats",
                    "+brewgis.nlcd.nlcd_tree_canopy_parcel_stats",
                ]
            )
        if osm:
            model_selectors.extend(
                [
                    "+brewgis.staging.overture_transport",
                    "+brewgis.nlcd.overture_road_impervious",
                ]
            )

        # Default CBP employment controls: 0 (use LEHD block-level allocation
        # without county-level control totals). Users can override via --cbp-employment.
        plan_vars: dict[str, object] = {
            "parcel_table": "brewgis.fresno.parcel_shim",
            "dasymetric_source": "brewgis.fresno.comparison_dasymetric",
            "local_srid": LOCAL_SRID,
            "acs_year": BASE_YEAR,
            "state_fips": STATE_FIPS,
            "county_fips": COUNTY_FIPS,
            # CBP county-level employment controls default to 0 (Fresno County, 2021)
            # Use --cbp-employment to set from Census CBP API
            "cbp_county_emp_agriculture": cbp_vars.get("cbp_county_emp_agriculture", 0),
            "cbp_county_emp_extraction": cbp_vars.get("cbp_county_emp_extraction", 0),
            "cbp_county_emp_construction": cbp_vars.get(
                "cbp_county_emp_construction", 0
            ),
            "cbp_county_emp_manufacturing": cbp_vars.get(
                "cbp_county_emp_manufacturing", 0
            ),
            "cbp_county_emp_transport_warehousing": cbp_vars.get(
                "cbp_county_emp_transport_warehousing", 0
            ),
            "cbp_county_emp_utilities": cbp_vars.get("cbp_county_emp_utilities", 0),
            "cbp_county_emp_wholesale": cbp_vars.get("cbp_county_emp_wholesale", 0),
            "cbp_county_emp_retail_services": cbp_vars.get(
                "cbp_county_emp_retail_services", 0
            ),
            "cbp_county_emp_office_services": cbp_vars.get(
                "cbp_county_emp_office_services", 0
            ),
            "cbp_county_emp_education": cbp_vars.get("cbp_county_emp_education", 0),
            "cbp_county_emp_medical_services": cbp_vars.get(
                "cbp_county_emp_medical_services", 0
            ),
            "cbp_county_emp_arts_entertainment": cbp_vars.get(
                "cbp_county_emp_arts_entertainment", 0
            ),
            "cbp_county_emp_accommodation": cbp_vars.get(
                "cbp_county_emp_accommodation", 0
            ),
            "cbp_county_emp_restaurant": cbp_vars.get("cbp_county_emp_restaurant", 0),
            "cbp_county_emp_other_services": cbp_vars.get(
                "cbp_county_emp_other_services", 0
            ),
            "cbp_county_emp_public_admin": cbp_vars.get(
                "cbp_county_emp_public_admin", 0
            ),
            "cbp_preserve_fraction": 0.5,
        }
        if osm:
            plan_vars["osm_intersection_table"] = "osm_intersection_density"

        self.stdout.write("  SQLMesh plan variables configured")
        if cbp_vars:
            self.stdout.write(f"  CBP employment overrides: {cbp_vars}")
        else:
            self.stdout.write(
                "  CBP employment controls: 0 (LEHD allocation without county totals). "
                "Set via --cbp-employment for accuracy."
            )

        # Fresh environment — all models build from scratch.
        # restate_models is not needed (would fail if env doesn't exist yet).
        run_sqlmesh_plan(
            environment="fdemo",
            skip_tests=True,
            select=model_selectors,
            variables=plan_vars,
            restate_models=False,
        )
        self.stdout.write(self.style.SUCCESS("  SQLMesh models complete"))

    def _create_analysis_view(self) -> None:
        """Create analysis compat view pointing at the SQLMesh fdemo environment."""
        # base_canvas_reconciled lives in the 'fdemo' SQLMesh environment
        env_schema = "base_canvas__fdemo"
        with connection.cursor() as cursor:
            # Check if the view exists in the fdemo environment
            cursor.execute(
                f"SELECT EXISTS (SELECT 1 FROM pg_views WHERE schemaname = '{env_schema}' "
                f"AND viewname = 'base_canvas_reconciled')"
            )
            exists = cursor.fetchone()[0]
            if not exists:
                self.stdout.write(
                    self.style.WARNING(
                        f"  base_canvas_reconciled not found in {env_schema}. "
                        f"Skipping analysis compat view creation."
                    )
                )
                return

            cursor.execute(
                f'CREATE OR REPLACE VIEW "{WORKSPACE_SCHEMA}".parcels AS '
                f"SELECT parcel_id AS id, geometry AS geom, * "
                f'FROM "{env_schema}"."base_canvas_reconciled"'
            )
            self.stdout.write(
                f"  Created analysis compat view: {WORKSPACE_SCHEMA}.parcels "
                f"from {env_schema}.base_canvas_reconciled"
            )

    def _import_poi(self) -> int:
        workspace = self._get_workspace()
        self.stdout.write("  Fetching POIs from OpenStreetMap Overpass...")

        from brewgis.workspace.dlt_pipelines.poi import run_poi_pipeline

        dlt_result = run_poi_pipeline(
            MIN_LNG,
            MIN_LAT,
            MAX_LNG,
            MAX_LAT,
            categories=POI_CATEGORIES,
            schema=WORKSPACE_SCHEMA,
        )
        self.stdout.write(
            f"  dlt pipeline loaded {dlt_result.get('row_count', 0)} raw POIs"
        )

        gdf = fetch_pois(MIN_LNG, MIN_LAT, MAX_LNG, MAX_LAT, POI_CATEGORIES)
        count = len(gdf)
        self.stdout.write(f"  Fetched {count} POIs")

        suffix = uuid4().hex[:8]
        table_name = f"poi_{suffix}"
        self._write_to_postgis(gdf, table_name, WORKSPACE_SCHEMA)
        self._register_layer(
            f"poi_{suffix}",
            "Points of Interest (Fresno)",
            workspace,
            geometry_type="circle",
            layer_source="OpenStreetMap",
        )
        self.stdout.write(f"  POI data written to {WORKSPACE_SCHEMA}.{table_name}")
        return count

    def _ingest_constraints(self) -> None:
        workspace = self._get_workspace()
        constraint_files = {
            "flood_zones.geojson": "floodplains",
            "wetlands.geojson": "wetlands",
            "farmland.geojson": "farmland",
        }

        for filename, target_table in constraint_files.items():
            filepath = CACHE_DIR / filename
            if not filepath.exists():
                self.stdout.write(
                    f"  [SKIP] {filename} not cached; skipping {target_table}"
                )
                continue

            self.stdout.write(f"  Ingesting {filename} -> {target_table}...")
            df = gpd.read_file(str(filepath))
            if df.empty:
                self.stdout.write(f"  [SKIP] Empty dataset: {filename}")
                continue
            df.columns = [c.lower() for c in df.columns]
            if "geom" not in df.columns and "geometry" in df.columns:
                df = df.rename_geometry("geom")
            self._write_to_postgis(df, target_table, WORKSPACE_SCHEMA)
            self._register_layer(
                target_table,
                target_table.capitalize(),
                workspace,
                "fill",
                "Environmental Constraints",
            )
            self.stdout.write(f"  {target_table}: {len(df)} features")

        if not self._table_exists(WORKSPACE_SCHEMA, "steep_slopes"):
            with connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE TABLE IF NOT EXISTS {WORKSPACE_SCHEMA}.steep_slopes ("
                    f"id SERIAL PRIMARY KEY, "
                    f"geom geometry(Polygon, 4326)"
                    f")"
                )
            self.stdout.write("  Created empty steep_slopes table (DEM deferred)")
            self._register_layer(
                "steep_slopes",
                "Steep Slopes",
                workspace,
                "fill",
                "Environmental Constraints",
            )

    def _create_base_scenario(self) -> Scenario:
        workspace = self._get_workspace()
        slug = "fresno_baseline"
        scenario, created = Scenario.objects.get_or_create(
            slug=slug,
            workspace=workspace,
            defaults={
                "name": "Fresno Baseline",
                "description": "Baseline scenario for Fresno Demo",
                "scenario_type": "base",
                "base_year": BASE_YEAR,
                "horizon_year": HORIZON_YEAR,
            },
        )
        if created:
            self.stdout.write(
                f"  Created scenario: {scenario.name} (slug: {scenario.slug})"
            )
        else:
            self.stdout.write(f"  Scenario already exists: {scenario.name}")
        return scenario

    def _export_built_forms(self) -> int:
        count = export_building_types(schema=WORKSPACE_SCHEMA, table="built_forms")
        self.stdout.write(
            f"  Exported {count} building types to {WORKSPACE_SCHEMA}.built_forms"
        )
        return count

    def _run_analysis(self) -> dict[str, Any]:
        """Run the analysis pipeline via run_modules_sync."""
        workspace = self._get_workspace()
        scenario = Scenario.objects.get(slug="fresno_baseline", workspace=workspace)

        run = AnalysisRun.objects.create(
            workspace=workspace,
            scenario=scenario,
            status="running",
            modules=[
                "env_constraint",
                "core",
                "water_demand",
                "energy_demand",
                "trip_generation",
                "trip_distribution",
                "mode_choice",
                "vmt",
            ],
        )

        pipeline_vars = dict(PIPELINE_VARS)
        pipeline_vars["target_schema"] = scenario.target_schema
        pipeline_vars["scenario_id"] = scenario.id

        self._create_db_schema(scenario.target_schema)

        result = run_modules_sync(
            modules=[
                "env_constraint",
                "core",
                "water_demand",
                "energy_demand",
                "trip_generation",
                "trip_distribution",
                "mode_choice",
                "vmt",
            ],
            base_vars=pipeline_vars,
            target_schema=scenario.target_schema,
            workspace_id=workspace.pk,
            scenario_id=scenario.slug,
        )

        all_success = result.get("success", False)
        run.status = "completed" if all_success else "failed"
        run.completed_at = timezone.now()
        run.vars = {"modules": result.get("results", [])}
        run.save(update_fields=["status", "completed_at", "vars"])

        self.stdout.write(f"  Analysis pipeline: {run.status}")
        for res in result.get("results", []):
            status = (
                self.style.SUCCESS("OK")
                if res.get("success")
                else self.style.ERROR("FAIL")
            )
            self.stdout.write(f"    {res['module']}: {status}")

        return result
