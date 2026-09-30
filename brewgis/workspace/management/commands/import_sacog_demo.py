"""Import SACOG v1 demo database into BrewGIS — end-to-end orchestration command.

Usage:
    python manage.py import_sacog_demo [--step STEP] [--force]

Steps:
    all         — full pipeline (default)
    discover    — schema discovery & manifest generation
    built_forms — complete the Building Type library, then extract the v1 built forms
    workspace   — create workspace, scenario, layers
    base_canvas — materialize the base canvas table over the v1 parcels
    analysis    — run analysis pipeline
    validate    — imputation validation report

The base canvas is a *table* materialized with
``sacog_column_mapping.build_materialized_select_sql``, the same projection
``materialize_sacog_base_canvas`` loads its adoptable canvas from: every column
is cast to the type ``BaseCanvasSchema`` declares, the parcel key is the source
``geography_id`` and the geometry is reprojected from the source CRS (3310) to
the contract's ``GEOMETRY(MultiPolygon, 4326)``. That is what makes the table
tileable, adoptable through the base canvas picker, and readable by the
blueprinted analysis models — and it fills the contract's NOT NULL columns as it
loads, so it needs no separate NULL-filling pass.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

logger = logging.getLogger(__name__)

WORKSPACE_NAME = "SACOG Demo"
WORKSPACE_SCHEMA = "sacog_demo"
SCENARIO_NAME = "base"
BASE_YEAR = 2012
HORIZON_YEAR = 2050

V1_BASE_TABLE = "public.elk_grove_base_canvas"
BASE_CANVAS_TABLE = "base_canvas_v1"

SCENARIO_SLUG = "base"

CONSTRAINT_LAYER_TABLES: dict[str, dict[str, str]] = {
    "sacog_floodplains": {
        "table": "parcel_tag",
        "description": "FEMA Flood Hazard Zones (from v1 parcel_tag)",
    },
    "sacog_habitat": {
        "table": "parcel_tag",
        "description": "Critical Habitat Areas (from v1 parcel_tag)",
    },
    "sacog_endangered_species": {
        "table": "parcel_tag",
        "description": "Endangered Species Zones (from v1 parcel_tag)",
    },
    "sacog_conservation_areas": {
        "table": "sac_cnty_cpad_holdings",
        "description": "CPAD Conservation Holdings",
    },
}


class Command(BaseCommand):
    help = "Import SACOG v1 demo database and run the full analysis pipeline."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--step",
            default="all",
            choices=[
                "all",
                "discover",
                "built_forms",
                "workspace",
                "base_canvas",
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

    def handle(self, *args: Any, **options: Any) -> None:
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
        """Report the schemas and tables the restored v1 dump holds."""
        self.stdout.write("Phase 1: Schema Discovery...")

        from brewgis.workspace.services.sacog_schema_discovery import discover_schema
        from brewgis.workspace.services.sacog_schema_discovery import print_summary

        manifest = discover_schema()
        print_summary(manifest)

        n_tables = sum(len(tables) for tables in manifest.values())
        self.stdout.write(
            self.style.SUCCESS(
                f"  ✓ Discovered {n_tables} tables across {len(manifest)} schemas"
            )
        )

    # ── Step: built_forms ─────────────────────────────────────────────

    def _step_built_forms(self, *, force: bool = False) -> None:
        """Complete the Building Type library, then extract the v1 built forms."""
        self.stdout.write("Phase 3: Built Form Extraction...")

        from brewgis.workspace.built_forms.default_library import (
            backfill_library_fields,
        )
        from brewgis.workspace.built_forms.default_library import (
            seed_default_built_forms,
        )
        from brewgis.workspace.built_forms.models import BuildingType
        from brewgis.workspace.services.sacog_built_form_extractor import (
            extract_built_forms,
        )

        workspace = self._resolve_workspace()

        # ``--force`` rebuilds the catalogue from scratch: wipe first, so the
        # library is re-seeded onto a clean workspace rather than the wipe
        # landing after it and leaving the 29 v1 keys with no library beside
        # them.
        if force:
            deleted, _ = BuildingType.objects.filter(workspace=workspace).delete()
            self.stdout.write(f"  ✓ Cleared {deleted} existing Building Type rows")

        # The library is seeded before the extraction, and that order is
        # load-bearing. A Building Type answers for a canvas key by name
        # (``services.built_form_keys``): the library's entries are named for the
        # land uses, and 14 of the demo's 29 keys normalize onto one of those
        # names, so the library already answers for them. The extraction then
        # adds an entry only for the keys nothing answers for. Run the other way
        # round, the extraction would claim all 29 keys first and the seeding
        # that followed would add the library's own names beside them — two
        # Building Types matching one key, and every parcel carrying it counted
        # twice by ``core_end_state``.
        seeded = seed_default_built_forms(workspace)
        backfilled = backfill_library_fields(workspace)
        self.stdout.write(f"  ✓ Library: {seeded} seeded, {backfilled} realigned")

        count = extract_built_forms(workspace)
        total = BuildingType.objects.filter(workspace=workspace).count()
        self.stdout.write(
            f"  ✓ Extracted {count} SACOG v1 built forms; "
            f"{total} Building Types in the workspace"
        )

    def _resolve_workspace(self) -> Any:
        """Get-or-create the demo workspace, pointed at this demo's base canvas.

        Get-or-create rather than create because ``built_forms`` and
        ``base_canvas`` may run before the ``workspace`` step. An existing
        workspace is repaired rather than left alone: one left on the
        ``base_table`` column's default (``public.base_canvas``) has the analysis
        blueprints read a canvas that has nothing to do with this demo.
        """
        from brewgis.workspace.models import Workspace

        base_table = f"{WORKSPACE_SCHEMA}.{BASE_CANVAS_TABLE}"
        workspace, _created = Workspace.objects.get_or_create(
            name=WORKSPACE_NAME,
            defaults={
                "db_schema": WORKSPACE_SCHEMA,
                "base_table": base_table,
            },
        )
        if (workspace.db_schema, workspace.base_table) != (
            WORKSPACE_SCHEMA,
            base_table,
        ):
            workspace.db_schema = WORKSPACE_SCHEMA
            workspace.base_table = base_table
            workspace.save(update_fields=["db_schema", "base_table"])
        return workspace

    # ── Step: workspace ───────────────────────────────────────────────

    def _step_workspace(self, *, force: bool = False) -> None:
        """Create workspace, scenario, and register layers."""
        self.stdout.write("Phase 4: Workspace & Scenario Bootstrap...")

        from django.db import connection

        from brewgis.workspace.models import Scenario

        ws = self._resolve_workspace()
        self.stdout.write(
            f"  ✓ Workspace: {WORKSPACE_NAME} (schema: {WORKSPACE_SCHEMA}, "
            f"base table: {ws.base_table})"
        )

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

        self.stdout.write(self.style.SUCCESS("  ✓ Workspace bootstrap complete"))

    def _register_constraint_layers(self, ws: Any) -> int:
        """Register constraint tables as Layer records in the workspace."""
        from brewgis.workspace.models import Layer

        count = 0
        for name, info in CONSTRAINT_LAYER_TABLES.items():
            layer, created = Layer.objects.get_or_create(
                workspace=ws,
                key=name,
                defaults={
                    "name": name,
                    "description": info["description"],
                    "db_table": info["table"],
                    # The v1 constraint tables live in ``public``, not in the
                    # workspace schema: a blank ``db_schema`` would inherit
                    # ``sacog_demo`` and point the layer at a table that does
                    # not exist.
                    "db_schema": "public",
                    "layer_source": f"public.{info['table']}",
                    "geometry_type": "fill",
                },
            )
            if created:
                count += 1
            elif layer.db_schema != "public":
                # Registered by an earlier run that left the schema blank, so it
                # inherited the workspace schema and resolves to a table that
                # does not exist.
                layer.db_schema = "public"
                layer.save(update_fields=["db_schema"])
        return count

    def _step_base_canvas(self, *, force: bool = False) -> None:
        """Materialize the base canvas table over the v1 parcels."""
        self.stdout.write("Phase 2/5: Base Canvas Materialization...")

        from django.core.management import call_command

        # The projection, the DDL and the contract verification are
        # ``materialize_sacog_base_canvas``'s — one implementation of "a v1 table
        # as an adoptable base canvas", not a second one here. It also verifies
        # the result against the projection column by column and checks that the
        # base canvas picker will offer it, neither of which this command would
        # get around to.
        target = f"{WORKSPACE_SCHEMA}.{BASE_CANVAS_TABLE}"
        call_command(
            "materialize_sacog_base_canvas",
            source_table=V1_BASE_TABLE,
            target_table=target,
            replace=force,
            stdout=self.stdout,
        )

        self._register_base_canvas_layer(self._resolve_workspace())
        self._promote_base_canvas_model(target)
        self.stdout.write(self.style.SUCCESS("  ✓ Base canvas ready"))

    def _promote_base_canvas_model(self, target: str) -> None:
        """Promote the base canvas's model into ``prod`` so the analysis can read it.

        The analysis reads the workspace's parcels by the canvas's *model* name
        (``sqlmesh/macros/analysis_blueprints.py``: the base canvas, whichever
        layer that is) and SQLMesh resolves such a name against its
        *environments*, not against the project: the declaration in
        ``sqlmesh/external_models.yaml`` says which physical table the name
        stands for, but a snapshot that was never promoted is still unknown to
        ``ExecutionContext.resolve_table`` — which every Python analysis model
        calls for its inputs at plan time, whether or not it ends up reading
        them. So the canvas has to be promoted once, before the first plan that
        names it; ``pipeline._network_distance_inputs`` selects the region road
        networks it routes over for the same reason.

        Nothing is built or restated: the rows are already in the table this
        model stands for, and re-promoting an unchanged snapshot is a no-op.
        """
        from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan

        run_sqlmesh_plan(
            environment="prod",
            select=[f"brewgis.{target}"],
            skip_tests=True,
            auto_apply=True,
            no_prompts=True,
        )
        self.stdout.write(f"  ✓ Promoted brewgis.{target} into prod")

    # ── Step: analysis ────────────────────────────────────────────────

    def _step_analysis(self, *, force: bool = False) -> None:
        """Run the full analysis pipeline."""
        self.stdout.write("Phase 5: Analysis Pipeline...")

        from brewgis.workspace.analysis.pipeline import MODULE_RESULT_TABLES
        from brewgis.workspace.analysis.pipeline import resolve_module_order
        from brewgis.workspace.analysis.pipeline import run_analysis_pipeline
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

        # Export built forms for analysis pipeline
        self._export_built_forms(ws)

        # Resolve module order
        all_modules = list(MODULE_RESULT_TABLES.keys())
        ordered_modules = resolve_module_order(all_modules)
        self.stdout.write(f"  ✓ Module order: {', '.join(ordered_modules)}")

        # Record the run before planning: each scenario's analysis models are
        # blueprinted, and the blueprint set comes from the scenarios that have
        # an AnalysisRun (see sqlmesh/macros/analysis_blueprints.py), so the run
        # has to exist before the plan loads the project. The plan itself reads
        # every input off the Scenario and the Workspace — there are no plan-time
        # variables to pass.
        run = run_analysis_pipeline(
            scenario_id=scenario.pk,
            module_names=ordered_modules,
        )
        if run.status == "completed":
            self.stdout.write(
                self.style.SUCCESS("  ✓ Analysis pipeline completed successfully")
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"  ⚠ Analysis run #{run.pk} {run.status}: "
                    f"{run.failure_cause or 'see the run log'}"
                )
            )

        # Verify output tables
        self._verify_output_tables(scenario)

    def _check_prerequisites(self) -> None:
        """Check that the environment and tables are ready for analysis."""
        from django.db import connection

        required_tables = [
            (V1_BASE_TABLE, "v1 base parcel table"),
            (
                f"{WORKSPACE_SCHEMA}.{BASE_CANVAS_TABLE}",
                "materialized base canvas table",
            ),
            ("public.sacog_building_types_may14", "SACOG v1 built-type catalogue"),
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

    def _export_built_forms(self, ws: Any) -> None:
        """Export BuildingType records to the workspace schema."""
        from django.db import connection

        from brewgis.workspace.analysis.data_export import export_building_types

        export_building_types(workspace=ws, schema=WORKSPACE_SCHEMA)
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM "{WORKSPACE_SCHEMA}"."built_forms"')
            count = cursor.fetchone()[0]
        self.stdout.write(
            f"  ✓ Exported {count} built forms to {WORKSPACE_SCHEMA}.built_forms"
        )

    def _register_base_canvas_layer(self, ws: Any) -> None:
        """Register the materialized base canvas as a Layer record."""
        from brewgis.workspace.models import Layer

        Layer.objects.get_or_create(
            workspace=ws,
            key=BASE_CANVAS_TABLE,
            defaults={
                "name": f"SACOG Base Canvas ({BASE_CANVAS_TABLE})",
                "description": f"Base canvas materialized from v1 {V1_BASE_TABLE}",
                "db_table": BASE_CANVAS_TABLE,
                # Left blank it would inherit the workspace schema, which is
                # where the table is — stating it keeps the layer readable even
                # if the workspace's ``db_schema`` is repointed later.
                "db_schema": WORKSPACE_SCHEMA,
                "layer_source": f"{WORKSPACE_SCHEMA}.{BASE_CANVAS_TABLE}",
                "geometry_type": "fill",
            },
        )

    def _verify_output_tables(self, scenario: Any) -> None:
        """Verify that all analysis modules produced output tables."""
        from django.db import connection

        from brewgis.workspace.analysis.module_registry import get_result_table_names
        from brewgis.workspace.analysis.pipeline import MODULE_RESULT_TABLES

        all_ok = True
        for module_name in MODULE_RESULT_TABLES:
            for qualified in get_result_table_names(module_name, scenario.pk):
                schema, _, table_name = qualified.partition(".")
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
        self.stdout.write("Phase 6: Imputation Validation...")

        from brewgis.workspace.services.sacog_imputation_validator import (
            run_validation_report,
        )

        results = run_validation_report(
            scenario_schema=WORKSPACE_SCHEMA,
            base_canvas_view=BASE_CANVAS_TABLE,
        )

        if results:
            self.stdout.write(self.style.SUCCESS("  ✓ Validation complete"))
        else:
            self.stdout.write(self.style.WARNING("  ⚠ No validation results"))
