# ruff: noqa: ANN201
"""Tests for the layer_toggle_visibility view.

Covers auth guard, method guard, toggling, and 404 handling.
"""

from __future__ import annotations

import pytest
from django.shortcuts import reverse
from django.test import TestCase

from tests.factories import LayerFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory


@pytest.mark.views
class TestLayerToggleVisibilityView(TestCase):
    """Tests for the layer_toggle_visibility view."""

    def setUp(self):
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()
        self.layer = LayerFactory(workspace=self.workspace)

    def _toggle_url(self, layer_pk: int | None = None) -> str:
        return reverse(
            "workspace:layer_toggle_visibility",
            kwargs={"pk": layer_pk or self.layer.pk},
        )

    def test_requires_auth(self):
        """Unauthenticated POST should redirect to login."""
        response = self.client.post(self._toggle_url())
        assert response.status_code == 302
        self.layer.refresh_from_db()
        assert self.layer.is_visible is True

    def test_get_method_not_allowed(self):
        """GET request should return 405 Method Not Allowed."""
        self.client.force_login(self.user)
        response = self.client.get(self._toggle_url())
        assert response.status_code == 405

    def test_toggle_flips_visibility(self):
        """POST flips is_visible from True to False and back."""
        self.client.force_login(self.user)
        assert self.layer.is_visible is True

        response = self.client.post(self._toggle_url())
        assert response.status_code == 204
        self.layer.refresh_from_db()
        assert self.layer.is_visible is False

        response = self.client.post(self._toggle_url())
        assert response.status_code == 204
        self.layer.refresh_from_db()
        assert self.layer.is_visible is True

    def test_toggle_nonexistent_layer_returns_404(self):
        """POST for non-existent layer PK returns 404."""
        self.client.force_login(self.user)
        url = self._toggle_url(layer_pk=99999)
        response = self.client.post(url)
        assert response.status_code == 404

    def test_toggle_does_not_affect_other_layers(self):
        """Toggling one layer does not affect other layers."""
        self.client.force_login(self.user)
        other_layer = LayerFactory(workspace=self.workspace)

        self.client.post(self._toggle_url())

        self.layer.refresh_from_db()
        other_layer.refresh_from_db()
        assert self.layer.is_visible is False
        assert other_layer.is_visible is True
