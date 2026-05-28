# ruff: noqa: PT009
"""Tests for analysis workspace/scenario isolation and non-cascading behavior.

Behaviors covered:
- Workspace isolation: AnalysisRun records are scoped to exactly one workspace.
  Running analysis in workspace A must not create records or tables in workspace B.
- Scenario isolation: Different scenarios produce distinct result table names
  and AnalysisRun records, even within the same workspace.
- Single-analysis run isolation: Requesting one module dispatches only that
  module's chain, not unrelated modules.
- No cascading triggers: Running an analysis creates exactly one AnalysisRun,
  with no unintended side effects on other workspaces.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.test import TestCase

from brewgis.workspace.analysis.module_registry import MODULE_RESULT_TABLES
from brewgis.workspace.analysis.module_registry import get_result_table_names
from brewgis.workspace.analysis.module_registry import resolve_module_order
from brewgis.workspace.analysis.pipeline import run_analysis_pipeline
from brewgis.workspace.models import AnalysisRun
from tests.factories import ScenarioFactory
from tests.factories import WorkspaceFactory

# ── Helpers ───────────────────────────────────────────────────────────────────


# ═══════════════════════════════════════════════════════════════════════════════
#  Workspace Isolation
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestWorkspaceIsolation(TestCase):
    """AnalysisRuns are scoped to exactly one workspace.

    Running analysis in workspace A must not affect workspace B's state
    or produce output tables in workspace B's schema.
    """

    def setUp(self) -> None:
        self.workspace_a = WorkspaceFactory(db_schema="workspace_a_schema")
        self.workspace_b = WorkspaceFactory(db_schema="workspace_b_schema")
        self.scenario_a = ScenarioFactory(workspace=self.workspace_a, slug="ws-a-scope")
        self.scenario_b = ScenarioFactory(workspace=self.workspace_b, slug="ws-b-scope")

    def test_analysis_run_belongs_to_single_workspace(self) -> None:
        """An AnalysisRun FK points to exactly one workspace."""
        run_a = AnalysisRun.objects.create(
            workspace=self.workspace_a, scenario=self.scenario_a
        )
        run_b = AnalysisRun.objects.create(
            workspace=self.workspace_b, scenario=self.scenario_b
        )

        self.assertEqual(run_a.workspace, self.workspace_a)
        self.assertEqual(run_b.workspace, self.workspace_b)

    def test_filtering_by_workspace_returns_only_its_runs(self) -> None:
        """Querying runs by workspace FK returns only that workspace's runs."""
        r1 = AnalysisRun.objects.create(
            workspace=self.workspace_a,
            scenario=self.scenario_a,
            modules=["env_constraint"],
        )
        r2 = AnalysisRun.objects.create(
            workspace=self.workspace_a,
            scenario=self.scenario_a,
            modules=["core"],
        )
        r3 = AnalysisRun.objects.create(
            workspace=self.workspace_b,
            scenario=self.scenario_b,
            modules=["env_constraint"],
        )

        a_pks = set(
            AnalysisRun.objects.filter(workspace=self.workspace_a).values_list(
                "pk",
                flat=True,
            )
        )
        b_pks = set(
            AnalysisRun.objects.filter(workspace=self.workspace_b).values_list(
                "pk",
                flat=True,
            )
        )

        self.assertEqual(a_pks, {r1.pk, r2.pk})
        self.assertEqual(b_pks, {r3.pk})
        self.assertNotIn(r3.pk, a_pks, "Workspace B's run leaked into workspace A")
        self.assertNotIn(r1.pk, b_pks, "Workspace A's run leaked into workspace B")
        self.assertNotIn(r2.pk, b_pks, "Workspace A's run leaked into workspace B")

    @patch("brewgis.workspace.analysis.pipeline.run_modules_sync")
    def test_pipeline_creates_run_with_correct_workspace(
        self, mock_sync: MagicMock
    ) -> None:
        """run_analysis_pipeline creates an AnalysisRun for the given workspace."""
        mock_sync.return_value = {"success": True, "completed": [], "results": []}
        vars_ = {
            "scenario_id": "test-ws-a",
            "target_schema": self.workspace_a.db_schema,
            "parcel_table": "parcels",
        }
        run = run_analysis_pipeline(
            workspace_id=self.workspace_a.pk,
            module_names=["env_constraint"],
            vars_=vars_,
            scenario_id=self.scenario_a.pk,
        )

        self.assertEqual(run.workspace_id, self.workspace_a.pk)
        self.assertNotEqual(run.workspace_id, self.workspace_b.pk)

    @patch("brewgis.workspace.analysis.pipeline.run_modules_sync")
    def test_pipeline_vars_carry_correct_workspace_schema(
        self, mock_sync: MagicMock
    ) -> None:
        """target_schema in vars matches the launching workspace's schema."""
        mock_sync.return_value = {"success": True, "completed": [], "results": []}
        vars_ = {
            "scenario_id": "test-schema",
            "target_schema": self.workspace_a.db_schema,
            "parcel_table": "parcels",
        }
        run = run_analysis_pipeline(
            workspace_id=self.workspace_a.pk,
            module_names=["env_constraint"],
            vars_=vars_,
            scenario_id=self.scenario_a.pk,
        )

        self.assertEqual(run.vars.get("target_schema"), self.workspace_a.db_schema)

    @patch("brewgis.workspace.analysis.pipeline.run_modules_sync")
    def test_pipeline_workspace_b_isolation(self, mock_sync: MagicMock) -> None:
        """Pipeline for workspace B uses B's schema, not A's."""
        mock_sync.return_value = {"success": True, "completed": [], "results": []}
        ws_a_schema = self.workspace_a.db_schema
        ws_b_schema = self.workspace_b.db_schema

        vars_b = {
            "scenario_id": "test-ws-b",
            "target_schema": ws_b_schema,
            "parcel_table": "parcels",
        }
        run = run_analysis_pipeline(
            workspace_id=self.workspace_b.pk,
            module_names=["env_constraint"],
            scenario_id=self.scenario_b.pk,
            vars_=vars_b,
        )

        self.assertEqual(run.vars.get("target_schema"), ws_b_schema)
        self.assertNotEqual(
            run.vars.get("target_schema"),
            ws_a_schema,
            "Workspace B's analysis should not use workspace A's schema",
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  Scenario Isolation
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestScenarioIsolation(TestCase):
    """Analysis runs for different scenarios must not interfere.

    Two scenarios in the same workspace should produce distinct output
    tables and AnalysisRun records.
    """

    def setUp(self) -> None:
        self.workspace = WorkspaceFactory()
        self.scenario_a = ScenarioFactory(
            workspace=self.workspace,
            slug="scenario-a",
        )
        self.scenario_b = ScenarioFactory(
            workspace=self.workspace,
            slug="scenario-b",
        )

    def test_analysis_run_belongs_to_single_scenario(self) -> None:
        """An AnalysisRun FK points to exactly one scenario."""
        run_a = AnalysisRun.objects.create(
            workspace=self.workspace,
            scenario=self.scenario_a,
        )
        run_b = AnalysisRun.objects.create(
            workspace=self.workspace,
            scenario=self.scenario_b,
        )

        self.assertEqual(run_a.scenario, self.scenario_a)
        self.assertEqual(run_b.scenario, self.scenario_b)
        self.assertNotEqual(run_a.scenario, run_b.scenario)

    def test_filtering_by_scenario_returns_only_its_runs(self) -> None:
        """Querying runs by scenario FK returns only that scenario's runs."""
        r1 = AnalysisRun.objects.create(
            workspace=self.workspace,
            scenario=self.scenario_a,
            modules=["env_constraint"],
        )
        r2 = AnalysisRun.objects.create(
            workspace=self.workspace,
            scenario=self.scenario_b,
            modules=["env_constraint"],
        )

        a_pks = set(
            AnalysisRun.objects.filter(scenario=self.scenario_a).values_list(
                "pk",
                flat=True,
            )
        )
        b_pks = set(
            AnalysisRun.objects.filter(scenario=self.scenario_b).values_list(
                "pk",
                flat=True,
            )
        )

        self.assertEqual(a_pks, {r1.pk})
        self.assertEqual(b_pks, {r2.pk})
        self.assertNotIn(
            r2.pk,
            a_pks,
            "Scenario B's run leaked into scenario A",
        )

    def test_different_scenario_ids_produce_different_table_names(self) -> None:
        """Result table names are scoped by scenario_id.

        Running the same module for two different scenarios must produce
        different output table names so they don't overwrite each other.
        """
        tables_a = get_result_table_names("core", "scenario-a")
        tables_b = get_result_table_names("core", "scenario-b")

        self.assertEqual(len(tables_a), len(tables_b))
        for ta, tb in zip(tables_a, tables_b, strict=True):
            self.assertIn(
                "scenario-a",
                ta,
                f"Table name '{ta}' for scenario A is missing scenario_a identifier",
            )
            self.assertIn(
                "scenario-b",
                tb,
                f"Table name '{tb}' for scenario B is missing scenario_b identifier",
            )
            self.assertNotEqual(
                ta,
                tb,
                f"Table name '{ta}' is identical for both scenarios; "
                f"scenario_id should differentiate them",
            )

    def test_env_constraint_tables_scoped_by_scenario(self) -> None:
        """env_constraint output tables include scenario_id."""
        tables_a = get_result_table_names("env_constraint", "scenario-a")
        tables_b = get_result_table_names("env_constraint", "scenario-b")

        for ta in tables_a:
            self.assertIn("scenario-a", ta)
            self.assertNotIn("scenario-b", ta)
        for tb in tables_b:
            self.assertIn("scenario-b", tb)
            self.assertNotIn("scenario-a", tb)

    def test_all_modules_produce_scenario_scoped_tables(self) -> None:
        """Every registered module scopes its output tables by scenario_id.

        This is a regression guard: any new module must follow the
        scenario-scoping convention.
        """
        for module, templates in MODULE_RESULT_TABLES.items():
            for template in templates:
                self.assertIn(
                    "{scenario_id}",
                    template,
                    f"Module '{module}' table template '{template}' "
                    f"is missing {{scenario_id}} placeholder — "
                    f"output would not be scoped by scenario",
                )

    @patch("brewgis.workspace.analysis.pipeline.run_modules_sync")
    def test_pipeline_stores_scenario_id(self, mock_sync: MagicMock) -> None:
        """run_analysis_pipeline persists scenario_id in the run's vars."""
        mock_sync.return_value = {"success": True, "completed": [], "results": []}
        vars_ = {
            "scenario_id": "scenario-a",
            "target_schema": "public",
            "parcel_table": "parcels",
        }
        run = run_analysis_pipeline(
            workspace_id=self.workspace.pk,
            module_names=["env_constraint"],
            vars_=vars_,
            scenario_id=self.scenario_a.pk,
        )

        self.assertEqual(run.vars.get("scenario_id"), "scenario-a")

    @patch("brewgis.workspace.analysis.pipeline.run_modules_sync")
    def test_two_scenarios_parallel_runs_are_separate_records(
        self, mock_sync: MagicMock
    ) -> None:
        """Running analysis for two scenarios produces separate AnalysisRun records."""
        mock_sync.return_value = {"success": True, "completed": [], "results": []}
        vars_a = {
            "scenario_id": "scenario-a",
            "target_schema": self.workspace.db_schema,
            "parcel_table": "parcels",
        }
        run_a = run_analysis_pipeline(
            workspace_id=self.workspace.pk,
            module_names=["env_constraint"],
            vars_=vars_a,
            scenario_id=self.scenario_a.pk,
        )

        vars_b = {
            "scenario_id": "scenario-b",
            "target_schema": self.workspace.db_schema,
            "parcel_table": "parcels",
        }
        run_b = run_analysis_pipeline(
            workspace_id=self.workspace.pk,
            module_names=["env_constraint"],
            vars_=vars_b,
            scenario_id=self.scenario_b.pk,
        )

        self.assertNotEqual(
            run_a.pk,
            run_b.pk,
            "Two scenario runs should produce distinct AnalysisRun records",
        )
        self.assertEqual(run_a.vars.get("scenario_id"), "scenario-a")
        self.assertEqual(run_b.vars.get("scenario_id"), "scenario-b")


# ═══════════════════════════════════════════════════════════════════════════════
#  Single Module Execution — No Unwanted Cascading
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestSingleModuleExecution(TestCase):
    """Running only one analysis module must dispatch only that module's chain.

    Requesting one specific module must not trigger other modules
    that were not requested, even indirectly via dependency resolution.
    """

    def test_resolve_order_single_leaf_module_adds_deps_only(self) -> None:
        """resolve_module_order('water_demand') includes deps but not peers."""
        ordered = resolve_module_order(["water_demand"])
        expected = ["env_constraint", "core", "water_demand"]
        self.assertEqual(ordered, expected)

        # Peers that depend on the same parent should NOT appear
        for peer in [
            "energy_demand",
            "land_consumption",
            "fiscal",
            "agriculture",
            "trip_generation",
            "trip_distribution",
            "mode_choice",
            "vmt",
        ]:
            self.assertNotIn(
                peer,
                ordered,
                f"Unrequested peer '{peer}' leaked into execution order "
                f"for water_demand-only run",
            )

    def test_resolve_order_single_root_module_no_extras(self) -> None:
        """resolve_module_order('env_constraint') returns only that module."""
        ordered = resolve_module_order(["env_constraint"])
        self.assertEqual(ordered, ["env_constraint"])

    def test_resolve_order_explicit_deps_only(self) -> None:
        """Requesting ['env_constraint', 'core'] does not include water_demand etc."""
        ordered = resolve_module_order(["env_constraint", "core"])
        self.assertEqual(ordered, ["env_constraint", "core"])

        for unwanted in [
            "water_demand",
            "energy_demand",
            "land_consumption",
            "fiscal",
            "agriculture",
        ]:
            self.assertNotIn(unwanted, ordered)

    def test_vmt_chain_deps_only_no_extras(self) -> None:
        """Resolving vmt includes its full dependency chain but no peers."""
        ordered = resolve_module_order(["vmt"])
        expected = [
            "env_constraint",
            "core",
            "trip_generation",
            "trip_distribution",
            "mode_choice",
            "vmt",
        ]
        self.assertEqual(ordered, expected)

        # water_demand etc are peers of core — should NOT appear
        self.assertNotIn("water_demand", ordered)
        self.assertNotIn("energy_demand", ordered)
        self.assertNotIn("land_consumption", ordered)

    @patch("brewgis.workspace.analysis.pipeline.run_modules_sync")
    def test_pipeline_with_single_module_creates_run_with_correct_modules(
        self,
        mock_sync: MagicMock,
    ) -> None:
        """run_analysis_pipeline with one module creates AnalysisRun with only that module chain."""
        mock_sync.return_value = {"success": True, "completed": [], "results": []}
        ws = WorkspaceFactory()
        sc = ScenarioFactory(workspace=ws)
        run = run_analysis_pipeline(
            workspace_id=ws.pk,
            module_names=["env_constraint"],
            scenario_id=sc.pk,
        )
        self.assertEqual(run.modules, ["env_constraint"])

    @patch("brewgis.workspace.analysis.pipeline.run_modules_sync")
    def test_pipeline_water_demand_does_not_include_energy(
        self, mock_sync: MagicMock
    ) -> None:
        """Requesting water_demand pipeline does not add energy_demand to run."""
        mock_sync.return_value = {"success": True, "completed": [], "results": []}
        ws = WorkspaceFactory()
        sc = ScenarioFactory(workspace=ws)
        run = run_analysis_pipeline(
            workspace_id=ws.pk,
            module_names=["water_demand"],
            scenario_id=sc.pk,
        )
        self.assertIn("water_demand", run.modules)
        self.assertIn("env_constraint", run.modules)
        self.assertIn("core", run.modules)
        self.assertNotIn("energy_demand", run.modules)
        self.assertNotIn("land_consumption", run.modules)
        self.assertNotIn("fiscal", run.modules)
        self.assertNotIn("trip_generation", run.modules)
        self.assertNotIn("trip_distribution", run.modules)
        self.assertNotIn("mode_choice", run.modules)
        self.assertNotIn("vmt", run.modules)

    @patch("brewgis.workspace.analysis.pipeline.run_modules_sync")
    def test_pipeline_dispatches_all_modules_via_sync(
        self, mock_sync: MagicMock
    ) -> None:
        """run_analysis_pipeline dispatches all resolved modules via run_modules_sync."""
        mock_sync.return_value = {"success": True, "completed": [], "results": []}
        ws = WorkspaceFactory()
        sc = ScenarioFactory(workspace=ws)
        vars_ = {
            "scenario_id": "test-dispatch",
            "target_schema": ws.db_schema,
            "parcel_table": "parcels",
        }
        run_analysis_pipeline(
            workspace_id=ws.pk,
            module_names=["water_demand"],
            vars_=vars_,
            scenario_id=sc.pk,
        )

        mock_sync.assert_called_once()

    @patch("brewgis.workspace.analysis.pipeline.run_modules_sync")
    def test_pipeline_core_does_not_include_downstream_modules(
        self, mock_sync: MagicMock
    ) -> None:
        """Requesting only core does not add water_demand, energy_demand, or transport modules."""
        mock_sync.return_value = {"success": True, "completed": [], "results": []}
        ws = WorkspaceFactory()
        sc = ScenarioFactory(workspace=ws)
        run = run_analysis_pipeline(
            workspace_id=ws.pk,
            module_names=["core"],
            scenario_id=sc.pk,
        )
        # core needs env_constraint as a dependency
        self.assertIn("core", run.modules)
        self.assertIn("env_constraint", run.modules)
        # but NOT anything downstream
        for downstream in [
            "water_demand",
            "energy_demand",
            "land_consumption",
            "fiscal",
            "agriculture",
            "trip_generation",
            "trip_distribution",
            "mode_choice",
            "vmt",
        ]:
            self.assertNotIn(
                downstream,
                run.modules,
                f"Unrequested downstream module '{downstream}' should not appear "
                f"when only core was requested",
            )


# ═══════════════════════════════════════════════════════════════════════════════
#  No Cascading Triggers
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestNoCascadingAnalysisTriggers(TestCase):
    """Running one analysis must not inadvertently trigger other analyses.

    Verified behaviors:
    - run_analysis_pipeline creates exactly ONE AnalysisRun record
    - No cross-workspace side effects from running analysis
    - No unintended extra records are created
    """

    @patch("brewgis.workspace.analysis.pipeline.run_modules_sync")
    def test_creates_exactly_one_analysis_run(self, mock_sync: MagicMock) -> None:
        """run_analysis_pipeline creates exactly one new AnalysisRun."""
        mock_sync.return_value = {"success": True, "completed": [], "results": []}
        ws = WorkspaceFactory()
        sc = ScenarioFactory(workspace=ws)
        count_before = AnalysisRun.objects.count()

        run = run_analysis_pipeline(
            workspace_id=ws.pk,
            module_names=["env_constraint"],
            scenario_id=sc.pk,
        )

        count_after = AnalysisRun.objects.count()
        self.assertEqual(
            count_after,
            count_before + 1,
            "Expected exactly one new AnalysisRun record",
        )

    @patch("brewgis.workspace.analysis.pipeline.run_modules_sync")
    def test_other_workspace_untouched(self, mock_sync: MagicMock) -> None:
        """Running analysis in workspace A does not create runs in workspace B."""
        mock_sync.return_value = {"success": True, "completed": [], "results": []}
        ws_a = WorkspaceFactory()
        ws_b = WorkspaceFactory()
        sc = ScenarioFactory(workspace=ws_a)

        b_count_before = AnalysisRun.objects.filter(workspace=ws_b).count()

        run_analysis_pipeline(
            workspace_id=ws_a.pk,
            module_names=["env_constraint"],
            scenario_id=sc.pk,
        )

        b_count_after = AnalysisRun.objects.filter(workspace=ws_b).count()
        self.assertEqual(
            b_count_after,
            b_count_before,
            "Workspace B should have no new AnalysisRun records after "
            "running analysis in workspace A",
        )

    def test_querying_by_workspace_excludes_other_workspace_runs(self) -> None:
        """Workspace-scoped queries return correct, isolated result sets."""
        ws_a = WorkspaceFactory()
        ws_b = WorkspaceFactory()
        sc_a = ScenarioFactory(workspace=ws_a)
        sc_b = ScenarioFactory(workspace=ws_b)

        run_a1 = AnalysisRun.objects.create(workspace=ws_a, scenario=sc_a)
        run_a2 = AnalysisRun.objects.create(workspace=ws_a, scenario=sc_a)
        run_b = AnalysisRun.objects.create(workspace=ws_b, scenario=sc_b)

        a_pks = set(
            AnalysisRun.objects.filter(workspace=ws_a).values_list("pk", flat=True)
        )
        b_pks = set(
            AnalysisRun.objects.filter(workspace=ws_b).values_list("pk", flat=True)
        )

        self.assertEqual(a_pks, {run_a1.pk, run_a2.pk})
        self.assertEqual(b_pks, {run_b.pk})
        self.assertNotIn(run_b.pk, a_pks)
        self.assertNotIn(run_a1.pk, b_pks)
        self.assertNotIn(run_a2.pk, b_pks)
