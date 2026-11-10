# ruff: noqa: ANN201
"""Tests for drag-and-drop reordering in the Layers panel.

Dropping a layer on another POSTs ``target_layer_pk`` to
``layer_group_move_layer``, which moves the dragged layer to the target's
place in the active scenario's panel. Every layer starts at display_order 0,
so the move has to work while all of them tie.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from django.shortcuts import reverse

from brewgis.workspace.analysis.layer_registry import visible_layers_for_panel
from brewgis.workspace.models import Layer
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.models import Workspace
from tests.factories import LayerFactory
from tests.factories import ScenarioFactory

if TYPE_CHECKING:
    from django.http import HttpResponse
    from django.test import Client


@dataclass
class Panel:
    """A logged-in client on a base scenario's panel of tied layers a-d."""

    client: Client
    workspace: Workspace
    scenario: Scenario
    layers: dict[str, Layer]

    def drop(self, dragged: Layer, target: Layer) -> HttpResponse:
        return self.client.post(
            reverse("workspace:layer_group_move_layer", args=[dragged.pk])
            + f"?scenario={self.scenario.pk}",
            {"target_layer_pk": target.pk},
        )

    def keys(self) -> str:
        qs = visible_layers_for_panel(self.workspace, self.scenario)
        return "".join(qs.values_list("key", flat=True))


@pytest.fixture
def panel(client, user, workspace):
    client.force_login(user)
    scenario = ScenarioFactory(workspace=workspace, scenario_type=ScenarioType.BASE)
    layers = {
        key: LayerFactory(
            workspace=workspace, key=key, scenario=scenario, display_order=0
        )
        for key in "abcd"
    }
    return Panel(client, workspace, scenario, layers)


@pytest.mark.views
@pytest.mark.django_db
class TestDragToReorder:
    @pytest.mark.parametrize(
        ("dragged", "target", "expected"),
        [
            pytest.param("a", "c", "bcad", id="down-lands-after-target"),
            pytest.param("d", "b", "adbc", id="up-lands-before-target"),
            pytest.param("b", "a", "bacd", id="up-onto-first"),
            pytest.param("c", "d", "abdc", id="down-onto-last"),
        ],
    )
    def test_dropped_layer_takes_the_targets_place(
        self, panel, dragged, target, expected
    ):
        response = panel.drop(panel.layers[dragged], panel.layers[target])

        assert response.status_code == 200
        assert panel.keys() == expected
        rendered = response.content.decode()
        positions = [rendered.index(f'data-layer-key="{key}"') for key in expected]
        assert positions == sorted(positions)

    def test_successive_drops_build_on_each_other(self, panel):
        layers = panel.layers

        panel.drop(layers["d"], layers["a"])
        panel.drop(layers["a"], layers["c"])

        assert panel.keys() == "dbca"

    def test_drop_on_another_groups_layer_joins_that_group(self, panel):
        layers = panel.layers
        group = panel.workspace.layer_groups.create(name="Results")
        for key in "cd":
            layers[key].group = group
            layers[key].save()
        assert panel.keys() == "cdab"

        panel.drop(layers["a"], layers["d"])

        layers["a"].refresh_from_db()
        assert layers["a"].group == group
        assert panel.keys() == "cadb"

    def test_announces_one_layers_changed(
        self, panel, map_events, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            panel.drop(panel.layers["a"], panel.layers["c"])

        assert [payload["kind"] for _, payload in map_events] == ["layers.changed"]

    def test_layer_outside_the_scenarios_panel_is_not_found(self, panel):
        other = ScenarioFactory(
            workspace=panel.workspace, scenario_type=ScenarioType.ALTERNATIVE
        )
        foreign = LayerFactory(workspace=panel.workspace, key="x", scenario=other)

        response = panel.drop(foreign, panel.layers["a"])

        assert response.status_code == 404
        assert panel.keys() == "abcd"
