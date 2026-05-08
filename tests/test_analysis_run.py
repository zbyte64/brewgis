# ruff: noqa: ANN001
"""Tests for the AnalysisRun model."""
from __future__ import annotations

import pytest

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from tests.factories import AnalysisRunFactory
from tests.factories import ScenarioFactory
from tests.factories import WorkspaceFactory

from brewgis.workspace.models import AnalysisRun


@pytest.mark.integration
class TestAnalysisRunModel(TestCase):
    """Tests for the AnalysisRun model fields and methods."""

    def setUp(self) -> None:
        self.workspace = WorkspaceFactory()
        self.scenario = ScenarioFactory(workspace=self.workspace)
        self.run = AnalysisRunFactory(
            workspace=self.workspace,
            scenario=self.scenario,
            modules=["env_constraint", "core"],
            status="pending",
            vars={"target_year": 2050},
        )

    def test_str_default(self) -> None:
        """__str__ should return format with pk, status, and modules."""
        expected = (
            f"AnalysisRun #{self.run.pk} [pending] (env_constraint, core)"
        )
        self.assertEqual(str(self.run), expected)

    def test_str_empty_modules(self) -> None:
        """__str__ should show 'unknown' when modules is empty."""
        run = AnalysisRunFactory(
            workspace=self.workspace,
            modules=[],
            status="completed",
        )
        expected = f"AnalysisRun #{run.pk} [completed] (unknown)"
        self.assertEqual(str(run), expected)

    def test_default_status_is_pending(self) -> None:
        """Default status should be 'pending'."""
        run = AnalysisRun.objects.create(workspace=self.workspace)
        self.assertEqual(run.status, "pending")

    def test_status_transition_pending_to_running_to_completed(self) -> None:
        """Status should transition pending -> running -> completed."""
        self.run.status = "running"
        self.run.started_at = timezone.now()
        self.run.save()

        run = AnalysisRun.objects.get(pk=self.run.pk)
        self.assertEqual(run.status, "running")
        self.assertIsNotNone(run.started_at)

        run.status = "completed"
        run.completed_at = timezone.now()
        run.save()

        run = AnalysisRun.objects.get(pk=self.run.pk)
        self.assertEqual(run.status, "completed")
        self.assertIsNotNone(run.completed_at)

    def test_status_transition_pending_to_running_to_failed(self) -> None:
        """Status should transition pending -> running -> failed with error_log."""
        self.run.status = "running"
        self.run.started_at = timezone.now()
        self.run.save()

        self.run.status = "failed"
        self.run.completed_at = timezone.now()
        self.run.error_log = "dbt run failed: model env_constraint timed out"
        self.run.save()

        run = AnalysisRun.objects.get(pk=self.run.pk)
        self.assertEqual(run.status, "failed")
        self.assertIsNotNone(run.completed_at)
        self.assertEqual(
            run.error_log,
            "dbt run failed: model env_constraint timed out",
        )

    def test_ordering_by_created_at_descending(self) -> None:
        """AnalysisRuns should be ordered by -created_at (newest first)."""
        run_a = AnalysisRunFactory(workspace=self.workspace)
        run_b = AnalysisRunFactory(workspace=self.workspace)
        run_c = AnalysisRunFactory(workspace=self.workspace)

        qs = AnalysisRun.objects.filter(
            pk__in=[run_a.pk, run_b.pk, run_c.pk],
        )
        pks = list(qs.values_list("pk", flat=True))
        self.assertEqual(pks, sorted(pks, reverse=True))

    def test_modules_accepts_list_of_strings(self) -> None:
        """modules JSONField should accept a list of strings."""
        self.run.modules = ["env_constraint", "core", "water_demand"]
        self.run.save()

        run = AnalysisRun.objects.get(pk=self.run.pk)
        self.assertEqual(
            run.modules,
            ["env_constraint", "core", "water_demand"],
        )

    def test_modules_defaults_to_empty_list(self) -> None:
        """modules should default to an empty list."""
        run = AnalysisRun.objects.create(workspace=self.workspace)
        self.assertEqual(run.modules, [])

    def test_vars_accepts_dict(self) -> None:
        """vars JSONField should accept a dict."""
        self.run.vars = {
            "target_year": 2040,
            "scenario": "aggressive",
            "tags": ["growth", "infill"],
        }
        self.run.save()

        run = AnalysisRun.objects.get(pk=self.run.pk)
        self.assertEqual(
            run.vars,
            {"target_year": 2040, "scenario": "aggressive", "tags": ["growth", "infill"]},
        )

    def test_vars_defaults_to_empty_dict(self) -> None:
        """vars should default to an empty dict."""
        run = AnalysisRun.objects.create(workspace=self.workspace)
        self.assertEqual(run.vars, {})

    def test_created_at_is_auto_set(self) -> None:
        """created_at should be set automatically on creation."""
        now = timezone.now()
        run = AnalysisRun.objects.create(workspace=self.workspace)

        self.assertIsNotNone(run.created_at)
        self.assertLess(
            run.created_at - now,
            timedelta(seconds=5),
        )

    def test_started_at_completed_at_nullable(self) -> None:
        """started_at and completed_at should be nullable."""
        run = AnalysisRun.objects.create(workspace=self.workspace)
        self.assertIsNone(run.started_at)
        self.assertIsNone(run.completed_at)

    def test_scenario_fk(self) -> None:
        """AnalysisRun can be associated with a Scenario via FK."""
        self.assertEqual(self.run.scenario, self.scenario)

    def test_scenario_nullable(self) -> None:
        """scenario FK should be nullable for backward compat."""
        run = AnalysisRun.objects.create(workspace=self.workspace)
        self.assertIsNone(run.scenario)

