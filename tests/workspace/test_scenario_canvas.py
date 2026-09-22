# ruff: noqa: ANN201, ARG002
"""Tests for the scenario canvas lifecycle — health probe and reconciliation.

Requires a PostgreSQL+PostGIS database.
"""

from __future__ import annotations

import pytest
from django.db import connection

from brewgis.workspace.models import ScenarioType
from brewgis.workspace.services.canvas_view_manager import _fetch_base_columns
from brewgis.workspace.services.canvas_view_manager import _qi
from brewgis.workspace.services.canvas_view_manager import build_canvas_view_select
from brewgis.workspace.services.scenario_canvas import canvas_view_is_healthy
from brewgis.workspace.services.scenario_canvas import reconcile_scenario_canvases
from tests.factories import ScenarioFactory
from tests.factories import WorkspaceFactory

BASE_TABLE = "public.base_canvas"


def _qualified(scenario) -> str:
    return f"{scenario.target_schema}.scenario_{scenario.slug}_canvas"


def _build_canvas_view(scenario) -> None:
    """Create *scenario*'s canvas view the way its SQLMesh model would.

    The model itself can't be planned here: its blueprint profiles read the
    Django ORM (this test database) while `run_sqlmesh_plan` plans against the
    stack's database. Build the same view from the same generator instead.
    """
    _, _, all_columns = _fetch_base_columns(scenario.workspace.base_table)
    select = build_canvas_view_select(
        base_ref=scenario.workspace.base_table,
        all_columns=all_columns,
        scenario_id=scenario.pk,
    )
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {_qi(scenario.target_schema)}")
        cursor.execute(
            f"CREATE OR REPLACE VIEW {_qi(_qualified(scenario))} AS {select}"
        )


@pytest.fixture
def scenario_with_canvas_view(db, base_canvas_table):
    """An ALTERNATIVE scenario with a live canvas view over the base canvas."""
    scenario = ScenarioFactory(
        workspace=WorkspaceFactory(base_table=BASE_TABLE),
        slug="lifecycle-canvas",
        scenario_type=ScenarioType.ALTERNATIVE,
    )
    _build_canvas_view(scenario)
    return scenario


@pytest.mark.integration
class TestCanvasViewHealth:
    """`canvas_view_is_healthy` reports which canvas views reconciliation found broken."""

    def test_reports_healthy_for_a_live_view(self, scenario_with_canvas_view):
        assert canvas_view_is_healthy(scenario_with_canvas_view) is True

    def test_reports_unhealthy_when_the_view_is_gone(self, scenario_with_canvas_view):
        with connection.cursor() as cursor:
            cursor.execute(
                f"DROP VIEW IF EXISTS {_qi(_qualified(scenario_with_canvas_view))}"
            )

        assert canvas_view_is_healthy(scenario_with_canvas_view) is False


@pytest.mark.integration
class TestReconcileScenarioCanvases:
    """Reconciliation restates every canvas model, so staleness is repaired too."""

    def test_recreates_every_scenario_canvas_in_one_restating_plan(
        self, scenario_with_canvas_view, monkeypatch
    ):
        broken = ScenarioFactory(
            workspace=WorkspaceFactory(base_table=BASE_TABLE),
            slug="never-materialized",
            scenario_type=ScenarioType.ALTERNATIVE,
        )
        plans: list[dict] = []
        monkeypatch.setattr(
            "brewgis.workspace.services.scenario_canvas.run_sqlmesh_plan",
            lambda **kwargs: plans.append(kwargs),
        )

        unhealthy = reconcile_scenario_canvases()

        assert unhealthy == [broken.pk]
        assert len(plans) == 1
        plan = plans[0]
        assert plan["environment"] == "prod"
        assert plan["restate_models"] == plan["select"]
        assert sorted(plan["select"]) == sorted(
            [
                f'brewgis."scenario_canvas"."canvas_{scenario.pk}"'
                for scenario in (scenario_with_canvas_view, broken)
            ]
        )

    def test_reports_nothing_unhealthy_when_every_view_is_live(
        self, scenario_with_canvas_view, monkeypatch
    ):
        plans: list[dict] = []
        monkeypatch.setattr(
            "brewgis.workspace.services.scenario_canvas.run_sqlmesh_plan",
            lambda **kwargs: plans.append(kwargs),
        )

        assert reconcile_scenario_canvases() == []
        assert len(plans) == 1

    def test_plans_nothing_when_there_are_no_scenarios(self, db, monkeypatch):
        plans: list[dict] = []
        monkeypatch.setattr(
            "brewgis.workspace.services.scenario_canvas.run_sqlmesh_plan",
            lambda **kwargs: plans.append(kwargs),
        )

        assert reconcile_scenario_canvases() == []
        assert plans == []
