"""Custom SQLMesh linter rules for BrewGIS.

Rules in this directory are auto-discovered by SQLMesh and run during
``sqlmesh lint`` and ``sqlmesh plan`` when enabled in config.
"""

from __future__ import annotations

import re
from pathlib import Path

import sqlglot.expressions as exp
from sqlmesh.core.dialect import normalize_model_name
from sqlmesh.core.linter.rule import Rule
from sqlmesh.core.linter.rule import RuleViolation
from sqlmesh.core.model import Model
from sqlmesh.core.model import SeedModel
from sqlmesh.core.model import SqlModel


class NoTransformInJoinWhere(Rule):
    """``ST_Transform`` inside a JOIN condition or WHERE clause forces the
    query planner to compute the transform for every row, defeating GiST
    index usage. Pre-compute the transform into a CTE or column once,
    then join/filter against the already-transformed column.

    .. code-block:: sql

        -- Bad (no index pushdown):
        JOIN other t ON ST_Intersects(ST_Transform(p.geom, 3310), t.geom)
        WHERE ST_Intersects(ST_Transform(p.geom, 4326), envelope)

        -- Good:
        WITH transformed AS (
            SELECT *, ST_Transform(geom, 3310) AS geom_3310 FROM parcels
        )
        SELECT ...
        JOIN other t ON ST_Intersects(t.geom, transformed.geom_3310)
    """

    def check_model(self, model: Model) -> RuleViolation | None:
        if not isinstance(model, SqlModel):
            return None

        query = model.query
        if query is None:
            return None

        for node in query.find_all(exp.Func):
            if node.name.upper() != "ST_TRANSFORM":
                continue

            # Walk parent chain to find the surrounding context.
            parent: exp.Expression | None = node.parent
            while parent is not None:
                if isinstance(parent, (exp.Join, exp.OnCondition)):
                    line = getattr(node, "line", None)
                    loc = f" at line {line}" if line else ""
                    return self.violation(
                        f"ST_Transform inside {type(parent).__name__}{loc}."
                        f" Pre-compute the transform in a CTE to preserve"
                        f" GiST index pushdown."
                    )
                if isinstance(parent, (exp.Where, exp.Having)):
                    line = getattr(node, "line", None)
                    loc = f" at line {line}" if line else ""
                    return self.violation(
                        f"ST_Transform inside {type(parent).__name__}{loc}."
                        f" Pre-compute the transform in a CTE to preserve"
                        f" GiST index pushdown."
                    )
                parent = parent.parent

        return None


class MissingGeometryIndex(Rule):
    """Models with a spatial column ``(geometry, geography, GEOMETRY)``
    must create a GiST index on that column in their ``post_statements``
    block.

    Without the index, every downstream spatial join or boundary filter
    performs a sequential scan. Raw ``CREATE INDEX`` outside the MODEL
    block is dead code — SQLMesh never executes it.

    Seed models and models without geometry columns are exempt.
    """

    def check_model(self, model: Model) -> RuleViolation | None:
        if isinstance(model, SeedModel):
            return None

        if not isinstance(model, SqlModel):
            return None

        # VIEW models can't have indexes. DuckDB gateway models use
        # DuckDB, not Postgres GiST. Skip both.
        kind = getattr(model, "kind", None)
        if kind is not None and getattr(kind, "is_view", False):
            return None
        gateway = getattr(model, "gateway", None) or ""
        if "duckdb" in str(gateway).lower():
            return None

        # Collect geometry column names from the model schema.
        try:
            columns = model.columns_to_types_or_raise
        except (KeyError, ValueError, TypeError):
            return None

        geometry_cols: list[str] = []
        for col_name, col_type in columns.items():
            raw = str(col_type)
            # DType enum: DType.GEOMETRY, DType.GEOGRAPHY, DType.UNKNOWN, etc.
            # Match by type or by column name when unresolvable.
            raw_upper = raw.upper()
            if (
                "GEOMETRY" in raw_upper
                or "GEOGRAPHY" in raw_upper
                or ("UNKNOWN" in raw_upper and "geom" in col_name.lower())
            ):
                geometry_cols.append(col_name)

        # Exclude local_* variants (local_geometry) — these are projected
        # copies used only for ST_Area computations, never in spatial joins.
        geometry_cols = [c for c in geometry_cols if "local_" not in c.lower()]

        if not geometry_cols:
            return None

        # Read the source file to inspect post_statements.
        source_path = getattr(model, "_path", None)
        if not source_path:
            return None

        try:
            source = Path(source_path).read_text()
        except OSError:
            return None

        # Check if post_statements exists at all.
        if "post_statements" not in source.lower():
            # Check for raw CREATE INDEX outside the MODEL block (dead DDL).
            has_raw_ddl = bool(
                re.search(r"CREATE\s+(UNIQUE\s+)?INDEX", source, re.IGNORECASE)
            )
            if has_raw_ddl:
                return self.violation(
                    f"Model has geometry columns ({', '.join(geometry_cols)})"
                    f" but uses raw CREATE INDEX outside post_statements."
                    f" This DDL is never executed by SQLMesh. Move it into"
                    f" a post_statements block."
                )
            return self.violation(
                f"Model has geometry columns ({', '.join(geometry_cols)})"
                f" but no post_statements. Add a post_statements block"
                f" with CREATE INDEX USING GIST on each geometry column."
            )

        # Check for GiST index per geometry column in post_statements.
        missing_index_cols: list[str] = []
        for col in geometry_cols:
            gist_pattern = re.compile(
                r"USING\s+GIST\s*\(.*\b" + re.escape(col) + r"\b.*\)",
                re.IGNORECASE,
            )
            if not gist_pattern.search(source):
                missing_index_cols.append(col)

        if missing_index_cols:
            return self.violation(
                f"Missing GiST index for geometry column(s):"
                f" {', '.join(missing_index_cols)}. Add a CREATE INDEX"
                f" USING GIST (<col>) statement in post_statements."
            )

        return None