@pytest.mark.integration
class TestPipelineCrossModuleRefs(TestCase):
    """Tests for cross-module variable resolution in the analysis pipeline."""

    def test_constraints_output_fully_qualified(self) -> None:
        """When env_constraint completed, core should get fully qualified constraints_output.

        The ``constraints_output`` should include the schema prefix so
        that ``core_end_state.sql`` can reference it without prepending
        ``source_schema`` (which would be the wrong schema).
        """
        from brewgis.workspace.analysis.pipeline import _get_vars_for_module

        base_vars = {
            "scenario_id": "test-scenario",
            "target_schema": "scenario_test-scenario",
            "parcel_table": "parcels",
            "completed_modules": ["env_constraint"],
        }

        core_vars = _get_vars_for_module("core", base_vars)

        constraints_output = core_vars.get("constraints_output")
        assert constraints_output is not None, (
            "constraints_output should be set when env_constraint is completed"
        )
        assert constraints_output == "scenario_test-scenario.env_constraint_test-scenario", (
            f"Expected 'scenario_test-scenario.env_constraint_test-scenario', "
            f"got '{constraints_output}'"
        )

    def test_no_constraints_output_without_env_constraint(self) -> None:
        """When env_constraint not completed, constraints_output should not be set."""
        from brewgis.workspace.analysis.pipeline import _get_vars_for_module

        base_vars = {
            "scenario_id": "test-scenario",
            "target_schema": "scenario_test-scenario",
            "parcel_table": "parcels",
            "completed_modules": [],
        }

        core_vars = _get_vars_for_module("core", base_vars)

        assert "constraints_output" not in core_vars, (
            "constraints_output should NOT be set when env_constraint is not completed"
        )

    def test_constraints_output_uses_default_schema_fallback(self) -> None:
        """If target_schema is missing, constraints_output should fall back to 'public'."""
        from brewgis.workspace.analysis.pipeline import _get_vars_for_module

        base_vars = {
            "scenario_id": "test-scenario",
            "parcel_table": "parcels",
            "completed_modules": ["env_constraint"],
        }

        core_vars = _get_vars_for_module("core", base_vars)

        constraints_output = core_vars.get("constraints_output")
        assert constraints_output == "public.env_constraint_test-scenario", (
            f"Expected 'public.env_constraint_test-scenario', got '{constraints_output}'"
        )
@pytest.mark.integration
class TestNewModuleResolution(TestCase):
    """Tests for resolution of new Phase 3 modules in the analysis pipeline."""

    def test_land_consumption_depends_on_core(self) -> None:
        """land_consumption requires core in its dependency chain."""
        from brewgis.workspace.analysis.pipeline import resolve_module_order

        ordered = resolve_module_order(["env_constraint", "core", "land_consumption"])
        assert ordered.index("core") < ordered.index("land_consumption")

    def test_fiscal_depends_on_core(self) -> None:
        """fiscal requires core in its dependency chain."""
        from brewgis.workspace.analysis.pipeline import resolve_module_order

        ordered = resolve_module_order(["env_constraint", "core", "fiscal"])
        assert ordered.index("core") < ordered.index("fiscal")

    def test_agriculture_depends_on_core(self) -> None:
        """agriculture requires core in its dependency chain."""
        from brewgis.workspace.analysis.pipeline import resolve_module_order

        ordered = resolve_module_order(["env_constraint", "core", "agriculture"])
        assert ordered.index("core") < ordered.index("agriculture")

    def test_all_new_modules_independent_of_each_other(self) -> None:
        """land_consumption, fiscal, and agriculture should not depend on each other."""
        from brewgis.workspace.analysis.pipeline import resolve_module_order

        ordered = resolve_module_order(
            ["env_constraint", "core", "land_consumption", "fiscal", "agriculture"]
        )
        # All three should be after core, and can be in any order among themselves
        core_idx = ordered.index("core")
        for mod in ["land_consumption", "fiscal", "agriculture"]:
            assert ordered.index(mod) > core_idx, (
                f"{mod} should run after core, got {ordered}"
            )

    def test_full_pipeline_resolution(self) -> None:
        """All modules together should resolve in correct dependency order."""
        from brewgis.workspace.analysis.pipeline import resolve_module_order

        ordered = resolve_module_order([
            "env_constraint",
            "core",
            "water_demand",
            "energy_demand",
            "land_consumption",
            "fiscal",
            "agriculture",
        ])
        # env_constraint must be first
        assert ordered[0] == "env_constraint"
        # core must be after env_constraint
        assert ordered.index("env_constraint") < ordered.index("core")
        # All new modules must be after core
        core_idx = ordered.index("core")
        for mod in ["water_demand", "energy_demand", "land_consumption", "fiscal", "agriculture"]:
            assert ordered.index(mod) > core_idx, (
                f"{mod} should run after core, got {ordered}"
            )

    def test_module_result_tables_defined(self) -> None:
        """All new modules must have result table templates in MODULE_RESULT_TABLES."""
        from brewgis.workspace.analysis.pipeline import MODULE_RESULT_TABLES

        for module in ["land_consumption", "fiscal", "agriculture"]:
            assert module in MODULE_RESULT_TABLES, (
                f"{module} missing from MODULE_RESULT_TABLES"
            )
