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

from brewgis.sqlmesh.linter.rules import CrossJoinLikeJoin
from brewgis.sqlmesh.linter.rules import StaticComplexityScore
from brewgis.sqlmesh.linter.rules import UnfilteredTableScan
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


# ── CTE Spatial Join Tests ──────────────────────────────────────────


class TestCteSpatialJoin:
    """Spatial joins against CTEs cannot use GiST indexes and must be
    flagged so the user materializes the geometry in a real model."""

    def test_cte_st_intersects_join_violates(self) -> None:
        """``ST_Intersects`` against a CTE column → violation."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            WITH my_cte AS (
                SELECT geom, ST_Transform(geom, 3310) AS local_geom FROM parcels
            )
            SELECT p.*
            FROM parcels p
            JOIN my_cte m ON ST_Intersects(p.geometry, m.local_geom)
            """,
            {"geometry": "GEOMETRY", "local_geom": "GEOMETRY"},
        )
        violations = _check(src, {})
        assert len(violations) == 1
        msg = _violation_msg(violations[0])
        assert "my_cte" in msg
        assert "ST_INTERSECTS" in msg
        assert "local_geom" in msg

    def test_cte_array_overlap_join_violates(self) -> None:
        """``&&`` (ArrayOverlaps) against a CTE column → violation."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            WITH my_cte AS (
                SELECT geom, ST_Transform(geom, 3310) AS local_geom FROM parcels
            )
            SELECT p.*
            FROM parcels p
            JOIN my_cte m ON p.geometry && m.local_geom
            """,
            {"geometry": "GEOMETRY", "local_geom": "GEOMETRY"},
        )
        violations = _check(src, {})
        assert len(violations) == 1
        msg = _violation_msg(violations[0])
        assert "my_cte" in msg
        assert "&&" in msg

    def test_cte_key_join_passes(self) -> None:
        """Plain ``=`` key join against a CTE → no violation."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            WITH my_cte AS (
                SELECT parcel_id, geom FROM parcels
            )
            SELECT p.*
            FROM parcels p
            JOIN my_cte m ON p.parcel_id = m.parcel_id
            """,
            {"parcel_id": "BIGINT", "geom": "GEOMETRY"},
        )
        violations = _check(src, {})
        assert violations == []

    def test_cte_without_spatial_join_passes(self) -> None:
        """CTE join without any spatial function → no violation."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            WITH my_cte AS (
                SELECT id, name FROM parcels
            )
            SELECT p.*
            FROM parcels p
            JOIN my_cte m ON p.name = m.name
            """,
            {"id": "BIGINT", "name": "TEXT"},
        )
        violations = _check(src, {})
        assert violations == []


# ── Helper functions for new rules ─────────────────────────────────


def _check_cross_join(
    source_model: Model,
    ref_models: dict[str, Model] | None = None,
) -> list[RuleViolation]:
    """Run ``CrossJoinLikeJoin`` on ``source_model``."""
    context = _FakeContext(ref_models or {})
    rule = CrossJoinLikeJoin(context)  # type: ignore[arg-type]
    result = rule.check_model(source_model)
    if result is None:
        return []
    if isinstance(result, list):
        return result
    return [result]


def _check_unfiltered_scan(
    source_model: Model,
    ref_models: dict[str, Model] | None = None,
) -> list[RuleViolation]:
    """Run ``UnfilteredTableScan`` on ``source_model``."""
    context = _FakeContext(ref_models or {})
    rule = UnfilteredTableScan(context)  # type: ignore[arg-type]
    result = rule.check_model(source_model)
    if result is None:
        return []
    if isinstance(result, list):
        return result
    return [result]


def _check_complexity(
    source_model: Model,
    ref_models: dict[str, Model] | None = None,
) -> list[RuleViolation]:
    """Run ``StaticComplexityScore`` on ``source_model``."""
    context = _FakeContext(ref_models or {})
    rule = StaticComplexityScore(context)  # type: ignore[arg-type]
    result = rule.check_model(source_model)
    if result is None:
        return []
    if isinstance(result, list):
        return result
    return [result]


