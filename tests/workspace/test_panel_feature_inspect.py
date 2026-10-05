# ruff: noqa: ANN201
"""Tests for the map's feature-inspect panel (``views.panels.panel_feature_inspect``).

Only the HTTP/HTML layer is covered here — the panel is rendered from the
properties the browser already decoded out of the vector tile, so no tile
server or PostGIS connection is required.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from django.test import TestCase
from django.urls import reverse

from brewgis.workspace.analysis.layer_registry import BASE_CANVAS_LAYER_KEY
from brewgis.workspace.models import ScenarioType
from tests.factories import LayerFactory
from tests.factories import ScenarioFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory

if TYPE_CHECKING:
    from django.http import HttpResponse

PANEL_URL_NAME = "workspace:panel_feature_inspect"

FEATURE_ID = "32829025"
TILE_PROPERTIES = {
    "id": FEATURE_ID,
    "parcel_id": FEATURE_ID,
    "area_parcel": "24.7304",
    "pop": 0.0,
    "built_form_key": "mixed_use",
    "geometry": "POINT(0 0)",
}


def _pane_class(html: str) -> str:
    """Return the ``class`` attribute of the Parcel tab pane.

    Bootstrap 5 hides every ``.tab-pane`` that lacks ``.active`` (and, through
    ``.fade``, anything that lacks ``.show``), so this attribute — not the
    presence of the rows in the HTML — decides whether the clicked parcel's
    data is actually visible to the user.
    """
    match = re.search(r'<div class="([^"]*)"\s+id="parcel-inspect-tab"', html)
    assert match is not None, "Parcel tab pane missing from panel HTML"
    return match.group(1)


@pytest.mark.views
class TestPanelFeatureInspect(TestCase):
    """Tests for the feature-inspect panel returned to the map shell."""

    def setUp(self):
        self.user = UserFactory()
        self.workspace = WorkspaceFactory(db_schema="public")
        self.scenario = ScenarioFactory(workspace=self.workspace)
        self.layer = LayerFactory(workspace=self.workspace, key=BASE_CANVAS_LAYER_KEY)
        self.url = reverse(PANEL_URL_NAME, kwargs={"workspace_pk": self.workspace.pk})
        self.client.force_login(self.user)

    def _inspect(self, properties: dict | None = None, query: str = "") -> HttpResponse:
        return self.client.post(
            f"{self.url}{query}",
            json.dumps(
                {"feature_id": FEATURE_ID, "properties": properties or TILE_PROPERTIES}
            ),
            content_type="application/json",
        )

    def test_parcel_pane_is_active_without_layer_tabs(self):
        """A feature no other layer has a row for still gets a visible panel.

        Regression: the Parcel pane used to be marked active only when a tab
        strip was rendered, so clicking a parcel absent from every analysis
        result table produced a panel whose contents were hidden.
        """
        response = self._inspect()

        assert response.status_code == 200
        html = response.content.decode()
        classes = _pane_class(html).split()
        assert "tab-pane" in classes
        assert "active" in classes
        assert "show" in classes
        assert "24.7304" in html
        assert "mixed_use" in html

    def test_values_are_suffixed_with_units(self):
        """Area and currency rows carry their unit; plain counts stay bare.

        The value must be *followed* by the unit inside the same cell — a
        unit rendered elsewhere in the panel would not read as belonging to
        the value beside it.
        """
        response = self._inspect({**TILE_PROPERTIES, "median_income": 43521.0})

        assert response.status_code == 200
        html = response.content.decode()
        assert re.search(r'24\.7304\s*<span class="text-muted">acres</span>', html)
        assert re.search(r'43521\.0\s*<span class="text-muted">\$/yr</span>', html)
        # `pop` is a plain count — the row label already names it, so the
        # cell holds the bare value and no unit span.
        assert re.search(r"<td>\s*0\.0\s*</td>", html)

    def test_paintable_value_keeps_its_unit_next_to_the_input(self):
        """With a scenario active the value becomes an ``<input>``; the unit
        must survive that swap rather than being dropped with the text."""
        alternative = ScenarioFactory(
            workspace=self.workspace, scenario_type=ScenarioType.ALTERNATIVE
        )

        response = self._inspect(
            {**TILE_PROPERTIES, "median_income": 43521.0},
            query=f"?scenario={alternative.pk}",
        )

        assert response.status_code == 200
        html = response.content.decode()
        assert re.search(
            r'<input[^>]*value="43521\.0"[^>]*/>\s*<span class="text-muted">\$/yr</span>',
            html,
        )

    def test_parcel_pane_is_active_with_layer_tabs(self):
        """The Parcel pane stays the default tab when other layers do match."""
        other_layer = LayerFactory(workspace=self.workspace, name="VMT 6")
        with patch(
            "brewgis.workspace.views.panels._fetch_layer_row_for_feature",
            side_effect=lambda layer, _feature_id: (
                [
                    {
                        "name": "area_parcel",
                        "label": "Parcel Area",
                        "value": 12.5,
                        "unit": "acres",
                    }
                ]
                if layer.pk == other_layer.pk
                else None
            ),
        ):
            response = self._inspect()

        assert response.status_code == 200
        html = response.content.decode()
        assert "tab-pane" in _pane_class(html).split()
        assert "active" in _pane_class(html).split()
        assert "nav-tabs" in html
        assert f'id="layer-inspect-tab-{other_layer.pk}"' in html
        assert "Parcel Area" in html
        assert "12.5" in html
        # An analysis layer's own rows are suffixed like the parcel's.
        assert re.search(r'12\.5\s*<span class="text-muted">acres</span>', html)
