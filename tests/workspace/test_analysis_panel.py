# ruff: noqa: ANN201
"""Tests for the map view's Analysis panel — cards, per-analysis form, and
non-blocking (Celery) launch."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django import forms
from django.test import TestCase
from django.urls import reverse

from brewgis.workspace.analysis.module_registry import get_available_analyses
from brewgis.workspace.analysis.pipeline import launch_analysis_run
from brewgis.workspace.views.analysis import AnalysisModuleForm
from tests.factories import AnalysisRunFactory
from tests.factories import ScenarioFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory


class TestGetAvailableAnalyses(TestCase):
    """Unit tests for the card metadata registry helper."""

    def test_excludes_modules_with_no_result_table(self):
        """acs_equity is a pure data wrapper with nothing of its own to show."""
        keys = {a["key"] for a in get_available_analyses()}
        assert "acs_equity" not in keys

    def test_includes_water_demand_with_description(self):
        by_key = {a["key"]: a for a in get_available_analyses()}
        assert "water_demand" in by_key
        assert by_key["water_demand"]["label"] == "Water Demand"
        assert by_key["water_demand"]["description"]

    def test_water_demand_needs_constraints_and_column_mapping(self):
        """water_demand depends on core, which depends on env_constraint."""
        by_key = {a["key"]: a for a in get_available_analyses()}
        assert by_key["water_demand"]["needs_constraints"] is True
        assert by_key["water_demand"]["needs_column_mapping"] is True


class TestAnalysisModuleForm(TestCase):
    """Direct form unit tests — verifies per-module fields, no JSON fields."""

    def setUp(self):
        self.workspace = WorkspaceFactory()
        self.scenario = ScenarioFactory(workspace=self.workspace)

    def test_no_json_fields(self):
        """The form never exposes a raw JSON textarea (unlike AnalysisLaunchForm)."""
        form = AnalysisModuleForm(
            workspace=self.workspace, scenario=self.scenario, module="water_demand"
        )
        assert "constraints_json" not in form.fields
        assert "column_mapping" not in form.fields
        assert not any(
            isinstance(field.widget, forms.Textarea) for field in form.fields.values()
        )

    def test_constraint_fields_present_for_water_demand(self):
        form = AnalysisModuleForm(
            workspace=self.workspace, scenario=self.scenario, module="water_demand"
        )
        assert "floodplain_discount_pct" in form.fields
        assert "wetlands_discount_pct" in form.fields
        assert "steep_slopes_discount_pct" in form.fields
        assert "column_pop" in form.fields

    def test_constraint_fields_absent_for_module_with_no_env_constraint_dependency(
        self,
    ):
        """A module that never resolves through env_constraint or core gets no
        constraint/column-mapping fields."""
        form = AnalysisModuleForm(
            workspace=self.workspace, scenario=self.scenario, module="acs_equity"
        )
        assert "floodplain_discount_pct" not in form.fields
        assert "column_pop" not in form.fields

    def test_defaults_parcel_table_to_scenario_canvas(self):
        form = AnalysisModuleForm(
            workspace=self.workspace, scenario=self.scenario, module="water_demand"
        )
        expected = f"{self.scenario.target_schema}.scenario_{self.scenario.slug}_canvas"
        assert form.fields["parcel_table"].initial == expected


@pytest.mark.views
class TestAnalysisPanelViews(TestCase):
    """Tests for the card-list, single-card, configure, and launch views."""

    def setUp(self):
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()
        self.scenario = ScenarioFactory(workspace=self.workspace)

    def test_card_list_unauthenticated_redirects(self):
        response = self.client.get(
            reverse("workspace:panel_analysis_launch", args=[self.workspace.pk])
        )
        assert response.status_code == 302

    def test_card_list_renders_one_card_per_analysis(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("workspace:panel_analysis_launch", args=[self.workspace.pk]),
            {"scenario": self.scenario.pk},
        )
        assert response.status_code == 200
        self.assertContains(response, "Water Demand")
        self.assertContains(response, "Never run")

    def test_card_list_reflects_last_run_status(self):
        AnalysisRunFactory(
            workspace=self.workspace,
            scenario=self.scenario,
            modules=["env_constraint", "core", "water_demand"],
            status="completed",
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("workspace:panel_analysis_launch", args=[self.workspace.pk]),
            {"scenario": self.scenario.pk},
        )
        assert response.status_code == 200
        self.assertContains(response, "Completed")

    def test_card_status_unknown_module_404s(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "workspace:analysis_card_status",
                args=[self.workspace.pk, "not_a_real_module"],
            )
        )
        assert response.status_code == 404

    def test_configure_view_renders_form(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "workspace:analysis_module_configure",
                args=[self.workspace.pk, "water_demand"],
            ),
            {"scenario": self.scenario.pk},
        )
        assert response.status_code == 200
        self.assertContains(response, "Run Analysis")

    @patch(
        "brewgis.workspace.views.analysis.check_analysis_prerequisites", return_value=[]
    )
    @patch("brewgis.workspace.views.analysis.launch_analysis_run")
    def test_launch_dispatches_and_returns_immediately(self, mock_launch, mock_prereq):
        """Launching never blocks on completion — it hands off to Celery."""
        mock_launch.return_value = AnalysisRunFactory(
            workspace=self.workspace,
            scenario=self.scenario,
            modules=["water_demand"],
            status="pending",
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse(
                "workspace:analysis_module_launch",
                args=[self.workspace.pk, "water_demand"],
            ),
            {
                "scenario": self.scenario.pk,
                "parcel_table": "parcels",
                "base_canvas_table": self.workspace.base_table,
            },
        )
        assert response.status_code == 200
        mock_launch.assert_called_once()
        mock_prereq.assert_called_once()
        _, kwargs = mock_launch.call_args
        assert kwargs["module_names"] == ["water_demand"]
        assert response.headers["HX-Trigger"]
        self.assertContains(response, "kicked off")


class TestLaunchAnalysisRun(TestCase):
    """launch_analysis_run must never execute the pipeline in-process itself —
    it only dispatches to Celery, so the map view's launch request never
    blocks on analysis completion."""

    def setUp(self):
        self.workspace = WorkspaceFactory()
        self.scenario = ScenarioFactory(workspace=self.workspace)

    @patch("brewgis.workspace.tasks.run_analysis_task.delay")
    def test_dispatches_to_celery_without_running_inline(self, mock_delay):
        run = launch_analysis_run(
            workspace_id=self.workspace.pk,
            module_names=["water_demand"],
            vars_={
                "target_schema": self.workspace.db_schema,
                "parcel_table": "parcels",
                "base_canvas_table": self.workspace.base_table,
            },
            scenario_id=self.scenario.pk,
        )
        mock_delay.assert_called_once_with(run.pk)
        # With .delay() mocked out, the run must still be "pending" —
        # proof launch_analysis_run itself never executes the SQLMesh plan.
        assert run.status == "pending"
