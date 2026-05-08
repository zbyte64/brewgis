# ruff: noqa: ANN201
"""Tests for paint views — direct column painting and built form painting.

These tests verify the HTTP layer (auth, validation, JSON response shape)
but do NOT require PostGIS — the canvas view refresh is mocked.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.test import TestCase
from django.urls import reverse

from brewgis.workspace.models import PaintedCanvas
from tests.factories import BuildingTypeFactory
from tests.factories import PaintedCanvasFactory
from tests.factories import PlaceTypeBuildingTypeMixFactory
from tests.factories import PlaceTypeFactory
from tests.factories import ScenarioFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory

PAINT_URL_NAME = "workspace:paint_features"
CLEAR_URL_NAME = "workspace:clear_paint"
BF_PAINT_URL_NAME = "workspace:paint_built_form"


@pytest.mark.views
class TestPaintFeaturesView(TestCase):
    """Tests for ``paint_features`` view — direct column paint."""

    def setUp(self):
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()
        self.scenario = ScenarioFactory(workspace=self.workspace)
        self.paint_url = reverse(
            PAINT_URL_NAME,
            kwargs={
                "workspace_pk": self.workspace.pk,
                "scenario_pk": self.scenario.pk,
            },
        )
        self.clear_url = reverse(
            CLEAR_URL_NAME,
            kwargs={
                "workspace_pk": self.workspace.pk,
                "scenario_pk": self.scenario.pk,
            },
        )

    def _patch_refresh(self) -> patch:
        """Mock refresh_canvas_view to avoid PostGIS requirement."""
        return patch(
            "brewgis.workspace.views.paint.refresh_canvas_view",
            return_value="public.mock_canvas_view",
        )

    def test_unauthenticated_returns_403(self):
        """Unauthenticated POST redirects to login (302)."""
        response = self.client.post(
            self.paint_url, json.dumps({}), content_type="application/json"
        )
        assert response.status_code == 302

    def test_paint_creates_rows(self):
        """Direct column paint creates PaintedCanvas rows."""
        self.client.force_login(self.user)
        with self._patch_refresh():
            response = self.client.post(
                self.paint_url,
                json.dumps({"features": ["1", "2"], "column": "du", "value": 100.0}),
                content_type="application/json",
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["painted_count"] == 2

        rows = PaintedCanvas.objects.filter(scenario=self.scenario)
        assert rows.count() == 2
        assert set(rows.values_list("feature_id", flat=True)) == {"1", "2"}
        assert set(rows.values_list("column_name", flat=True)) == {"du"}

    def test_paint_none_value(self):
        """Painting with null value creates row with None."""
        self.client.force_login(self.user)
        with self._patch_refresh():
            response = self.client.post(
                self.paint_url,
                json.dumps({"features": ["1"], "column": "pop", "value": None}),
                content_type="application/json",
            )
        assert response.status_code == 200

        row = PaintedCanvas.objects.get(
            scenario=self.scenario, feature_id="1", column_name="pop"
        )
        assert row.painted_value is None

    def test_repaint_updates_existing_row(self):
        """Painting the same scenario/feature/column updates existing row."""
        self.client.force_login(self.user)
        PaintedCanvasFactory(
            scenario=self.scenario,
            feature_id="1",
            column_name="du",
            painted_value=50.0,
        )

        with self._patch_refresh():
            response = self.client.post(
                self.paint_url,
                json.dumps({"features": ["1"], "column": "du", "value": 200.0}),
                content_type="application/json",
            )
        assert response.status_code == 200

        rows = PaintedCanvas.objects.filter(
            scenario=self.scenario, feature_id="1", column_name="du"
        )
        assert rows.count() == 1
        assert rows.first().painted_value == 200.0

    def test_invalid_column_returns_400(self):
        """Invalid column name returns 400."""
        self.client.force_login(self.user)
        with self._patch_refresh():
            response = self.client.post(
                self.paint_url,
                json.dumps(
                    {"features": ["1"], "column": "nonexistent", "value": 100.0}
                ),
                content_type="application/json",
            )
        assert response.status_code == 400
        data = response.json()
        assert "error" in data["status"]

    def test_empty_features_returns_400(self):
        """Empty feature list returns 400."""
        self.client.force_login(self.user)
        with self._patch_refresh():
            response = self.client.post(
                self.paint_url,
                json.dumps({"features": [], "column": "du", "value": 100.0}),
                content_type="application/json",
            )
        assert response.status_code == 400

    def test_nonexistent_scenario_returns_404(self):
        """Request for nonexistent scenario returns 404."""
        self.client.force_login(self.user)
        url = reverse(
            PAINT_URL_NAME,
            kwargs={"workspace_pk": self.workspace.pk, "scenario_pk": 99999},
        )
        with self._patch_refresh():
            response = self.client.post(
                url,
                json.dumps({"features": ["1"], "column": "du", "value": 100.0}),
                content_type="application/json",
            )
        assert response.status_code == 404

    def test_clear_paint_removes_rows(self):
        """Clear paint removes rows for selected features."""
        self.client.force_login(self.user)
        PaintedCanvasFactory(scenario=self.scenario, feature_id="1", column_name="du")
        PaintedCanvasFactory(scenario=self.scenario, feature_id="2", column_name="du")
        PaintedCanvasFactory(scenario=self.scenario, feature_id="1", column_name="pop")

        with self._patch_refresh():
            response = self.client.post(
                self.clear_url,
                json.dumps({"features": ["1"]}),
                content_type="application/json",
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

        remaining = PaintedCanvas.objects.filter(scenario=self.scenario)
        assert remaining.count() == 1
        assert remaining.first().feature_id == "2"

    def test_clear_nonexistent_features(self):
        """Clear with features that have no paint rows returns ok with 0 count."""
        self.client.force_login(self.user)
        with self._patch_refresh():
            response = self.client.post(
                self.clear_url,
                json.dumps({"features": ["999"]}),
                content_type="application/json",
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_get_method_not_allowed(self):
        """GET on paint endpoint returns 405."""
        self.client.force_login(self.user)
        response = self.client.get(self.paint_url)
        assert response.status_code == 405

    def test_paint_cross_scenario_isolation(self):
        """Painting one scenario does not affect another."""
        self.client.force_login(self.user)
        other_scenario = ScenarioFactory(workspace=self.workspace)

        with self._patch_refresh():
            self.client.post(
                self.paint_url,
                json.dumps({"features": ["1"], "column": "du", "value": 100.0}),
                content_type="application/json",
            )

        assert PaintedCanvas.objects.filter(scenario=self.scenario).count() == 1
        assert PaintedCanvas.objects.filter(scenario=other_scenario).count() == 0


@pytest.mark.views
class TestPaintBuiltFormView(TestCase):
    """Tests for ``paint_built_form`` view — built form painting."""

    def setUp(self):
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()
        self.scenario = ScenarioFactory(workspace=self.workspace)

        self.bt = BuildingTypeFactory(
            du_per_acre=10.0,
            household_size=2.5,
            vacancy_rate=5.0,
            emp_per_acre=0.0,
            far=0.5,
        )
        self.pt = PlaceTypeFactory(row_allocation_pct=25.0)
        PlaceTypeBuildingTypeMixFactory(
            place_type=self.pt, building_type=self.bt, percentage=100.0
        )

        self.bf_paint_url = reverse(
            BF_PAINT_URL_NAME,
            kwargs={
                "workspace_pk": self.workspace.pk,
                "scenario_pk": self.scenario.pk,
            },
        )

    def _patch_refresh_and_data(self) -> tuple[patch, patch]:
        """Mock refresh_canvas_view and _fetch_feature_data."""
        patcher1 = patch(
            "brewgis.workspace.views.paint.refresh_canvas_view",
            return_value="public.mock_canvas_view",
        )
        patcher2 = patch(
            "brewgis.workspace.views.paint._fetch_feature_data",
            return_value={
                "1": {"id": 1, "area_gross": 10.0, "area_parcel": 8.0},
            },
        )
        patcher1.start()
        patcher2.start()
        return patcher1, patcher2

    def test_built_form_paint_building_type(self):
        """Built form paint with BuildingType creates correct painted rows."""
        self.client.force_login(self.user)
        p1, p2 = self._patch_refresh_and_data()
        try:
            response = self.client.post(
                self.bf_paint_url,
                json.dumps(
                    {
                        "features": ["1"],
                        "bf_type": "building",
                        "bf_id": self.bt.pk,
                    }
                ),
                content_type="application/json",
            )
        finally:
            p1.stop()
            p2.stop()

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

        rows = PaintedCanvas.objects.filter(scenario=self.scenario, feature_id="1")
        assert rows.count() > 0

        # Verify expected columns were created
        col_names = set(rows.values_list("column_name", flat=True))
        # du = 10 acres * 10 du/acre = 100 du (after 0% ROW since we pass 0.0)
        # For building_type with row_allocation_pct=0.0, developable = 10 acres
        # du = 10 * 10 = 100
        # pop = 100 * 2.5 = 250
        # hh = 100 * (1 - 0.05) = 95
        assert "du" in col_names
        assert "pop" in col_names
        assert "hh" in col_names

        du_row = rows.get(column_name="du")
        assert abs(float(du_row.painted_value) - 100.0) < 0.1

    def test_built_form_paint_place_type(self):
        """Built form paint with PlaceType runs allocation and creates rows."""
        self.client.force_login(self.user)
        p1, p2 = self._patch_refresh_and_data()
        try:
            response = self.client.post(
                self.bf_paint_url,
                json.dumps(
                    {
                        "features": ["1"],
                        "bf_type": "place",
                        "bf_id": self.pt.pk,
                    }
                ),
                content_type="application/json",
            )
        finally:
            p1.stop()
            p2.stop()

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

        rows = PaintedCanvas.objects.filter(scenario=self.scenario, feature_id="1")
        assert rows.count() > 0
        col_names = set(rows.values_list("column_name", flat=True))
        assert "du" in col_names
        assert "pop" in col_names

    def test_built_form_paint_invalid_type(self):
        """Invalid bf_type returns 400."""
        self.client.force_login(self.user)
        p1, p2 = self._patch_refresh_and_data()
        try:
            response = self.client.post(
                self.bf_paint_url,
                json.dumps(
                    {
                        "features": ["1"],
                        "bf_type": "invalid",
                        "bf_id": 1,
                    }
                ),
                content_type="application/json",
            )
        finally:
            p1.stop()
            p2.stop()

        assert response.status_code == 400

    def test_built_form_paint_missing_bf_id(self):
        """Missing bf_id returns 400."""
        self.client.force_login(self.user)
        p1, p2 = self._patch_refresh_and_data()
        try:
            response = self.client.post(
                self.bf_paint_url,
                json.dumps(
                    {
                        "features": ["1"],
                        "bf_type": "building",
                    }
                ),
                content_type="application/json",
            )
        finally:
            p1.stop()
            p2.stop()

        assert response.status_code == 400

    def test_built_form_paint_nonexistent_bf(self):
        """Nonexistent bf_id returns 404."""
        self.client.force_login(self.user)
        p1, p2 = self._patch_refresh_and_data()
        try:
            response = self.client.post(
                self.bf_paint_url,
                json.dumps(
                    {
                        "features": ["1"],
                        "bf_type": "building",
                        "bf_id": 99999,
                    }
                ),
                content_type="application/json",
            )
        finally:
            p1.stop()
            p2.stop()

        assert response.status_code == 404

    def test_built_form_paint_unauthenticated(self):
        """Unauthenticated built form POST redirects to login (302)."""
        response = self.client.post(
            self.bf_paint_url,
            json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 302
