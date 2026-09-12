# ruff: noqa: ANN201
"""Tests for report generation, listing, and deletion views.

Covers the report_delete view, the generate_scenario_report content
negotiation (JSON API vs htmx partial), and the map-panel report list.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.shortcuts import reverse
from django.test import TestCase

from brewgis.workspace.models import ScenarioReport
from tests.factories import ScenarioReportFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory


@pytest.mark.views
class TestReportDeleteView(TestCase):
    def setUp(self):
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()
        self.report = ScenarioReportFactory(workspace=self.workspace)

    def _delete_url(self, report_pk: int | None = None) -> str:
        return reverse(
            "workspace:report_delete",
            kwargs={
                "workspace_pk": self.workspace.pk,
                "report_pk": report_pk or self.report.pk,
            },
        )

    def test_requires_auth(self):
        response = self.client.post(self._delete_url())
        assert response.status_code == 302
        assert ScenarioReport.objects.filter(pk=self.report.pk).exists() is True

    def test_get_method_not_allowed(self):
        self.client.force_login(self.user)
        response = self.client.get(self._delete_url())
        assert response.status_code == 405

    def test_delete_removes_report_and_returns_list(self):
        self.client.force_login(self.user)
        response = self.client.post(self._delete_url())
        assert response.status_code == 200
        assert ScenarioReport.objects.filter(pk=self.report.pk).exists() is False
        assert b"No reports generated yet" in response.content

    def test_delete_nonexistent_report_returns_404(self):
        self.client.force_login(self.user)
        response = self.client.post(self._delete_url(report_pk=99999))
        assert response.status_code == 404


@pytest.mark.views
class TestGenerateScenarioReportView(TestCase):
    def setUp(self):
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()
        self.client.force_login(self.user)

    def _generate_url(self) -> str:
        return reverse(
            "workspace:generate_scenario_report",
            kwargs={"workspace_pk": self.workspace.pk},
        )

    def test_plain_post_returns_json(self):
        with patch(
            "brewgis.workspace.views.report.generate_report_task.delay"
        ) as mock_delay:
            response = self.client.post(self._generate_url(), {"name": "My Report"})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "pk" in data
        mock_delay.assert_called_once()
        assert ScenarioReport.objects.filter(pk=data["pk"], name="My Report").exists()

    def test_htmx_post_returns_report_list_partial(self):
        with patch("brewgis.workspace.views.report.generate_report_task.delay"):
            response = self.client.post(
                self._generate_url(),
                {"name": "My Report"},
                HTTP_HX_REQUEST="true",
            )

        assert response.status_code == 200
        assert b"My Report" in response.content
        assert response["Content-Type"].startswith("text/html")


@pytest.mark.views
class TestPanelReportList(TestCase):
    def setUp(self):
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()
        self.client.force_login(self.user)

    def test_lists_existing_reports(self):
        ScenarioReportFactory(workspace=self.workspace, name="Existing Report")
        url = reverse(
            "workspace:panel_report_list",
            kwargs={"workspace_pk": self.workspace.pk},
        )
        response = self.client.get(url)
        assert response.status_code == 200
        assert b"Existing Report" in response.content

    def test_empty_state_when_no_reports(self):
        url = reverse(
            "workspace:panel_report_list",
            kwargs={"workspace_pk": self.workspace.pk},
        )
        response = self.client.get(url)
        assert response.status_code == 200
        assert b"No reports generated yet" in response.content
