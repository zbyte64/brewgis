"""Tests for SQLMesh column description auto-inference from inline comments.

Verifies that ``SqlModel.column_descriptions`` does not silently extract
column descriptions from inline SQL comments (``--``) for columns that are
not declared in the model's ``columns`` block.

When the ``columns`` block omits columns that appear in the SELECT, and inline
comments are present, SQLMesh auto-infers ``column_descriptions`` for those
columns. This creates a mismatch: the physical table is created with only the
explicitly declared columns, but ``COMMENT ON COLUMN`` is attempted for the
auto-described columns — causing ``UndefinedColumn`` errors.
"""

from __future__ import annotations

from pathlib import Path

import sqlglot.expressions as exp
from sqlmesh.core.model import SqlModel
from sqlmesh.core.model import create_sql_model

# ── Helpers ──────────────────────────────────────────────────────────


def _make_model(
    name: str,
    query_sql: str,
    columns: dict[str, str],
) -> SqlModel:
    """Create a ``SqlModel`` with explicit column types and a query."""
    parsed_cols = {
        k: exp.DataType.build(v, dialect="postgres") for k, v in columns.items()
    }
    return create_sql_model(
        name,
        query=exp.maybe_parse(query_sql, dialect="postgres"),
        columns=parsed_cols,
        path=Path("/dev/null/test.sql"),
        dialect="postgres",
    )


# ── Column Description Auto-Inference Tests ─────────────────────────


