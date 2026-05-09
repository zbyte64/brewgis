"""Tests for the workspace detail page data catalog."""

from __future__ import annotations

import pytest
from django.test import TestCase
from django.urls import reverse

from brewgis.workspace.models import DataImportRun
from brewgis.workspace.models import DataSource
from brewgis.workspace.models import DataSourceCategory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory


@pytest.mark.models
@pytest.mark.views
class TestWorkspaceDetailCatalog(TestCase):
    """Tests that the workspace detail page renders the catalog correctly."""

    def setUp(self) -> None:
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()
        self.url = reverse("workspace:workspace_detail", kwargs={"pk": self.workspace.pk})

    def test_catalog_categories_in_context(self) -> None:
        """Workspace detail includes catalog_categories in context."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert "catalog_categories" in response.context

    def test_catalog_includes_all_categories(self) -> None:
        """All seeded categories appear in context."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        categories = response.context["catalog_categories"]
        assert len(categories) == DataSourceCategory.objects.count()

    def test_imported_types_in_context(self) -> None:
        """Workspace detail includes imported_types in context."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        assert "imported_types" in response.context

    def test_unauthenticated_redirects(self) -> None:
        """Unauthenticated users are redirected."""
        response = self.client.get(self.url)
        assert response.status_code == 302

    def test_imported_type_reflects_runs(self) -> None:
        """Completed import runs show in imported_types."""
        DataImportRun.objects.create(
            workspace=self.workspace,
            import_type="census",
            status="completed",
        )
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        assert "census" in response.context["imported_types"]
