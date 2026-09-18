# ruff: noqa: ANN201
"""Tests for the async PaintRun/Celery task plumbing behind paint operations.

These exercise the PaintRun row and ``paint_status`` polling endpoint
directly, on top of the HTTP-response-shape coverage in
``test_paint_views.py`` (which already proves the "apply" endpoints return
the same result as before — CELERY_TASK_ALWAYS_EAGER runs the task inline
in tests, so those endpoints look synchronous even though they now go
through a PaintRun + Celery task).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.test import TestCase
from django.urls import reverse

from brewgis.workspace.models import PaintRun
from brewgis.workspace.models import ScenarioType
from tests.factories import BuildingTypeFactory
from tests.factories import ScenarioFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory


def _patch_refresh() -> patch:
    return patch(
        "brewgis.workspace.views.paint.refresh_canvas_view",
        return_value="public.mock_canvas_view",
    )


@pytest.mark.views
class TestPaintRunTracking(TestCase):
    """A paint "apply" request creates a PaintRun and runs it to completion."""

    def setUp(self):
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()
        self.scenario = ScenarioFactory(
            workspace=self.workspace, scenario_type=ScenarioType.ALTERNATIVE
        )
        self.client.force_login(self.user)

    def test_direct_paint_creates_a_completed_paint_run(self):
        url = reverse(
            "workspace:paint_features",
            kwargs={"workspace_pk": self.workspace.pk, "scenario_pk": self.scenario.pk},
        )
        with _patch_refresh():
            response = self.client.post(
                url,
                json.dumps({"features": ["1", "2"], "column": "du", "value": 100.0}),
                content_type="application/json",
            )
        assert response.status_code == 200

        run = PaintRun.objects.get(workspace=self.workspace, scenario=self.scenario)
        assert run.operation == "direct"
        assert run.status == "completed"
        assert run.result["status"] == "ok"
        assert run.result["painted_count"] == 2
        assert run.params == {"features": ["1", "2"], "column": "du", "value": 100.0}
        assert run.created_by == self.user
        assert run.started_at is not None
        assert run.completed_at is not None

    def test_paint_status_returns_the_same_result_as_the_apply_response(self):
        url = reverse(
            "workspace:paint_features",
            kwargs={"workspace_pk": self.workspace.pk, "scenario_pk": self.scenario.pk},
        )
        with _patch_refresh():
            apply_response = self.client.post(
                url,
                json.dumps({"features": ["1"], "column": "du", "value": 50.0}),
                content_type="application/json",
            )
        run = PaintRun.objects.get(workspace=self.workspace, scenario=self.scenario)

        status_url = reverse(
            "workspace:paint_status",
            kwargs={
                "workspace_pk": self.workspace.pk,
                "scenario_pk": self.scenario.pk,
                "run_pk": run.pk,
            },
        )
        status_response = self.client.get(status_url)

        assert status_response.status_code == 200
        assert status_response.json() == apply_response.json()

    def test_paint_status_404s_for_a_run_in_another_scenario(self):
        other_scenario = ScenarioFactory(
            workspace=self.workspace, scenario_type=ScenarioType.ALTERNATIVE
        )
        url = reverse(
            "workspace:paint_features",
            kwargs={"workspace_pk": self.workspace.pk, "scenario_pk": self.scenario.pk},
        )
        with _patch_refresh():
            self.client.post(
                url,
                json.dumps({"features": ["1"], "column": "du", "value": 1.0}),
                content_type="application/json",
            )
        run = PaintRun.objects.get(workspace=self.workspace, scenario=self.scenario)

        status_url = reverse(
            "workspace:paint_status",
            kwargs={
                "workspace_pk": self.workspace.pk,
                "scenario_pk": other_scenario.pk,
                "run_pk": run.pk,
            },
        )
        response = self.client.get(status_url)
        assert response.status_code == 404

    def test_a_failed_run_reports_error_status_via_polling(self):
        """A run that ends up with an error result is exposed as status=failed."""
        url = reverse(
            "workspace:paint_features",
            kwargs={"workspace_pk": self.workspace.pk, "scenario_pk": self.scenario.pk},
        )
        # No matching PAINTABLE_COLUMNS entry -> validation 400, before any
        # PaintRun is created — use an operation-level failure instead:
        # constraint block is easiest to trigger without extra fixtures by
        # mocking the constraint checker directly.
        blocked = {
            "status": "error",
            "message": "Paint operation blocked by workspace constraints.",
            "violations": [{"message": "too high"}],
            "http_status": 409,
        }
        with (
            _patch_refresh(),
            patch(
                "brewgis.workspace.views.paint._enforce_paint_constraints",
                return_value=blocked,
            ),
        ):
            response = self.client.post(
                url,
                json.dumps({"features": ["1"], "column": "du", "value": 999.0}),
                content_type="application/json",
            )

        assert response.status_code == 409
        assert response.json()["status"] == "error"

        run = PaintRun.objects.get(workspace=self.workspace, scenario=self.scenario)
        assert run.status == "failed"
        assert run.result["violations"] == [{"message": "too high"}]


@pytest.mark.views
class TestPaintRunTrackingBuiltFormOperations(TestCase):
    """Each built-form-driven "apply" endpoint creates its own PaintRun too —
    not just direct paint (see TestPaintRunTracking above)."""

    def setUp(self):
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()
        self.scenario = ScenarioFactory(
            workspace=self.workspace, scenario_type=ScenarioType.ALTERNATIVE
        )
        self.client.force_login(self.user)
        self.bt = BuildingTypeFactory(
            workspace=self.workspace,
            name="Mid Rise Mixed Use",
            du_per_acre=10.0,
            emp_per_acre=0.0,
            household_size=2.5,
            vacancy_rate=5.0,
            far=0.5,
        )

    def test_paint_built_form_creates_a_completed_paint_run(self):
        url = reverse(
            "workspace:paint_built_form",
            kwargs={"workspace_pk": self.workspace.pk, "scenario_pk": self.scenario.pk},
        )
        with (
            _patch_refresh(),
            patch(
                "brewgis.workspace.views.paint._fetch_feature_data",
                return_value={"1": {"id": 1, "area_gross": 10.0, "area_parcel": 8.0}},
            ),
        ):
            response = self.client.post(
                url,
                json.dumps(
                    {"features": ["1"], "bf_type": "building", "bf_id": self.bt.pk}
                ),
                content_type="application/json",
            )

        assert response.status_code == 200
        run = PaintRun.objects.get(workspace=self.workspace, scenario=self.scenario)
        assert run.operation == "built_form"
        assert run.status == "completed"
        assert run.result["status"] == "ok"
        assert run.params == {
            "features": ["1"],
            "bf_type": "building",
            "bf_id": self.bt.pk,
        }

    def test_match_built_form_creates_a_completed_paint_run(self):
        url = reverse(
            "workspace:match_built_form",
            kwargs={"workspace_pk": self.workspace.pk, "scenario_pk": self.scenario.pk},
        )
        with (
            _patch_refresh(),
            patch(
                "brewgis.workspace.views.paint._fetch_canvas_feature_data",
                return_value={
                    "1": {
                        "id": 1,
                        "du": 100.0,
                        "emp": 0.0,
                        "area_gross": 10.0,
                        "area_parcel": 10.0,
                    }
                },
            ),
        ):
            response = self.client.post(
                url,
                json.dumps({"features": ["1"]}),
                content_type="application/json",
            )

        assert response.status_code == 200
        run = PaintRun.objects.get(workspace=self.workspace, scenario=self.scenario)
        assert run.operation == "match"
        assert run.status == "completed"
        assert run.result["status"] == "ok"
        assert run.result["matches"][0]["building_type_id"] == self.bt.pk
        assert run.params == {"features": ["1"]}

    def test_fill_built_form_creates_a_completed_paint_run(self):
        url = reverse(
            "workspace:fill_built_form",
            kwargs={"workspace_pk": self.workspace.pk, "scenario_pk": self.scenario.pk},
        )
        with (
            _patch_refresh(),
            patch(
                "brewgis.workspace.views.paint._fetch_canvas_feature_data",
                return_value={
                    "1": {
                        "id": 1,
                        "area_gross": 10.0,
                        "area_parcel": 10.0,
                        "built_form_key": "bt__mid_rise_mixed_use",
                    }
                },
            ),
        ):
            response = self.client.post(
                url,
                json.dumps({"features": ["1"]}),
                content_type="application/json",
            )

        assert response.status_code == 200
        run = PaintRun.objects.get(workspace=self.workspace, scenario=self.scenario)
        assert run.operation == "fill"
        assert run.status == "completed"
        assert run.result["status"] == "ok"
        assert run.result["matched"][0]["building_type_id"] == self.bt.pk
        assert run.params == {"features": ["1"]}
