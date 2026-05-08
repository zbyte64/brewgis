"""Set up the Fresno Demo workspace end-to-end.

Usage:
    python manage.py setup_fresno_workspace
    python manage.py setup_fresno_workspace --skip-download   # use cached data only
    python manage.py setup_fresno_workspace --force-download   # re-download everything
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import geopandas as gpd
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.core.management.base import CommandParser
from django.db import connection
from django.utils import timezone

from brewgis.workspace.analysis.data_export import export_building_types
from brewgis.workspace.analysis.dbt_runner import DbtRunnerWrapper
from brewgis.workspace.analysis.layer_registry import register_result_layer
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import Layer
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.census_fetcher import fetch_acs_block_groups
from brewgis.workspace.services.lehd_fetcher import fetch_lehd_block_data
from brewgis.workspace.services.poi_fetcher import fetch_pois
from brewgis.workspace.services.spatial_allocator import allocate_attributes
from brewgis.workspace.services.stitcher import impute_constant
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

# Fresno city core bounding box
BBOX = (-119.82, 36.72, -119.72, 36.80)
MIN_LNG, MIN_LAT, MAX_LNG, MAX_LAT = BBOX

# Base scenario config
BASE_YEAR = 2022
HORIZON_YEAR = 2050

# DBT vars template
DBT_VARS_TEMPLATE: dict[str, Any] = {
    "source_schema": WORKSPACE_SCHEMA,
    "parcel_table": "fresno_parcels",
    "constraints": [
        {"table": "floodplains", "discount_pct": 100, "geom_col": "geom"},
        {"table": "wetlands", "discount_pct": 100, "geom_col": "geom"},
        {"table": "steep_slopes", "discount_pct": 75, "geom_col": "geom"},
        {"table": "farmland", "discount_pct": 50, "geom_col": "geom"},
    ],
    "target_schema": None,  # set per scenario
    "scenario_id": None,  # set per scenario
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
            "--step",
            choices=[
                "all",
                "download",
                "workspace",
                "parcels",
                "census",
                "lehd",
                "poi",
                "constraints",
                "allocate",
                "stitch",
                "scenario",
                "analysis",
            ],
            default="all",
            help="Run a specific step.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be done without doing it.",
        )

    def handle(self, **options: Any) -> None:  # noqa: C901
        self.dry_run = options["dry_run"]
        step = options["step"]

        steps: list[tuple[str, Any, tuple]] = []

        if step in ("all", "download"):
            steps.append(("Download data", self._download_data, (options,)))

        if step in ("all", "workspace"):
            steps.append(("Create workspace", self._create_workspace, ()))

        if step in ("all", "parcels"):
            steps.append(("Ingest parcels", self._ingest_parcels, ()))
            steps.append(("Ingest city boundary", self._ingest_city_boundary, ()))

        if step in ("all", "census"):
            steps.append(("Import Census ACS data", self._import_census, ()))

        if step in ("all", "lehd"):
            steps.append(("Import LEHD employment", self._import_lehd, ()))

        if step in ("all", "poi"):
            steps.append(("Import POIs", self._import_poi, ()))

        if step in ("all", "constraints"):
            steps.append(("Ingest constraint layers", self._ingest_constraints, ()))

        if step in ("all", "allocate"):
            steps.append(
                ("Spatial allocation (Census", self._allocate_census, ())
            )
            steps.append(
                ("Spatial allocation (LEHD", self._allocate_lehd, ())
            )

        if step in ("all", "stitch"):
            steps.append(("Column stitching", self._stitch_columns, ()))

        if step in ("all", "scenario"):
            steps.append(("Create base scenario", self._create_base_scenario, ()))

        if step in ("all", "analysis"):
            steps.append(("Export building types", self._export_built_forms, ()))
            steps.append(("Run dbt analysis pipeline", self._run_analysis, ()))

        # Mark non-critical steps that should not crash the pipeline
        nonfatal_labels = {"Import LEHD employment", "Import POIs",
                           "Ingest constraint layers", "Spatial allocation (LEHD",
                           "Spatial allocation (Census",
                           "Ingest city boundary"}

        for label, fn, args in steps:
            if any(label.startswith(nf) for nf in nonfatal_labels):
                self._run_step_nonfatal(label, fn, *args)
            else:
                self._run_step(label, fn, *args)

        self.stdout.write(self.style.SUCCESS("\nFresno demo workspace setup complete!"))

    # -- helpers ----------------------------------------------------------

    def _run_step(self, label: str, fn: Any, *args: Any) -> Any:
        self.stdout.write(f"\n{'─'*60}")
        self.stdout.write(f"Step: {label}")
        self.stdout.write(f"{'─'*60}")
        if self.dry_run:
            self.stdout.write(f"  [DRY RUN] Would execute: {fn.__name__}")
            return None
        try:
            result = fn(*args)
            self.stdout.write(f"  [{self.style.SUCCESS('OK')}] {label}")
            return result
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"  [FAIL] {label}: {exc}"))
            raise

    def _run_step_nonfatal(self, label: str, fn: Any, *args: Any) -> Any:
        """Run a step; on failure log warning but do not crash."""
        self.stdout.write(f"\n{'─'*60}")
        self.stdout.write(f"Step: {label}")
        self.stdout.write(f"{'─'*60}")
        if self.dry_run:
            self.stdout.write(f"  [DRY RUN] Would execute: {fn.__name__}")
            return None
        try:
            result = fn(*args)
            self.stdout.write(f"  [{self.style.SUCCESS('OK')}] {label}")
            return result
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(self.style.WARNING(f"  [WARN] {label}: {exc}"))
            return None

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
            return cursor.fetchone()[0]

    def _get_db_url(self) -> str:
        db = settings.DATABASES["default"]
        return (
            f"postgresql://{db['USER']}:{db['PASSWORD']}"
            f"@{db['HOST']}:{db['PORT']}/{db['NAME']}"
        )

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
        from sqlalchemy import create_engine

        # Ensure geometry column is named 'geom' for allocator/tile server consistency
        if df.geometry.name != "geom":
            df = df.rename_geometry("geom")
        if "geometry" in df.columns and "geom" in df.columns:
            df = df.drop(columns=["geometry"])
        df.columns = [c.lower() for c in df.columns]
        if df.crs is None or df.crs.to_string() != "EPSG:4326":
            df = df.to_crs("EPSG:4326")
        engine = create_engine(self._get_db_url())
        df.to_postgis(table, engine, schema=schema, if_exists="replace", chunksize=50000)
        engine.dispose()

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
            try:
                auto_generate_symbology(layer)
            except Exception:  # noqa: S110, BLE001
                pass
        return layer

    # -- Step implementations ---------------------------------------------

    def _download_data(self, options: Any) -> None:
        args = []
        if options.get("force_download"):
            args.append("--force")
        call_command("download_fresno_demo", *args)

    def _create_workspace(self) -> Workspace:
        self._create_db_schema(WORKSPACE_SCHEMA)
        workspace = self._get_workspace()
        self.stdout.write(f"  Workspace: {workspace.name} (schema: {workspace.db_schema})")

        from brewgis.workspace.built_forms.models import BuildingType

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
        workspace = self._get_workspace()
        df = self._read_geojson("fresno_parcels.geojson")
        self._write_to_postgis(df, "fresno_parcels", WORKSPACE_SCHEMA)
        self._register_layer("fresno_parcels", "Fresno County Parcels", workspace, "fill")
        count = len(df)
        self.stdout.write(f"  Ingested {count} parcels")
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
            "fresno_city_boundary", "Fresno City Boundary", workspace, "fill"
        )
        count = len(df)
        self.stdout.write(f"  Ingested city boundary ({count} features)")
        return count

    def _import_census(self) -> int:
        workspace = self._get_workspace()
        self.stdout.write("  Fetching ACS block group data from Census API...")
        gdf = fetch_acs_block_groups(STATE_FIPS, COUNTY_FIPS)
        count = len(gdf)
        self.stdout.write(f"  Fetched {count} block groups")

        table_name = f"census_acs_{STATE_FIPS}_{COUNTY_FIPS}"
        self._write_to_postgis(gdf, table_name, WORKSPACE_SCHEMA)
        self._register_layer(
            f"census_acs_{STATE_FIPS}_{COUNTY_FIPS}",
            f"ACS Demographics ({STATE_FIPS}-{COUNTY_FIPS})",
            workspace,
            geometry_type="circle",
            layer_source="Census ACS",
        )
        self.stdout.write(f"  Census data written to {WORKSPACE_SCHEMA}.{table_name}")
        return count

    def _import_lehd(self) -> int:
        workspace = self._get_workspace()
        self.stdout.write("  Fetching LEHD employment data from Census API...")
        gdf = fetch_lehd_block_data(STATE_FIPS, COUNTY_FIPS)
        count = len(gdf)
        self.stdout.write(f"  Fetched {count} census blocks with employment data")

        table_name = f"lehd_{STATE_FIPS}_{COUNTY_FIPS}"
        self._write_to_postgis(gdf, table_name, WORKSPACE_SCHEMA)
        self._register_layer(
            f"lehd_{STATE_FIPS}_{COUNTY_FIPS}",
            f"LEHD Employment ({STATE_FIPS}-{COUNTY_FIPS})",
            workspace,
            geometry_type="circle",
            layer_source="Census LEHD",
        )
        self.stdout.write(f"  LEHD data written to {WORKSPACE_SCHEMA}.{table_name}")
        return count

    def _import_poi(self) -> int:
        workspace = self._get_workspace()
        self.stdout.write("  Fetching POIs from OpenStreetMap Overpass...")
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
                self.stdout.write(f"  [SKIP] {filename} not cached; skipping {target_table}")
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

    def _allocate_census(self) -> dict[str, Any]:
        """Spatial allocation: census block groups -> parcels."""
        census_table = f"census_acs_{STATE_FIPS}_{COUNTY_FIPS}"
        if not self._table_exists(WORKSPACE_SCHEMA, census_table):
            self.stdout.write("  [SKIP] Census table does not exist")
            return {"success": False, "error": "Census table missing"}

        numeric_cols = self._get_numeric_columns(census_table, exclusions=("id", "geoid", "statefp", "countyfp"))

        self.stdout.write(f"  Allocating {len(numeric_cols)} columns from {census_table}...")
        result = allocate_attributes(
            source_schema=WORKSPACE_SCHEMA,
            source_table=census_table,
            target_schema=WORKSPACE_SCHEMA,
            target_table="fresno_parcels",
            columns=numeric_cols,
            target_column_prefix="acs_",
        )
        self.stdout.write(f"  Allocation result: {result}")
        return result

    def _allocate_lehd(self) -> dict[str, Any]:
        """Spatial allocation: LEHD blocks -> parcels."""
        lehd_table = f"lehd_{STATE_FIPS}_{COUNTY_FIPS}"
        if not self._table_exists(WORKSPACE_SCHEMA, lehd_table):
            self.stdout.write("  [SKIP] LEHD table does not exist")
            return {"success": False, "error": "LEHD table missing"}

        numeric_cols = self._get_numeric_columns(lehd_table, exclusions=("id", "geoid", "statefp", "countyfp"))

        self.stdout.write(f"  Allocating {len(numeric_cols)} columns from {lehd_table}...")
        result = allocate_attributes(
            source_schema=WORKSPACE_SCHEMA,
            source_table=lehd_table,
            target_schema=WORKSPACE_SCHEMA,
            target_table="fresno_parcels",
            columns=numeric_cols,
            target_column_prefix="lehd_",
        )
        self.stdout.write(f"  Allocation result: {result}")
        return result

    @staticmethod
    def _get_numeric_columns(
        table: str,
        schema: str = WORKSPACE_SCHEMA,
        exclusions: tuple[str, ...] = (),
    ) -> list[str]:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s "
                "AND data_type IN ('integer', 'numeric', 'double precision', 'real', 'bigint')",
                [schema, table],
            )
            return [row[0] for row in cursor.fetchall() if row[0] not in exclusions]

    def _stitch_columns(self) -> None:
        """Impute missing values on parcels table."""
        # First, ensure base canvas columns exist on the table
        column_defs: list[dict[str, str]] = [
            {"col": "land_use_code", "type": "double precision"},
            {"col": "land_use_category", "type": "double precision"},
            {"col": "dwelling_units", "type": "double precision"},
            {"col": "households", "type": "double precision"},
            {"col": "population", "type": "double precision"},
            {"col": "employment", "type": "double precision"},
            {"col": "sqft_per_unit", "type": "double precision"},
            {"col": "lot_sqft", "type": "double precision"},
            {"col": "year_built", "type": "double precision"},
            {"col": "stories", "type": "double precision"},
            {"col": "building_sqft", "type": "double precision"},
            {"col": "residential_sqft", "type": "double precision"},
            {"col": "non_residential_sqft", "type": "double precision"},
            {"col": "irrigated_area_sqft", "type": "double precision"},
            {"col": "total_area_sqft", "type": "double precision"},
        ]
        with connection.cursor() as cursor:
            for col_def in column_defs:
                col_name = col_def["col"]
                col_type = col_def["type"]
                cursor.execute(
                    f"ALTER TABLE {WORKSPACE_SCHEMA}.fresno_parcels "
                    f"ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
                )

        stitchees: list[dict[str, Any]] = [
            {"col": "land_use_code", "default": 0.0},
            {"col": "land_use_category", "default": 0.0},
            {"col": "dwelling_units", "default": 1.0},
            {"col": "households", "default": 1.0},
            {"col": "population", "default": 2.5},
            {"col": "employment", "default": 0.0},
            {"col": "sqft_per_unit", "default": 1500.0},
            {"col": "lot_sqft", "default": 7000.0},
            {"col": "year_built", "default": 1990.0},
            {"col": "stories", "default": 1.0},
            {"col": "building_sqft", "default": 1500.0},
            {"col": "residential_sqft", "default": 1500.0},
            {"col": "non_residential_sqft", "default": 0.0},
            {"col": "irrigated_area_sqft", "default": 2000.0},
            {"col": "total_area_sqft", "default": 7000.0},
        ]

        success_count = 0
        for item in stitchees:
            try:
                impute_constant(
                    schema=WORKSPACE_SCHEMA,
                    table="fresno_parcels",
                    column=item["col"],
                    value=item["default"],
                )
                success_count += 1
            except Exception:  # noqa: S110, BLE001
                pass

        self.stdout.write(f"  Stitched {success_count}/{len(stitchees)} columns")

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
            self.stdout.write(f"  Created scenario: {scenario.name} (slug: {scenario.slug})")
        else:
            self.stdout.write(f"  Scenario already exists: {scenario.name}")
        return scenario

    def _export_built_forms(self) -> int:
        count = export_building_types(schema=WORKSPACE_SCHEMA, table="built_forms")
        self.stdout.write(f"  Exported {count} building types to {WORKSPACE_SCHEMA}.built_forms")
        return count

    def _run_analysis(self) -> list[dict[str, Any]]:  # noqa: PLR0915
        workspace = self._get_workspace()
        scenario = Scenario.objects.get(slug="fresno_baseline", workspace=workspace)

        run = AnalysisRun.objects.create(
            workspace=workspace,
            scenario=scenario,
            status="running",
            modules=["env_constraint", "core", "water_demand", "energy_demand"],
        )

        dbt_vars = dict(DBT_VARS_TEMPLATE)
        dbt_vars["target_schema"] = scenario.target_schema
        dbt_vars["scenario_id"] = scenario.id

        self._create_db_schema(scenario.target_schema)

        runner = DbtRunnerWrapper()
        results: list[dict[str, Any]] = []

        # 1. env_constraint
        self.stdout.write("  Running env_constraint...")
        dbt_result = runner.run(
            select=["env_constraint"],
            vars_=dbt_vars,
            full_refresh=True,
        )
        env_result = {
            "module": "env_constraint",
            "success": dbt_result.success,
            "error": dbt_result.error,
        }
        results.append(env_result)
        if dbt_result.success:
            register_result_layer(
                workspace_id=workspace.pk,
                schema=scenario.target_schema,
                table=f"env_constraint_{scenario.id}",
                name=f"Environmental Constraints (scenario {scenario.id})",
            )
            self.stdout.write("  env_constraint complete")
        else:
            self.stderr.write(self.style.ERROR(f"  env_constraint failed: {dbt_result.error}"))
            run.status = "failed"
            run.save(update_fields=["status"])
            return results

        # 2. core (end_state + increment)
        self.stdout.write("  Running core module...")
        dbt_result = runner.run(
            select=["core_end_state", "core_increment"],
            vars_=dbt_vars,
            full_refresh=True,
        )
        core_result = {
            "module": "core",
            "success": dbt_result.success,
            "error": dbt_result.error,
        }
        results.append(core_result)
        if dbt_result.success:
            for tbl in (f"end_state_{scenario.id}", f"increment_{scenario.id}"):
                register_result_layer(
                    workspace_id=workspace.pk,
                    schema=scenario.target_schema,
                    table=tbl,
                    name=f"{tbl} (scenario {scenario.id})",
                )
            self.stdout.write("  core module complete")
        else:
            self.stderr.write(self.style.ERROR(f"  core module failed: {dbt_result.error}"))
            run.status = "failed"
            run.save(update_fields=["status"])
            return results

        # 3. water_demand
        self.stdout.write("  Running water_demand...")
        dbt_result = runner.run(
            select=["water_demand"],
            vars_=dbt_vars,
            full_refresh=True,
        )
        water_result = {
            "module": "water_demand",
            "success": dbt_result.success,
            "error": dbt_result.error,
        }
        results.append(water_result)
        if dbt_result.success:
            register_result_layer(
                workspace_id=workspace.pk,
                schema=scenario.target_schema,
                table=f"water_demand_{scenario.id}",
                name=f"Water Demand (scenario {scenario.id})",
            )
            self.stdout.write("  water_demand complete")
        else:
            self.stderr.write(self.style.ERROR(f"  water_demand failed: {dbt_result.error}"))

        # 4. energy_demand
        self.stdout.write("  Running energy_demand...")
        dbt_result = runner.run(
            select=["energy_demand"],
            vars_=dbt_vars,
            full_refresh=True,
        )
        energy_result = {
            "module": "energy_demand",
            "success": dbt_result.success,
            "error": dbt_result.error,
        }
        results.append(energy_result)
        if dbt_result.success:
            register_result_layer(
                workspace_id=workspace.pk,
                schema=scenario.target_schema,
                table=f"energy_demand_{scenario.id}",
                name=f"Energy Demand (scenario {scenario.id})",
            )
            self.stdout.write("  energy_demand complete")
        else:
            self.stderr.write(self.style.ERROR(f"  energy_demand failed: {dbt_result.error}"))

        all_success = all(r.get("success") for r in results)
        run.status = "completed" if all_success else "failed"
        run.completed_at = timezone.now()
        run.vars = {"modules": results}
        run.save(update_fields=["status", "completed_at", "vars"])

        self.stdout.write(f"  Analysis pipeline: {run.status}")
        return results
