# ruff: noqa: ANN201
"""Tests for scenario scoping of layers.

Each scenario owns an instance of every analysis model, and its result views
live in its own ``analysis__scenario_<pk>`` schema. A layer records the
scenario it belongs to (``Layer.scenario``; null for workspace-level layers
like the base canvas), and every surface that lists layers — the map, the
Layers panel, the requests that refresh it — must show the active scenario's
own layers only, or the same analysis appears once per scenario.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.http import HttpResponse
from django.shortcuts import reverse
from django.test import RequestFactory
from django.test import TestCase

from brewgis.workspace.analysis.layer_registry import visible_layers_for_panel
from brewgis.workspace.models import Layer
from brewgis.workspace.models import LayerGroup
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.views.panels import resolve_scenario_param
from tests.factories import LayerFactory
from tests.factories import ScenarioFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory


def _scoped_workspace() -> tuple:
    """A workspace with a base scenario, an alternative, and a foreign one.

    Returns ``(workspace, base_scenario, scenario, other_scenario)``.
    """
    workspace = WorkspaceFactory(db_schema="public")
    base_scenario = ScenarioFactory(
        workspace=workspace, scenario_type=ScenarioType.BASE
    )
    scenario = ScenarioFactory(
        workspace=workspace, scenario_type=ScenarioType.ALTERNATIVE
    )
    other_scenario = ScenarioFactory(
        workspace=workspace, scenario_type=ScenarioType.ALTERNATIVE
    )
    return workspace, base_scenario, scenario, other_scenario


@pytest.mark.views
class TestVisibleLayersForPanel(TestCase):
    """``visible_layers_for_panel`` decides which layers a scenario shows."""

    def setUp(self):
        (
            self.workspace,
            self.base_scenario,
            self.scenario,
            self.other_scenario,
        ) = _scoped_workspace()
        self.workspace_layer = LayerFactory(
            workspace=self.workspace, key="imported_parcels", scenario=None
        )
        self.base_results = LayerFactory(
            workspace=self.workspace,
            key="vmt_base",
            scenario=self.base_scenario,
        )
        self.results = LayerFactory(
            workspace=self.workspace, key="vmt_alt", scenario=self.scenario
        )
        self.other_results = LayerFactory(
            workspace=self.workspace,
            key="vmt_other",
            scenario=self.other_scenario,
        )

    def _visible_keys(self, scenario) -> set[str]:
        return {
            layer.key for layer in visible_layers_for_panel(self.workspace, scenario)
        }

    def test_shows_own_and_workspace_level_layers(self):
        assert self._visible_keys(self.scenario) == {
            self.workspace_layer.key,
            self.results.key,
        }

    def test_excludes_another_scenarios_layers(self):
        keys = self._visible_keys(self.scenario)
        assert self.other_results.key not in keys
        assert self.base_results.key not in keys

    def test_base_scenario_shows_its_own_results(self):
        assert self._visible_keys(self.base_scenario) == {
            self.workspace_layer.key,
            self.base_results.key,
        }


@pytest.mark.views
class TestMapLayersAreScenarioScoped(TestCase):
    """``view_workspace_map`` renders only the active scenario's layers."""

    def setUp(self):
        self.user = UserFactory()
        self.client.force_login(self.user)
        (
            self.workspace,
            self.base_scenario,
            self.scenario,
            _other,
        ) = _scoped_workspace()
        LayerFactory(
            workspace=self.workspace, key="vmt_base", scenario=self.base_scenario
        )
        LayerFactory(workspace=self.workspace, key="vmt_alt", scenario=self.scenario)
        self.map_url = reverse("workspace:workspace_map", args=[self.workspace.pk])

    def _rendered_layer_keys(self, query: str = "") -> set[str]:
        captured: dict = {}

        def fake_render(request, template_name, context=None, *args, **kwargs):
            captured["context"] = context or {}
            return HttpResponse("")

        with patch("brewgis.workspace.views.map.render", side_effect=fake_render):
            self.client.get(f"{self.map_url}{query}")
        return {layer["id"] for layer in captured["context"]["layer_data"]}

    def test_alternative_scenario_renders_only_its_own_layers(self):
        # The painted-features overlay is this scenario's own canvas view (it
        # has no source without an alternative scenario), so it belongs here.
        assert self._rendered_layer_keys(f"?scenario={self.scenario.pk}") == {
            "vmt_alt",
            "painted_features",
        }

    def test_base_scenario_renders_only_its_own_layers(self):
        assert self._rendered_layer_keys(f"?scenario={self.base_scenario.pk}") == {
            "vmt_base"
        }


