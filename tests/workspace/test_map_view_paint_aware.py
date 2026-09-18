# ruff: noqa: ANN201, ANN202, ANN002, ANN003
"""Tests that the workspace map view tiles the base parcel layer from the
scenario's painted-aware canvas view (not the raw base table) once a
scenario is active — otherwise symbology/colors on the map silently ignore
paint overrides.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.http import HttpResponse
from django.test import TestCase
from django.urls import reverse

from brewgis.workspace.analysis.layer_registry import PAINTED_FEATURES_LAYER_KEY
from brewgis.workspace.models import ScenarioType
from tests.factories import LayerFactory
from tests.factories import ScenarioFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory


@pytest.mark.views
class TestMapViewBaseLayerSource(TestCase):
    """Tests for the base parcel layer's tile source in ``view_workspace_map``."""

    def setUp(self):
        self.user = UserFactory()
        self.client.force_login(self.user)
        # Matches Workspace.base_table's default ("public.base_canvas") so
        # this Layer is recognized as *the* base canvas layer.
        self.workspace = WorkspaceFactory(
            center_lng=-119.7, center_lat=36.7, tile_server_backend="martin"
        )
        self.layer = LayerFactory(
            workspace=self.workspace,
            key="base_canvas",
            db_schema="public",
            db_table="base_canvas",
        )
        # Every workspace always has exactly one BASE scenario (see
        # resolve_scenario_param's docstring in views/panels.py) — real
        # workspaces get this from the workspace-creation flow; the factory
        # doesn't do it automatically, so it's created explicitly here for
        # the "no ?scenario= param" case below to have something to fall
        # back to.
        self.base_scenario = ScenarioFactory(
            workspace=self.workspace, scenario_type=ScenarioType.BASE
        )
        self.scenario = ScenarioFactory(
            workspace=self.workspace, scenario_type=ScenarioType.ALTERNATIVE
        )
        self.map_url = reverse("workspace:workspace_map", args=[self.workspace.pk])

    def _get_layer_data(self, query: str = "") -> list[dict]:
        captured: dict = {}

        def fake_render(request, template_name, context=None, *args, **kwargs):
            captured["context"] = context or {}
            return HttpResponse("")

        with patch("brewgis.workspace.views.map.render", side_effect=fake_render):
            self.client.get(f"{self.map_url}{query}")
        return captured["context"]["layer_data"]

    def test_base_layer_uses_raw_table_without_scenario(self):
        """With no active scenario, the base layer tiles from the raw base table."""
        layer_data = self._get_layer_data()
        base = next(layer for layer in layer_data if layer["id"] == "base_canvas")
        source_str = str(base["source"])
        assert "base_canvas" in source_str
        assert "scenario_" not in source_str
        assert base["source-layer"] == "public.base_canvas"

    def test_base_layer_uses_canvas_view_with_scenario(self):
        """With a scenario active, the base layer tiles from the canvas view
        instead of the raw base table, matching the separate canvas overlay layer."""
        layer_data = self._get_layer_data(f"?scenario={self.scenario.pk}")
        base = next(layer for layer in layer_data if layer["id"] == "base_canvas")
        # The painted-features overlay is one shared Layer per workspace
        # (key=PAINTED_FEATURES_LAYER_KEY), not a per-scenario one — see
        # ensure_painted_features_layer's docstring in layer_registry.py.
        overlay = next(
            layer for layer in layer_data if layer["id"] == PAINTED_FEATURES_LAYER_KEY
        )

        assert base["source"]["tiles"] == overlay["source"]["tiles"]
        assert base["source-layer"] == overlay["source-layer"]
        assert f"scenario_{self.scenario.slug}_canvas" in str(base["source"])

    def test_non_base_layers_unaffected_by_scenario(self):
        """A layer that isn't the base canvas keeps its own raw table source
        even when a scenario is active."""
        other_layer = LayerFactory(
            workspace=self.workspace,
            key="zoning",
            db_schema="public",
            db_table="zoning_districts",
        )
        layer_data = self._get_layer_data(f"?scenario={self.scenario.pk}")
        other = next(layer for layer in layer_data if layer["id"] == other_layer.key)
        assert "zoning_districts" in str(other["source"])
        assert "scenario_" not in str(other["source"])
