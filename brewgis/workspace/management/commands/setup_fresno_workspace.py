"""Set up the Fresno Demo workspace end-to-end.

Uses dbt base_canvas models for ETL (instead of the deprecated Python SQL
pipeline), dlt for data ingestion, and Soda for data quality validation.

Usage:
    python manage.py setup_fresno_workspace
    python manage.py setup_fresno_workspace --skip-download   # use cached data only
    python manage.py setup_fresno_workspace --force-download   # re-download everything
    python manage.py setup_fresno_workspace --nlcd             # include NLCD land cover
"""

from __future__ import annotations

import contextlib
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

from brewgis.workspace.analysis.data_export import export_building_types
from brewgis.workspace.analysis.pipeline import run_modules_sync
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
HORIZON_YEAR = 2050

# DBT vars template — used by the analysis pipeline (not base canvas dbt)
DBT_VARS_TEMPLATE: dict[str, Any] = {
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

# ── dbt base_canvas model names (in dependency order) ────────────────
BASE_CANVAS_MODELS = [
    "base_canvas_geometry",
    "base_canvas_demographics",
    "base_canvas_employment",
    "base_canvas_attributes",
    "base_canvas_imputed",
    "base_canvas_reconciled",
]


class Command(BaseCommand):
    help = "Set up the Fresno Demo workspace end-to-end."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--skip-download",
            action="store_true",
            help="Skip data downloads; use cached files only.",
        )
        parser.add_argument(
            "--force-download",
            action="store_true",
            help="Re-download all data even if cached.",
        )
        parser.add_argument(
            "--skip-census",
            action="store_true",
            default=False,
            help="Skip Census ACS population data fetch and staging.",
        )
        parser.add_argument(
            "--skip-lehd",
            action="store_true",
            default=False,
            help="Skip LEHD employment data fetch and staging.",
        )
        parser.add_argument(
            "--skip-poi",
            action="store_true",
            default=False,
            help="Skip POI import from OpenStreetMap.",
        )
        parser.add_argument(
            "--skip-constraints",
            action="store_true",
            default=False,
            help="Skip environmental constraint layer ingest.",
        )
        parser.add_argument(
            "--skip-city-boundary",
            action="store_true",
            default=False,
            help="Skip city boundary ingest.",
        )
        parser.add_argument(
            "--nlcd",
            action="store_true",
            default=False,
            help="Enable NLCD land cover classification (zonal stats per parcel).",
        )
        parser.add_argument(
            "--osm",
            action="store_true",
            default=False,
            help="Enable OSM intersection density computation.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be done without doing it.",
        )

    def handle(self, **options: Any) -> None:  # noqa: PLR0912, PLR0915
        self.dry_run = options["dry_run"]
        skip_census = bool(options.get("skip_census", False))
        skip_lehd = bool(options.get("skip_lehd", False))
        skip_poi = bool(options.get("skip_poi", False))
        skip_constraints = bool(options.get("skip_constraints", False))
        skip_city_boundary = bool(options.get("skip_city_boundary", False))
        nlcd = bool(options.get("nlcd", False))
        osm = bool(options.get("osm", False))

        # ── Step 1: Download data ──────────────────────────────────────
        if not options.get("skip_download"):
            self._run_step("Download data", self._download_data, (options,))
        else:
            self.stdout.write("  [SKIP] Download data")

        # ── Step 2: Create workspace + load built form fixtures ────────
        workspace = self._run_step("Create workspace", self._create_workspace, ())

        # ── Step 3: Ingest parcels (GeoJSON → table) ──────────────────
        self._run_step("Ingest parcels", self._ingest_parcels, ())

        # ── Step 4: Ingest city boundary ──────────────────────────────
        if not skip_city_boundary:
            self._run_step("Ingest city boundary", self._ingest_city_boundary, ())
        else:
            self.stdout.write("  [SKIP] Ingest city boundary")

        # ── Step 5: Census — TIGER → ACS dlt → acs_block_group ─────────
        if not skip_census:
            self._run_step(
                "Census ACS data (dlt → dbt acs_block_group)",
                self._populate_census,
                (),
            )
        else:
            self.stdout.write("  [SKIP] Census ACS data")

        # ── Step 6: LEHD — dlt → wac_block ────────────────────────────
        if not skip_lehd:
            self._run_step(
                "LEHD employment data (dlt → dbt wac_block)",
                self._populate_lehd,
                (),
            )
        else:
            self.stdout.write("  [SKIP] LEHD employment data")

        # ── Step 7: NLCD pipeline (opt-in) ────────────────────────────
        nlcd_table = ""
        if nlcd:
            self._run_step(
                "NLCD land cover pipeline",
                self._run_nlcd_pipeline,
                (workspace,),
            )
            nlcd_table = self._last_nlcd_table
        else:
            self.stdout.write("  [SKIP] NLCD (not enabled)")

        # ── Step 8: OSM pipeline (opt-in) ─────────────────────────────
        osm_table = ""
        if osm:
            self._run_step(
                "OSM intersection density pipeline",
                self._run_osm_pipeline,
                (workspace,),
            )
            osm_table = self._last_osm_table
        else:
            self.stdout.write("  [SKIP] OSM (not enabled)")

        # ── Step 9: dbt base_canvas models ────────────────────────────
        self._run_step(
            "dbt base_canvas models",
            self._run_dbt_base_canvas,
            (workspace, self._last_nlcd_table, osm_table),
        )

        # ── Step 11: Import POIs ──────────────────────────────────────
        if not skip_poi:
            self._run_step("Import POIs", self._import_poi, ())
        else:
            self.stdout.write("  [SKIP] Import POIs")

        # ── Step 12: Ingest constraint layers ─────────────────────────
        if not skip_constraints:
            self._run_step("Ingest constraint layers", self._ingest_constraints, ())
        else:
            self.stdout.write("  [SKIP] Ingest constraint layers")

        # ── Step 13: Export building types ────────────────────────────
        self._run_step("Export building types", self._export_built_forms, ())

        # ── Step 14: Create base scenario ─────────────────────────────
        self._run_step("Create base scenario", self._create_base_scenario, ())

        # ── Step 15: Run analysis pipeline ────────────────────────────
        self._run_step("Run analysis pipeline", self._run_analysis, ())

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
        # Ensure geometry column is named 'geom' for tile server consistency
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
        if options.get("force_download"):
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
        """Ingest parcels from GeoJSON directly to fresno_parcels."""
        workspace = self._get_workspace()
        df = self._read_geojson("fresno_parcels.geojson")

        # Normalize parcel ID column to dbt contract
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

        # Write directly to the target table (no staging/ETL pipeline)
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

    def _populate_census(self) -> int:
        """Run TIGER BG + Census ACS dlt pipelines, then populate acs_block_group."""
        from brewgis.workspace.dlt_pipelines.census import run_census_pipeline
        from brewgis.workspace.dlt_pipelines.tiger_bg import run_tiger_bg_pipeline
        from brewgis.workspace.services.census_fetcher import _populate_acs_block_group

        # TIGER/Line block group geometry
        self.stdout.write("  Populating TIGER/Line block group staging...")
        tiger_result = run_tiger_bg_pipeline(STATE_FIPS)
        self.stdout.write(f"  TIGER/BG loaded: {tiger_result.get('row_count', 0)} rows")

        # Census ACS raw data
        self.stdout.write("  Fetching Census ACS data...")
        census_result = run_census_pipeline(STATE_FIPS, COUNTY_FIPS, BASE_YEAR)
        if not census_result["success"]:
            msg = "Census ACS fetch failed: {census_result.get('error')}"
        raise CommandError(msg)
        self.stdout.write(
            f"  Census ACS loaded: {census_result.get('row_count', 0)} rows"
        )

        # Materialize census.acs_block_group via dbt
        self.stdout.write("  Materializing census.acs_block_group via dbt...")
        acs_bg_count = _populate_acs_block_group(STATE_FIPS, COUNTY_FIPS, BASE_YEAR)
        self.stdout.write(f"  census.acs_block_group populated: {acs_bg_count:,} rows")
        return acs_bg_count

    def _populate_lehd(self) -> int:
        """Run LEHD dlt pipeline, then populate lehd.wac_block."""
        from brewgis.workspace.dlt_pipelines.lehd import run_lehd_pipeline
        from brewgis.workspace.services.lehd_fetcher import _populate_wac_block

        # LEHD LODES raw data
        self.stdout.write("  Fetching LEHD employment data...")
        lehd_result = run_lehd_pipeline(STATE_FIPS, COUNTY_FIPS, 2021)
        if not lehd_result["success"]:
            msg = "LEHD LODES fetch failed: {lehd_result.get('error')}"
        raise CommandError(msg)
        self.stdout.write(
            f"  LEHD LODES loaded: {lehd_result.get('row_count', 0)} rows"
        )

        # Materialize lehd.wac_block via dbt
        self.stdout.write("  Materializing lehd.wac_block via dbt...")
        lehd_wac_count = _populate_wac_block(STATE_FIPS, COUNTY_FIPS, 2021)
        self.stdout.write(f"  lehd.wac_block populated: {lehd_wac_count:,} rows")
        return lehd_wac_count

    _last_nlcd_table: str = ""

    def _run_nlcd_pipeline(self, _workspace: Workspace) -> None:
        """Run NLCD raster loading pipeline."""
        from brewgis.workspace.dlt_pipelines.nlcd import run_nlcd_pipeline

        result = run_nlcd_pipeline(
            parcel_source="fresno_parcels",
            schema=WORKSPACE_SCHEMA,
        )
        raster_table = result.get("raster_table", "nlcd_raster")
        self._last_nlcd_table = f"{WORKSPACE_SCHEMA}.{raster_table}"
        self.stdout.write(
            f"  NLCD raster loaded: {result.get('row_count', 0)} tiles "
            f"in {self._last_nlcd_table}"
        )

    _last_osm_table: str = ""

    def _run_osm_pipeline(self, _workspace: Workspace) -> None:
        """Run OSM intersection density pipeline."""
        from brewgis.workspace.dlt_pipelines.osm import run_osm_pipeline

        result = run_osm_pipeline(
            parcel_table="fresno_parcels",
            schema=WORKSPACE_SCHEMA,
        )
        if not result.get("success"):
            msg = "OSM pipeline failed: {result.get('error')}"
        raise CommandError(msg)
        self._last_osm_table = result.get(
            "table_name", f"{WORKSPACE_SCHEMA}.osm_intersection_density"
        )
        self.stdout.write(
            f"  OSM intersection density loaded: {result.get('row_count', 0)} rows "
            f"in {self._last_osm_table}"
        )

    def _run_dbt_base_canvas(
        self,
        workspace: Workspace,
        nlcd_raster_table: str,
        osm_table: str,
    ) -> None:
        """Run dbt base_canvas models to produce the final base canvas table."""
        from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan

        dbt_vars: dict[str, Any] = {
            "parcel_table": "fresno_parcels",
            "source_schema": WORKSPACE_SCHEMA,
            "target_schema": WORKSPACE_SCHEMA,
            "base_canvas_materialized": "table",
            "projected_srid": LOCAL_SRID,
        }
        if nlcd_raster_table:
            dbt_vars["nlcd_enabled"] = True
            dbt_vars["nlcd_raster_table"] = nlcd_raster_table
            dbt_vars["nlcd_parcel_source"] = f"{WORKSPACE_SCHEMA}.fresno_parcels"
        if osm_table:
            dbt_vars["osm_intersection_table"] = osm_table

        self.stdout.write(f"  dbt vars: {dbt_vars}")
        run_sqlmesh_plan(
            environment="fresno_demo",
            select=BASE_CANVAS_MODELS,
        )
        self.stdout.write(self.style.SUCCESS("  SQLMesh base_canvas models complete"))

        # Create analysis compat view: maps dbt column names to legacy names
        # expected by the analysis pipeline dbt models (id, geom, etc.)
        with connection.cursor() as cursor:
            cursor.execute(
                f'CREATE OR REPLACE VIEW "{WORKSPACE_SCHEMA}".parcels AS '  # noqa: S608
                f"SELECT parcel_id AS id, geometry AS geom, * "
                f'FROM "{WORKSPACE_SCHEMA}"."base_canvas_reconciled"'
            )
        self.stdout.write(f"  Created analysis compat view: {WORKSPACE_SCHEMA}.parcels")

        # Register the final base canvas as a Layer
        self._register_layer(
            "base_canvas_reconciled",
            "Fresno Base Canvas (dbt)",
            workspace,
            "fill",
        )
        self.stdout.write("  Registered base_canvas_reconciled as Layer")

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
                    f"CREATE TABLE {WORKSPACE_SCHEMA}.steep_slopes ("
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

        dbt_vars = dict(DBT_VARS_TEMPLATE)
        dbt_vars["target_schema"] = scenario.target_schema
        dbt_vars["scenario_id"] = scenario.id

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
            base_vars=dbt_vars,
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
