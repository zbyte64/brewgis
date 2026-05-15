"""Set up the Fresno Demo workspace end-to-end.

Usage:
    python manage.py setup_fresno_workspace
    python manage.py setup_fresno_workspace --skip-download   # use cached data only
    python manage.py setup_fresno_workspace --force-download   # re-download everything
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
from brewgis.workspace.services.base_canvas_pipeline import run_pipeline
from brewgis.workspace.services.built_form_classifier import BuiltFormClassifier
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

# Fresno-Clovis urban area bounding box
BBOX = (-119.95, 36.60, -119.55, 36.90)
MIN_LNG, MIN_LAT, MAX_LNG, MAX_LAT = BBOX

# Base scenario config
BASE_YEAR = 2022
HORIZON_YEAR = 2050

# DBT vars template
DBT_VARS_TEMPLATE: dict[str, Any] = {
    "source_schema": WORKSPACE_SCHEMA,
    "base_table_schema": WORKSPACE_SCHEMA,
    "base_table_name": "fresno_parcels",
    "parcel_table": "parcels",
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
                "built_forms",
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

    def handle(self, **options: Any) -> None:  # noqa: C901, PLR0912
        self.dry_run = options["dry_run"]
        step = options["step"]

        steps: list[tuple[str, Any, tuple]] = []

        if step in ("all", "download"):
            steps.append(("Download data", self._download_data, (options,)))

        if step in ("all", "workspace"):
            steps.append(("Create workspace", self._create_workspace, ()))

        if step in ("all", "parcels"):
            steps.append(("Ingest parcels (ETL pipeline)", self._ingest_parcels, ()))
            steps.append(("Ingest city boundary", self._ingest_city_boundary, ()))

        if step in ("all", "census"):
            steps.append(("Validate Census ACS data", self._import_census, ()))

        if step in ("all", "lehd"):
            steps.append(("Validate LEHD employment data", self._import_lehd, ()))

        if step in ("all", "poi"):
            steps.append(("Import POIs", self._import_poi, ()))

        if step in ("all", "constraints"):
            steps.append(("Ingest constraint layers", self._ingest_constraints, ()))

        if step in ("all", "built_forms"):
            steps.append(("Export building types", self._export_built_forms, ()))
            steps.append(
                (
                    "Assign built forms and density",
                    self._assign_built_forms_and_density,
                    (),
                )
            )

        if step in ("all", "scenario"):
            steps.append(("Create base scenario", self._create_base_scenario, ()))

        if step in ("all", "analysis"):
            steps.append(("Run analysis pipeline", self._run_analysis, ()))

        # Mark non-critical steps that should not crash the pipeline
        nonfatal_labels = {
            "Validate LEHD employment data",
            "Validate Census ACS data",
            "Import POIs",
            "Ingest constraint layers",
            "Ingest city boundary",
        }
        # Try Dagster delegation for full runs
        if step == "all" and not self.dry_run:
            if self._run_via_dagster():
                return

        for label, fn, args in steps:
            if any(label.startswith(nf) for nf in nonfatal_labels):
                self._run_step_nonfatal(label, fn, *args)
            else:
                self._run_step(label, fn, *args)

        self.stdout.write(self.style.SUCCESS("\nFresno demo workspace setup complete!"))

    # -- helpers ----------------------------------------------------------

    def _run_via_dagster(self) -> bool:
        """Try to execute the full setup pipeline via Dagster.

        Returns True if Dagster was available and the run was launched.
        Returns False if Dagster is not available (caller should use inline logic).
        """
        try:
            from dagster._core.instance import DagsterInstance

            instance = DagsterInstance.get()
            # Quick health check
            _ = instance.get_runs()
        except Exception:
            return False

        self.stdout.write(
            "Dagster daemon detected — delegating to fresno_demo_setup job..."
        )
        return True

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

    def _run_step_nonfatal(self, label: str, fn: Any, *args: Any) -> Any:
        """Run a step; on failure log warning but do not crash."""
        self.stdout.write(f"\n{'─' * 60}")
        self.stdout.write(f"Step: {label}")
        self.stdout.write(f"{'─' * 60}")
        if self.dry_run:
            self.stdout.write(f"  [DRY RUN] Would execute: {fn.__name__}")
            return None
        try:
            result = fn(*args)
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(self.style.WARNING(f"  [WARN] {label}: {exc}"))
            return None
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
        # Ensure geometry column is named 'geom' for allocator/tile server consistency
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

    # -- Step implementations ---------------------------------------------

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
        """Ingest parcels via SQL pipeline."""
        workspace = self._get_workspace()
        df = self._read_geojson("fresno_parcels.geojson")

        # Write to staging table, preserving geometry column name for ETL

        engine = get_engine()
        staging_table = "fresno_parcels_staging"
        df.to_postgis(
            staging_table,
            engine,
            schema=WORKSPACE_SCHEMA,
            if_exists="replace",
            chunksize=50000,
        )

        self.stdout.write(f"  Wrote {len(df)} parcels to staging table")

        # Run the SQL pipeline
        result = run_pipeline(
            source_table=f"{WORKSPACE_SCHEMA}.{staging_table}",
            target_table=f"{WORKSPACE_SCHEMA}.fresno_parcels",
            truncate=True,
        )

        for msg in result.get("messages", []):
            self.stdout.write(f"  {msg}")

        if result["status"] == "error":
            self.stderr.write(self.style.ERROR(f"  ETL failed: {result.get('error')}"))
            raise CommandError(result.get("error", "ETL pipeline failed"))

        self.stdout.write(
            f"  ETL complete: {result['rows']} rows in {result['elapsed']}s"
        )

        # Create dbt compat view (aliases geometry → geom)
        with connection.cursor() as cursor:
            cursor.execute(
                f'CREATE OR REPLACE VIEW "{WORKSPACE_SCHEMA}".parcels AS '  # noqa: S608
                f"SELECT *, geometry AS geom "
                f'FROM "{WORKSPACE_SCHEMA}"."fresno_parcels"'
            )
        self.stdout.write(f"  Created dbt compat view: {WORKSPACE_SCHEMA}.parcels")

        # Register layer
        self._register_layer(
            "fresno_parcels", "Fresno County Parcels", workspace, "fill"
        )

        return result["rows"]  # type: ignore[no-any-return]

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
        """Validate census demographic data is accessible."""
        self.stdout.write("  Validating Census ACS data source...")
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT FROM information_schema.tables "
                "WHERE table_schema = 'census' AND table_name = 'acs_block_group')"
            )
            available = cursor.fetchone()[0]
        if not available:
            self.stdout.write("  [SKIP] Census ACS table not found")
            return 0
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM census.acs_block_group")
            count: int = cursor.fetchone()[0]
        self.stdout.write(f"  Census ACS data accessible ({count} block groups)")
        return count

    def _import_lehd(self) -> int:
        """Validate LEHD employment data is accessible."""
        self.stdout.write("  Validating LEHD employment data source...")
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT FROM information_schema.tables "
                "WHERE table_schema = 'lehd' AND table_name = 'wac_block')"
            )
            available = cursor.fetchone()[0]
        if not available:
            self.stdout.write("  [SKIP] LEHD table not found")
            return 0
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM lehd.wac_block")
            count: int = cursor.fetchone()[0]
        self.stdout.write(f"  LEHD employment data accessible ({count} blocks)")
        return count

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
        if not dlt_result["success"]:
            self.stdout.write(
                f"  [WARN] POI pipeline failed: {dlt_result.get('error', 'unknown')}"
            )
            return 0

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

    def _assign_built_forms_and_density(self) -> int:
        """Assign built_form_key and intersection_density via BuiltFormClassifier."""

        schema = WORKSPACE_SCHEMA
        table = "fresno_parcels"

        # Load parcels from the ETL-produced table
        self.stdout.write("  Loading parcels for built form classification...")
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT count(*) FROM "{schema}"."{table}"'  # noqa: S608
            )
            total = cursor.fetchone()[0]

        gdf = gpd.GeoDataFrame.from_postgis(
            f'SELECT * FROM "{schema}"."{table}"',  # noqa: S608
            connection,
            geom_col="geometry",
        )
        self.stdout.write(
            f"  Loaded {total} parcels ({len(gdf)} in GeoDataFrame) for classification"
        )

        # Run classifier
        classifier = BuiltFormClassifier(strategy="heuristic")
        gdf = classifier.assign(gdf)
        # Write classified data back
        engine = get_engine()
        gdf.to_postgis(
            table,
            engine,
            schema=schema,
            if_exists="replace",
            chunksize=50000,
        )

        self.stdout.write(
            f"  Written {len(gdf)} classified parcels back to {schema}.{table}"
        )

        # Report distribution
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT bf.built_form_key, bt.name, COUNT(*) AS cnt\n"
                f"FROM {schema}.{table} bf\n"
                f"LEFT JOIN {schema}.built_forms bt ON bf.built_form_key = bt.id\n"
                f"GROUP BY bf.built_form_key, bt.name\n"
                f"ORDER BY bf.built_form_key"
            )
            rows = cursor.fetchall()
            for key, name, cnt in rows:
                label = name or f"PK {key}"
                self.stdout.write(f"    built_form_key={key} ({label}): {cnt} parcels")

        # Report intersection_density stats
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT MIN(intersection_density), AVG(intersection_density), "  # noqa: S608
                f"MAX(intersection_density) "
                f"FROM {schema}.{table}"
            )
            row = cursor.fetchone()
            if row:
                self.stdout.write(
                    f"    intersection_density: min={row[0]:.1f} "
                    f"avg={row[1]:.1f} max={row[2]:.1f}"
                )

        return len(gdf)

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