_SPATIAL_FUNCTIONS = frozenset(
    {
        "ST_INTERSECTS",
        "ST_CONTAINS",
        "ST_DWITHIN",
        "ST_WITHIN",
        "ST_COVERS",
        "ST_COVEREDBY",
        "ST_OVERLAPS",
        "ST_TOUCHES",
        "ST_CROSSES",
        "ST_EQUALS",
    }
)

_EXPRESSION_WRAPPERS = frozenset(
    {
        "LEFT",
        "TRIM",
        "LTRIM",
        "RTRIM",
        "COALESCE",
        "IFNULL",
        "UPPER",
        "LOWER",
        "SUBSTR",
        "SUBSTRING",
        "DATE_TRUNC",
    }
)


# ── Module-level helpers ──────────────────────────────────────────────


def _table_fqn(table: exp.Table, model: Model) -> str | None:
    """Build a fully-qualified name from a Table expression that
    matches the quoting convention used by SQLMesh model FQNs."""
    catalog = getattr(model, "default_catalog", None)
    dialect = getattr(model, "dialect", None) or ""
    try:
        return normalize_model_name(
            table,
            default_catalog=catalog,
            dialect=dialect,
        )
    except Exception:  # noqa: BLE001
        # Fallback: build a bare dotted name.
        parts: list[str] = []
        if table.args.get("catalog"):
            parts.append(str(table.args["catalog"]))
        if table.args.get("db"):
            parts.append(str(table.args["db"]))
        name = table.name
        if not name:
            return None
        parts.append(name)
        return ".".join(parts)


def _extract_indexes_from_sql(
    sql_text: str,
    model_name: str,
    result: dict[str, bool],
) -> None:
    """Extract indexed columns from a SQL string into ``result``.

    The value is ``True`` if the index uses ``USING GIST`` (spatial index),
    ``False`` for B-tree indexes.
    """
    pattern = re.compile(
        r"""
        CREATE\s+(UNIQUE\s+)?INDEX
        (\s+IF\s+NOT\s+EXISTS)?\s+\S+
        \s+ON\s+\S+
        (\s+USING\s+(?P<gist>GIST))?
        \s*\(
        (?P<cols>[^)]+)
        \)
        """,
        re.IGNORECASE | re.VERBOSE | re.DOTALL,
    )

    # Match the short table name too (last part of FQN).
    short_name = model_name.rsplit(".", 1)[-1] if "." in model_name else model_name

    for match in pattern.finditer(sql_text):
        on_clause = match.group(0)
        on_table_pattern = r"ON\s+" + re.escape(model_name)
        on_short_pattern = r"ON\s+" + re.escape(short_name) + r"\b"
        if not re.search(on_table_pattern, on_clause, re.IGNORECASE) and not re.search(
            on_short_pattern, on_clause, re.IGNORECASE
        ):
            continue

        is_gist = match.group("gist") is not None
        cols_section = match.group("cols")
        for col_expr in cols_section.split(","):
            col_name = col_expr.strip().split()[0].strip('"')
            if col_name:
                result[col_name] = result.get(col_name, False) or is_gist


