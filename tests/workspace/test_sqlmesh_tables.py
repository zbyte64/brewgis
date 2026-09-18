# ruff: noqa: ARG002
"""Tests for pure-python helpers in ``services/sqlmesh_tables.py``.

Table discovery itself requires a live database (see ``list_sqlmesh_tables``)
so these tests monkeypatch it and only exercise the link-building logic.
"""

from __future__ import annotations

import pytest

from brewgis.workspace.services import sqlmesh_tables
from brewgis.workspace.services.sqlmesh_tables import SqlmeshTableInfo
from brewgis.workspace.services.sqlmesh_tables import _canonical_schema
from brewgis.workspace.services.sqlmesh_tables import sqlmesh_link_for_table
from brewgis.workspace.services.sqlmesh_tables import sqlmesh_links_for_tables


class TestCanonicalSchema:
    def test_strips_scenario_environment_suffix(self) -> None:
        assert _canonical_schema("analysis__scenario_5") == "analysis"

    def test_strips_non_numeric_scenario_suffix(self) -> None:
        assert _canonical_schema("analysis__scenario_abc123") == "analysis"

    def test_leaves_plain_schema_unchanged(self) -> None:
        assert _canonical_schema("analysis") == "analysis"

    def test_leaves_unrelated_double_underscore_unchanged(self) -> None:
        # The physical-table prefix convention ("sqlmesh__<schema>") is a
        # different shape and must not be touched by this suffix stripper.
        assert _canonical_schema("sqlmesh__analysis") == "sqlmesh__analysis"


@pytest.fixture
def known_tables(monkeypatch: pytest.MonkeyPatch) -> list[SqlmeshTableInfo]:
    tables = [
        SqlmeshTableInfo(
            schema="analysis",
            table="core_end_state",
            has_geometry=True,
            geometry_type="fill",
        ),
    ]
    monkeypatch.setattr(sqlmesh_tables, "list_sqlmesh_tables", lambda: tables)
    return tables


class TestSqlmeshLinkForTable:
    def test_links_a_known_model(self, known_tables: list[SqlmeshTableInfo]) -> None:
        link = sqlmesh_link_for_table("analysis", "core_end_state")
        assert link is not None
        assert link.endswith("/data-catalog/models/brewgis.analysis.core_end_state")

    def test_links_an_analysis_run_layer_via_scenario_schema(
        self, known_tables: list[SqlmeshTableInfo]
    ) -> None:
        # Analysis-run result layers are registered under the SQLMesh
        # dev-environment schema (e.g. "analysis__scenario_5"), not the
        # canonical "analysis" schema — the link must still resolve.
        link = sqlmesh_link_for_table("analysis__scenario_5", "core_end_state")
        assert link is not None
        assert link.endswith("/data-catalog/models/brewgis.analysis.core_end_state")

    def test_links_when_the_catalog_only_has_the_scenario_schema(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Regression: an analysis model that has never been promoted to a
        # bare "analysis" environment only ever exists in postgres as
        # "analysis__scenario_<id>" — list_sqlmesh_tables() reports that raw
        # (unstripped) schema, never a plain "analysis" entry. The link must
        # still resolve by canonicalizing the *known* schemas too, not just
        # the one being looked up.
        monkeypatch.setattr(
            sqlmesh_tables,
            "list_sqlmesh_tables",
            lambda: [
                SqlmeshTableInfo(
                    schema="analysis__scenario_7",
                    table="core_end_state",
                    has_geometry=True,
                    geometry_type="fill",
                ),
            ],
        )
        link = sqlmesh_link_for_table("analysis__scenario_7", "core_end_state")
        assert link is not None
        assert link.endswith("/data-catalog/models/brewgis.analysis.core_end_state")

    def test_returns_none_for_a_non_sqlmesh_table(
        self, known_tables: list[SqlmeshTableInfo]
    ) -> None:
        assert sqlmesh_link_for_table("public", "some_shapefile_import") is None

    def test_returns_none_for_unknown_table_in_known_schema(
        self, known_tables: list[SqlmeshTableInfo]
    ) -> None:
        assert sqlmesh_link_for_table("analysis", "not_a_real_model") is None

    def test_returns_none_for_a_painted_features_canvas_view(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Regression: a scenario's painted-features overlay is a plain
        # Postgres view this codebase creates itself (see
        # Scenario.base_layer_source / canvas_view_manager), living in its
        # own non-excluded "scenario_<slug>" schema — so it shows up in
        # list_sqlmesh_tables() just like a real model would. It must never
        # get a SQLMesh link since no such model exists.
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
    def test_omits_keys_without_a_sqlmesh_backed_table(
        self, known_tables: list[SqlmeshTableInfo]
    ) -> None:
        links = sqlmesh_links_for_tables(
            {
                1: ("analysis", "core_end_state"),
                2: ("analysis__scenario_9", "core_end_state"),
                3: ("public", "census_import"),
            }
        )
        assert set(links) == {1, 2}
        assert links[1] == links[2]

    def test_links_scenario_only_layers_when_catalog_has_no_bare_schema(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            sqlmesh_tables,
            "list_sqlmesh_tables",
            lambda: [
                SqlmeshTableInfo(
                    schema="analysis__scenario_7",
                    table="core_end_state",
                    has_geometry=True,
                    geometry_type="fill",
                ),
            ],
        )
        links = sqlmesh_links_for_tables(
            {1: ("analysis__scenario_7", "core_end_state")}
        )
        assert 1 in links
