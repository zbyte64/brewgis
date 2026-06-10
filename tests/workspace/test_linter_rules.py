"""Tests for the ``UnindexedJoin`` SQLMesh lint rule.

Tests create synthetic ``SqlModel`` objects and verify that the rule
correctly flags joins against unindexed columns while passing joins
against properly indexed columns.
"""

from __future__ import annotations

from pathlib import Path

import sqlglot.expressions as exp
from sqlmesh.core.linter.rule import RuleViolation
from sqlmesh.core.model import Model
from sqlmesh.core.model import create_sql_model

from brewgis.sqlmesh.linter.rules import UnindexedGroupBy
from brewgis.sqlmesh.linter.rules import UnindexedJoin
from brewgis.sqlmesh.linter.rules import UnindexedWhereClause

# ── Helpers ─────────────────────────────────────────────────────────


def _make_ref_model(
    name: str,
    columns: dict[str, str],
    post_statements: list[str] | None = None,
    *,
    dialect: str = "postgres",
) -> Model:
    """Create a SQLMesh model that serves as a JOIN target.

    The model's query is a simple ``SELECT ... FROM source``.
    """
    col_exprs = ", ".join(columns.keys())
    parsed_cols = {
        k: exp.DataType.build(v, dialect=dialect) for k, v in columns.items()
    }
    parsed_post = (
        [exp.maybe_parse(s, dialect=dialect) for s in post_statements]
        if post_statements
        else None
    )
    return create_sql_model(
        name,
        query=exp.maybe_parse(f"SELECT {col_exprs} FROM source_table", dialect=dialect),  # noqa: S608
        columns=parsed_cols,
        path=Path("/dev/null/test_ref.sql"),
        dialect=dialect,
        depends_on=set(),
        post_statements=parsed_post or [],
    )


def _make_source_model(
    name: str,
    query_sql: str,
    columns: dict[str, str],
    deps: set[str] | None = None,
    *,
    dialect: str = "postgres",
) -> Model:
    """Create a SQLMesh model with a JOIN against a reference model."""
    parsed_cols = {
        k: exp.DataType.build(v, dialect=dialect) for k, v in columns.items()
    }
    return create_sql_model(
        name,
        query=exp.maybe_parse(query_sql, dialect=dialect),
        columns=parsed_cols,
        path=Path("/dev/null/test_src.sql"),
        dialect=dialect,
        depends_on=deps or set(),
        post_statements=[],
    )


class _FakeContext:
    """Minimal context stub that holds a ``_models`` dict."""

    def __init__(self, models: dict[str, Model]) -> None:
        self._models: dict[str, Model] = models


def _check(
    source_model: Model,
    ref_models: dict[str, Model],
) -> list[RuleViolation]:
    """Run ``UnindexedJoin`` on ``source_model`` with ``ref_models`` as context."""
    context = _FakeContext(ref_models)
    rule = UnindexedJoin(context)  # type: ignore[arg-type]
    result = rule.check_model(source_model)
    if result is None:
        return []
    if isinstance(result, list):
        return result
    return [result]


def _violation_msg(v: RuleViolation) -> str:
    return str(v)


def _check_groupby(
    source_model: Model,
    ref_models: dict[str, Model],
) -> list[RuleViolation]:
    """Run ``UnindexedGroupBy`` on ``source_model``."""
    context = _FakeContext(ref_models)
    rule = UnindexedGroupBy(context)  # type: ignore[arg-type]
    result = rule.check_model(source_model)
    if result is None:
        return []
    if isinstance(result, list):
        return result
    return [result]


def _check_where(
    source_model: Model,
    ref_models: dict[str, Model],
) -> list[RuleViolation]:
    """Run ``UnindexedWhereClause`` on ``source_model``."""
    context = _FakeContext(ref_models)
    rule = UnindexedWhereClause(context)  # type: ignore[arg-type]
    result = rule.check_model(source_model)
    if result is None:
        return []
    if isinstance(result, list):
        return result
    return [result]


# ── Key Join Tests ──────────────────────────────────────────────────