def _get_indexed_columns(model: SqlModel) -> dict[str, bool]:
    """Return ``{column_name: is_spatial}`` from ``post_statements``.

    Checks both the model's source file and its ``post_statements_``
    for ``CREATE INDEX`` statements and extracts column names.
    """
    result: dict[str, bool] = {}

    # 1) Try reading from post_statements_ (in-memory, works for synthetic models).
    for ps in getattr(model, "post_statements_", []) or []:
        sql_text = ps.sql if hasattr(ps, "sql") else str(ps)
        _extract_indexes_from_sql(sql_text, model.name, result)

    # 2) Fall back to reading the source file (for real models on disk).
    source_path = getattr(model, "_path", None)
    if source_path:
        try:
            source = Path(source_path).read_text()
            _extract_indexes_from_sql(source, model.name, result)
        except OSError:
            pass

    return result


def _build_alias_table_map(query: exp.Expr, model: Model) -> dict[str, str]:
    """Build ``{alias: fully_qualified_table_name}`` from FROM/JOIN clauses.

    Handles both ``FROM t AS alias`` and bare ``FROM t`` (alias = table name).
    Dynamic table references (starting with ``@``) are excluded.
    """
    alias_map: dict[str, str] = {}

    for from_node in query.find_all(exp.From):
        table = from_node.this
        if isinstance(table, exp.Table):
            alias = table.alias_or_name
            fqn = _table_fqn(table, model)
            if fqn:
                alias_map[alias] = fqn

    for join_node in query.find_all(exp.Join):
        table = join_node.this
        if isinstance(table, exp.Table):
            alias = table.alias_or_name
            fqn = _table_fqn(table, model)
            if fqn:
                alias_map[alias] = fqn

    return alias_map


def _is_in_spatial_function(col: exp.Column) -> bool:
    """Check if a column is an argument to a spatial function.

    Walks the parent chain to detect ``ST_Intersects(..., col, ...)``
    and similar spatial predicates handled by ``UnindexedJoin``.
    """
    parent = col.parent
    while parent is not None:
        if isinstance(parent, exp.Func) and parent.name.upper() in _SPATIAL_FUNCTIONS:
            return True
        parent = parent.parent
    return False


def _func_name(func: exp.Func) -> str:
    """Return the uppercased function name, handling both ``Anonymous``
    and specific function classes (``Left``, ``Coalesce``, etc.)."""
    if func.name:
        return func.name.upper()
    sql_name = func.sql_name()
    if callable(sql_name):
        sql_name = sql_name()
    return (sql_name or "").upper()


# ── UnindexedJoin ────────────────────────────────────────────────────


