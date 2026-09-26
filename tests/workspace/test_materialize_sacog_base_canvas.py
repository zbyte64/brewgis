# ruff: noqa: ARG002, S608  # unused fixture args; plain identifiers in test SQL
"""Tests for the ``materialize_sacog_base_canvas`` management command.

The command turns a SACOG v1 table into a table a workspace can adopt as its
base canvas (``list_base_canvas_candidates``). The test database has no SACOG
restore, so the fixture builds a miniature v1-shaped source — every column the
v1→base-canvas mapping reads, at the v1 types — and the tests assert the contract
the canvas views and paint mode depend on: the full column set, the source parcel
key, SRID 4326, and the values themselves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema
from brewgis.workspace.services.sacog_column_mapping import ALL_MAPPINGS
from brewgis.workspace.services.sqlmesh_tables import BaseCanvasCandidate
from brewgis.workspace.services.sqlmesh_tables import list_base_canvas_candidates

if TYPE_CHECKING:
    from collections.abc import Iterator


SOURCE_TABLE = "public.probe_v1_parcels"
TARGET_TABLE = "public.probe_materialized_canvas"
VIEW_NAME = "public.probe_canvas_view"

#: The columns the fixture names explicitly; every other mapped v1 column is a
#: plain ``double precision`` count/area column.
NAMED_SOURCE_COLUMNS = {
    "geography_id": "integer",
    "source_id": "varchar(64)",
    "wkb_geometry": "geometry(MultiPolygon, 3310)",
    "built_form_key": "varchar(128)",
    "land_development_category": "varchar(64)",
}

FILLED_SOURCE_COLUMNS: tuple[str, ...] = tuple(
    sorted(
        {m.v1_column for m in ALL_MAPPINGS if m.v1_column} - set(NAMED_SOURCE_COLUMNS)
    )
)


@pytest.fixture
def v1_source(db) -> Iterator[str]:
    """A SACOG v1-shaped source table holding two parcels.

    Parcel 2 carries the NULLs the real source has (no land use code, no built
    form key); parcel 1 carries values the projection has to copy verbatim. The
    v1 geometry is in SRID 3310, so a base canvas row proves the reprojection.
    """
    column_defs = ", ".join(
        f'"{name}" {sql_type}' for name, sql_type in NAMED_SOURCE_COLUMNS.items()
    )
    filler = ", ".join(f'"{name}" double precision' for name in FILLED_SOURCE_COLUMNS)
    fillers = ", ".join("1.0" for _ in FILLED_SOURCE_COLUMNS)
    names = ", ".join(f'"{name}"' for name in FILLED_SOURCE_COLUMNS)
    with connection.cursor() as cursor:
        cursor.execute(f"DROP VIEW IF EXISTS {VIEW_NAME}")
        cursor.execute(f"DROP TABLE IF EXISTS {TARGET_TABLE}")
        cursor.execute(f"DROP TABLE IF EXISTS {SOURCE_TABLE}")
        cursor.execute(f"CREATE TABLE {SOURCE_TABLE} ({column_defs}, {filler})")
        cursor.execute(
            f"INSERT INTO {SOURCE_TABLE} "
            f"(geography_id, source_id, wkb_geometry, built_form_key, "
            f"land_development_category, {names}) "
            "SELECT g, 'S' || g, "
            "ST_Multi(ST_Buffer(ST_Transform(ST_SetSRID(ST_MakePoint(-121.49, 38.58), 4326), 3310), 50)), "
            "CASE WHEN g = 2 THEN NULL ELSE 'residential' END, "
            "CASE WHEN g = 2 THEN NULL ELSE 'residential' END, "
            f"{fillers} "
            "FROM generate_series(1, 2) AS g"
        )
        # A value only the source has, so a passthrough can be proven.
        cursor.execute(f"UPDATE {SOURCE_TABLE} SET acres_gross = geography_id * 10.0")
    yield SOURCE_TABLE
    with connection.cursor() as cursor:
        cursor.execute(f"DROP VIEW IF EXISTS {VIEW_NAME}")
        cursor.execute(f"DROP TABLE IF EXISTS {TARGET_TABLE}")
        cursor.execute(f"DROP TABLE IF EXISTS {SOURCE_TABLE}")


def _materialize(*extra: str) -> None:
    call_command(
        "materialize_sacog_base_canvas",
        "--source-table",
        SOURCE_TABLE,
        "--target-table",
        TARGET_TABLE,
        *extra,
    )


def _scalar(sql: str) -> object:
    with connection.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()
    return row[0] if row else None


def _rows(sql: str) -> list[tuple]:
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return list(cursor.fetchall())


@pytest.mark.integration
class TestMaterializeSacogBaseCanvas:
    """What the command writes into the base canvas table."""

    def test_materializes_the_full_base_canvas_contract(self, v1_source: str) -> None:
        _materialize()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s "
                "ORDER BY ordinal_position",
                [TARGET_TABLE.partition(".")[2]],
            )
            columns = [row[0] for row in cursor.fetchall()]
        assert columns == list(BaseCanvasSchema.COLUMN_NAMES)
        assert _scalar(f"SELECT count(*) FROM {TARGET_TABLE}") == 2

    def test_keeps_the_source_parcel_identity(self, v1_source: str) -> None:
        _materialize()

        assert _rows(
            f"SELECT parcel_id, geography_id, id_source, geometry_key "
            f"FROM {TARGET_TABLE} ORDER BY parcel_id"
        ) == [(1, 1, "sacog_v1", "S1@sacog"), (2, 2, "sacog_v1", "S2@sacog")]

    def test_reprojects_the_geometry_onto_the_contract_crs(
        self, v1_source: str
    ) -> None:
        _materialize()

        assert _scalar(f"SELECT DISTINCT ST_SRID(geometry) FROM {TARGET_TABLE}") == 4326
        assert (
            _scalar(f"SELECT DISTINCT GeometryType(geometry) FROM {TARGET_TABLE}")
            == "MULTIPOLYGON"
        )

    def test_copies_the_source_values_verbatim(self, v1_source: str) -> None:
        _materialize()

        assert _rows(
            f"SELECT area_gross, built_form_key FROM {TARGET_TABLE} ORDER BY parcel_id"
        ) == [(10.0, "residential"), (20.0, None)]

    def test_fills_the_nulls_a_v1_source_leaves_in_not_null_columns(
        self, v1_source: str
    ) -> None:
        _materialize()

        # parcel 2 carries no land use code; the column is NOT NULL in the
        # contract, so it takes the schema's default rather than failing the load.
        assert (
            _scalar(
                f"SELECT land_development_category FROM {TARGET_TABLE} WHERE parcel_id = 2"
            )
            == ""
        )

    def test_fills_the_columns_v1_has_no_counterpart_for(self, v1_source: str) -> None:
        _materialize()

        assert _rows(
            f"SELECT land_use, assessor_use_code, median_income FROM {TARGET_TABLE}"
        ) == [("", "", 0.0), ("", "", 0.0)]

    def test_the_picker_offers_it_as_an_imported_table(self, v1_source: str) -> None:
        _materialize()

        candidates: dict[str, BaseCanvasCandidate] = {
            candidate.qualified: candidate
            for candidate in list_base_canvas_candidates()
        }
        assert TARGET_TABLE in candidates
        assert candidates[TARGET_TABLE].is_sqlmesh_model is False

    def test_rebuilding_keeps_a_view_over_the_table_valid(self, v1_source: str) -> None:
        _materialize()
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE VIEW {VIEW_NAME} AS SELECT parcel_id, geometry FROM {TARGET_TABLE}"
            )

        _materialize()

        assert _scalar(f"SELECT count(*) FROM {VIEW_NAME}") == 2

    def test_replace_drops_what_read_the_table(self, v1_source: str) -> None:
        # The documented cost of --replace: PostgreSQL cascades the drop to every
        # scenario canvas view over that base canvas.
        _materialize()
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE VIEW {VIEW_NAME} AS SELECT parcel_id FROM {TARGET_TABLE}"
            )

        _materialize("--replace")

        assert _scalar(f"SELECT to_regclass('{VIEW_NAME}')") is None
        assert _scalar(f"SELECT count(*) FROM {TARGET_TABLE}") == 2


@pytest.mark.integration
class TestMaterializeSacogBaseCanvasGuards:
    """What the command refuses to do."""

    def test_refuses_a_source_without_the_v1_columns(self, base_canvas_table) -> None:
        # ``public.base_canvas`` has every base canvas column and none of the v1
        # column names, so it cannot be projected.
        with pytest.raises(CommandError, match="mapped columns are missing"):
            call_command(
                "materialize_sacog_base_canvas",
                "--source-table",
                "public.base_canvas",
                "--target-table",
                TARGET_TABLE,
            )

    def test_refuses_a_missing_source(self, db) -> None:
        with pytest.raises(CommandError, match="Source table not found"):
            call_command(
                "materialize_sacog_base_canvas",
                "--source-table",
                "public.no_such_parcels",
                "--target-table",
                TARGET_TABLE,
            )

    def test_refuses_to_load_a_source_into_itself(self, db) -> None:
        # Without this the TRUNCATE would empty the source before reading it.
        with pytest.raises(CommandError, match="must differ"):
            call_command(
                "materialize_sacog_base_canvas",
                "--source-table",
                SOURCE_TABLE,
                "--target-table",
                SOURCE_TABLE,
            )

    def test_refuses_an_unqualified_table_name(self, db) -> None:
        with pytest.raises(CommandError, match="schema-qualified"):
            call_command(
                "materialize_sacog_base_canvas",
                "--source-table",
                "probe_v1_parcels",
                "--target-table",
                TARGET_TABLE,
            )