class TestKeyJoin:
    """Key-based joins (column = column) need B-tree indexes."""

    def test_indexed_key_join_passes(self) -> None:
        """Model A joins Model B on an indexed column → no violation."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "geom": "GEOMETRY"},
            post_statements=[
                "CREATE INDEX idx_parcels_parcel_id ON brewdb.public.parcels (parcel_id)",
            ],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT p.*
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p ON s.parcel_id = p.parcel_id
            """,
            {"parcel_id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check(src, {"brewdb.public.parcels": ref})
        assert violations == []

    def test_unindexed_key_join_violates(self) -> None:
        """Model A joins Model B on an unindexed column → violation."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "geom": "GEOMETRY"},
            post_statements=[],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT s.*
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p ON s.parcel_id = p.parcel_id
            """,
            {"parcel_id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check(src, {"brewdb.public.parcels": ref})
        assert len(violations) == 1
        assert "without an index" in _violation_msg(violations[0])
        assert "brewdb" in _violation_msg(violations[0])
        assert "parcel_id" in _violation_msg(violations[0])

    def test_multiple_joins_partial_index(self) -> None:
        """One join column is indexed, another is not → one violation."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "owner_id": "BIGINT", "geom": "GEOMETRY"},
            post_statements=[
                "CREATE INDEX idx_parcels_owner ON brewdb.public.parcels (owner_id)",
            ],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT s.*
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p
                ON s.parcel_id = p.parcel_id AND s.owner_id = p.owner_id
            """,
            {"parcel_id": "BIGINT", "owner_id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check(src, {"brewdb.public.parcels": ref})
        assert len(violations) >= 1
        assert any("parcel_id" in m for m in [_violation_msg(v) for v in violations])


# ── Spatial Join Tests ──────────────────────────────────────────────


class TestSpatialJoin:
    """Spatial joins need GiST indexes."""

    def test_gist_indexed_spatial_join_passes(self) -> None:
        """ST_Intersects against a geometry with GiST → no violation."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "geom": "GEOMETRY"},
            post_statements=[
                "CREATE INDEX idx_parcels_geom ON brewdb.public.parcels USING GIST (geom)",
            ],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT p.*
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p ON ST_Intersects(s.geom, p.geom)
            """,
            {"parcel_id": "BIGINT", "geom": "GEOMETRY", "result": "BIGINT"},
        )
        violations = _check(src, {"brewdb.public.parcels": ref})
        assert violations == []

    def test_missing_gist_spatial_join_violates(self) -> None:
        """ST_Intersects without GiST on the geometry → violation."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "geom": "GEOMETRY"},
            post_statements=[
                "CREATE INDEX idx_parcels_id ON brewdb.public.parcels (parcel_id)",
            ],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT p.*
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p ON ST_Intersects(s.geom, p.geom)
            """,
            {"parcel_id": "BIGINT", "geom": "GEOMETRY", "result": "BIGINT"},
        )
        violations = _check(src, {"brewdb.public.parcels": ref})
        assert len(violations) == 1
        assert "GiST" in _violation_msg(violations[0])

    def test_array_overlap_join_violates(self) -> None:
        """``&&`` spatial operator without GiST → violation."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "geom": "GEOMETRY"},
            post_statements=[],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT p.*
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p ON s.geom && p.geom
            """,
            {"parcel_id": "BIGINT", "geom": "GEOMETRY", "result": "BIGINT"},
            dialect="postgres",
        )
        violations = _check(src, {"brewdb.public.parcels": ref})
        assert len(violations) == 1
        assert "GiST" in _violation_msg(violations[0])

    def test_gist_only_on_key_column_spatial_still_violates(self) -> None:
        """GiST on a non-geometry column doesn't help spatial joins."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "geom": "GEOMETRY"},
            post_statements=[
                "CREATE INDEX idx_parcels_geom ON brewdb.public.parcels USING GIST (parcel_id)",
            ],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT p.*
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p ON ST_Contains(p.geom, s.geom)
            """,
            {"parcel_id": "BIGINT", "geom": "GEOMETRY", "result": "BIGINT"},
        )
        violations = _check(src, {"brewdb.public.parcels": ref})
        assert len(violations) == 1


# ── Expression Join Tests ────────────────────────────────────────────


