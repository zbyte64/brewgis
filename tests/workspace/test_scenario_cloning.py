# ruff: noqa: ANN201
"""Tests for scenario cloning service.

Requires a PostgreSQL+PostGIS database for SQL view operations.
"""

from __future__ import annotations

import pytest
from django.db import connection

from brewgis.workspace.models import Layer
from brewgis.workspace.services.canvas_view_manager import _fetch_base_columns
from brewgis.workspace.services.canvas_view_manager import _qi
from brewgis.workspace.services.canvas_view_manager import build_canvas_view_select
from brewgis.workspace.services.scenario_cloner import clone_scenario
from tests.factories import PaintedCanvasFactory


def _build_canvas_view(scenario) -> None:
    """Create *scenario*'s canvas view the way its SQLMesh model would.

    The model itself can't be planned from a test process: ``run_sqlmesh_plan``
    plans against the stack's database while the model's blueprint profiles read
    the Django ORM — i.e. the *test* database — so a plan here would create the
    view somewhere else entirely (and mutate the developer's database on the
    way). Build the same view from the same generator instead, exactly as
    ``test_scenario_canvas.py`` does, so cloning and deletion still act on the
    view they create and drop.
    """
    _, _, all_columns = _fetch_base_columns(scenario.workspace.base_table)
    select = build_canvas_view_select(
        base_ref=scenario.workspace.base_table,
        all_columns=all_columns,
        scenario_id=scenario.pk,
    )
    view = _qi(f"{scenario.target_schema}.scenario_{scenario.slug}_canvas")
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {_qi(scenario.target_schema)}")
        cursor.execute(f"CREATE OR REPLACE VIEW {view} AS {select}")


@pytest.fixture(autouse=True)
def _canvas_views(monkeypatch) -> None:
    """Give every test in this module the canvas-view builder, not a plan."""
    monkeypatch.setattr(
        "brewgis.workspace.services.scenario_cloner.materialize_scenario_canvas",
        _build_canvas_view,
    )


@pytest.mark.integration
class TestScenarioCloning:
    """Tests for :func:`clone_scenario`."""

    def test_creates_alternative_with_correct_attributes(
        self, base_canvas_table, scenario
    ):
        """Cloned scenario has ALTERNATIVE type, correct parent, base & horizon year."""
        cloned = clone_scenario(
            source=scenario,
            name="Alternative 1",
        )

        assert cloned.scenario_type == "alternative"
        assert cloned.parent == scenario
        assert cloned.base_year == scenario.base_year
        assert cloned.horizon_year == scenario.horizon_year
        assert cloned.workspace == scenario.workspace

    def test_preserves_workspace_and_base_year(self, base_canvas_table, scenario):
        """Clone preserves workspace and base_year from source."""
        cloned = clone_scenario(
            source=scenario,
            name="Alternative 2",
        )

        assert cloned.workspace_id == scenario.workspace_id
        assert cloned.base_year == scenario.base_year

    def test_does_not_copy_painted_canvas_rows(self, base_canvas_table, scenario):
        """Cloning does not copy PaintedCanvas overrides to the new scenario."""
        PaintedCanvasFactory(scenario=scenario, feature_id="1", column_name="du")

        cloned = clone_scenario(
            source=scenario,
            name="Clean Canvas",
        )

        assert cloned.painted_features.count() == 0

    def test_can_create_multiple_alternatives(self, base_canvas_table, scenario):
        """Multiple alternatives can be cloned from the same base."""
        alt1 = clone_scenario(source=scenario, name="Alt A")
        alt2 = clone_scenario(source=scenario, name="Alt B")

        assert alt1.pk != alt2.pk
        assert alt1.parent == scenario
        assert alt2.parent == scenario
        assert alt1.slug != alt2.slug

    def test_creates_canvas_view(self, base_canvas_table, scenario):
        """Cloning creates a valid SQL view in the database."""
        cloned = clone_scenario(
            source=scenario,
            name="View Test",
        )

        view_name = f"scenario_{cloned.slug}_canvas"
        view_schema = cloned.target_schema

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name FROM information_schema.views
                WHERE table_schema = %s AND table_name = %s
                """,
                [view_schema, view_name],
            )
            result = cursor.fetchone()

        assert result is not None, f"View {view_schema}.{view_name} does not exist"

    def test_registers_layer(self, base_canvas_table, scenario):
        """Cloning registers a Layer for the canvas view."""
        cloned = clone_scenario(
            source=scenario,
            name="Layer Test",
        )

        layer = Layer.objects.filter(
            workspace=scenario.workspace,
            key=f"scenario_{cloned.slug}_canvas",
        ).first()

        assert layer is not None
        assert cloned.target_schema in layer.db_table
        assert cloned.slug in layer.db_table

    def test_delete_drops_canvas_view(self, base_canvas_table, scenario):
        """Deleting a scenario drops its canvas view."""
        cloned = clone_scenario(
            source=scenario,
            name="Drop Test",
        )

        view_schema = cloned.target_schema
        view_name = f"scenario_{cloned.slug}_canvas"

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name FROM information_schema.views
                WHERE table_schema = %s AND table_name = %s
                """,
                [view_schema, view_name],
            )
            assert cursor.fetchone() is not None

        cloned.delete()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name FROM information_schema.views
                WHERE table_schema = %s AND table_name = %s
                """,
                [view_schema, view_name],
            )
            assert cursor.fetchone() is None

    def test_auto_creates_symbology_config(self, base_canvas_table, scenario):
        """Cloning auto-generates a SymbologyConfig for the canvas layer."""
        cloned = clone_scenario(
            source=scenario,
            name="Symbology Test",
        )

        layer = Layer.objects.get(
            workspace=scenario.workspace,
            key=f"scenario_{cloned.slug}_canvas",
        )

        assert hasattr(layer, "symbology")
        assert layer.symbology is not None
        assert layer.symbology.auto_generated is True