class TestAutoInferredColumnDescriptions:
    """Column descriptions extracted from inline SQL comments should be
    a subset of the columns declared in the model's columns block."""

    def test_inline_comment_creates_column_description(self) -> None:
        """A line-before comment on a SELECT expression causes SQLMesh
        to auto-infer a column description for that column, even though
        the column is not declared in the model's columns block."""
        model = _make_model(
            "db.test_model",
            query_sql="""
                SELECT
                    id,
                    name,
                    -- Gross area in acres
                    ROUND(area::numeric, 4) AS area_gross_acres,
                    -- APN identifier
                    apn
                FROM source_table
            """,
            columns={
                "id": "INTEGER",
                "name": "TEXT",
            },
        )

        # The columns block declares only id + name.
        assert model.columns_to_types is not None
        assert set(model.columns_to_types) == {"id", "name"}

        # But column_descriptions is auto-inferred from inline comments.
        descriptions = model.column_descriptions
        assert "area_gross_acres" in descriptions, (
            "area_gross_acres should be auto-described from inline comment"
        )
        assert "apn" in descriptions, "apn should be auto-described from inline comment"
        assert descriptions["area_gross_acres"] == "Gross area in acres"
        assert descriptions["apn"] == "APN identifier"

        # The auto-described columns are NOT in columns_to_types — this
        # mismatch causes UndefinedColumn when SQLMesh issues
        # COMMENT ON COLUMN for them.
        for col in descriptions:
            assert col not in model.columns_to_types, (
                f"Auto-described column '{col}' should not be in "
                f"columns_to_types (which only has {set(model.columns_to_types)})"
            )

    def test_no_inline_comments_means_no_descriptions(self) -> None:
        """SELECT expressions without inline comments produce no auto-inferred
        column descriptions, even if the column is absent from the columns block."""
        model = _make_model(
            "db.test_model",
            query_sql="""
                SELECT
                    id,
                    name,
                    ROUND(area::numeric, 4) AS area_gross_acres,
                    population / NULLIF(area, 0) AS pop_density
                FROM source_table
            """,
            columns={
                "id": "INTEGER",
                "name": "TEXT",
            },
        )

        descriptions = model.column_descriptions
        assert "area_gross_acres" not in descriptions, (
            "No inline comment → no auto-inferred description"
        )
        assert "pop_density" not in descriptions, (
            "No inline comment → no auto-inferred description"
        )
        assert descriptions == {}, "Expected empty descriptions dict"

    def test_explicit_column_descriptions_override_auto_inference(self) -> None:
        """When column_descriptions is explicitly set in the MODEL block,
        auto-inference from inline comments should not occur."""
        model = create_sql_model(
            "db.test_model",
            query=exp.maybe_parse(
                """
                SELECT
                    id,
                    -- Gross area in acres
                    ROUND(area::numeric, 4) AS area_gross_acres
                FROM source_table
                """,
                dialect="postgres",
            ),
            columns={
                "id": exp.DataType.build("INTEGER", dialect="postgres"),
            },
            column_descriptions={
                "id": "Primary key identifier",
            },
            path=Path("/dev/null/test.sql"),
            dialect="postgres",
        )

        # column_descriptions_ is explicitly set (not None), so the
        # cached_property returns it directly without query-render inference.
        descriptions = model.column_descriptions
        # Only the explicitly-declared description should be present.
        assert descriptions == {"id": "Primary key identifier"}, (
            f"Expected only explicit descriptions, got {descriptions}"
        )

    def test_replicates_base_canvas_geometry_pattern(self) -> None:
        """Reproduce the exact pattern from ``base_canvas_geometry.sql``:
        a ``columns`` block with 3 narrow columns plus inline comments on
        SELECT expressions that are NOT in the columns block."""
        model = _make_model(
            "brewgis.base_canvas.base_canvas_geometry_test",
            query_sql="""
                SELECT
                    id,
                    geometry,
                    -- Area columns with _acres suffix (per methodology)
                    ROUND(area::numeric, 4) AS area_gross_acres,
                    ROUND(area::numeric, 4) AS area_parcel_acres,
                    -- Methodology columns
                    apn,
                    du_subtype
                FROM source_table
            """,
            columns={
                "id": "TEXT",
                "geometry": "GEOMETRY",
                "local_geometry": "GEOMETRY",
            },
        )

        descriptions = model.column_descriptions

        # These two columns have inline comments in the SELECT, so they
        # get auto-inferred descriptions — yet they are NOT in the columns block.
        assert "area_gross_acres" in descriptions
        assert "apn" in descriptions

        # Neither area_gross_acres nor apn is in columns_to_types.
        ctt = model.columns_to_types
        assert ctt is not None
        assert "area_gross_acres" not in ctt
        assert "apn" not in ctt

        # This is the failure mode: column descriptions exist for columns
        # that the model does not declare — causing UndefinedColumn when
        # SQLMesh tries to COMMENT ON COLUMN.
        extra_cols = set(descriptions) - set(ctt)
        assert extra_cols == {"area_gross_acres", "apn"}, (
            f"Columns with auto-inferred descriptions but not in "
            f"columns_to_types: {extra_cols}"
        )

    def test_column_descriptions_are_subset_of_columns_to_types(self) -> None:
        """ENFORCE: ``column_descriptions`` must be a subset of
        ``columns_to_types``.  Column descriptions for columns not in
        the columns block cause ``UndefinedColumn`` errors when SQLMesh
        issues ``COMMENT ON COLUMN`` at table-creation time.

        This test should FAIL with the current implementation because
        inline comments in the SQL cause auto-inference of descriptions
        for non-declared columns."""
        model = _make_model(
            "db.test_model",
            query_sql="""
                SELECT
                    id,
                    name,
                    -- Gross area in acres
                    ROUND(area::numeric, 4) AS area_gross_acres,
                    -- APN identifier
                    apn
                FROM source_table
            """,
            columns={
                "id": "INTEGER",
                "name": "TEXT",
            },
        )

        descriptions = model.column_descriptions
        ctt = model.columns_to_types
        assert ctt is not None

        # Every described column MUST appear in columns_to_types.
        # Inline comments that generate auto-descriptions for columns
        # not in the columns block violate this invariant.
        extra_cols = set(descriptions) - set(ctt)
        assert extra_cols == set(), (
            f"Column descriptions exist for columns not in columns_to_types: "
            f"{extra_cols}. "
            f"descriptions={descriptions}, columns_to_types={set(ctt)}"
        )
