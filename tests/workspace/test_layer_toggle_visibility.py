# ruff: noqa: ANN201
"""Tests for the layer_toggle_visibility view.

Covers auth guard, method guard, toggling, and 404 handling.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.shortcuts import reverse
from django.test import TestCase

from brewgis.workspace.analysis.layer_registry import visible_layers_for_panel
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

    def test_tied_layers_keep_creation_order_across_toggles(self):
        """Layers tied on display_order list in creation order, toggle or not.

        Every layer starts at display_order 0. Left to Postgres, tied rows come
        back in the order the plan reads them; a seq scan — what the planner
        picks for a real workspace's layer table — reads heap order, which the
        toggle's UPDATE changes, so the panel and the map's stack reshuffled on
        the reload a toggle triggers. Index scans are switched off to get that
        plan on the test DB's near-empty table.
        """
        self.client.force_login(self.user)
        with connection.cursor() as cursor:
            cursor.execute(
                "SET LOCAL enable_indexscan = off; SET LOCAL enable_bitmapscan = off"
            )
        workspace = WorkspaceFactory()
        created = [
            LayerFactory(workspace=workspace, display_order=0).pk for _ in range(4)
        ]

        def panel_order() -> list[int]:
            return list(
                visible_layers_for_panel(workspace).values_list("pk", flat=True)
            )

        assert panel_order() == created
        for pk in created[:2]:
            self.client.post(self._toggle_url(pk))
            assert panel_order() == created