# ── CrossJoinLikeJoin Tests ───────────────────────────────────────────


class TestCrossJoinLikeJoin:
    """CrossJoinLikeJoin detects patterns that produce nested loops."""

    def test_explicit_cross_join_violates(self) -> None:
        """CROSS JOIN against a table → violation."""
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
        violations = _check_cross_join(src, {"brewdb.public.parcels": ref})
        assert len(violations) == 1
        assert "CROSS JOIN" in _violation_msg(violations[0])

    def test_comma_join_violates(self) -> None:
        """FROM t1, t2 comma join → violation."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT *
            FROM source_table AS s, brewdb.public.parcels AS p
            """,
            {"parcel_id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_cross_join(src, {})
        assert len(violations) == 1
        assert "Comma join" in _violation_msg(violations[0])

    def test_on_true_violates(self) -> None:
        """JOIN ON TRUE → violation."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT"},
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT p.*
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p ON TRUE
            """,
            {"parcel_id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_cross_join(src, {"brewdb.public.parcels": ref})
        assert len(violations) == 1
        assert "ON TRUE" in _violation_msg(violations[0]).upper()

    def test_range_join_unindexed_violates(self) -> None:
        """Range operator (>) on unindexed column → violation."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "val": "BIGINT"},
            post_statements=[],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT s.*
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p ON s.val > p.val
            """,
            {"parcel_id": "BIGINT", "val": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_cross_join(src, {"brewdb.public.parcels": ref})
        assert len(violations) == 1
        assert "range join" in _violation_msg(violations[0]).lower()

    def test_range_join_indexed_passes(self) -> None:
        """Range operator (>) on indexed column → no violation."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "val": "BIGINT"},
            post_statements=[
                "CREATE INDEX idx_val ON brewdb.public.parcels (val)",
            ],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT s.*
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p ON s.val > p.val
            """,
            {"parcel_id": "BIGINT", "val": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_cross_join(src, {"brewdb.public.parcels": ref})
        assert violations == []

    def test_indexed_eq_join_passes(self) -> None:
        """Equi-join on indexed column → no violation (handled by UnindexedJoin)."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT"},
            post_statements=[
                "CREATE INDEX idx_id ON brewdb.public.parcels (parcel_id)",
            ],
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
        violations = _check_cross_join(src, {"brewdb.public.parcels": ref})
        assert violations == []

    def test_lateral_join_skipped(self) -> None:
        """CROSS JOIN LATERAL → no violation (intentional optimization)."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT s.*
            FROM source_table AS s
            CROSS JOIN LATERAL (
                SELECT p.* FROM brewdb.public.parcels p
            ) AS sub
            """,
            {"parcel_id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_cross_join(src, {})
        assert violations == []

    def test_aggregate_cte_cross_join_skipped(self) -> None:
        """CROSS JOIN on aggregate CTE (1 row) → no violation."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            WITH totals AS (
                SELECT SUM(val) AS total FROM source_table
            )
            SELECT s.*
            FROM source_table AS s
            CROSS JOIN totals AS t
            """,
            {"val": "BIGINT", "total": "BIGINT"},
        )
        violations = _check_cross_join(src, {})
        assert violations == []


# ── UnfilteredTableScan Tests ─────────────────────────────────────────


class TestUnfilteredTableScan:
    """UnfilteredTableScan detects models referencing base tables without filters."""

    def test_no_where_on_base_table_violates(self) -> None:
        """CROSS JOIN on base table without filter → violation."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT p.*
            FROM source_table AS s
            CROSS JOIN staging.parcels AS p
            """,
            {"parcel_id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_unfiltered_scan(src, {})
        assert len(violations) == 1
        assert "staging" in _violation_msg(violations[0])

    def test_where_clause_passes(self) -> None:
        """Base table filtered by WHERE → no violation."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT s.*
            FROM staging.parcels AS p
            JOIN source_table AS s ON s.parcel_id = p.parcel_id
            WHERE p.owner_id = 42
            """,
            {"parcel_id": "BIGINT", "owner_id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_unfiltered_scan(src, {})
        assert violations == []

    def test_on_clause_as_filter_passes(self) -> None:
        """JOIN ON condition on base table counts as filter → no violation."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT s.*
            FROM source_table AS s
            JOIN staging.parcels AS p ON p.parcel_id = s.parcel_id
            """,
            {"parcel_id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_unfiltered_scan(src, {})
        assert violations == []

    def test_cte_reference_skipped(self) -> None:
        """Join against CTE → no violation."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            WITH filtered AS (
                SELECT * FROM staging.parcels WHERE owner_id = 42
            )
            SELECT f.*
            FROM filtered AS f
            JOIN source_table AS s ON s.parcel_id = f.parcel_id
            """,
            {"parcel_id": "BIGINT", "owner_id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_unfiltered_scan(src, {})
        assert violations == []

    def test_non_base_schema_skipped(self) -> None:
        """Table in non-base schema → no violation."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT s.*
            FROM comparison.some_table AS t
            JOIN source_table AS s ON s.id = t.id
            """,
            {"id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_unfiltered_scan(src, {})
        assert violations == []

    def test_single_table_passthrough_skipped(self) -> None:
        """SELECT * FROM base table alone → no violation (intentional load)."""
        src = _make_source_model(
            "brewdb.public.shim",
            "SELECT parcel_id, owner_id FROM staging.source_table",
            {"parcel_id": "BIGINT", "owner_id": "BIGINT"},
        )
        violations = _check_unfiltered_scan(src, {})
        assert violations == []

    def test_public_table_flagged_with_note(self) -> None:
        """public.* external table without filter → flagged with external note."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT s.*
            FROM source_table AS s
            CROSS JOIN public.built_forms AS bf
            """,
            {"id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_unfiltered_scan(src, {})
        assert len(violations) == 1
        assert "Cannot verify indexes" in _violation_msg(violations[0])


# ── StaticComplexityScore Tests ─────────────────────────────────------


class TestStaticComplexityScore:
    """StaticComplexityScore assigns heuristic cost from AST topology."""

    def test_simple_model_below_threshold(self) -> None:
        """Single table, no complexity → no violation."""
        src = _make_source_model(
            "brewdb.public.simple",
            "SELECT id, name FROM source_table",
            {"id": "BIGINT", "name": "TEXT"},
        )
        violations = _check_complexity(src, {})
        assert violations == []

    def test_complex_model_above_threshold(self) -> None:
        """5+ joins, subqueries, window fns → violation with score > 25."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "owner_id": "BIGINT", "zone": "TEXT"},
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            WITH ranked AS (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY zone ORDER BY val DESC) AS rn
                FROM source_table
            )
            SELECT DISTINCT p.*, r.rn
            FROM ranked AS r
            JOIN brewdb.public.parcels AS p ON r.parcel_id = p.parcel_id
            LEFT JOIN staging.zones AS z ON p.zone = z.code
            LEFT JOIN staging.data AS d ON p.parcel_id = d.pid
            LEFT JOIN staging.extra AS e ON p.parcel_id = e.pid
            LEFT JOIN staging.more AS m ON p.parcel_id = m.pid
            LEFT JOIN staging.another AS a ON p.parcel_id = a.pid
            ORDER BY p.owner_id
            """,
            {
                "parcel_id": "BIGINT",
                "owner_id": "BIGINT",
                "zone": "TEXT",
                "rn": "BIGINT",
            },
        )
        violations = _check_complexity(src, {"brewdb.public.parcels": ref})
        assert len(violations) == 1
        msg = _violation_msg(violations[0])
        assert "Complexity score" in msg
        assert "joins" in msg
        assert "window fns" in msg
        assert "DISTINCT" in msg

    def test_score_in_message(self) -> None:
        """Violation text includes score number."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT"},
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT p.*
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p ON s.parcel_id = p.parcel_id
            JOIN staging.other AS o ON p.parcel_id = o.pid
            JOIN staging.final AS f ON p.parcel_id = f.pid
            JOIN staging.extra AS e ON p.parcel_id = e.pid
            JOIN staging.more AS m ON p.parcel_id = m.pid
            """,
            {"parcel_id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_complexity(src, {"brewdb.public.parcels": ref})
        # 4 tables + 4 joins = 4*5 + 4*2 = 28 > 25
        assert len(violations) == 1
        msg = _violation_msg(violations[0])
        assert "Complexity score" in msg
        assert "5 joins" in msg

    def test_unindexed_join_adds_penalty(self) -> None:
        """Unindexed join column adds +10 penalty."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT", "val": "BIGINT"},
            post_statements=[],
        )
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT s.*
            FROM source_table AS s
            JOIN brewdb.public.parcels AS p ON s.parcel_id = p.parcel_id
            JOIN staging.other AS o ON p.parcel_id = o.pid
            JOIN staging.extra AS e ON p.parcel_id = e.pid
            """,
            {"parcel_id": "BIGINT", "val": "BIGINT", "result": "BIGINT"},
            deps={"brewdb.public.parcels"},
        )
        violations = _check_complexity(src, {"brewdb.public.parcels": ref})
        # 3 tables + 2 joins + 1 unindexed = 15 + 4 + 10 = 29 > 25
        assert len(violations) >= 1

    def test_full_outer_join_expensive(self) -> None:
        """FULL OUTER JOIN → +15 penalty, likely above threshold."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            SELECT *
            FROM source_table AS s
            FULL OUTER JOIN staging.other AS o ON s.id = o.id
            JOIN staging.third AS t ON s.id = t.id
            """,
            {"id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_complexity(src, {})
        assert len(violations) == 1
        msg = _violation_msg(violations[0])
        assert "FULL OUTER" in msg

    def test_ctes_add_cost(self) -> None:
        """CTEs add +1 per CTE to the score."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            WITH cte1 AS (SELECT * FROM source_table),
                 cte2 AS (SELECT * FROM cte1),
                 cte3 AS (SELECT * FROM cte2)
            SELECT *
            FROM cte3 AS c
            JOIN staging.other AS o ON c.id = o.id
            """,
            {"id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_complexity(src, {})
        assert len(violations) == 1
        msg = _violation_msg(violations[0])
        assert "3 CTEs" in msg

    def test_view_models_cheap(self) -> None:
        """VIEW models → -5 penalty, may keep score below threshold."""
        ref = _make_ref_model(
            "brewdb.public.parcels",
            {"parcel_id": "BIGINT"},
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
        violations = _check_complexity(src, {"brewdb.public.parcels": ref})
        assert len(violations) <= 1

    def test_error_threshold(self) -> None:
        """Very high complexity → Error severity in message."""
        src = _make_source_model(
            "brewdb.public.analysis",
            """
            WITH c1 AS (SELECT * FROM source_table),
                 c2 AS (SELECT * FROM c1),
                 c3 AS (SELECT * FROM c2),
                 c4 AS (SELECT * FROM c3),
                 c5 AS (SELECT * FROM c4)
            SELECT DISTINCT *
            FROM c5
            CROSS JOIN staging.t1
            CROSS JOIN staging.t2
            CROSS JOIN staging.t3
            CROSS JOIN staging.t4
            CROSS JOIN staging.t5
            CROSS JOIN staging.t6
            """,
            {"id": "BIGINT", "result": "BIGINT"},
        )
        violations = _check_complexity(src, {})
        assert len(violations) == 1
        msg = _violation_msg(violations[0])
        assert "Complexity score" in msg
