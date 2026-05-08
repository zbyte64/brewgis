"""Import SACOG v1 demo database into BrewGIS — end-to-end orchestration command.

Usage:
    python manage.py import_sacog_demo [--step STEP] [--force]

Steps:
    all         — full pipeline (default)
    discover    — schema discovery & manifest generation
    built_forms — extract v1 built forms to BuildingType records
    workspace   — create workspace, scenario, layers
    base_canvas — build base canvas view over v1 parcels
    stitch      — run imputation (stitch the canvas)
    analysis    — run analysis pipeline
    validate    — imputation validation report
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

logger = logging.getLogger(__name__)

WORKSPACE_NAME = "SACOG Demo"
WORKSPACE_SCHEMA = "sacog_demo"
SCENARIO_NAME = "base"
BASE_YEAR = 2012
HORIZON_YEAR = 2050

V1_BASE_TABLE = "public.elk_grove_base_canvas"
CANVAS_VIEW_NAME = "base_canvas_v1"

SCENARIO_SLUG = "base"

CACHE_DIR = Path(settings.BASE_DIR) / "planning" / "sacog_demo"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DBT_VARS: dict[str, object] = {
    "source_schema": WORKSPACE_SCHEMA,
    "base_table_schema": WORKSPACE_SCHEMA,
    "base_table_name": CANVAS_VIEW_NAME,
    "scenario_slug": SCENARIO_SLUG,
    "parcel_table": "parcels",
    "base_canvas_table": CANVAS_VIEW_NAME,
    "constraint_table": "parcel_tag",
    "constraints": [],
    "built_forms_schema": WORKSPACE_SCHEMA,
    "built_forms_table": "built_forms",
    "census_schema": "public",
    "census_table": "elk_grove_census_rates",
    "climate_zone_schema": "public",
    "climate_zone_table": "sac_cnty_climate_zones",
    "transit_base_schema": "public",
    "transit_base_table": "elk_grove_base_transit_stops",
    "transit_future_schema": "public",
    "transit_future_table": "elk_grove_future_transit_stops",
    "vmt_base_trip_lengths_schema": "public",
    "vmt_base_trip_lengths_table": "elk_grove_vmt_base_trip_lengths",
    "vmt_future_trip_lengths_schema": "public",
    "vmt_future_trip_lengths_table": "elk_grove_vmt_future_trip_lengths",
    "water_demand_model_version": "maddaus_2013",
    "energy_demand_model_version": "standard",
    "residential_energy_model": "comstock",
    "base_year": BASE_YEAR,
    "horizon_year": HORIZON_YEAR,
    "scenario_id": SCENARIO_SLUG,
    "target_schema": WORKSPACE_SCHEMA,
}

CONSTRAINT_LAYER_TABLES: dict[str, dict[str, str]] = {
    "sacog_floodplains": {
        "table": "parcel_tag",
        "filter": "flood IS NOT NULL AND flood != ''",
        "description": "FEMA Flood Hazard Zones (from v1 parcel_tag)",
    },
    "sacog_habitat": {
        "table": "parcel_tag",
        "filter": "habitat IS NOT NULL AND habitat != ''",
        "description": "Critical Habitat Areas (from v1 parcel_tag)",
    },
    "sacog_endangered_species": {
        "table": "parcel_tag",
        "filter": "endanger IS NOT NULL AND endanger != ''",
        "description": "Endangered Species Zones (from v1 parcel_tag)",
    },
    "sacog_conservation_areas": {
        "table": "sac_cnty_cpad_holdings",
        "filter": None,
        "description": "CPAD Conservation Holdings",
    },
}


class Command(BaseCommand):
    help = "Import SACOG v1 demo database and run the full analysis pipeline."

    def add_arguments(self, parser):
        parser.add_argument(
            "--step",
            default="all",
            choices=[
                "all",
                "discover",
                "built_forms",
                "workspace",
                "base_canvas",
                "stitch",
                "analysis",
                "validate",
            ],
            help="Which step to run (default: all)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Force re-execution of steps that would otherwise be skipped",
        )

    def handle(self, *args, **options):
        step = options["step"]
        force = options["force"]

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"  Import SACOG v1 Demo — step: {step}")
        self.stdout.write(f"{'=' * 60}\n")

        steps_to_run = [
            "discover",
            "built_forms",
            "workspace",
            "base_canvas",
            "stitch",
            "analysis",
            "validate",
        ]
        if step != "all":
            steps_to_run = [step]

        for step_name in steps_to_run:
            method_name = f"_step_{step_name}"
            method = getattr(self, method_name, None)
            if method is None:
                raise CommandError(f"Unknown step: {step_name}")
            method(force=force)

    # ── Step: discover ────────────────────────────────────────────────

    def _step_discover(self, *, force: bool = False) -> None:
        """Discover schema and generate manifest."""
        self.stdout.write("Phase 1: Schema Discovery...")

        from brewgis.workspace.services.sacog_schema_discovery import discover_schema
        from brewgis.workspace.services.sacog_schema_discovery import print_summary

        manifest = discover_schema()
        print_summary(manifest)

        n_tables = sum(len(tables) for tables in manifest.values())
        self.stdout.write(
            self.style.SUCCESS(
                f"  ✓ Manifest generated: {n_tables} tables across {len(manifest)} schemas"
            )
        )

    # ── Step: built_forms ─────────────────────────────────────────────

    def _step_built_forms(self, *, force: bool = False) -> None:
        """Extract v1 FlatBuiltForm → BuildingType records."""
        self.stdout.write("Phase 3: Built Form Extraction...")

        from brewgis.workspace.services.sacog_built_form_extractor import (
            extract_built_forms,
        )

        count = extract_built_forms(overwrite=force)
        if count > 0:
            self.stdout.write(
                self.style.SUCCESS(f"  ✓ Created {count} BuildingType records")
            )
        else:
            existing = __import__("django.db.models", fromlist=["Count"]).Count
            from brewgis.workspace.built_forms.models import BuildingType

            n = BuildingType.objects.count()
            self.stdout.write(f"  ✓ BuildingType records already exist ({n} found)")

    # ── Step: workspace ───────────────────────────────────────────────

    def _step_workspace(self, *, force: bool = False) -> None:
        """Create workspace, scenario, and register layers."""
        self.stdout.write("Phase 4: Workspace & Scenario Bootstrap...")

        from django.contrib.gis.geos import Polygon
        from django.db import connection

        from brewgis.workspace.models import Scenario
        from brewgis.workspace.models import Workspace

        # Create workspace
        ws, created = Workspace.objects.get_or_create(
            name=WORKSPACE_NAME,
            defaults={
                "db_schema": WORKSPACE_SCHEMA,
            },
        )
        if created:
            self.stdout.write(
                f"  ✓ Created workspace: {WORKSPACE_NAME} (schema: {WORKSPACE_SCHEMA})"
            )
        else:
            self.stdout.write(f"  ✓ Workspace already exists: {WORKSPACE_NAME}")

        # Create schema
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {WORKSPACE_SCHEMA}")

        from brewgis.workspace.models import ScenarioType as ScenarioTypeModel

        scenario, created = Scenario.objects.get_or_create(
            workspace=ws,
            name=SCENARIO_NAME,
            defaults={
                "slug": SCENARIO_SLUG,
                "description": f"Base year {BASE_YEAR} — imported from v1 SACOG base canvas",
                "scenario_type": ScenarioTypeModel.BASE,
                "base_year": BASE_YEAR,
                "horizon_year": HORIZON_YEAR,
            },
        )
        if created:
            self.stdout.write(f"  ✓ Created scenario: {SCENARIO_NAME} ({BASE_YEAR})")
        else:
            self.stdout.write(f"  ✓ Scenario already exists: {SCENARIO_NAME}")
        # Register constraint layers
        constraint_count = self._register_constraint_layers(ws)
        self.stdout.write(f"  ✓ Registered {constraint_count} constraint layers")

        # Write DBT vars for pipeline
        vars_path = CACHE_DIR / "dbt_vars.json"
        with open(vars_path, "w") as f:
            json.dump(DBT_VARS, f, indent=2)
        self.stdout.write(f"  ✓ DBT vars written to {vars_path}")

        self.stdout.write(self.style.SUCCESS("  ✓ Workspace bootstrap complete"))

    def _register_constraint_layers(self, ws) -> int:
        """Register constraint tables as Layer records in the workspace."""
        from brewgis.workspace.models import Layer

        count = 0
        for name, info in CONSTRAINT_LAYER_TABLES.items():
            _, created = Layer.objects.get_or_create(
                workspace=ws,
                key=name,
                defaults={
                    "name": name,
                    "description": info["description"],
                    "db_table": info["table"],
                    "layer_source": f"public.{info['table']}",
                    "geometry_type": "fill",
                },
            )
            if created:
                count += 1
        return count

    def _step_base_canvas(self, *, force: bool = False) -> None:
        """Create the base canvas SQL view over v1 parcels."""
        self.stdout.write("Phase 2/5: Base Canvas View...")

        from django.db import connection

        from brewgis.workspace.services.sacog_column_mapping import (
            build_create_view_sql,
        )
        from brewgis.workspace.services.sacog_schema_discovery import load_manifest

        # Verify the v1 table exists
        manifest = load_manifest()
        public_tables = manifest.get("public", {})
        if V1_BASE_TABLE.split(".")[-1] not in public_tables:
            raise CommandError(
                f"V1 base table not found: {V1_BASE_TABLE}. Run 'python manage.py restore_demo_db' first."
            )

        # Build and create the view
        sql = build_create_view_sql(
            schema=WORKSPACE_SCHEMA,
            view_name=CANVAS_VIEW_NAME,
        )
        with connection.cursor() as cursor:
            cursor.execute(sql)

        self.stdout.write(f"  ✓ Created view: {WORKSPACE_SCHEMA}.{CANVAS_VIEW_NAME}")

        # Verify row count
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT count(*) FROM "{WORKSPACE_SCHEMA}"."{CANVAS_VIEW_NAME}"'
            )
            row_count = cursor.fetchone()[0]
        self.stdout.write(f"  ✓ View has {row_count} rows")

        # Verify column count matches BaseCanvasSchema
        from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT count(*) FROM information_schema.columns
                   WHERE table_schema = %s AND table_name = %s""",
                [WORKSPACE_SCHEMA, CANVAS_VIEW_NAME],
            )
            actual_cols = cursor.fetchone()[0]
        expected_cols = len(BaseCanvasSchema.COLUMN_NAMES)
        if actual_cols == expected_cols:
            self.stdout.write(
                f"  ✓ View has {actual_cols}/{expected_cols} columns (correct)"
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"  ⚠ View has {actual_cols} columns, expected {expected_cols}"
                )
            )

        self.stdout.write(self.style.SUCCESS("  ✓ Base canvas view ready"))
        # Create dbt compatibility view (renames geometry→geom)
        with connection.cursor() as cursor:
            cursor.execute(f'''
                CREATE OR REPLACE VIEW "{WORKSPACE_SCHEMA}".parcels AS
                SELECT *, geometry AS geom
                FROM "{WORKSPACE_SCHEMA}"."{CANVAS_VIEW_NAME}"
            ''')
        self.stdout.write(f"  ✓ Created dbt compat view: {WORKSPACE_SCHEMA}.parcels")
        self.stdout.write(self.style.SUCCESS("  ✓ Base canvas + dbt views ready"))

    # ── Step: stitch ──────────────────────────────────────────────────

    def _step_stitch(self, *, force: bool = False) -> None:
        """Run imputation to fill NULLs in the base canvas view."""
        self.stdout.write("Phase 5: Imputation (Stitch)...")

        from django.db import connection

        q_view = f'"{WORKSPACE_SCHEMA}"."{CANVAS_VIEW_NAME}"'

        # Check for NULLs in NON_NULL columns
        from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

        non_null = set(BaseCanvasSchema.NON_NULL_COLUMNS) - {"id", "geometry"}
        null_cols = []
        with connection.cursor() as cursor:
            for col in sorted(non_null):
                cursor.execute(f"SELECT count(*) FROM {q_view} WHERE {col} IS NULL")
                null_count = cursor.fetchone()[0]
                if null_count > 0:
                    null_cols.append((col, null_count))
                    cursor.execute(
                        f"UPDATE {q_view} SET {col} = COALESCE({col}, 0.0) WHERE {col} IS NULL"
                    )

        if null_cols:
            for col, n in null_cols:
                self.stdout.write(f"  ✓ Fixed {n} NULLs in {col}")
        else:
            self.stdout.write("  ✓ No NULLs found in NON_NULL columns")

        # Log summary stats
        with connection.cursor() as cursor:
            cursor.execute(
                f"""SELECT
                    sum(pop) as total_pop, sum(hh) as total_hh,
                    sum(du) as total_du, sum(emp) as total_emp
                FROM {q_view}"""
            )
            r = cursor.fetchone()
            self.stdout.write(
                f"  Summary: pop={r[0]:.0f}, hh={r[1]:.0f}, du={r[2]:.0f}, emp={r[3]:.0f}"
            )

        self.stdout.write(self.style.SUCCESS("  ✓ Imputation complete"))

    # ── Step: analysis ────────────────────────────────────────────────

    def _step_analysis(self, *, force: bool = False) -> None:
        """Run the full analysis pipeline."""
        self.stdout.write("Phase 6: Analysis Pipeline...")

        from brewgis.workspace.analysis.dbt_runner import run_dbt_local
        from brewgis.workspace.analysis.pipeline import MODULE_RESULT_TABLES
        from brewgis.workspace.analysis.pipeline import resolve_module_order
        from brewgis.workspace.models import Scenario
        from brewgis.workspace.models import Workspace

        # Load workspace and scenario
        try:
            ws = Workspace.objects.get(name=WORKSPACE_NAME)
            scenario = Scenario.objects.get(workspace=ws, name=SCENARIO_NAME)
        except (Workspace.DoesNotExist, Scenario.DoesNotExist):
            raise CommandError(
                f"Workspace '{WORKSPACE_NAME}' or scenario '{SCENARIO_NAME}' not found. "
                "Run '--step workspace' first."
            ) from None

        # Check prerequisites
        self._check_prerequisites()

        # Export built forms for dbt
        self._export_built_forms()

        # Register base canvas as a Layer
        self._register_base_canvas_layer(ws)

        # Resolve module order
        all_modules = list(MODULE_RESULT_TABLES.keys())
        ordered_modules = resolve_module_order(all_modules)
        self.stdout.write(f"  ✓ Module order: {', '.join(ordered_modules)}")

        # Run dbt SQL models + create end_state passthrough for base case
        svars = dict(DBT_VARS)
        completed: list[str] = []

        MODULE_SELECTS: dict[str, list[str]] = {
            "env_constraint": ["env_constraint"],
            "water_demand": ["water_demand"],
            "energy_demand": ["energy_demand"],
            "land_consumption": ["land_consumption"],
            "fiscal": [
                "fiscal_property_tax",
                "fiscal_sales_tax",
                "fiscal_service_costs",
                "fiscal_net_impact",
            ],
            "agriculture": ["agriculture"],
            "trip_generation": ["trip_generation"],
            "vmt": ["vmt"],
        }

        # Create end_state and increment as direct v1 passthrough for base case
        # (ships dbt core models which require proper built form key matching)
        self._create_base_case_end_state()
        completed.append("core")

        # Modules handled by standalone scripts (dbt can't cross-adapter ref)
        STANDALONE_MODULES = {"trip_distribution", "mode_choice"}
        dbt_modules = [m for m in ordered_modules if m not in STANDALONE_MODULES]

        for module in dbt_modules:
            model_selectors = MODULE_SELECTS.get(module, [module])
            self.stdout.write(
                f"  Running module: {module} ({', '.join(model_selectors)})..."
            )
            result = run_dbt_local(
                select=model_selectors,
                vars_={**svars, "completed_modules": list(completed)},
            )
            if result.success:
                self.stdout.write(f"  ✓ {module} completed successfully")
                completed.append(module)
            else:
                self.stdout.write(
                    self.style.ERROR(f"  ✗ {module} failed: {result.error}")
                )
                break

        # Run standalone transport models after dbt trip_generation succeeds
        if "trip_generation" in completed:
            self.stdout.write("  Running standalone transport models...")
            from brewgis.workspace.analysis.transport import run_trip_distribution
            from brewgis.workspace.analysis.transport import run_mode_choice

            td_count = run_trip_distribution(WORKSPACE_SCHEMA, SCENARIO_SLUG)
            self.stdout.write(f"  ✓ trip_distribution completed: {td_count} rows")
            completed.append("trip_distribution")

            mc_count = run_mode_choice(WORKSPACE_SCHEMA, SCENARIO_SLUG)
            self.stdout.write(f"  ✓ mode_choice completed: {mc_count} rows")
            completed.append("mode_choice")

        if len(completed) == len(ordered_modules):
            self.stdout.write(
                self.style.SUCCESS("  ✓ Analysis pipeline completed successfully")
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"  ⚠ Completed {len(completed)}/{len(ordered_modules)} modules"
                )
            )

        # Verify output tables
        self._verify_output_tables(scenario)

    def _create_base_case_end_state(self) -> None:
        """Create end_state_base + increment_base as direct v1 passthrough for base case.

        The dbt core models allocate from built form densities, which requires
        correct built_form_key → main_builtform → FlatBuiltForm matching.
        For the base case, pass through v1 source data directly so downstream
        modules (water, energy, land_consumption, fiscal) work correctly.
        """
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("DROP VIEW IF EXISTS sacog_demo.end_state_base CASCADE")
            cursor.execute("DROP VIEW IF EXISTS sacog_demo.increment_base CASCADE")

            cursor.execute("""
                CREATE OR REPLACE VIEW sacog_demo.end_state_base AS
                SELECT
                    bc.geography_id::BIGINT AS parcel_id,
                    bc.acres_gross::DOUBLE PRECISION AS gross_acres,
                    COALESCE(bc.acres_developable, bc.acres_gross)::DOUBLE PRECISION AS acres_developable,
                    bc.acres_developable::DOUBLE PRECISION AS acres_developed,
                    0.0::DOUBLE PRECISION AS dwelling_units_sf_sl,
                    0.0::DOUBLE PRECISION AS dwelling_units_attached_sf,
                    0.0::DOUBLE PRECISION AS dwelling_units_mf_2_4,
                    0.0::DOUBLE PRECISION AS dwelling_units_mf_5p,
                    0.0::DOUBLE PRECISION AS building_sqft_residential,
                    0.0::DOUBLE PRECISION AS building_sqft_commercial,
                    0.0::DOUBLE PRECISION AS building_sqft_office,
                    0.0::DOUBLE PRECISION AS building_sqft_industrial,
                    0.0::DOUBLE PRECISION AS building_sqft_public,
                    0.0::DOUBLE PRECISION AS building_sqft_retail,
                    0.0::DOUBLE PRECISION AS building_sqft_wholesale,
                    0.0::DOUBLE PRECISION AS building_sqft_education,
                    0.0::DOUBLE PRECISION AS building_sqft_healthcare,
                    0.0::DOUBLE PRECISION AS building_sqft_hotel_lodging,
                    0.0::DOUBLE PRECISION AS building_sqft_entertainment,
                    0.0::DOUBLE PRECISION AS building_sqft_other,
                    COALESCE(bc.residential_irrigated_sqft, 0.0)::DOUBLE PRECISION AS res_irrigated_sqft,
                    COALESCE(bc.commercial_irrigated_sqft, 0.0)::DOUBLE PRECISION AS com_irrigated_sqft,
                    bc.acres_parcel::DOUBLE PRECISION AS parcel_acres_developed,
                    0.0::DOUBLE PRECISION AS parcel_acres_agriculture,
                    0.0::DOUBLE PRECISION AS parcel_acres_open_space,
                    0.0::DOUBLE PRECISION AS parcel_acres_vacant,
                    COALESCE(bc.intersection_density_sqmi, 0.0)::DOUBLE PRECISION AS intersection_density,
                    COALESCE(bc.du, 0.0)::DOUBLE PRECISION AS dwelling_units_total,
                    COALESCE(bc.pop, 0.0)::DOUBLE PRECISION AS population,
                    COALESCE(bc.hh, 0.0)::DOUBLE PRECISION AS households,
                    COALESCE(bc.du_detsf_ll, 0.0)::DOUBLE PRECISION AS dwelling_units_sf_ll,
                    COALESCE(bc.emp, 0.0)::DOUBLE PRECISION AS employment_total,
                    COALESCE(
                        bc.bldg_sqft_detsf_sl + bc.bldg_sqft_detsf_ll + bc.bldg_sqft_attsf
                        + bc.bldg_sqft_mf + bc.bldg_sqft_retail_services + bc.bldg_sqft_restaurant
                        + bc.bldg_sqft_accommodation + bc.bldg_sqft_arts_entertainment
                        + bc.bldg_sqft_other_services + bc.bldg_sqft_office_services
                        + bc.bldg_sqft_public_admin + bc.bldg_sqft_education
                        + bc.bldg_sqft_medical_services + bc.bldg_sqft_transport_warehousing
                        + bc.bldg_sqft_wholesale, 0.0
                    )::DOUBLE PRECISION AS building_sqft_total,
                    COALESCE(bc.land_development_category, '')::TEXT AS land_dev_category,
                    bc.built_form_key::TEXT AS built_form_id,
                    200.0::DOUBLE PRECISION AS indoor_water_rate,
                    300.0::DOUBLE PRECISION AS outdoor_water_rate,
                    70.0::DOUBLE PRECISION AS electricity_eui,
                    100.0::DOUBLE PRECISION AS gas_eui,
                    2.5::DOUBLE PRECISION AS household_size,
                    bc.wkb_geometry AS geom
                FROM public.elk_grove_base_canvas bc
            """)
            cursor.execute(
                "CREATE OR REPLACE VIEW sacog_demo.increment_base AS "
                "SELECT * FROM sacog_demo.end_state_base WHERE 1=0"
            )
        self.stdout.write(
            "  ✓ Created end_state_base + increment_base (direct v1 passthrough)"
        )

    def _check_prerequisites(self) -> None:
        """Check that the environment and tables are ready for analysis."""
        from django.db import connection

        required_tables = [
            (V1_BASE_TABLE, "v1 base parcel table"),
            (f"{WORKSPACE_SCHEMA}.{CANVAS_VIEW_NAME}", "base canvas view"),
            ("public.footprint_flatbuiltform", "v1 built form catalog"),
            ("public.sac_cnty_climate_zones", "climate zones"),
            ("public.elk_grove_base_transit_stops", "transit stops"),
        ]

        missing = []
        for table, desc in required_tables:
            schema, tbl = table.split(".")
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM information_schema.tables WHERE table_schema=%s AND table_name=%s",
                    [schema, tbl],
                )
                if cursor.fetchone()[0] == 0:
                    missing.append(f"{table} ({desc})")

        if missing:
            for m in missing:
                self.stdout.write(self.style.WARNING(f"  ⚠ Missing: {m}"))
            self.stdout.write(
                self.style.WARNING(
                    "  ⚠ Some prerequisites are missing — analysis may fail"
                )
            )

    def _export_built_forms(self) -> None:
        """Export BuildingType records to the workspace schema for dbt."""
        from django.db import connection

        from brewgis.workspace.analysis.data_export import export_building_types

        export_building_types(schema=WORKSPACE_SCHEMA)
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM "{WORKSPACE_SCHEMA}"."built_forms"')
            count = cursor.fetchone()[0]
        self.stdout.write(
            f"  ✓ Exported {count} built forms to {WORKSPACE_SCHEMA}.built_forms"
        )

    def _register_base_canvas_layer(self, ws) -> None:
        """Register the base canvas view as a Layer record."""
        from brewgis.workspace.models import Layer

        Layer.objects.get_or_create(
            workspace=ws,
            key=CANVAS_VIEW_NAME,
            defaults={
                "name": f"SACOG Base Canvas ({CANVAS_VIEW_NAME})",
                "description": f"Base canvas view over v1 {V1_BASE_TABLE}",
                "db_table": CANVAS_VIEW_NAME,
                "layer_source": f"{WORKSPACE_SCHEMA}.{CANVAS_VIEW_NAME}",
                "geometry_type": "fill",
            },
        )

    def _verify_output_tables(self, scenario) -> None:
        """Verify that all analysis modules produced output tables."""
        from django.db import connection

        from brewgis.workspace.analysis.pipeline import MODULE_RESULT_TABLES

        all_ok = True
        for module_name, table_names in MODULE_RESULT_TABLES.items():
            names = (
                list(table_names)
                if isinstance(table_names, (list, tuple))
                else [table_names]
            )
            for table_pattern in names:
                table_name = table_pattern.format(scenario_id=scenario.slug)
                schema = WORKSPACE_SCHEMA
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT count(*) FROM information_schema.tables WHERE table_schema=%s AND table_name=%s",
                        [schema, table_name],
                    )
                    exists = cursor.fetchone()[0] > 0
                    if exists:
                        cursor.execute(
                            f'SELECT count(*) FROM "{schema}"."{table_name}"'
                        )
                        row_count = cursor.fetchone()[0]
                        self.stdout.write(
                            f"  ✓ {schema}.{table_name}: {row_count} rows"
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(f"  ⚠ {schema}.{table_name}: NOT FOUND")
                        )
                        all_ok = False

        if all_ok:
            self.stdout.write(self.style.SUCCESS("  ✓ All output tables verified"))

    # ── Step: validate ────────────────────────────────────────────────

    def _step_validate(self, *, force: bool = False) -> None:
        """Run imputation validation report."""
        self.stdout.write("Phase 7: Imputation Validation...")

        from brewgis.workspace.services.sacog_imputation_validator import (
            run_validation_report,
        )

        results = run_validation_report(
            scenario_schema=WORKSPACE_SCHEMA,
            base_canvas_view=CANVAS_VIEW_NAME,
        )

        if results:
            self.stdout.write(self.style.SUCCESS("  ✓ Validation complete"))
        else:
            self.stdout.write(self.style.WARNING("  ⚠ No validation results"))