class TestExpressionJoin:
    """Expression-wrapped columns should be flagged as a warning."""

    def test_left_expression_join_warns(self) -> None:
        """LEFT() wrapping a join column → flagged."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "parcel_key": "TEXT"},
            post_statements=[
                "CREATE INDEX idx_parcels_key ON brewdb.public.parcels (parcel_key)",
            ],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT s.*
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p
                ON LEFT(p.parcel_key, 4) = LEFT(s.some_key, 4)
            """,
            {"parcel_key": "TEXT", "result": "BIGINT"},
        )
        violations = _check(src, {"brewdb.public.parcels": ref})
        assert len(violations) == 1
        assert "expression index" in _violation_msg(violations[0]).lower()

    def test_coalesce_expression_join_warns(self) -> None:
        """COALESCE() wrapping a join column → flagged."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "owner_id": "BIGINT"},
            post_statements=[],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT s.*
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p
                ON COALESCE(p.owner_id, -1) = COALESCE(s.owner_id, -1)
            """,
            {"parcel_id": "BIGINT", "owner_id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check(src, {"brewdb.public.parcels": ref})
        assert len(violations) == 1
        assert "expression index" in _violation_msg(violations[0]).lower()


# ── Skip Tests ──────────────────────────────────────────────────────


class TestSkipCases:
    """Cases that should never produce a violation."""

    def test_cross_join_skipped(self) -> None:
        """CROSS JOIN has no ON clause → skipped."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT"},
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT p.*
            FROM source_table AS s
            CROSS JOIN brewdb.public.parcels AS p
            """,
            {"parcel_id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check(src, {"brewdb.public.parcels": ref})
        assert violations == []

    def test_external_table_skipped(self) -> None:
        """JOIN against a table not in context._models → skipped."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT s.*
            FROM source_table AS s
            JOIN public.some_table AS t ON s.id = t.id
            """,
            {"id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check(src, {})
        assert violations == []

    def test_dynamic_table_ref_skipped(self) -> None:
        """Dynamic table references like ``@parcel_table`` → skipped."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT"},
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT s.*
            FROM source_table AS s
            JOIN @dynamic_table AS p ON s.id = p.id
            """,
            {"id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check(src, {"brewdb.public.parcels": ref})
        assert violations == []

    def test_self_join_with_index_passes(self) -> None:
        """Self-join (model joining itself) with index → no violation."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "parent_id": "BIGINT"},
            post_statements=[
                "CREATE INDEX idx_parcel_id ON brewdb.public.parcels (parcel_id)",
                "CREATE INDEX idx_parent ON brewdb.public.parcels (parent_id)",
            ],
        )
        src = _make_source_model(
            "brewdb.public.parcels",
            """
            SELECT c.*
            FROM brewdb.public.parcels AS c
            LEFT JOIN brewdb.public.parcels AS p ON c.parent_id = p.parcel_id
            """,
            {"parcel_id": "BIGINT", "parent_id": "BIGINT"},
        )
        violations = _check(src, {"brewdb.public.parcels": ref})
        assert violations == []

    def test_no_join_model_skipped(self) -> None:
        """Model with no JOIN at all → no violation."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT"},
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            "SELECT id, name FROM source_table",
            {"id": "BIGINT", "name": "TEXT"},
        )
        violations = _check(src, {"brewdb.public.parcels": ref})
        assert violations == []


# ── GROUP BY Tests ──────────────────────────────────────────────────


class TestGroupByColumn:
    """GROUP BY columns need B-tree indexes on the referenced model."""

    def test_indexed_group_by_passes(self) -> None:
        """GROUP BY on indexed column with alias → no violation."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "owner_id": "BIGINT"},
            post_statements=[
                "CREATE INDEX idx_parcels_owner ON brewdb.public.parcels (owner_id)",
            ],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT p.owner_id, COUNT(*)
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p ON s.parcel_id = p.parcel_id
            GROUP BY p.owner_id
            """,
            {"owner_id": "BIGINT", "count": "BIGINT"},
            deps={"brewdb.public.parcels"},
        )
        violations = _check_groupby(src, {"brewdb.public.parcels": ref})
        assert violations == []

    def test_unindexed_group_by_violates(self) -> None:
        """GROUP BY on unindexed column with alias → violation."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "owner_id": "BIGINT"},
            post_statements=[],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT p.owner_id, COUNT(*)
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p ON s.parcel_id = p.parcel_id
            GROUP BY p.owner_id
            """,
            {"owner_id": "BIGINT", "count": "BIGINT"},
            deps={"brewdb.public.parcels"},
        )
        violations = _check_groupby(src, {"brewdb.public.parcels": ref})
        assert len(violations) == 1
        msg = _violation_msg(violations[0])
        assert "GROUP BY" in msg
        assert "brewdb" in msg
        assert "owner_id" in msg

    def test_unqualified_group_by_column_skipped(self) -> None:
        """GROUP BY without table qualifier (bare column) → skipped."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT"},
            post_statements=[],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT owner_id, COUNT(*)
            FROM source_table
            GROUP BY owner_id
            """,
            {"owner_id": "BIGINT", "count": "BIGINT"},
        )
        violations = _check_groupby(src, {"brewdb.public.parcels": ref})
        assert violations == []

    def test_group_by_indexed_among_many_passes(self) -> None:
        """Multiple GROUP BY columns, all indexed → no violation."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "owner_id": "BIGINT", "zone": "TEXT"},
            post_statements=[
                "CREATE INDEX idx_parcels_owner ON brewdb.public.parcels (owner_id)",
                "CREATE INDEX idx_parcels_zone ON brewdb.public.parcels (zone)",
            ],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT p.owner_id, p.zone, COUNT(*)
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p ON s.parcel_id = p.parcel_id
            GROUP BY p.owner_id, p.zone
            """,
            {"owner_id": "BIGINT", "zone": "TEXT", "count": "BIGINT"},
            deps={"brewdb.public.parcels"},
        )
        violations = _check_groupby(src, {"brewdb.public.parcels": ref})
        assert violations == []


