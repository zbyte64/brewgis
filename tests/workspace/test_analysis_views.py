# ruff: noqa: ANN201
"""Tests for analysis pipeline views — launch, status, list, prereq check."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.test import Client
from django.test import RequestFactory
from django.test import TestCase
from django.urls import reverse

from brewgis.workspace.views.analysis import AnalysisLaunchForm
from brewgis.workspace.views.analysis import AnalysisLaunchView
from tests.factories import AnalysisRunFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory

# URL names (app_name = "workspace")
LAUNCH_URL = "workspace:analysis_launch"
STATUS_URL = "workspace:analysis_status"
LIST_URL = "workspace:analysis_list"
PREREQ_URL = "workspace:check_prerequisites"


class TestAnalysisLaunchForm(TestCase):
    """Direct form unit tests for ``AnalysisLaunchForm`` (avoids template rendering)."""

    def setUp(self):
        self.workspace = WorkspaceFactory()

    def test_form_requires_workspace(self):
        """Form with no workspace is invalid."""
        form = AnalysisLaunchForm(data={"modules": ["env_constraint"]})
        assert not form.is_valid()
        assert "workspace" in form.errors

    def test_form_requires_at_least_one_module(self):
        """Form with empty modules list is invalid."""
        form = AnalysisLaunchForm(
            data={
                "workspace": self.workspace.pk,
                "modules": [],
                "parcel_table": "parcels",
            },
        )
        assert not form.is_valid()
        assert "modules" in form.errors

        """Field-level validation passes for workspace + modules fields.
        parcel_table validation depends on schema-level check_analysis_prerequisites.
        """
        form = AnalysisLaunchForm(
            data={
                "workspace": self.workspace.pk,
                "modules": ["env_constraint"],
                "parcel_table": "parcels",
            },
        )
        assert "workspace" not in form.errors
        assert "modules" not in form.errors

    def test_form_initial_constraints_json(self):
        """Form has a default constraints JSON initial value."""
        form = AnalysisLaunchForm()
        initial = form.fields["constraints_json"].initial
        assert initial is not None
        parsed = json.loads(initial)
        assert isinstance(parsed, list)

    def test_form_rejects_bad_constraints_json(self):
        """Invalid JSON in constraints_json field raises validation error."""
        form = AnalysisLaunchForm(
            data={
                "workspace": self.workspace.pk,
                "modules": ["env_constraint"],
                "parcel_table": "parcels",
                "constraints_json": "not valid json",
            },
        )
        assert not form.is_valid()
        assert "constraints_json" in form.errors


@pytest.mark.views
class TestAnalysisLaunchView(TestCase):
    """Tests for ``AnalysisLaunchView`` — uses RequestFactory to avoid template rendering."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()

    def test_unauthenticated_get_redirects(self):
        """Unauthenticated GET redirects to login (user_passes_test)."""
        client = Client()
        response = client.get(reverse(LAUNCH_URL))
        assert response.status_code == 302

    def test_unauthenticated_post_redirects(self):
        """Unauthenticated POST redirects to login."""
        client = Client()
        response = client.post(
            reverse(LAUNCH_URL),
            json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 302

    def test_get_launch_page_context_title(self):
        """GET returns form with title in context_data."""
        request = self.factory.get("/analysis/launch/")
        request.user = self.user
        view = AnalysisLaunchView()
        view.setup(request)
        response = view.dispatch(request)
        assert response.status_code == 200
        assert response.context_data["title"] == "Run Analysis"

    def test_get_launch_page_context_has_form(self):
        """GET has 'form' key in context_data."""
        request = self.factory.get("/analysis/launch/")
        request.user = self.user
        view = AnalysisLaunchView()
        view.setup(request)
        response = view.dispatch(request)
        assert response.status_code == 200
        assert "form" in response.context_data

    def test_get_launch_page_context_form_fields(self):
        """GET response context_data['form'] has expected fields."""
        request = self.factory.get("/analysis/launch/")
        request.user = self.user
        view = AnalysisLaunchView()
        view.setup(request)
        response = view.dispatch(request)
        form = response.context_data["form"]
        expected_fields = {
            "workspace",
            "modules",
            "scenario_id",
            "parcel_table",
            "built_form_table",
            "source_schema",
            "base_canvas_table",
            "constraints_json",
        }
        assert expected_fields.issubset(form.fields.keys())

    def test_get_launch_page_uses_form_template(self):
        """GET response template name is 'form.html'."""
        request = self.factory.get("/analysis/launch/")
        request.user = self.user
        view = AnalysisLaunchView()
        view.setup(request)
        response = view.dispatch(request)
        assert "form.html" in response.template_name

    @patch(
        "brewgis.workspace.views.analysis.check_analysis_prerequisites", return_value=[]
    )
    @patch("brewgis.workspace.views.analysis.run_analysis_pipeline")
    def test_post_valid_creates_run(self, mock_pipeline, mock_prereq):
        """POST with valid data calls run_analysis_pipeline."""
        mock_pipeline.return_value = AnalysisRunFactory(
            workspace=self.workspace,
            modules=["env_constraint"],
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse(LAUNCH_URL),
            {
                "workspace": self.workspace.pk,
                "modules": ["env_constraint"],
                "parcel_table": "parcels",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code in (200, 302)
        mock_pipeline.assert_called_once()
        mock_prereq.assert_called_once()


@pytest.mark.views
class TestAnalysisStatusView(TestCase):
    """Tests for ``analysis_status`` view — htmx polling endpoint."""

    def setUp(self):
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()
        self.run = AnalysisRunFactory(
            workspace=self.workspace,
            modules=["env_constraint"],
            status="pending",
        )
        self.status_url = reverse(STATUS_URL, kwargs={"run_pk": self.run.pk})

    def test_status_returns_run_state(self):
        """GET returns 200 and includes the run status."""
        self.client.force_login(self.user)
        response = self.client.get(self.status_url)
        assert response.status_code == 200

        self.assertContains(response, "Pending")

    def test_status_missing_run_returns_404(self):
        """GET with invalid run_pk returns 404."""
        self.client.force_login(self.user)
        bad_url = reverse(STATUS_URL, kwargs={"run_pk": 99999})
        response = self.client.get(bad_url)
        assert response.status_code == 404

    def test_status_with_completed_run(self):
        """GET with a completed run renders completed status text."""
        self.client.force_login(self.user)
        self.run.status = "completed"
        self.run.save()
        response = self.client.get(self.status_url)
        assert response.status_code == 200
        self.assertContains(response, "Completed")

    def test_unauthenticated_returns_200(self):
        """Unauthenticated GET returns status (no login decorator)."""
        response = self.client.get(self.status_url)
        assert response.status_code == 200


@pytest.mark.views
class TestAnalysisListView(TestCase):
    """Tests for ``analysis_list`` view — recent run listing."""

    def setUp(self):
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()
        self.list_url = reverse(LIST_URL)
        self.run = AnalysisRunFactory(
            workspace=self.workspace,
            modules=["env_constraint"],
            status="completed",
        )

    def test_list_returns_recent_runs(self):
        """GET returns 200 with runs in context."""
        self.client.force_login(self.user)
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        assert "runs" in response.context
        assert self.run in response.context["runs"]

    def test_list_empty_when_no_runs(self):
        """GET returns 200 with empty runs list when no runs exist."""
        self.client.force_login(self.user)
        self.run.delete()
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        assert list(response.context["runs"]) == []

    def test_unauthenticated_returns_200(self):
        """Unauthenticated GET returns list (no login decorator)."""
        response = self.client.get(self.list_url)
        assert response.status_code == 200


@pytest.mark.views
class TestCheckPrerequisitesView(TestCase):
    """Tests for ``check_prerequisites`` view — htmx preflight endpoint."""

    def setUp(self):
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()
        self.prereq_url = reverse(PREREQ_URL)

    def test_get_returns_405(self):
        """GET request returns 405 (POST-only endpoint)."""
        self.client.force_login(self.user)
        response = self.client.get(self.prereq_url)
        assert response.status_code == 405

    def test_post_missing_parcel_shows_warning(self):
        """POST without parcel_table returns warning message."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.prereq_url,
            {"source_schema": self.workspace.db_schema},
        )
        assert response.status_code == 200
        self.assertContains(response, "No parcel table specified")

    def test_post_returns_validation_results(self):
        """POST with parcel table renders prereq check results."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.prereq_url,
            {
                "source_schema": self.workspace.db_schema,
                "parcel_table": "nonexistent_parcels",
            },
        )
        assert response.status_code == 200
        # Should return an alert (success or failure)
        self.assertContains(response, "alert")

    def test_unauthenticated_post_returns_200(self):
        """Unauthenticated POST runs preflight (no login decorator)."""
        response = self.client.post(
            self.prereq_url,
            {"parcel_table": "test_parcels"},
        )
        assert response.status_code == 200
