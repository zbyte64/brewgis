# ruff: noqa: ANN001, ANN201
"""Tests for the AnalysisRun model."""
from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from tests.factories import AnalysisRunFactory
from tests.factories import ScenarioFactory
from tests.factories import WorkspaceFactory

from brewgis.workspace.models import AnalysisRun


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
