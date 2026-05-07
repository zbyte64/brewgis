# ruff: noqa: ANN201
"""Tests for canvas SQL view manager.

Requires a PostgreSQL+PostGIS database.
"""

from __future__ import annotations

import pytest
from django.db import connection

from brewgis.workspace.services.canvas_view_manager import create_canvas_view
from brewgis.workspace.services.canvas_view_manager import drop_canvas_view
from brewgis.workspace.services.canvas_view_manager import refresh_canvas_view
from tests.factories import PaintedCanvasFactory
from tests.factories import ScenarioFactory


@pytest.fixture
def base_canvas_table(db) -> str:
    """Create a minimal base canvas table with static + paintable columns."""
    with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS test_base_canvas_vm (
                id SERIAL PRIMARY KEY,
                geometry GEOMETRY(POLYGON, 4326),
                du DOUBLE PRECISION,
                pop DOUBLE PRECISION,
                hh DOUBLE PRECISION,
                status VARCHAR(32)
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO test_base_canvas_vm (geometry, du, pop, hh, status)
            VALUES
                (ST_SetSRID(ST_MakeEnvelope(0, 0, 1, 1), 4326), 100.0, 250.0, 80.0, 'active'),
                (ST_SetSRID(ST_MakeEnvelope(1, 0, 2, 1), 4326), 50.0, 120.0, 40.0, 'active')
            """
        )
    yield "public.test_base_canvas_vm"
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS test_base_canvas_vm CASCADE")


@pytest.fixture
def canvas_scenario(db, workspace):
    """A scenario with a specific slug for canvas view tests."""
    return ScenarioFactory(workspace=workspace, slug="testcanvasvm")


class TestCanvasViewManager:
    """Tests for :mod:`brewgis.workspace.services.canvas_view_manager`."""

    def test_create_view_creates_valid_view(self, base_canvas_table, canvas_scenario):
        """create_canvas_view creates a valid PostGIS view."""
        result = create_canvas_view(canvas_scenario, base_canvas_table)
        assert f"scenario_{canvas_scenario.slug}_canvas" in result

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name FROM information_schema.views
                WHERE table_schema = %s AND table_name = %s
                """,
                [
                    canvas_scenario.target_schema,
                    f"scenario_{canvas_scenario.slug}_canvas",
                ],
            )
            assert cursor.fetchone() is not None

    def test_view_has_correct_columns(self, base_canvas_table, canvas_scenario):
        """View exposes static columns, COALESCE'd paintable columns, and uf_is_painted."""
        create_canvas_view(canvas_scenario, base_canvas_table)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                [
                    canvas_scenario.target_schema,
                    f"scenario_{canvas_scenario.slug}_canvas",
                ],
            )
            cols = {row[0]: row[1] for row in cursor.fetchall()}

        assert "id" in cols
        assert "geometry" in cols
        assert "status" in cols
        assert "du" in cols
        assert "pop" in cols
        assert "hh" in cols
        assert "uf_is_painted" in cols

    def test_view_returns_base_values_when_unpainted(
        self, base_canvas_table, canvas_scenario
    ):
        """Unpainted view returns base canvas values."""
        create_canvas_view(canvas_scenario, base_canvas_table)
        view_id = f"scenario_{canvas_scenario.slug}_canvas"
        qview = f'"{canvas_scenario.target_schema}"."{view_id}"'

        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT du, pop, hh, uf_is_painted FROM {qview} ORDER BY id"
            )
            rows = cursor.fetchall()

        assert len(rows) == 2
        assert rows[0] == (100.0, 250.0, 80.0, False)
        assert rows[1] == (50.0, 120.0, 40.0, False)

    def test_coalesce_picks_painted_value(self, base_canvas_table, canvas_scenario):
        """COALESCE returns painted value when an override exists."""
        create_canvas_view(canvas_scenario, base_canvas_table)
        view_id = f"scenario_{canvas_scenario.slug}_canvas"
        qview = f'"{canvas_scenario.target_schema}"."{view_id}"'

        PaintedCanvasFactory(
            scenario=canvas_scenario,
            feature_id="1",
            column_name="du",
            painted_value=999.0,
        )

        refresh_canvas_view(canvas_scenario, base_canvas_table)

        with connection.cursor() as cursor:
            cursor.execute(f"SELECT du, pop, uf_is_painted FROM {qview} ORDER BY id")
            rows = cursor.fetchall()

        assert rows[0][0] == 999.0
        assert rows[0][1] == 250.0
        assert rows[0][2] is True

        assert rows[1][0] == 50.0
        assert rows[1][1] == 120.0
        assert rows[1][2] is False

    def test_multiple_painted_columns(self, base_canvas_table, canvas_scenario):
        """Multiple columns can be painted on the same feature."""
        create_canvas_view(canvas_scenario, base_canvas_table)
        view_id = f"scenario_{canvas_scenario.slug}_canvas"
        qview = f'"{canvas_scenario.target_schema}"."{view_id}"'

        PaintedCanvasFactory(
            scenario=canvas_scenario,
            feature_id="1",
            column_name="du",
            painted_value=200.0,
        )
        PaintedCanvasFactory(
            scenario=canvas_scenario,
            feature_id="1",
            column_name="pop",
            painted_value=400.0,
        )
        PaintedCanvasFactory(
            scenario=canvas_scenario,
            feature_id="1",
            column_name="hh",
            painted_value=150.0,
        )

        refresh_canvas_view(canvas_scenario, base_canvas_table)

        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT du, pop, hh, uf_is_painted FROM {qview} ORDER BY id"
            )
            rows = cursor.fetchall()

        assert rows[0][0] == 200.0
        assert rows[0][1] == 400.0
        assert rows[0][2] == 150.0
        assert rows[0][3] is True

    def test_drop_view_removes_it(self, base_canvas_table, canvas_scenario):
        """drop_canvas_view removes the view from the database."""
        create_canvas_view(canvas_scenario, base_canvas_table)
        drop_canvas_view(canvas_scenario)

        view_name = f"scenario_{canvas_scenario.slug}_canvas"
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name FROM information_schema.views
                WHERE table_schema = %s AND table_name = %s
                """,
                [canvas_scenario.target_schema, view_name],
            )
            assert cursor.fetchone() is None

    def test_drop_nonexistent_view_does_not_raise(self, canvas_scenario):
        """Dropping a non-existent view is a no-op (DROP IF EXISTS)."""
        drop_canvas_view(canvas_scenario)
