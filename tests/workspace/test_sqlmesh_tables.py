# ruff: noqa: ARG002
"""Tests for pure-python helpers in ``services/sqlmesh_tables.py``.

Table discovery itself requires a live database (see ``list_sqlmesh_tables``)
so these tests monkeypatch it and only exercise the link-building logic.
"""

from __future__ import annotations

import pytest

from brewgis.workspace.services import sqlmesh_tables
from brewgis.workspace.services.sqlmesh_tables import SqlmeshTableInfo
from brewgis.workspace.services.sqlmesh_tables import _model_schema
from brewgis.workspace.services.sqlmesh_tables import sqlmesh_link_for_table
from brewgis.workspace.services.sqlmesh_tables import sqlmesh_links_for_tables
from brewgis.workspace.services.sqlmesh_tables import sqlmesh_model_ui_url


class TestModelSchema:
    """``_model_schema`` names the model schema behind a table's schema."""

    def test_maps_a_result_schema_to_its_model_schema(self) -> None:
        assert _model_schema("analysis__scenario_7") == "ascn7"

    def test_leaves_a_model_schema_unchanged(self) -> None:
        assert _model_schema("ascn7") == "ascn7"

    def test_leaves_a_plain_schema_unchanged(self) -> None:
        assert _model_schema("analysis") == "analysis"
        assert _model_schema("scenario_my-scenario") == "scenario_my-scenario"


class TestSqlmeshModelUiUrl:
    """``sqlmesh_model_ui_url`` names the model behind the table."""

    def test_maps_a_result_view_to_the_model_schema(self) -> None:
        # Regression: the import picker linked the table's own schema
        # (".../brewgis.analysis__scenario_7.vmt"), which no model lives at —
        # the SQLMesh UI answers that with "Model not found".
        assert sqlmesh_model_ui_url("analysis__scenario_7", "vmt").endswith(
            "/data-catalog/models/brewgis.ascn7.vmt"
        )

    def test_leaves_a_models_own_schema_alone(self) -> None:
        assert sqlmesh_model_ui_url("fresno", "base_canvas_reconciled").endswith(
            "/data-catalog/models/brewgis.fresno.base_canvas_reconciled"
        )


@pytest.fixture(autouse=True)
def no_blueprinted_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the database-backed half of model discovery.

    ``_blueprinted_model_tables`` reads the workspaces with the built-form
    fill enabled, because a blueprinted model's name (``fill_<workspace pk>``)
    exists only in the database. These tests run without one by design; the
    blueprinted path is pinned by the database-backed regression tests in
    ``tests/workspace/test_base_canvas_view.py``.
    """

    def none_enabled() -> frozenset[tuple[str, str]]:
        return frozenset()

    monkeypatch.setattr(sqlmesh_tables, "_blueprinted_model_tables", none_enabled)


@pytest.fixture
def known_tables(monkeypatch: pytest.MonkeyPatch) -> list[SqlmeshTableInfo]:
    tables = [
        SqlmeshTableInfo(
            schema="ascn7",
            table="core_end_state",
            has_geometry=True,
            geometry_type="fill",
        ),
        SqlmeshTableInfo(
            schema="analysis__scenario_7",
            table="core_end_state",
            has_geometry=True,
            geometry_type="fill",
        ),
    ]
    monkeypatch.setattr(sqlmesh_tables, "list_sqlmesh_tables", lambda: tables)
    return tables


class TestSqlmeshLinkForTable:
    def test_links_a_known_model(self, known_tables: list[SqlmeshTableInfo]) -> None:
        link = sqlmesh_link_for_table("ascn7", "core_end_state")
        assert link is not None
        assert link.endswith("/data-catalog/models/brewgis.ascn7.core_end_state")

    def test_links_a_result_view_to_the_model_that_publishes_it(
        self, known_tables: list[SqlmeshTableInfo]
    ) -> None:
        # Analysis results are read from "analysis__scenario_<pk>", but they are
        # published by that scenario's models in the internal "ascn<pk>" schema
        # — the link has to name the model, since no model lives at the result
        # schema.
        link = sqlmesh_link_for_table("analysis__scenario_7", "core_end_state")
        assert link is not None
        assert link.endswith("/data-catalog/models/brewgis.ascn7.core_end_state")

    def test_returns_none_for_a_result_schema_with_no_live_view(
        self, known_tables: list[SqlmeshTableInfo]
    ) -> None:
        # A scenario whose models were never run has no result view to link.
        assert sqlmesh_link_for_table("analysis__scenario_8", "core_end_state") is None

    def test_returns_none_for_a_non_sqlmesh_table(
        self, known_tables: list[SqlmeshTableInfo]
    ) -> None:
        assert sqlmesh_link_for_table("public", "some_shapefile_import") is None

    def test_returns_none_for_unknown_table_in_known_schema(
        self, known_tables: list[SqlmeshTableInfo]
    ) -> None:
        assert sqlmesh_link_for_table("ascn7", "not_a_real_model") is None

    def test_links_a_model_written_in_python(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A model's table name is its file's stem, whatever language that is.

        Regression: only ``*.sql`` files were scanned, so the view a Python
        model publishes (``fresno.du_regressor``, from
        ``models/base_canvas/du_regressor.py``) resolved to no link even
        though the model is right there in the UI catalog.
        """
        monkeypatch.setattr(
            sqlmesh_tables,
            "list_sqlmesh_tables",
            lambda: [
                SqlmeshTableInfo(
                    schema="fresno",
                    table="du_regressor",
                    has_geometry=True,
                    geometry_type="fill",
                ),
            ],
        )

        link = sqlmesh_link_for_table("fresno", "du_regressor")

        assert link is not None
        assert link.endswith("/data-catalog/models/brewgis.fresno.du_regressor")

    def test_returns_none_for_a_painted_features_canvas_view(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Regression: a scenario's painted-features overlay is a plain
        # Postgres view SQLMesh creates (see Scenario.base_layer_source /
        # sqlmesh/models/scenarios/scenario_canvas.py), living in its own
        # non-excluded "scenario_<slug>" schema — so it shows up in
        # list_sqlmesh_tables() just like a real model view would. It must
        # never get a SQLMesh link: the model behind it is named after the
        # scenario id in the internal "scenario_canvas" schema, not after
        # this view.
        monkeypatch.setattr(
            sqlmesh_tables,
            "list_sqlmesh_tables",
            lambda: [
                SqlmeshTableInfo(
                    schema="scenario_my-scenario",
                    table="scenario_my-scenario_canvas",
                    has_geometry=True,
                    geometry_type="fill",
                ),
            ],
        )
        link = sqlmesh_link_for_table(
            "scenario_my-scenario", "scenario_my-scenario_canvas"
        )
        assert link is None


class TestSqlmeshLinksForTables:
    def test_omits_keys_without_a_live_sqlmesh_backed_table(
        self, known_tables: list[SqlmeshTableInfo]
    ) -> None:
        links = sqlmesh_links_for_tables(
            {
                1: ("analysis__scenario_7", "core_end_state"),
                2: ("analysis__scenario_9", "core_end_state"),
                3: ("public", "census_import"),
            }
        )
        assert set(links) == {1}
        assert links[1].endswith("/data-catalog/models/brewgis.ascn7.core_end_state")
