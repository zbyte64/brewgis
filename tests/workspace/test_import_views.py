"""Tests for import views — import center, status polling, and census fetch.

These tests verify the HTTP layer (auth, rendering, status responses) but do
NOT test actual task execution, which requires Celery.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import TestCase
from django.urls import reverse

from brewgis.workspace.models import DataImportRun
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory

IMPORT_CENTER_URL = "workspace:import_center"
IMPORT_STATUS_URL = "workspace:import_status"
CENSUS_FETCH_URL = "workspace:census_fetch"


@pytest.mark.integration
@pytest.mark.views
class TestImportCenterView(TestCase):
    """Tests for the unified import landing page."""

    def setUp(self) -> None:
        self.user = UserFactory()
        self.url = reverse(IMPORT_CENTER_URL)

    def test_import_center_renders_correctly(self) -> None:
        """GET import center returns 200 and renders the correct template."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertTemplateUsed(response, "workspace/import_center.html")

    def test_unauthenticated_redirects_to_login(self) -> None:
        """Unauthenticated GET redirects to login (302)."""
        response = self.client.get(self.url)
        assert response.status_code == 302
        assert response.url.startswith("/accounts/login/")

    def test_import_center_with_tab_param(self) -> None:
        """GET import center with ?tab=census uses the census tab."""
        self.client.force_login(self.user)
        response = self.client.get(self.url, {"tab": "census"})
        assert response.status_code == 200
        self.assertTemplateUsed(response, "workspace/import_center.html")


@pytest.mark.integration
@pytest.mark.views
class TestImportStatusView(TestCase):
    """Tests for the data import status polling view."""

    def setUp(self) -> None:
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()

    def test_import_status_returns_status(self) -> None:
        """GET with valid run_pk returns 200 and renders status partial."""
        run = DataImportRun.objects.create(
            workspace=self.workspace,
            import_type="census",
            params={"state_fips": "06", "county_fips": "067"},
            status="pending",
        )
        url = reverse(IMPORT_STATUS_URL, kwargs={"run_pk": run.pk})
        self.client.force_login(self.user)
        response = self.client.get(url)
        assert response.status_code == 200
        self.assertTemplateUsed(response, "import-status")

    def test_import_status_includes_run_data(self) -> None:
        """Response context includes the correct DataImportRun."""
        run = DataImportRun.objects.create(
            workspace=self.workspace,
            import_type="census",
            params={"state_fips": "06", "county_fips": "067"},
            status="pending",
        )
        url = reverse(IMPORT_STATUS_URL, kwargs={"run_pk": run.pk})
        self.client.force_login(self.user)
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["run"] == run
        assert response.context["run"].status == "pending"

    def test_import_status_not_found(self) -> None:
        """GET with non-existent run_pk returns 404."""
        url = reverse(IMPORT_STATUS_URL, kwargs={"run_pk": 99999})
        self.client.force_login(self.user)
        response = self.client.get(url)
        assert response.status_code == 404

    def test_import_status_unauthenticated(self) -> None:
        """Unauthenticated GET redirects to login."""
        run = DataImportRun.objects.create(
            workspace=self.workspace,
            import_type="census",
            params={},
            status="pending",
        )
        url = reverse(IMPORT_STATUS_URL, kwargs={"run_pk": run.pk})
        response = self.client.get(url)
        assert response.status_code == 302


@pytest.mark.integration
@pytest.mark.views
class TestCensusFetchView(TestCase):
    """Tests for the Census ACS demographics import view."""

    def setUp(self) -> None:
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()
        self.url = reverse(CENSUS_FETCH_URL)

    def test_census_fetch_post_returns_200(self) -> None:
        """Valid POST creates a DataImportRun and renders status template."""
        self.client.force_login(self.user)
        with patch("brewgis.workspace.views.fetch_census.run_census_fetch.delay"):
            response = self.client.post(
                self.url,
                {
                    "workspace": self.workspace.pk,
                    "state_fips": "06",
                    "county_fips": "067",
                },
            )
        assert response.status_code == 200
        self.assertTemplateUsed(response, "workspace/import/status.html")

    def test_census_fetch_creates_import_run(self) -> None:
        """Valid POST creates a DataImportRun record."""
        self.client.force_login(self.user)
        with patch("brewgis.workspace.views.fetch_census.run_census_fetch.delay"):
            self.client.post(
                self.url,
                {
                    "workspace": self.workspace.pk,
                    "state_fips": "06",
                    "county_fips": "067",
                },
            )
        run = DataImportRun.objects.get(workspace=self.workspace)
        assert run.import_type == "census"
        assert run.params["state_fips"] == "06"
        assert run.params["county_fips"] == "067"
        assert run.status == "pending"

    def test_census_fetch_unauthenticated(self) -> None:
        """Unauthenticated POST redirects to login."""
        response = self.client.post(
            self.url,
            {
                "workspace": self.workspace.pk,
                "state_fips": "06",
                "county_fips": "067",
            },
        )
        assert response.status_code == 302
