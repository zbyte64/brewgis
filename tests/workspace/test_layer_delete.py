# ruff: noqa: ANN201
"""Tests for layer delete view.

Covers auth guard, layer deletion, cascade behavior, and 404 handling.
"""

from __future__ import annotations

import pytest
from django.shortcuts import reverse
from django.test import TestCase

from brewgis.workspace.models import Layer
from brewgis.workspace.models import SymbologyConfig
from tests.factories import LayerFactory
from tests.factories import SymbologyConfigFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory


@pytest.mark.views
class TestLayerDeleteView(TestCase):
    """Tests for the layer_delete view."""

    def setUp(self):
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()
        self.layer = LayerFactory(workspace=self.workspace)

    def _delete_url(self, layer_pk: int | None = None) -> str:
        return reverse("workspace:layer_delete", kwargs={"pk": layer_pk or self.layer.pk})

    def test_requires_auth(self):
        """Unauthenticated POST should redirect to login."""
        response = self.client.post(self._delete_url())
        assert response.status_code == 302
        assert Layer.objects.filter(pk=self.layer.pk).exists() is True

    def test_get_method_not_allowed(self):
        """GET request should return 405 Method Not Allowed."""
        self.client.force_login(self.user)
        response = self.client.get(self._delete_url())
        assert response.status_code == 405
        assert Layer.objects.filter(pk=self.layer.pk).exists() is True

    def test_delete_layer(self):
        """POST deletes the layer."""
        self.client.force_login(self.user)
        response = self.client.post(self._delete_url())
        assert response.status_code == 302
        assert Layer.objects.filter(pk=self.layer.pk).exists() is False

    def test_delete_with_symbology_cascades(self):
        """Deleting a layer cascades to its SymbologyConfig."""
        self.client.force_login(self.user)
        SymbologyConfigFactory(layer=self.layer)
        symbology_pk = self.layer.symbology.pk

        self.client.post(self._delete_url())

        assert Layer.objects.filter(pk=self.layer.pk).exists() is False
        assert SymbologyConfig.objects.filter(pk=symbology_pk).exists() is False

    def test_delete_redirects_to_workspace_detail(self):
        """POST redirects to workspace detail page."""
        self.client.force_login(self.user)
        response = self.client.post(self._delete_url())
        assert response.status_code == 302
        expected_url = reverse(
            "workspace:workspace_detail",
            kwargs={"pk": self.workspace.pk},
        )
        assert response.url == expected_url

    def test_delete_nonexistent_layer_returns_404(self):
        """POST for non-existent layer PK returns 404."""
        self.client.force_login(self.user)
        url = self._delete_url(layer_pk=99999)
        response = self.client.post(url)
        assert response.status_code == 404

    def test_workspace_preserved_when_one_layer_deleted(self):
        """Deleting one layer does not affect other layers or workspace."""
        self.client.force_login(self.user)
        other_layer = LayerFactory(workspace=self.workspace)

        self.client.post(self._delete_url())

        assert Layer.objects.filter(pk=self.layer.pk).exists() is False
        assert Layer.objects.filter(pk=other_layer.pk).exists() is True
        assert self.workspace.layers.count() == 1