# ── WHERE Clause Tests ──────────────────────────────────────────────


class TestWhereClauseColumn:
    """WHERE filter columns need B-tree indexes on the referenced model."""

    def test_indexed_where_column_passes(self) -> None:
        """WHERE filter on indexed column with alias → no violation."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "owner_id": "BIGINT"},
            post_statements=[
                "CREATE INDEX idx_parcels_owner ON brewdb.public.parcels (owner_id)",
            ],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT s.*
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p ON s.parcel_id = p.parcel_id
            WHERE p.owner_id = 42
            """,
            {"owner_id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_where(src, {"brewdb.public.parcels": ref})
        assert violations == []

    def test_unindexed_where_column_violates(self) -> None:
        """WHERE filter on unindexed column → violation."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "owner_id": "BIGINT"},
            post_statements=[],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT s.*
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p ON s.parcel_id = p.parcel_id
            WHERE p.owner_id = 42
            """,
            {"owner_id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_where(src, {"brewdb.public.parcels": ref})
        assert len(violations) == 1
        msg = _violation_msg(violations[0])
        assert "WHERE" in msg
        assert "brewdb" in msg
        assert "owner_id" in msg

    def test_unqualified_where_column_skipped(self) -> None:
        """WHERE filter without table qualifier → skipped."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"owner_id": "BIGINT"},
            post_statements=[],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT *
            FROM source_table
            WHERE owner_id = 42
            """,
            {"owner_id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_where(src, {"brewdb.public.parcels": ref})
        assert violations == []

    def test_spatial_function_in_where_skipped(self) -> None:
        """WHERE with spatial function column → skipped (handled by UnindexedJoin)."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "geom": "GEOMETRY"},
            post_statements=[],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT s.*
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p ON s.parcel_id = p.parcel_id
            WHERE ST_Intersects(s.geom, p.geom)
            """,
            {"parcel_id": "BIGINT", "geom": "GEOMETRY", "result": "BIGINT"},
        )
        violations = _check_where(src, {"brewdb.public.parcels": ref})
        assert violations == []


# ── Expanded Skip Tests ─────────────────────────────────────────────


class TestSkipCasesNew:
    """Skip cases for UnindexedGroupBy and UnindexedWhereClause."""

    def test_external_table_group_by_skipped(self) -> None:
        """GROUP BY on column from external table → skipped."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT t.owner_id, COUNT(*)
            FROM source_table AS s
            JOIN public.external_table AS t ON s.id = t.id
            GROUP BY t.owner_id
            """,
            {"owner_id": "BIGINT", "count": "BIGINT"},
        )
        violations = _check_groupby(src, {})
        assert violations == []

    def test_external_table_where_skipped(self) -> None:
        """WHERE on column from external table → skipped."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT t.*
            FROM source_table AS s
            JOIN public.external_table AS t ON s.id = t.id
            WHERE t.owner_id = 42
            """,
            {"owner_id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_where(src, {})
        assert violations == []