class UnindexedJoin(Rule):
    """JOIN conditions that reference columns from other SQLMesh models
    must have corresponding indexes on those columns in the referenced
    model's ``post_statements``. Missing indexes force sequential scans.

    Detects:

    * **Key joins** (``a.parcel_id = b.parcel_id``) — requires a B-tree index
      on the referenced model's join column.
    * **Spatial joins** (``ST_Intersects(a.geom, b.geom)``, ``a.geom && b.geom``)
      — requires a GiST index on the geometry column.
    * **Expression joins** (``LEFT(a.key, 4) = LEFT(b.key, 4)``) — flags a
      warning that an expression index may be needed.

    Skips CROSS JOIN, ``ON TRUE``, LATERAL, dynamic table references
    (``@var``), and external tables not managed by SQLMesh.
    """

    def check_model(self, model: Model) -> RuleViolation | list[RuleViolation] | None:
        if not isinstance(model, SqlModel):
            return None

        query = model.query
        if query is None:
            return None

        violations: list[RuleViolation] = []

        for join in query.find_all(exp.Join):
            violation = self._check_join(join, model)
            if violation is not None:
                violations.append(violation)

        if not violations:
            return None
        if len(violations) == 1:
            return violations[0]
        return violations

    def _check_join(self, join: exp.Join, model: Model) -> RuleViolation | None:
        # Skip CROSS JOIN (no ON clause).
        if "on" not in join.arg_types:
            return None
        on = join.args.get("on")
        if on is None:
            return None

        # Skip LATERAL joins — they reference the outer query, not a table.
        if join.args.get("kind") == "LATERAL":
            return None

        # Extract the referenced table.
        table = join.this
        if not isinstance(table, exp.Table):
            return None

        # Skip dynamic/variable table references (@parcel_table, @constraint_table).
        table_sql = table.sql()
        if table_sql.startswith("@"):
            return None

        # Build FQN for lookup.
        fqn = _table_fqn(table, model)
        if fqn is None:
            return None

        # Look up the referenced model. Try the normalized FQN first,
        # then fall back to the bare name (for test models).
        ref_model = self.context._models.get(fqn)  # noqa: SLF001
        if ref_model is None:
            # Try bare dotted name in case normalization added quotes.
            parts: list[str] = []
            if table.args.get("catalog"):
                parts.append(str(table.args["catalog"]))
            if table.args.get("db"):
                parts.append(str(table.args["db"]))
            if table.name:
                parts.append(table.name)
            bare = ".".join(parts)
            if bare != fqn:
                ref_model = self.context._models.get(bare)  # noqa: SLF001
        if ref_model is None:
            # External table or not a SQLMesh model — skip.
            return None
        if not isinstance(ref_model, SqlModel):
            return None

        # Collect indexed columns from the referenced model.
        indexed_cols = _get_indexed_columns(ref_model)

        # Analyze the ON condition for join columns on the referenced side.
        join_alias = table.alias_or_name

        # Check for spatial operators first.
        spatial_violation = self._check_spatial_join(
            on,
            join_alias,
            fqn,
            indexed_cols,
        )
        if spatial_violation:
            return spatial_violation

        # Check for expression wrapping.
        expr_violation = self._check_expression_join(on, join_alias, fqn)
        if expr_violation:
            return expr_violation

        # Check key-based EQ joins.
        return self._check_key_join(on, join_alias, fqn, indexed_cols)

    def _check_spatial_join(
        self,
        on: exp.Expr,
        join_alias: str,
        fqn: str,
        indexed_cols: dict[str, bool],
    ) -> RuleViolation | None:
        """Check spatial JOIN conditions for GiST indexes."""
        # Check for && (ArrayOverlaps / Overlap).
        for node in on.find_all(exp.ArrayOverlaps):
            for col in node.find_all(exp.Column):
                if col.table == join_alias:
                    col_name = col.name
                    if col_name not in indexed_cols or not indexed_cols.get(col_name):
                        return self.violation(
                            f"Spatial join against ``{fqn}`` uses ``&&`` on "
                            f"``{col_name}`` without a GiST index on the "
                            f"referenced column."
                        )

        # Check for ST_Intersects etc.
        for func in on.find_all(exp.Func):
            if _func_name(func) not in _SPATIAL_FUNCTIONS:
                continue
            for col in func.find_all(exp.Column):
                if col.table == join_alias:
                    col_name = col.name
                    if col_name not in indexed_cols or not indexed_cols.get(col_name):
                        return self.violation(
                            f"Spatial join against ``{fqn}`` uses "
                            f"``{_func_name(func)}(..., {col_name})`` without a "
                            f"GiST index on the referenced column."
                        )

        return None

    def _check_expression_join(
        self,
        on: exp.Expr,
        join_alias: str,
        fqn: str,
    ) -> RuleViolation | None:
        """Flag JOIN conditions that wrap columns in functions."""
        for func in on.find_all(exp.Func):
            if _func_name(func) not in _EXPRESSION_WRAPPERS:
                continue
            # Check all args for column references to the joined table.
            for arg in _func_args(func):
                for col in arg.find_all(exp.Column):
                    if col.table == join_alias:
                        return self.violation(
                            f"Join ON clause wraps ``{fqn}`` column "
                            f"``{col.name}`` in ``{_func_name(func)}()``. "
                            f"Consider an expression index."
                        )

        return None

    def _check_key_join(
        self,
        on: exp.Expr,
        join_alias: str,
        fqn: str,
        indexed_cols: dict[str, bool],
    ) -> RuleViolation | None:
        """Check key-based ``=`` JOIN conditions for B-tree indexes."""
        for eq in on.find_all(exp.EQ):
            for col in eq.find_all(exp.Column):
                if col.table == join_alias:
                    col_name = col.name
                    if col_name not in indexed_cols:
                        return self.violation(
                            f"Key join against ``{fqn}`` on column ``{col_name}``"
                            f" without an index. Add a ``CREATE INDEX`` on this"
                            f" column in the referenced model's "
                            f"``post_statements``."
                        )

        return None


# ── UnindexedGroupBy ─────────────────────────────────────────────────


