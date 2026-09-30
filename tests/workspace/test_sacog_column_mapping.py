"""Tests for ``services/sacog_column_mapping.build_materialized_select_sql``.

The projection is the whole contract of ``materialize_sacog_base_canvas``: what
a v1 SACOG table's columns become in an adoptable base canvas table. It is pure
string building over ``BaseCanvasSchema`` + ``ALL_MAPPINGS``, so these tests pin
the decisions a live run would otherwise only reveal 500k rows later — the parcel
key, the geometry CRS, and where a truncated or mistyped value could come from.
"""

from __future__ import annotations

from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema
from brewgis.workspace.services.sacog_column_mapping import (
    build_materialized_select_sql,
)

SOURCE = "public.sac_cnty_region_base_canvas"


def _projection(table: str = SOURCE) -> dict[str, str]:
    """Return ``{column: expression}`` from the generated ``SELECT``."""
    sql = build_materialized_select_sql(table)
    select_list, separator, from_clause = sql.partition("\nFROM ")
    assert separator, sql
    assert from_clause == table

    expressions: dict[str, str] = {}
    for line in select_list.splitlines()[1:]:
        expression, _, alias = line.strip().rstrip(",").rpartition(" AS ")
        expressions[alias.strip('"')] = expression
    return expressions


class TestMaterializedProjection:
    """What the projection feeds the INSERT."""

    def test_names_every_base_canvas_column_once_in_schema_order(self) -> None:
        assert list(_projection()) == list(BaseCanvasSchema.COLUMN_NAMES)

    def test_keeps_the_source_parcel_identity(self) -> None:
        # Not a rendered ROW_NUMBER(): the comparison pipeline
        # (compare_sacog_basemap) and every model join SACOG parcels by the v1
        # geography_id, so a materialized canvas has to carry it in both keys.
        projection = _projection()
        assert projection["parcel_id"] == "CAST(geography_id AS BIGINT)"
        assert projection["geography_id"] == "CAST(geography_id AS INTEGER)"
        assert "ROW_NUMBER" not in build_materialized_select_sql()

    def test_reprojects_the_geometry_onto_the_contract_crs(self) -> None:
        assert _projection()["geometry"] == (
            f"CAST(ST_Multi(ST_Transform(wkb_geometry, 4326)) AS {BaseCanvasSchema.GEOMETRY_TYPE})"
        )

    def test_never_invents_a_parcel_key_or_a_geometry(self) -> None:
        # A NULL key or geometry must fail the insert loudly; a COALESCE here
        # would write parcel_id 0 and a garbage geometry into the canvas.
        projection = _projection()
        for name in ("parcel_id", "geography_id", "geometry"):
            assert "COALESCE" not in projection[name], name

    def test_casts_a_text_column_to_its_declared_width(self) -> None:
        # A ``CAST`` to VARCHAR(n) truncates without error, so the width has to
        # match the value's worst case; the command's verification compares every
        # value back to the source to catch a silent truncation.
        projection = _projection()
        assert projection["built_form_key"] == 'CAST("built_form_key" AS VARCHAR(128))'
        assert (
            projection["land_development_category"]
            == "CAST(COALESCE(\"land_development_category\", '') AS VARCHAR(64))"
        )
        for name in (
            "built_form_key",
            "land_development_category",
            "land_use",
            "assessor_use_code",
        ):
            assert "DOUBLE PRECISION" not in projection[name], name

    def test_derives_the_identity_columns(self) -> None:
        projection = _projection()
        assert projection["id_source"] == "CAST('sacog_v1' AS VARCHAR(64))"
        assert (
            projection["geometry_key"] == "CAST(source_id || '@sacog' AS VARCHAR(128))"
        )

    def test_fills_the_columns_v1_has_no_counterpart_for(self) -> None:
        # Both are NOT NULL in the contract and absent from the v1 mapping, so
        # they take the schema's own default rather than failing the load.
        projection = _projection()
        assert projection["land_use"] == "CAST('' AS VARCHAR(255))"
        assert projection["assessor_use_code"] == "CAST('' AS VARCHAR(32))"
        assert projection["median_income"] == "CAST(0.0 AS DOUBLE PRECISION)"

    def test_fills_a_null_in_a_not_null_count(self) -> None:
        # 1,267 of the region's 502,874 v1 parcels have no land use code at all,
        # and 79 of the 85 columns are NOT NULL.
        assert "land_development_category" in BaseCanvasSchema.NON_NULL_COLUMNS
        projection = _projection()
        assert projection["du"] == 'CAST(COALESCE("du", 0.0) AS DOUBLE PRECISION)'
        assert projection["pop"] == 'CAST(COALESCE("pop", 0.0) AS DOUBLE PRECISION)'

    def test_leaves_a_nullable_column_nullable(self) -> None:
        # built_form_key is nullable in the schema, so a v1 row without one stays
        # NULL rather than becoming an empty string that paint mode would read as
        # a classification.
        assert "built_form_key" not in BaseCanvasSchema.NON_NULL_COLUMNS
        assert (
            _projection()["built_form_key"] == 'CAST("built_form_key" AS VARCHAR(128))'
        )

    def test_renames_the_mapped_columns_and_quotes_them(self) -> None:
        projection = _projection()
        assert (
            projection["area_gross"]
            == 'CAST(COALESCE("acres_gross", 0.0) AS DOUBLE PRECISION)'
        )
        assert (
            projection["intersection_density"]
            == 'CAST(COALESCE("intersection_density_sqmi", 0.0) AS DOUBLE PRECISION)'
        )

    def test_applies_a_mapping_s_own_sql_expression(self) -> None:
        assert _projection()["residential_irrigated_area"] == (
            "CAST(COALESCE(residential_irrigated_sqft / 43560.0, 0.0) AS DOUBLE PRECISION)"
        )

    def test_reads_the_source_it_is_given(self) -> None:
        assert build_materialized_select_sql("public.other_v1").endswith(
            "\nFROM public.other_v1"
        )
