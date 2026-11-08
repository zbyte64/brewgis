"""Import the SACOG v1 database snapshot as a workspace — end-to-end orchestration.

The snapshot workspace is one of the two SACOG workspaces: it carries the
UrbanFootprint v1 region base canvas as imported, and is compared with the
workspace on ``sacog.base_canvas_reconciled`` (the reconstruction from public
data) to validate the base layer construction. The snapshot reaches its
workspace the way any exported workspace reaches another server: as a
workspace package (``services.sacog_v1_package`` writes it,
``services.workspace_package.attach_package`` attaches it), so its analysis
reads the data the snapshot shipped with — its streams/wetlands/vernal pools,
its SACSIM trip-length zones and the v1 built forms this command extracts —
through the same per-workspace input models as every other workspace.

Usage:
    python manage.py import_sacog_demo [--step STEP] [--force]

Steps:
    all         — full pipeline (default)
    discover    — schema discovery & manifest generation
    built_forms — complete the Building Type library, then extract the v1 built forms
    package     — write the snapshot as a package, attach it and build its base canvas
    workspace   — create the base scenario and register the v1 layers
    analysis    — run analysis pipeline
    validate    — imputation validation report

``package`` on an existing SACOG v1 workspace converts it in place: its
scenarios, paints and runs stay, and its base table becomes the packaged
``wsp<pk>.base_canvas`` (the same parcels, keyed on the v1 ``geography_id``).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

logger = logging.getLogger(__name__)

# How often the analysis step re-reads its run while a Celery worker executes it.
RUN_POLL_SECONDS = 5

WORKSPACE_NAME = "SACOG v1"
# The workspace's own schema (its uploads and exported Building Types).
WORKSPACE_SCHEMA = "sacog_v1"
SCENARIO_NAME = "base"
BASE_YEAR = 2012
HORIZON_YEAR = 2050

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
    help = "Import the SACOG v1 database snapshot as a workspace and analyze it."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--step",
            default="all",
            choices=[
                "all",
                "discover",
                "built_forms",
                "package",
                "workspace",
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
        self.stdout.write(f"  Import SACOG v1 snapshot — step: {step}")
        self.stdout.write(f"{'=' * 60}\n")

        steps_to_run = [
            "discover",
            "built_forms",
            "package",
            "workspace",
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
        # land uses, and many of the snapshot's keys normalize onto one of those
        # names (14 of Elk Grove's 29), so the library already answers for them.
        # The extraction then adds an entry only for the keys nothing answers
        # for. Run the other way round, the extraction would claim every key
        # first and the seeding
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
        """Get-or-create the snapshot workspace.

        Get-or-create rather than create because ``built_forms`` and ``package``
        run before the ``workspace`` step. Its base table and analysis inputs
        are the package's, set by the ``package`` step.
        """
        from brewgis.workspace.models import Workspace
        from brewgis.workspace.services.sacog_v1_package import V1_SRID

        workspace, _created = Workspace.objects.get_or_create(
            name=WORKSPACE_NAME,
            defaults={"db_schema": WORKSPACE_SCHEMA, "local_srid": V1_SRID},
        )
        if workspace.db_schema != WORKSPACE_SCHEMA:
            workspace.db_schema = WORKSPACE_SCHEMA
            workspace.save(update_fields=["db_schema"])
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

        # A workspace has exactly one BASE scenario, so an existing one (the
        # workspace was created in the UI, say) is adopted rather than joined by
        # a second.
        scenario, created = Scenario.objects.get_or_create(
            workspace=ws,
            scenario_type=ScenarioTypeModel.BASE,
            defaults={
                "name": SCENARIO_NAME,
                "slug": SCENARIO_SLUG,
                "description": f"Base year {BASE_YEAR} — imported from v1 SACOG base canvas",
                "base_year": BASE_YEAR,
                "horizon_year": HORIZON_YEAR,
            },
        )
        if created:
            self.stdout.write(f"  ✓ Created scenario: {scenario.name} ({BASE_YEAR})")
        else:
            self.stdout.write(f"  ✓ Base scenario already exists: {scenario.name}")

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
                    # ``sacog_v1`` and point the layer at a table that does
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

    def _step_package(self, *, force: bool = False) -> None:
        """Write the snapshot as a workspace package, attach it and build its base canvas.

        The package carries the workspace's Building Types as the library, so
        the ``built_forms`` step runs first; attaching keeps the workspace's
        own library (it is the same one) and every scenario, paint and run.
        """
        self.stdout.write("Phase 2: Workspace package...")

        import tempfile
        from pathlib import Path

        from brewgis.workspace.services.sacog_v1_package import build_sacog_v1_package
        from brewgis.workspace.services.workspace_package import attach_package
        from brewgis.workspace.services.workspace_package import build_package_base

        workspace = self._resolve_workspace()
        with tempfile.TemporaryDirectory(prefix="brewgis-sacog-v1-") as tmp:
            archive = build_sacog_v1_package(
                workspace, Path(tmp) / "sacog_v1.brewgis.zip"
            )
            manifest = attach_package(workspace, archive, replace_library=False)
        rows = {part.kind.value: part.rows for part in manifest.parts}
        self.stdout.write(f"  ✓ Package attached: {rows}")
        build_package_base(workspace)
        workspace.refresh_from_db()
        self.stdout.write(
            self.style.SUCCESS(f"  ✓ Base canvas ready: {workspace.base_table}")
        )

    # ── Step: analysis ────────────────────────────────────────────────

    def _step_analysis(self, *, force: bool = False) -> None:
        """Run the full analysis pipeline."""
        self.stdout.write("Phase 5: Analysis Pipeline...")

        from brewgis.workspace.analysis.launch import AnalysisLaunchError
        from brewgis.workspace.analysis.launch import launch_analysis
        from brewgis.workspace.analysis.pipeline import MODULE_RESULT_TABLES
        from brewgis.workspace.analysis.pipeline import resolve_module_order
        from brewgis.workspace.analysis.run_health import reconcile_abandoned_run
        from brewgis.workspace.models import Scenario
        from brewgis.workspace.models import ScenarioType
        from brewgis.workspace.models import Workspace

        # Load workspace and scenario
        try:
            ws = Workspace.objects.get(name=WORKSPACE_NAME)
            scenario = Scenario.objects.get(
                workspace=ws, scenario_type=ScenarioType.BASE
            )
        except (Workspace.DoesNotExist, Scenario.DoesNotExist):
            raise CommandError(
                f"Workspace '{WORKSPACE_NAME}' or its base scenario not found. "
                "Run '--step workspace' first."
            ) from None

        # Check prerequisites
        self._check_prerequisites(ws)

        # Export built forms for analysis pipeline
        self._export_built_forms(ws)

        # Resolve module order
        all_modules = list(MODULE_RESULT_TABLES.keys())
        ordered_modules = resolve_module_order(all_modules)
        self.stdout.write(f"  ✓ Module order: {', '.join(ordered_modules)}")

        # The same launch service the map view and the MCP tool use: it records
        # the run before the plan (the blueprint set comes from the scenarios
        # that have an AnalysisRun, see sqlmesh/macros/analysis_blueprints.py)
        # and the plan reads every input off the Scenario and the Workspace.
        try:
            run = launch_analysis(scenario=scenario, modules=ordered_modules)
        except AnalysisLaunchError as error:
            raise CommandError(f"Analysis not started: {error}") from error
        while run.status in {"pending", "running"}:
            time.sleep(RUN_POLL_SECONDS)
            run.refresh_from_db()
            reconcile_abandoned_run(run)
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

    def _check_prerequisites(self, ws: Any) -> None:
        """Refuse to analyze before the ``package`` step has built the base canvas.

        Everything else the analysis reads comes from the workspace's package
        and its input models, which the run builds itself.
        """
        from django.db import connection

        schema, _, table = ws.base_table.partition(".")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema=%s AND table_name=%s",
                [schema, table],
            )
            exists = cursor.fetchone()[0] > 0
        if not ws.package_dir or not exists:
            msg = (
                f"Workspace '{WORKSPACE_NAME}' has no packaged base canvas "
                f"({ws.base_table!r}). Run '--step package' first."
            )
            raise CommandError(msg)

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

        schema, _, table = self._resolve_workspace().base_table.partition(".")
        results = run_validation_report(scenario_schema=schema, base_canvas_view=table)

        if results:
            self.stdout.write(self.style.SUCCESS("  ✓ Validation complete"))
        else:
            self.stdout.write(self.style.WARNING("  ⚠ No validation results"))