class UnindexedGroupBy(Rule):
    """GROUP BY clauses that reference unindexed columns from other
    models force expensive sort or hash aggregate operations. Each
    GROUP BY column from a referenced model should have a corresponding
    B-tree index on that column in the referenced model's
    ``post_statements``.

    Only qualified columns (``alias.col``) are checked — unqualified
    columns cannot be resolved to a source model without full schema
    resolution and are skipped.
    """

    def check_model(self, model: Model) -> RuleViolation | list[RuleViolation] | None:
        if not isinstance(model, SqlModel):
            return None

        query = model.query
        if query is None:
            return None

        # Build alias → table FQN map from FROM/JOIN clauses.
        alias_map = _build_alias_table_map(query, model)

        violations: list[RuleViolation] = []

        # Scan all GROUP BY expressions in the query.
        for group_node in query.find_all(exp.Group):
            for expr in group_node.expressions:
                for col in expr.find_all(exp.Column):
                    if not col.table:
                        # Unqualified column — cannot resolve source model.
                        continue

                    alias = col.table
                    ref_fqn = alias_map.get(alias)
                    if ref_fqn is None:
                        # Alias not resolved — external table or unknown.
                        continue

                    ref_model = _get_model(self.context, ref_fqn)
                    if ref_model is None or not isinstance(ref_model, SqlModel):
                        continue

                    indexed_cols = _get_indexed_columns(ref_model)
                    col_name = col.name
                    if col_name not in indexed_cols:
                        violations.append(
                            self.violation(
                                f"GROUP BY references unindexed column "
                                f"``{ref_fqn}``.``{col_name}`` from alias "
                                f"``{alias}``. Add a B-tree index on this "
                                f"column in the referenced model's "
                                f"``post_statements``."
                            )
                        )
        if not violations:
            return None
        if len(violations) == 1:
            return violations[0]
        return violations


# ── UnindexedWhereClause ─────────────────────────────────────────────


class UnindexedWhereClause(Rule):
    """WHERE clause filter columns from other models force sequential
    scans when unindexed. Each filtered column from a referenced model
    should have a corresponding index on that column in the referenced
    model's ``post_statements``.

    Only qualified columns (``alias.col``) are checked — unqualified
    columns cannot be resolved to a source model without full schema
    resolution and are skipped.

    Columns inside spatial functions (``ST_Intersects``, etc.) are
    skipped — those are handled by ``UnindexedJoin``.
    """

    def check_model(self, model: Model) -> RuleViolation | list[RuleViolation] | None:
        if not isinstance(model, SqlModel):
            return None

        query = model.query
        if query is None:
            return None

        # Build alias → table FQN map from FROM/JOIN clauses.
        alias_map = _build_alias_table_map(query, model)

        violations: list[RuleViolation] = []

        # Scan the WHERE clause for qualified column references.
        where = query.args.get("where")
        if where is None:
            return None

        for col in where.find_all(exp.Column):
            if not col.table:
                # Unqualified column — cannot resolve source model.
                continue

            # Skip columns inside spatial functions — handled by UnindexedJoin.
            if _is_in_spatial_function(col):
                continue

            alias = col.table
            ref_fqn = alias_map.get(alias)
            if ref_fqn is None:
                # Alias not resolved — external table or unknown.
                continue

            ref_model = _get_model(self.context, ref_fqn)
            if ref_model is None or not isinstance(ref_model, SqlModel):
                continue

            indexed_cols = _get_indexed_columns(ref_model)
            col_name = col.name
            if col_name not in indexed_cols:
                violations.append(
                    self.violation(
                        f"WHERE clause filters on unindexed column "
                        f"``{ref_fqn}``.``{col_name}`` from alias "
                        f"``{alias}``. Add a B-tree index on this "
                        f"column in the referenced model's "
                        f"``post_statements``."
                    )
                )

        if not violations:
            return None
        if len(violations) == 1:
            return violations[0]
        return violations


# ── Shared utilities ─────────────────────────────────────────────────


def _get_model(context: object, fqn: str) -> Model | None:
    """Look up a model by FQN, trying both quoted and unquoted forms.

    ``normalize_model_name`` may return quoted FQNs (e.g.
    ``"brewdb"."public"."parcels"``) while test models and some
    context lookups store unquoted FQNs (``brewdb.public.parcels``).
    This helper tries both forms.
    """
    models: dict[str, Model] = getattr(context, "_models", {})
    model = models.get(fqn)
    if model is None:
        # Try unquoted form (test models use unquoted FQNs).
        unquoted = fqn.replace('"', "")
        if unquoted != fqn:
            model = models.get(unquoted)
    return model


def _func_args(func: exp.Func) -> list[exp.Expression]:
    """Collect all argument expressions from a function node.

    Different function classes store args differently:
    - ``Anonymous``: ``expressions`` key
    - ``Left`` / ``Right``: ``this`` and ``expression`` keys
    - ``Coalesce`` / ``IfNull``: ``this`` and ``expressions`` keys
    """
    args: list[exp.Expression] = []
    for key in ("this", "expression"):
        val = func.args.get(key)
        if val is not None and isinstance(val, exp.Expression):
            args.append(val)
    for val in func.args.get("expressions", []):
        if isinstance(val, exp.Expression):
            args.append(val)
    return args
