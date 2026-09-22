# ruff: noqa: ANN201, ARG002
"""Tests for the canvas view SQL generator and the scenario blueprint profiles.

The view itself is created by SQLMesh (``models/scenarios/scenario_canvas.py``);
what this module owns is the SELECT body it renders and the per-scenario
blueprint facts it is handed. Requires a PostgreSQL+PostGIS database.
"""

from __future__ import annotations

import pytest
from django.db import connection

from brewgis.sqlmesh.macros.scenario_canvas_blueprints import scenario_canvas_profiles
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.services.canvas_view_manager import TEXT_COLUMNS
from brewgis.workspace.services.canvas_view_manager import _fetch_base_columns
from brewgis.workspace.services.canvas_view_manager import build_canvas_view_select
from tests.factories import ScenarioFactory
from tests.factories import WorkspaceFactory

BASE_TABLE = "public.base_canvas"
BASE_REF = "brewgis.fresno.base_canvas_reconciled"


class TestBuildCanvasViewSelect:
    """The generated SELECT body — shared by the model and the paint surfaces."""

    def test_selects_from_the_given_reference_and_coalesces_paintable_columns(self):
        sql = build_canvas_view_select(
            base_ref=BASE_REF,
            all_columns=["parcel_id", "geometry", "du", "pop", "geometry_key"],
            scenario_id=12,
        )

        assert f"FROM {BASE_REF} bc" in sql
        assert "COALESCE(pc.du, bc.du) AS du" in sql
        assert "COALESCE(pc.pop, bc.pop) AS pop" in sql
        # Non-paintable columns pass through untouched.
        assert "bc.geometry_key" in sql
        assert "(pc._feature_id IS NOT NULL) AS uf_is_painted" in sql
        assert "WHERE scenario_id = 12" in sql
        assert "GROUP BY feature_id" in sql

    def test_text_columns_pivot_from_painted_text_value(self):
        assert "built_form_key" in TEXT_COLUMNS

        sql = build_canvas_view_select(
            base_ref=BASE_REF,
            all_columns=["parcel_id", "geometry", "built_form_key", "du"],
            scenario_id=1,
        )

        assert (
            "MAX(CASE WHEN column_name = 'built_form_key' THEN painted_text_value END)"
            " AS built_form_key" in sql
        )
        assert "MAX(CASE WHEN column_name = 'du' THEN painted_value END) AS du" in sql

    def test_column_order_follows_the_passed_column_list(self):
        # The list comes from the base table's ordinal order; iterating
        # PAINTABLE_COLUMNS (a frozenset) directly would order the SELECT
        # differently per process, and Postgres cannot reorder a view's columns.
        columns = ["parcel_id", "geometry", "du", "pop"]

        sql = build_canvas_view_select(
            base_ref=BASE_REF, all_columns=columns, scenario_id=1
        )

        assert sql.index("COALESCE(pc.du, bc.du)") < sql.index(
            "COALESCE(pc.pop, bc.pop)"
        )


@pytest.mark.integration
class TestScenarioCanvasProfiles:
    """Blueprint facts SQLMesh expands one model from, per ALTERNATIVE scenario."""

    @pytest.fixture
    def workspace_on_base_canvas(self, base_canvas_table):
        """A workspace whose base table is the shared base canvas."""
        return WorkspaceFactory(base_table=BASE_TABLE)

    @pytest.fixture
    def narrow_base_workspace(self, db):
        """A workspace whose base table lacks the base-canvas columns."""
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE TABLE public.paint_fixture_minimal "
                "(id text PRIMARY KEY, geometry geometry(Polygon, 4326))"
            )
        workspace = WorkspaceFactory(base_table="public.paint_fixture_minimal")
        try:
            yield workspace
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP TABLE IF EXISTS public.paint_fixture_minimal")

    def test_alternative_scenario_yields_one_profile(self, workspace_on_base_canvas):
        scenario = ScenarioFactory(
            workspace=workspace_on_base_canvas,
            slug="profiled-scenario",
            scenario_type=ScenarioType.ALTERNATIVE,
        )

        profiles = [
            profile
            for profile in scenario_canvas_profiles()
            if profile["scenario_id"] == scenario.pk
        ]

        assert len(profiles) == 1
        profile = profiles[0]
        assert profile["schema"] == scenario.target_schema
        assert profile["view_name"] == f"scenario_{scenario.slug}_canvas"
        assert profile["model_table"] == f"canvas_{scenario.pk}"
        assert profile["base_table"] == BASE_TABLE
        assert profile["base_model"] == f"brewgis.{BASE_TABLE}"
        assert profile["is_sqlmesh_base"] == 0
        columns = profile["all_columns"]
        assert isinstance(columns, list)
        assert sorted(columns) == sorted(_fetch_base_columns(BASE_TABLE)[2])

    def test_base_scenario_yields_no_profile(self, workspace_on_base_canvas):
        scenario = ScenarioFactory(
            workspace=workspace_on_base_canvas,
            slug="base-scenario",
            scenario_type=ScenarioType.BASE,
        )

        assert not [
            profile
            for profile in scenario_canvas_profiles()
            if profile["scenario_id"] == scenario.pk
        ]

    def test_skips_a_scenario_whose_base_table_is_not_a_base_canvas(
        self, narrow_base_workspace
    ):
        # A base table without the base-canvas columns can't carry a canvas
        # view; emitting a model for it would break every plan instead.
        scenario = ScenarioFactory(
            workspace=narrow_base_workspace,
            slug="narrow-base",
            scenario_type=ScenarioType.ALTERNATIVE,
        )

        assert not [
            profile
            for profile in scenario_canvas_profiles()
            if profile["scenario_id"] == scenario.pk
        ]

    def test_duplicate_scenario_slugs_claim_one_view(self, workspace_on_base_canvas):
        # Scenario schemas are not workspace-scoped, so two workspaces may ask
        # for the same view name; the first (lowest id) keeps it.
        first = ScenarioFactory(
            workspace=workspace_on_base_canvas,
            slug="shared-canvas",
            scenario_type=ScenarioType.ALTERNATIVE,
        )
        second = ScenarioFactory(
            workspace=WorkspaceFactory(base_table=BASE_TABLE),
            slug="shared-canvas",
            scenario_type=ScenarioType.ALTERNATIVE,
        )

        claimed = [
            profile["scenario_id"]
            for profile in scenario_canvas_profiles()
            if profile["view_name"] == "scenario_shared-canvas_canvas"
        ]

        assert claimed == [min(first.pk, second.pk)]
