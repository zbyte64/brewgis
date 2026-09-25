# ruff: noqa: ANN201, ANN202, ANN002, ANN003
"""Tests that ``view_workspace_map`` honours the viewport carried over from a
previous render of the same page (``?lng=&lat=&zoom=``), which is how
switching scenarios keeps the user where they were looking instead of
snapping back to the workspace's stored default.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.http import HttpResponse
from django.test import TestCase
from django.urls import reverse

from brewgis.workspace.models import ScenarioType
from tests.factories import ScenarioFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory

WORKSPACE_DEFAULT = {"center": [-119.7, 36.7], "zoom": 10.0}


@pytest.mark.views
class TestMapViewViewport(TestCase):
    """Tests for the viewport resolution in ``view_workspace_map``."""

    def setUp(self):
        self.user = UserFactory()
        self.client.force_login(self.user)
        self.workspace = WorkspaceFactory(
            center_lng=WORKSPACE_DEFAULT["center"][0],
            center_lat=WORKSPACE_DEFAULT["center"][1],
            zoom=WORKSPACE_DEFAULT["zoom"],
        )
        ScenarioFactory(workspace=self.workspace, scenario_type=ScenarioType.BASE)
        self.scenario = ScenarioFactory(
            workspace=self.workspace, scenario_type=ScenarioType.ALTERNATIVE
        )
        self.map_url = reverse("workspace:workspace_map", args=[self.workspace.pk])

    def _get_context(self, query: str = "") -> dict:
        captured: dict = {}

        def fake_render(request, template_name, context=None, *args, **kwargs):
            captured["context"] = context or {}
            return HttpResponse("")

        with patch("brewgis.workspace.views.map.render", side_effect=fake_render):
            response = self.client.get(f"{self.map_url}{query}")
        assert response.status_code == 200
        return captured["context"]

    def _get_viewport(self, query: str = "") -> dict:
        return json.loads(self._get_context(query)["viewport_json"])

    def test_without_query_viewport_uses_workspace_default(self):
        assert self._get_viewport() == WORKSPACE_DEFAULT

    def test_query_viewport_overrides_workspace_default(self):
        """The scenario-switch request shape: ?scenario= plus the live viewport."""
        viewport = self._get_viewport(
            f"?scenario={self.scenario.pk}&lng=-121.5&lat=38.25&zoom=14.5"
        )
        assert viewport == {"center": [-121.5, 38.25], "zoom": 14.5}

    def test_scenario_param_still_resolves_alongside_viewport(self):
        context = self._get_context(
            f"?scenario={self.scenario.pk}&lng=-121.5&lat=38.25&zoom=14.5"
        )
        assert context["scenario"].pk == self.scenario.pk
        assert context["is_alternative_scenario"] is True

    def test_pitch_and_bearing_carried_when_present(self):
        viewport = self._get_viewport(
            "?lng=-121.5&lat=38.25&zoom=14.5&pitch=45&bearing=30"
        )
        assert viewport == {
            "center": [-121.5, 38.25],
            "zoom": 14.5,
            "pitch": 45.0,
            "bearing": 30.0,
        }

    def test_longitude_and_bearing_wrapped_into_range(self):
        viewport = self._get_viewport("?lng=200&lat=10&zoom=5&bearing=190")
        assert viewport["center"][0] == pytest.approx(-160.0)
        assert viewport["bearing"] == pytest.approx(-170.0)

    def test_out_of_range_pitch_dropped_center_kept(self):
        assert self._get_viewport("?lng=1&lat=2&zoom=5&pitch=120") == {
            "center": [1.0, 2.0],
            "zoom": 5.0,
        }

    def test_unusable_query_viewport_falls_back_to_workspace_default(self):
        unusable = [
            "?lng=1&lat=2&zoom=abc",  # not a number
            "?lng=1&lat=2&zoom=nan",  # parses, but not finite
            "?lng=1&lat=2",  # incomplete
            "?lat=95&lng=1&zoom=5",  # latitude off the globe
            "?lng=1&lat=2&zoom=99",  # beyond MapLibre's max zoom
        ]
        for query in unusable:
            with self.subTest(query=query):
                assert self._get_viewport(query) == WORKSPACE_DEFAULT

    def test_query_viewport_is_not_persisted(self):
        """Another viewer's pan must not overwrite the workspace's saved default."""
        self._get_viewport("?lng=1&lat=2&zoom=5")
        self.workspace.refresh_from_db()
        assert (
            self.workspace.center_lng,
            self.workspace.center_lat,
            self.workspace.zoom,
        ) == (-119.7, 36.7, 10.0)