@pytest.mark.views
class TestLayerPanelIsScenarioScoped(TestCase):
    """The Layers panel and the requests that refresh it stay scoped."""

    def setUp(self):
        self.user = UserFactory()
        self.client.force_login(self.user)
        (
            self.workspace,
            self.base_scenario,
            self.scenario,
            self.other_scenario,
        ) = _scoped_workspace()
        self.group = LayerGroup.objects.create(
            workspace=self.workspace, name="Analysis Results"
        )
        self.base_results = LayerFactory(
            workspace=self.workspace,
            key="vmt_base",
            name="Vmt Base",
            scenario=self.base_scenario,
            group=self.group,
        )
        self.results = LayerFactory(
            workspace=self.workspace,
            key="vmt_alt",
            name="Vmt Alt",
            scenario=self.scenario,
            group=self.group,
        )
        self.other_results = LayerFactory(
            workspace=self.workspace,
            key="vmt_other",
            name="Vmt Other",
            scenario=self.other_scenario,
            group=self.group,
        )
        self.panel_url = reverse("workspace:panel_layer_list", args=[self.workspace.pk])
        self.group_list_url = reverse(
            "workspace:layer_group_list", args=[self.workspace.pk]
        )

    def test_panel_lists_only_the_active_scenarios_layers(self):
        html = self.client.get(
            f"{self.panel_url}?scenario={self.scenario.pk}"
        ).content.decode()
        assert "Vmt Alt" in html
        assert "Vmt Base" not in html
        assert "Vmt Other" not in html

    def test_group_list_lists_only_the_active_scenarios_layers(self):
        html = self.client.get(
            f"{self.group_list_url}?scenario={self.scenario.pk}"
        ).content.decode()
        assert "Vmt Alt" in html
        assert "Vmt Base" not in html
        assert "Vmt Other" not in html

    def test_delete_refresh_keeps_the_scenario_the_panel_was_rendered_from(self):
        """Deleting a layer re-renders the panel the user is looking at.

        The delete request carries no ``?scenario=`` of its own, so without the
        requesting page's scenario the list would silently swap to the base
        scenario's layers (htmx reports that page as ``HX-Current-URL``).
        """
        response = self.client.post(
            reverse("workspace:layer_delete", args=[self.results.pk]),
            headers={
                "HX-Request": "true",
                "HX-Current-URL": (
                    f"http://testserver/2/map/?scenario={self.scenario.pk}"
                ),
            },
        )
        assert response.status_code == 200
        html = response.content.decode()
        assert "Vmt Base" not in html
        assert "Vmt Other" not in html
        assert Layer.objects.filter(pk=self.results.pk).exists() is False


@pytest.mark.views
class TestResolveScenarioParam(TestCase):
    """``resolve_scenario_param`` resolves the panel's active scenario."""

    def setUp(self):
        self.workspace, self.base_scenario, self.scenario, _other = _scoped_workspace()

    def test_uses_the_scenario_of_the_requesting_page(self):
        request = RequestFactory().post(
            "/layers/1/delete/",
            HTTP_HX_CURRENT_URL=(
                f"http://testserver/2/map/?scenario={self.scenario.pk}"
            ),
        )
        assert resolve_scenario_param(request, self.workspace) == self.scenario

    def test_ignores_an_unknown_scenario_in_the_requesting_page(self):
        request = RequestFactory().post(
            "/layers/1/delete/",
            HTTP_HX_CURRENT_URL="http://testserver/2/map/?scenario=999999",
        )
        assert resolve_scenario_param(request, self.workspace) == self.base_scenario

    def test_prefers_the_explicit_param(self):
        request = RequestFactory().post(
            f"/layers/1/delete/?scenario={self.base_scenario.pk}",
            HTTP_HX_CURRENT_URL=(
                f"http://testserver/2/map/?scenario={self.scenario.pk}"
            ),
        )
        assert resolve_scenario_param(request, self.workspace) == self.base_scenario
