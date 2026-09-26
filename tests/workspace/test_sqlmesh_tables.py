# ruff: noqa: ARG002
"""Tests for ``services/sqlmesh_tables.py``.

The link-building helpers are pure python — table discovery (what
``list_sqlmesh_tables`` returns) needs a live database, so those tests
monkeypatch it and only exercise the link logic. The base-canvas candidate list
is discovery itself and is tested against the database
(``TestBaseCanvasCandidates``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.db import connection

from brewgis.workspace.services import sqlmesh_tables
from brewgis.workspace.services.sqlmesh_tables import BaseCanvasCandidate
from brewgis.workspace.services.sqlmesh_tables import SqlmeshTableInfo
from brewgis.workspace.services.sqlmesh_tables import _model_schema
from brewgis.workspace.services.sqlmesh_tables import list_base_canvas_candidates
from brewgis.workspace.services.sqlmesh_tables import sqlmesh_link_for_table
from brewgis.workspace.services.sqlmesh_tables import sqlmesh_links_for_tables
from brewgis.workspace.services.sqlmesh_tables import sqlmesh_model_ui_url

if TYPE_CHECKING:
    from collections.abc import Iterator


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


@pytest.mark.integration
class TestBaseCanvasCandidates:
    """What a workspace may adopt as its base canvas.

    The contract is the column set, not the producer: a SQLMesh model's view
    satisfies it, and so does a table a user imported. Discovery therefore spans
    every schema but the internal ones, ``public`` included — that is where the
    legacy shared base canvas and every table imported into a workspace whose
    ``db_schema`` is ``public`` live.
    """

    @pytest.fixture
    def adoptable_tables(self, base_canvas_table: str) -> Iterator[None]:
        """One table per location the picker has to get right."""

        def _like(schema: str, table: str) -> None:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            cursor.execute(
                f'CREATE TABLE "{schema}"."{table}" '
                "(LIKE public.base_canvas INCLUDING ALL)"
            )

        with connection.cursor() as cursor:
            _like("public", "candidate_import")
            _like("adoptable", "candidate_import")
            # A model's own (blueprint-generated) table: internal schema.
            _like("built_form_fill", "fill_999")
            # A model-backed table: the name is a model file's stem.
            _like("fresno", "base_canvas_reconciled")
            # Every required column but one.
            _like("adoptable", "candidate_missing_du")
            cursor.execute(
                'ALTER TABLE "adoptable"."candidate_missing_du" DROP COLUMN du'
            )
            # Every required column, but a paintable number as text.
            _like("adoptable", "candidate_text_number")
            cursor.execute(
                'ALTER TABLE "adoptable"."candidate_text_number" '
                "ALTER COLUMN du TYPE text USING du::text"
            )
            # The same columns at a different numeric type than the schema
            # declares (``numeric`` for what the model calls ``float8``).
            cursor.execute(
                'ALTER TABLE "public"."candidate_import" ALTER COLUMN emp TYPE numeric'
            )
        yield
        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA IF EXISTS adoptable CASCADE")
            cursor.execute("DROP SCHEMA IF EXISTS built_form_fill CASCADE")
            cursor.execute('DROP TABLE IF EXISTS "fresno"."base_canvas_reconciled"')
            cursor.execute('DROP TABLE IF EXISTS "public"."candidate_import"')

    @pytest.fixture
    def candidates(self, adoptable_tables) -> dict[str, BaseCanvasCandidate]:
        return {
            candidate.qualified: candidate
            for candidate in list_base_canvas_candidates()
        }

    def test_offers_an_imported_table(
        self, candidates: dict[str, BaseCanvasCandidate]
    ) -> None:
        assert candidates["public.candidate_import"].is_sqlmesh_model is False

    def test_offers_a_table_from_any_schema(
        self, candidates: dict[str, BaseCanvasCandidate]
    ) -> None:
        assert "adoptable.candidate_import" in candidates

    def test_offers_the_legacy_shared_base_canvas(
        self, candidates: dict[str, BaseCanvasCandidate]
    ) -> None:
        assert candidates["public.base_canvas"].is_sqlmesh_model is False

    def test_names_a_model_backed_table_as_a_model(
        self, candidates: dict[str, BaseCanvasCandidate]
    ) -> None:
        assert candidates["fresno.base_canvas_reconciled"].is_sqlmesh_model is True

    def test_omits_a_table_missing_a_required_column(
        self, candidates: dict[str, BaseCanvasCandidate]
    ) -> None:
        # Downstream consumers (paint, canvas views, analysis) read a fixed
        # column set, so a partial match has to be rejected here rather than
        # break at query time.
        assert "adoptable.candidate_missing_du" not in candidates

    def test_omits_a_paintable_number_stored_as_text(
        self, candidates: dict[str, BaseCanvasCandidate]
    ) -> None:
        """The canvas view COALESCEs every paintable column against its own
        double precision paint value, so a text one fails the plan *after* the
        base table has been saved on the workspace."""
        assert "adoptable.candidate_text_number" not in candidates

    def test_keeps_a_number_in_any_numeric_type(
        self, candidates: dict[str, BaseCanvasCandidate]
    ) -> None:
        # The rule is the type family, not the schema's declared type: a base
        # canvas counting in ``numeric`` is as usable as one in ``float8``.
        assert "public.candidate_import" in candidates

    def test_omits_a_blueprinted_models_own_table(
        self, candidates: dict[str, BaseCanvasCandidate]
    ) -> None:
        # ``built_form_fill.fill_<workspace>`` is the workspace's own fill
        # output; offering it back would let a workspace base itself on its
        # own derivative.
        assert "built_form_fill.fill_999" not in candidates
