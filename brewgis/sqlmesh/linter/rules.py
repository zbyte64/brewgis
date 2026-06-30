"""Custom SQLMesh linter rules for BrewGIS.

Rules in this directory are auto-discovered by SQLMesh and run during
``sqlmesh lint`` and ``sqlmesh plan`` when enabled in config.
"""

from __future__ import annotations

import re
from pathlib import Path

import sqlglot
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


_KEY_COLUMN_NAMES = frozenset(
    {
        "apn",
        "parcel_id",
        "geoid",
        "bg_geoid",
        "block_fips",
        "block_group_id",
        "tract_id",
        "county_fips",
        "place_id",
    }
)


class MissingKeyIndex(Rule):
    """Non-VIEW models with common join-key columns (apn, parcel_id, geoid,
    etc.) must create B-tree indexes on those columns in ``post_statements``.

    Downstream models join against these columns via CTEs, making the joins
    invisible to ``UnindexedJoin``'s table-reference walker. This rule
    ensures indexes exist at the source, complementing ``MissingGeometryIndex``
    (GiST) with a B-tree key-column analogue.
    """

    def check_model(self, model: Model) -> RuleViolation | None:
        if isinstance(model, SeedModel):
            return None
        if not isinstance(model, SqlModel):
            return None

        # VIEW models can't have indexes. DuckDB models use DuckDB.
        kind = getattr(model, "kind", None)
        if kind is not None and getattr(kind, "is_view", False):
            return None
        gateway = getattr(model, "gateway", None) or ""
        if "duckdb" in str(gateway).lower():
            return None

        # Collect key columns from model schema.
        try:
            columns = model.columns_to_types_or_raise
        except (KeyError, ValueError, TypeError):
            return None

        key_cols = [c for c in _KEY_COLUMN_NAMES if c in columns]
        if not key_cols:
            return None

        # Check post_statements for b-tree indexes on those columns.
        # _get_indexed_columns reuses existing infra (handles @this_model
        # via the Step 1 fix).
        indexed_cols = _get_indexed_columns(model)
        missing = sorted(c for c in key_cols if c not in indexed_cols)
        if missing:
            return self.violation(
                f"Missing B-tree index(es) for key column(s): "
                f"{', '.join(missing)}. These columns are used as JOIN keys "
                f"by downstream models. Add ``CREATE INDEX IF NOT EXISTS "
                f"<idx_name>_@snapshot_hash ON @this_model (<col>)`` in post_statements."
            )

        return None


class PostStatementIndexTarget(Rule):
    """``CREATE INDEX`` in ``post_statements`` must target ``@this_model``,
    not the model FQN.

    ``@this_model`` resolves to the physical versioned table (e.g.
    ``sqlmesh__assessor.assessor__parcel_dasymetric_weights__3077844791``).
    Using the model FQN (a view) silently fails — PostgreSQL refuses to
    create indexes on views. Silent failure produces runtime sequential
    scans instead of index scans.
    """

    def check_model(self, model: Model) -> RuleViolation | None:
        if isinstance(model, SeedModel):
            return None
        if not isinstance(model, SqlModel):
            return None

        kind = getattr(model, "kind", None)
        if kind is not None and getattr(kind, "is_view", False):
            return None

        source_path = getattr(model, "_path", None)
        if not source_path:
            return None
        try:
            source = Path(source_path).read_text()
        except OSError:
            return None

        model_name = model.name  # e.g. "brewgis"."assessor"."parcel_dasymetric_weights"
        short_name = model_name.rsplit(".", 1)[-1] if "." in model_name else model_name

        # Find all CREATE INDEX statements and check their ON target.
        pattern = re.compile(
            r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?\S+\s+ON\s+(\S+)",
            re.IGNORECASE,
        )

        for match in pattern.finditer(source):
            target = match.group(1).strip('"')
            if target == model_name or target == short_name:
                return self.violation(
                    f"CREATE INDEX in post_statements targets the model's "
                    f"view FQN (``{model_name}``). PostgreSQL cannot create "
                    f"indexes on views — this statement silently fails. "
                    f"Replace ``ON {target}`` with ``ON @this_model``."
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

_GEOMETRY_COMPUTE_FUNCTIONS = frozenset(
    {
        "ST_AREA",
        "ST_LENGTH",
        "ST_PERIMETER",
        "ST_CENTROID",
        "ST_BUFFER",
        "ST_INTERSECTION",
        "ST_UNION",
        "ST_DIFFERENCE",
        "ST_SYMDIFFERENCE",
    }
)

_ALL_CHECKED_FUNCTIONS = (
    _SPATIAL_FUNCTIONS | _GEOMETRY_COMPUTE_FUNCTIONS | frozenset({"ST_SETSRID"})
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
        on_this_model_pattern = r"ON\s+@this_model\b"
        if (
            not re.search(on_table_pattern, on_clause, re.IGNORECASE)
            and not re.search(on_short_pattern, on_clause, re.IGNORECASE)
            and not re.search(on_this_model_pattern, on_clause, re.IGNORECASE)
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


def _get_cte_names(query: exp.Expr) -> frozenset[str]:
    """Extract CTE alias names from a query's WITH clause.

    Returns a lowercase frozenset for case-insensitive comparison.
    """
    with_clause = query.args.get("with_")
    if with_clause is None:
        return frozenset()
    ctes = with_clause.args.get("expressions")
    if ctes is None:
        return frozenset()
    names: set[str] = set()
    for cte in ctes:
        alias = cte.args.get("alias")
        if alias is not None and alias.name:
            names.add(alias.name.lower())
    return frozenset(names)


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
            # Not a SQLMesh model — check if it's a CTE with a spatial join.
            cte_violation = self._check_cte_join(table, on, model)
            if cte_violation:
                return cte_violation
            # Genuinely external table — skip.
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

    def _check_cte_join(
        self,
        table: exp.Table,
        on: exp.Expr,
        model: Model,
    ) -> RuleViolation | None:
        """Check for spatial joins against CTEs, which can't have GiST indexes.

        CTE references that can't be resolved to a SQLMesh model are checked
        here. If the table is a CTE and the ON clause uses a spatial function,
        flag it since CTEs are always materialized on the fly and can't have
        persistent indexes.
        """
        query = model.query
        if query is None:
            return None

        cte_names = _get_cte_names(query)

        # If the table is not a CTE, it's genuinely external — skip.
        if table.name.lower() not in cte_names:
            return None

        join_alias = table.alias_or_name

        # Check for && (ArrayOverlaps / Overlap).
        for node in on.find_all(exp.ArrayOverlaps):
            for col in node.find_all(exp.Column):
                if col.table == join_alias:
                    return self.violation(
                        f"Spatial join against CTE ``{table.name}`` column "
                        f"``{col.name}`` uses ``&&``. CTEs cannot have GiST "
                        f"indexes. Materialize the transformed geometry into "
                        f"a dedicated model with a post_statements GiST index."
                    )

        # Check for ST_Intersects etc.
        for func in on.find_all(exp.Func):
            if _func_name(func) not in _SPATIAL_FUNCTIONS:
                continue
            for col in func.find_all(exp.Column):
                if col.table == join_alias:
                    return self.violation(
                        f"Spatial join against CTE ``{table.name}`` column "
                        f"``{col.name}`` uses ``{_func_name(func)}(..., "
                        f"{col.name})``. CTEs cannot have GiST indexes. "
                        f"Materialize the transformed geometry into a "
                        f"dedicated model with a post_statements GiST index."
                    )

        # Check for key-based (=) joins against CTEs.
        # These can't use indexes on the CTE itself, but the source model
        # whose table the CTE reads FROM should have a B-tree index.
        for eq in on.find_all(exp.EQ):
            for col in eq.find_all(exp.Column):
                if col.table == join_alias:
                    col_name = col.name.lower()
                    if col_name in _KEY_COLUMN_NAMES:
                        return self.violation(
                            f"Key join against CTE ``{table.name}`` on column "
                            f"``{col.name}`` cannot use an index. Ensure the "
                            f"underlying model has a B-tree index on "
                            f"``{col.name}`` via ``CREATE INDEX ON @this_model "
                            f"({col.name})`` in its post_statements."
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


# ── Additional helpers ────────────────────────────────────────────────


_RANGE_OPERATORS = frozenset({"GT", "GTE", "LT", "LTE", "NEQ", "Like", "ILIKE"})

_BASE_SCHEMAS = frozenset({"staging", "base_canvas", "assessor", "nlcd"})


_AGGREGATE_FUNCS = frozenset({"AVG", "SUM", "COUNT", "MIN", "MAX"})


def _is_comma_join(query: exp.Expr) -> bool:
    """Check if FROM clause contains comma-separated tables (implicit CROSS JOIN)."""
    for join in query.find_all(exp.Join):
        kind = join.args.get("kind") or ""
        on = join.args.get("on")
        # Comma join = empty kind with no ON clause (regular JOIN has kind="" but does have ON).
        if kind == "" and on is None:
            return True
    return False


def _is_literal_true(on: exp.Expr) -> bool:
    """Check if an ON condition is a literal TRUE (not a column comparison)."""
    if isinstance(on, exp.Boolean) and on.this is True:
        return True
    if isinstance(on, exp.Boolean):
        return bool(on.this)
    # Check for `1=1` pattern.
    if isinstance(on, exp.EQ):
        left = on.left
        right = on.right
        if isinstance(left, exp.Literal) and isinstance(right, exp.Literal):
            try:
                return int(left.this) == int(right.this)
            except (ValueError, TypeError):
                pass
    return False


def _is_aggregate_cte(query: exp.Expr, cte_name: str) -> bool:
    """Check if a CTE produces exactly 1 row (aggregate without GROUP BY)."""
    with_clause = query.args.get("with_")
    if with_clause is None:
        return False
    for cte in with_clause.args.get("expressions", []):
        alias = cte.args.get("alias")
        if alias is None or alias.name.lower() != cte_name.lower():
            continue
        cte_body = cte.args.get("this")
        if cte_body is None:
            continue
        # Check for aggregate funcs without GROUP BY.
        has_agg = any(
            isinstance(node, (exp.Avg, exp.Sum, exp.Count, exp.Min, exp.Max))
            for node in cte_body.find_all(exp.Func)
        )
        has_group = cte_body.find(exp.Group) is not None
        if has_agg and not has_group:
            return True
    return False


# ── CrossJoinLikeJoin ────────────────────────────────────────────────


class CrossJoinLikeJoin(Rule):
    """Detects JOIN patterns that PostgreSQL's planner will almost
    certainly execute as nested loops:

    * **Explicit CROSS JOIN** — always produces a nested loop.
    * **Comma joins** (``FROM t1, t2``) — implicit CROSS JOIN.
    * **ON TRUE** — ``JOIN t ON true`` / ``JOIN t ON 1=1``
    * **Range-operator joins on unindexed columns** — ``a.col > b.col``
      where the column has no index.

    Skips LATERAL joins (deliberate optimization pattern) and CROSS JOIN
    against aggregate CTEs (guaranteed single-row).
    """

    def check_model(self, model: Model) -> RuleViolation | list[RuleViolation] | None:
        if not isinstance(model, SqlModel):
            return None

        query = model.query
        if query is None:
            return None

        violations: list[RuleViolation] = []
        cte_names = _get_cte_names(query)

        # Check comma joins first.
        if _is_comma_join(query):
            for join in query.find_all(exp.Join):
                kind = join.args.get("kind") or ""
                on = join.args.get("on")
                if kind == "" and on is None:
                    table = join.this
                    if isinstance(table, exp.Table):
                        violations.append(
                            self.violation(
                                f"Comma join (implicit CROSS JOIN) against "
                                f"``{table.alias_or_name}`` — will produce nested"
                                f" loops. Add an explicit JOIN condition, or use"
                                f" a separate CTE to pre-filter the table."
                            )
                        )

        # Check each explicit JOIN.
        for join in query.find_all(exp.Join):
            violation = self._check_join(join, model, cte_names, query)
            if violation is not None:
                if isinstance(violation, list):
                    violations.extend(violation)
                else:
                    violations.append(violation)

        if not violations:
            return None
        if len(violations) == 1:
            return violations[0]
        return violations

    def _check_join(
        self,
        join: exp.Join,
        model: Model,
        cte_names: frozenset[str],
        query: exp.Expr,
    ) -> RuleViolation | list[RuleViolation] | None:
        table = join.this
        if not isinstance(table, exp.Table):
            return None

        kind = join.args.get("kind") or ""

        # Skip LATERAL joins — intentional optimization.
        if "LATERAL" in kind.upper():
            return None

        # Skip dynamic/variable table references.
        if table.sql().startswith("@"):
            return None

        # Handle explicit CROSS JOIN.
        if "CROSS" in kind.upper():
            # Check if target is a CTE.
            if table.name.lower() in cte_names:
                if _is_aggregate_cte(query, table.name):
                    # Aggregate CTE produces 1 row — skip.
                    return None
                # Non-aggregate CTE — downgrade to info.
                return self.violation(
                    f"CROSS JOIN against CTE ``{table.alias_or_name}`` — verify"
                    f" this CTE produces few rows."
                )
            return self.violation(
                f"CROSS JOIN against ``{table.alias_or_name}`` — will produce"
                f" nested loops. Add an explicit JOIN condition, or use a"
                f" separate CTE to pre-filter the table."
            )

        # Skip comma joins (already handled above).
        if kind == "":
            on = join.args.get("on")
            if on is None:
                return None

        on = join.args.get("on")
        if on is None:
            return None

        # Check for ON TRUE / ON 1=1.
        if _is_literal_true(on):
            return self.violation(
                f"JOIN ON TRUE against ``{table.alias_or_name}`` — will produce"
                f" nested loops. Add a meaningful JOIN condition."
            )

        # Check for range operators on unindexed columns.
        return self._check_range_operators(model, on, table)

    def _check_range_operators(
        self,
        model: Model,
        on: exp.Expr,
        table: exp.Table,
    ) -> RuleViolation | list[RuleViolation] | None:
        """Check ON clause for range operators (>, <, >=, <=, !=, LIKE, ILIKE)
        on columns that lack indexes."""
        fqn = _table_fqn(table, model)
        if fqn is None:
            return None

        # Try to find the referenced model.
        ref_model = _get_model(self.context, fqn)
        if ref_model is None or not isinstance(ref_model, SqlModel):
            return None

        indexed_cols = _get_indexed_columns(ref_model)
        join_alias = table.alias_or_name

        violations: list[RuleViolation] = []

        for node in on.find_all(exp.Binary):
            if node.key.upper() in _RANGE_OPERATORS:
                for col in node.find_all(exp.Column):
                    if col.table == join_alias:
                        col_name = col.name
                        if col_name not in indexed_cols:
                            violations.append(
                                self.violation(
                                    f"Range join (``{node.key}``) against "
                                    f"``{fqn}`` on unindexed column "
                                    f"``{col_name}`` — will likely produce"
                                    f" nested loops. Add a B-tree index on this"
                                    f" column."
                                )
                            )

        if not violations:
            return None
        if len(violations) == 1:
            return violations[0]
        return violations


# ── UnfilteredTableScan ──────────────────────────────────────────────


class UnfilteredTableScan(Rule):
    """Flags models that reference base-table models (in ``staging/``,
    ``base_canvas/``, ``assessor/``, ``nlcd/`` schemas) without any WHERE
    or JOIN ON clause restricting them. This pattern nearly always produces
    sequential scans on large production tables.

    A WHERE clause, JOIN ON condition, or HAVING clause qualifies as a
    filter — any condition that restricts rows from the base table.

    Skips:
    * Single-source passthrough models (``SELECT * FROM staging.parcels``)
    * Models that only reference tables via CTEs (intermediate, not base)
    """

    def check_model(self, model: Model) -> RuleViolation | list[RuleViolation] | None:
        if not isinstance(model, SqlModel):
            return None

        query = model.query
        if query is None:
            return None

        # Build alias → table FQN map (only from main FROM/JOIN, not inside CTE bodies).
        alias_map: dict[str, str] = {}
        from_node = query.args.get("from_")
        if from_node is not None:
            t = from_node.this
            if isinstance(t, exp.Table):
                fqn = _table_fqn(t, model)
                if fqn:
                    alias_map[t.alias_or_name] = fqn
        for join in query.args.get("joins", []):
            t = join.this
            if isinstance(t, exp.Table):
                fqn = _table_fqn(t, model)
                if fqn:
                    alias_map[t.alias_or_name] = fqn

        cte_names = _get_cte_names(query)

        # Collect all ON-clause column references per alias.
        on_referenced_aliases: set[str] = set()
        for join in query.find_all(exp.Join):
            on = join.args.get("on")
            if on is not None:
                for col in on.find_all(exp.Column):
                    if col.table:
                        on_referenced_aliases.add(col.table)

        # Collect all WHERE clause column references per alias.
        where = query.args.get("where")
        where_referenced_aliases: set[str] = set()
        if where is not None:
            for col in where.find_all(exp.Column):
                if col.table:
                    where_referenced_aliases.add(col.table)

        # Collect all HAVING clause column references per alias.
        having = query.args.get("having")
        having_referenced_aliases: set[str] = set()
        if having is not None:
            for col in having.find_all(exp.Column):
                if col.table:
                    having_referenced_aliases.add(col.table)

        filtered_aliases = (
            on_referenced_aliases | where_referenced_aliases | having_referenced_aliases
        )

        # Check if this is a single-source passthrough (no JOIN, no filter).
        tables = list(query.find_all(exp.Table))
        joins = list(query.find_all(exp.Join))
        is_passthrough = len(tables) == 1 and len(joins) == 0

        violations: list[RuleViolation] = []

        for alias, fqn in alias_map.items():
            # Skip CTE references.
            if alias.lower() in cte_names:
                continue

            # Parse FQN to determine schema (strip quotes for comparison).
            parts = fqn.split(".")
            schema = parts[-2].strip('"').lower() if len(parts) >= 2 else ""

            # Skip passthrough models (single table, no joins).
            if is_passthrough:
                continue

            # Check for base schemas.
            if schema in _BASE_SCHEMAS:
                if alias not in filtered_aliases:
                    violations.append(
                        self.violation(
                            f"Table ``{fqn}`` (alias ``{alias}``) is referenced"
                            f" without any WHERE or JOIN filter — likely full"
                            f" sequential scan."
                        )
                    )

            # Flag public.* external tables with a note.
            if schema == "public":
                if alias not in filtered_aliases:
                    violations.append(
                        self.violation(
                            f"External table ``{fqn}`` (alias ``{alias}``) is"
                            f" referenced without any WHERE or JOIN filter."
                            f" Cannot verify indexes on external table —"
                            f" ensure it has appropriate indexes."
                        )
                    )

        if not violations:
            return None
        if len(violations) == 1:
            return violations[0]
        return violations


# ── StaticComplexityScore ────────────────────────────────────────────


class StaticComplexityScore(Rule):
    """Assigns a heuristic complexity score from AST topology, providing
    an ordinal cost ranking across all models. Emits a warning when the
    cumulative score exceeds a configurable threshold.

    Scoring model::

        score = (
            num_base_tables * 5.0 +
            num_joins * 2.0 +
            num_unindexed_join_columns * 10.0 +
            num_ctes * 1.0 +
            num_subqueries * 3.0 +
            num_distinct * 2.0 +
            num_group_by_columns * 0.5 +
            num_window_functions * 2.0 +
            num_order_by * 1.0 +
            has_full_outer_join * 15.0 +
            is_view * (-5.0)
        )

    Thresholds:
        * **< 25**: No violation (normal).
        * **25–50**: Warning-level violation (review recommended).
        * **> 50**: Error-level violation (may need optimization).
    """

    WARN_THRESHOLD = 25.0
    ERROR_THRESHOLD = 50.0

    def check_model(self, model: Model) -> RuleViolation | None:
        if isinstance(model, SeedModel):
            return None

        if not isinstance(model, SqlModel):
            return None

        query = model.query
        if query is None:
            return None

        # Count components.
        tables = list(query.find_all(exp.Table))
        joins = list(query.find_all(exp.Join))
        ctes = self._count_ctes(query)
        subqueries = self._count_subqueries(query)
        distinct = 1 if query.find(exp.Distinct) else 0
        group_by_cols = self._count_group_by_columns(query)
        window_fns = len(list(query.find_all(exp.Window)))
        order_by = self._count_order_by(query)
        has_full_outer = self._has_full_outer_join(query)

        # Determine if this is a VIEW model.
        is_view = False
        kind = getattr(model, "kind", None)
        if kind is not None and getattr(kind, "is_view", False):
            is_view = True

        # Compute base score.
        num_base_tables = len(tables)
        num_joins = len(joins)
        num_ctes = ctes
        num_subqueries = subqueries
        num_distinct = distinct
        num_group_by_columns = group_by_cols
        num_window_functions = window_fns
        num_order_by = order_by
        full_outer_penalty = 15.0 if has_full_outer else 0.0
        view_penalty = -5.0 if is_view else 0.0

        score = (
            num_base_tables * 5.0
            + num_joins * 2.0
            + num_ctes * 1.0
            + num_subqueries * 3.0
            + num_distinct * 2.0
            + num_group_by_columns * 0.5
            + num_window_functions * 2.0
            + num_order_by * 1.0
            + full_outer_penalty
            + view_penalty
        )

        # Add unindexed join column penalty.
        unindexed_count = self._count_unindexed_join_columns(query, model)
        score += unindexed_count * 10.0

        if score < self.WARN_THRESHOLD:
            return None

        # Build message.
        factors: list[str] = []
        if num_base_tables:
            factors.append(f"{num_base_tables} base tables")
        if num_joins:
            factors.append(f"{num_joins} joins")
        if unindexed_count:
            factors.append(f"{unindexed_count} unindexed")
        if num_ctes:
            factors.append(f"{num_ctes} CTEs")
        if num_subqueries:
            factors.append(f"{num_subqueries} subqueries")
        if num_distinct:
            factors.append(f"{num_distinct} DISTINCT")
        if num_group_by_columns:
            factors.append(f"{num_group_by_columns} GROUP BY cols")
        if num_window_functions:
            factors.append(f"{num_window_functions} window fns")
        if has_full_outer:
            factors.append("FULL OUTER JOIN")
        if is_view:
            factors.append("view")

        factor_str = ", ".join(factors) if factors else "no complexity"

        severity = "Warning" if score < self.ERROR_THRESHOLD else "Error"

        return self.violation(
            f"Complexity score {score:.1f} (> {self.WARN_THRESHOLD:.0f}):"
            f" {factor_str}"
            f" ({severity})"
        )

    @staticmethod
    def _count_ctes(query: exp.Expr) -> int:
        """Count CTE definitions in a WITH clause."""
        with_clause = query.args.get("with_")
        if with_clause is None:
            return 0
        ctes = with_clause.args.get("expressions")
        if ctes is None:
            return 0
        return len(ctes)

    @staticmethod
    def _count_subqueries(query: exp.Expr) -> int:
        """Count nested subqueries (Subquery nodes that are not CTEs)."""
        count = 0
        for node in query.find_all(exp.Select):
            # Check if this is a nested SELECT (not the top-level query).
            parent = node.parent
            while parent is not None:
                if isinstance(parent, exp.Subquery):
                    count += 1
                    break
                parent = parent.parent
        return count

    @staticmethod
    def _count_group_by_columns(query: exp.Expr) -> int:
        """Count total columns across all GROUP BY clauses."""
        count = 0
        for group in query.find_all(exp.Group):
            count += len(group.expressions)
        return count

    @staticmethod
    def _count_order_by(query: exp.Expr) -> int:
        """Count ORDER BY expressions."""
        order = query.args.get("order")
        if order is None:
            return 0
        expressions = order.args.get("expressions")
        if expressions is None:
            return 0
        return len(expressions)

    @staticmethod
    def _has_full_outer_join(query: exp.Expr) -> bool:
        """Check if query contains a FULL OUTER JOIN."""
        for join in query.find_all(exp.Join):
            kind = join.args.get("kind") or ""
            side = join.args.get("side") or ""
            if "FULL" in kind.upper() or "FULL" in side.upper():
                return True
        return False

    def _count_unindexed_join_columns(
        self,
        query: exp.Expr,
        model: Model,
    ) -> int:
        """Count unindexed columns used in JOIN ON conditions."""
        count = 0
        seen: set[tuple[str, str]] = set()

        for join in query.find_all(exp.Join):
            on = join.args.get("on")
            if on is None:
                continue

            table = join.this
            if not isinstance(table, exp.Table):
                continue
            if table.sql().startswith("@"):
                continue

            fqn = _table_fqn(table, model)
            if fqn is None:
                continue

            ref_model = _get_model(self.context, fqn)
            if ref_model is None or not isinstance(ref_model, SqlModel):
                continue

            indexed_cols = _get_indexed_columns(ref_model)
            join_alias = table.alias_or_name

            for col in on.find_all(exp.Column):
                if col.table == join_alias:
                    col_name = col.name
                    key = (fqn, col_name)
                    if key not in seen and col_name not in indexed_cols:
                        seen.add(key)
                        count += 1

        return count


# ── IndexColumnExistence ──────────────────────────────────────────────


def _extract_index_columns(
    sql_text: str,
    model_name: str,
    result: set[str] | None = None,
) -> set[str]:
    """Extract column names from CREATE INDEX statements in
    ``sql_text`` that reference ``model_name``.

    If ``result`` is provided, columns are added to it (for incremental
    collection). Always returns the full set of columns found.
    """
    cols: set[str] = set() if result is None else result
    pattern = re.compile(
        r"""
        CREATE\s+(UNIQUE\s+)?INDEX
        (\s+IF\s+NOT\s+EXISTS)?\s+\S+
        \s+ON\s+(\S+\.)?(?P<on_table>\w+)
        (\s+USING\s+\w+)?
        \s*\(
        (?P<cols>[^)]+)
        \)
        """,
        re.IGNORECASE | re.VERBOSE | re.DOTALL,
    )

    # Short name (last component of FQN).
    short_name = model_name.rsplit(".", 1)[-1] if "." in model_name else model_name

    for match in pattern.finditer(sql_text):
        on_table = match.group("on_table")
        if on_table != short_name and on_table != model_name:
            continue
        cols_section = match.group("cols")
        for col_expr in cols_section.split(","):
            col_name = col_expr.strip().split()[0].strip('"')
            if col_name:
                cols.add(col_name)

    return cols


class IndexColumnExistence(Rule):
    """``CREATE INDEX`` statements in ``post_statements`` reference
    columns that exist in the model's schema.

    An index referencing a nonexistent column silently creates an index on
    a misspelled name, wasting DDL time and providing no query benefit.
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

        # Collect model column names.
        try:
            model_columns = model.columns_to_types_or_raise
        except (KeyError, ValueError, TypeError):
            return None

        # Extract column names from CREATE INDEX statements.
        index_cols: set[str] = set()

        # 1) Check post_statements_ (in-memory, works for synthetic models).
        for ps in getattr(model, "post_statements_", []) or []:
            sql_text = ps.sql if hasattr(ps, "sql") else str(ps)
            _extract_index_columns(sql_text, model.name, index_cols)

        # 2) Fall back to reading the source file (for real models on disk).
        if not index_cols:
            source_path = getattr(model, "_path", None)
            if source_path:
                try:
                    source = Path(source_path).read_text()
                    _extract_index_columns(source, model.name, index_cols)
                except OSError:
                    pass

        if not index_cols:
            return None

        # Check each index column exists in the model schema.
        missing = [c for c in index_cols if c not in model_columns]
        if missing:
            unique_missing = sorted(set(missing))
            return self.violation(
                f"CREATE INDEX references columns not in model schema:"
                f" {', '.join(unique_missing)}."
                f" Available columns: {', '.join(sorted(model_columns))}."
            )

        return None


# ── AuditColumnExistence ─────────────────────────────────────────────


class AuditColumnExistence(Rule):
    """Audits reference columns that exist in the model's schema.

    Catches two categories of column reference errors:

    1. **Inline built-in audits** (``not_null(columns := (col,))``,
       ``unique_values(columns := (col,))``) — extracts column names
       from the keyword arguments and validates them.

    2. **Named custom audit files** (e.g. ``assert_du_vacancy_rates``)
       — parses the audit SQL file and extracts columns referenced
       against ``@this_model``, then validates each against the model
       schema.
    """

    _AUDIT_DIR = Path(__file__).resolve().parent.parent / "audits"

    # Built-in audits that accept a ``columns`` keyword argument.
    _BUILTIN_COLUMN_AUDITS = frozenset(
        {
            "not_null",
            "unique",
            "unique_values",
            "distinct_values",
            "accepted_values",
        }
    )

    # Audits that intentionally take no column arguments (COUNT(*) etc.)
    _SKIP_AUDITS = frozenset(
        {
            "number_of_rows",
            "assert_row_count_greater_than_zero",
            "assert_row_count_between",
            "assert_parcel_du_estimation_row_count",
            "assert_parcel_bft_classification_row_count",
            "assert_sacog_assessor_parcels_row_count",
        }
    )

    def check_model(self, model: Model) -> RuleViolation | None:
        if not isinstance(model, SqlModel):
            return None

        try:
            model_columns = model.columns_to_types_or_raise
        except (KeyError, ValueError, TypeError):
            return None

        violations: list[RuleViolation] = []

        for audit_name, audit_args in getattr(model, "audits", None) or []:
            # ── Inline built-in audits (not_null, unique_values, etc.) ──
            if audit_name in self._SKIP_AUDITS:
                continue

            if audit_name in self._BUILTIN_COLUMN_AUDITS:
                missing = self._check_inline_audit(
                    audit_name,
                    audit_args,
                    model_columns,
                )
                if missing:
                    violations.append(
                        self.violation(
                            f"Inline audit ``{audit_name}`` references columns"
                            f" not in model schema: {', '.join(sorted(missing))}."
                        )
                    )
                continue

            # ── Named custom audit files ──
            audit_path = self._AUDIT_DIR / f"{audit_name}.sql"
            if not audit_path.exists():
                # Audit file not found — skip (the built-in
                # ``nomissingaudits`` rule catches missing files).
                continue

            try:
                audit_sql = audit_path.read_text()
            except OSError:
                continue

            missing = self._check_named_audit(
                audit_name,
                audit_sql,
                model_columns,
            )
            if missing:
                violations.append(
                    self.violation(
                        f"Audit ``{audit_name}`` references columns not in"
                        f" model schema: {', '.join(sorted(missing))}."
                    )
                )

        if not violations:
            return None
        if len(violations) == 1:
            return violations[0]
        return violations

    def _check_inline_audit(
        self,
        audit_name: str,
        audit_args: dict,
        model_columns: dict,
    ) -> list[str]:
        """Extract column names from a built-in audit's args and
        return any that don't exist in ``model_columns``."""
        cols_expr = audit_args.get("columns")
        if cols_expr is None:
            return []

        col_names: list[str] = []
        if hasattr(cols_expr, "expressions"):
            for c in cols_expr.expressions:
                if hasattr(c, "name"):
                    col_names.append(c.name)
                else:
                    col_names.append(str(c))

        return [c for c in col_names if c not in model_columns]

    @staticmethod
    def _strip_audit_wrapper(audit_sql: str) -> str:
        """Strip the AUDIT() wrapper from an audit SQL file, returning
        just the query body."""
        # Remove the AUDIT (...) wrapper block (may span multiple lines).
        stripped = re.sub(
            r"(?is)^\s*AUDIT\s*\(.*?\);\s*",
            "",
            audit_sql,
        )
        return stripped.strip()

    def _check_named_audit(
        self,
        audit_name: str,
        audit_sql: str,
        model_columns: dict,
    ) -> list[str]:
        """Parse a named audit SQL file and return columns referenced
        against ``@this_model`` that don't exist in ``model_columns``."""
        # Strip the AUDIT() wrapper before parsing.
        query_sql = self._strip_audit_wrapper(audit_sql)
        if not query_sql:
            return []

        try:
            parsed = sqlglot.parse_one(query_sql, read="postgres")
        except (sqlglot.errors.ParseError, Exception):
            return []

        # Find all @this_model references.
        # In FROM clauses, @this_model parses as an exp.Table with
        # name starting with '@' (the '@' is part of the table name).
        this_model_aliases: set[str] = set()
        has_bare_this_model = False

        # Check all FROM clauses for @this_model references.
        for from_node in parsed.find_all(exp.From):
            is_tm = False
            from_table = from_node.this
            if isinstance(from_table, exp.Table):
                if (
                    from_table.name.startswith("@this_model")
                    or from_table.name == "this_model"
                ):
                    is_tm = True
            elif isinstance(from_table, exp.Subquery):
                # CTE reference — check if alias matches a CTE wrapping @this_model.
                pass

            if not is_tm:
                continue

            alias = from_table.alias or ""
            if alias:
                this_model_aliases.add(alias.lower())
            else:
                has_bare_this_model = True

        # Also check CTEs for @this_model references.
        # A CTE wrapping @this_model makes its alias a @this_model alias.
        for cte in parsed.find_all(exp.CTE):
            cte_body = cte.this
            has_tm = any(
                isinstance(n, exp.Table)
                and (n.name.startswith("@this_model") or n.name == "this_model")
                for n in cte_body.find_all(exp.Table)
            )
            if has_tm:
                cte_alias = getattr(cte, "alias", None) or ""
                if isinstance(cte_alias, str):
                    alias_name = cte_alias
                elif hasattr(cte_alias, "name"):
                    alias_name = cte_alias.name
                else:
                    alias_name = str(cte_alias) if cte_alias else ""
                if alias_name:
                    this_model_aliases.add(alias_name.lower())
                else:
                    has_bare_this_model = True

        # Collect CTE names to avoid confusing CTE columns with model columns.
        cte_names = _get_cte_names(parsed)

        col_names: set[str] = set()
        for col in parsed.find_all(exp.Column):
            table_name = (col.table or "").lower()
            if table_name and table_name in this_model_aliases:
                # Column explicitly qualified with @this_model's alias.
                col_names.add(col.name)
            elif not table_name:
                # Unqualified column — could be from @this_model.
                # Include if:
                #   - bare @this_model (no alias) is used, OR
                #   - the column is inside a CTE that wraps @this_model
                in_unrelated_cte = _audit_col_inside_unrelated_cte(col, cte_names)
                if has_bare_this_model and not in_unrelated_cte:
                    col_names.add(col.name)
                elif not in_unrelated_cte:
                    # Check if inside a CTE that wraps @this_model
                    if _is_inside_this_model_cte(col, this_model_aliases):
                        col_names.add(col.name)

        if not col_names:
            return []

        return [c for c in sorted(col_names) if c not in model_columns]


def _is_inside_this_model_cte(col: exp.Column, this_model_aliases: set[str]) -> bool:
    """Check if a column is inside a CTE whose alias is in
    ``this_model_aliases`` (meaning the CTE wraps @this_model)."""
    parent = col.parent
    while parent is not None:
        if isinstance(parent, exp.CTE):
            cte_alias = getattr(parent, "alias", None) or ""
            if isinstance(cte_alias, str):
                alias_name = cte_alias
            elif hasattr(cte_alias, "name"):
                alias_name = cte_alias.name
            else:
                alias_name = str(cte_alias) if cte_alias else ""
            if alias_name and alias_name.lower() in this_model_aliases:
                return True
            return False
        if isinstance(parent, exp.Subquery):
            # Check if this subquery references @this_model.
            has_this = any(
                isinstance(n, exp.Table)
                and (n.name.startswith("@this_model") or n.name == "this_model")
                for n in parent.find_all(exp.Table)
            )
            if has_this:
                return True
            return False
        parent = parent.parent
    return False


def _audit_col_inside_unrelated_cte(col: exp.Column, cte_names: frozenset[str]) -> bool:
    """Check if a column is inside a CTE that does NOT reference
    @this_model. Columns inside unrelated CTEs are not model columns."""
    parent = col.parent
    while parent is not None:
        if isinstance(parent, exp.CTE):
            cte_alias = getattr(parent, "alias", None) or ""
            if isinstance(cte_alias, str):
                alias_name = cte_alias
            elif hasattr(cte_alias, "name"):
                alias_name = cte_alias.name
            else:
                alias_name = str(cte_alias) if cte_alias else ""
            if alias_name:
                if alias_name.lower() in cte_names:
                    # Check if this CTE references @this_model.
                    has_this = any(
                        isinstance(n, exp.Table)
                        and (n.name.startswith("@this_model") or n.name == "this_model")
                        for n in parent.find_all(exp.Table)
                    )
                    return not has_this
            return False
        if isinstance(parent, exp.Subquery):
            # Check if this subquery references @this_model.
            has_this = any(
                isinstance(n, exp.Table)
                and (n.name.startswith("@this_model") or n.name == "this_model")
                for n in parent.find_all(exp.Table)
            )
            return not has_this
        parent = parent.parent
    return False


# ── DuckDBGeometryUsage ────────────────────────────────────────────────


class DuckDBGeometryUsage(Rule):
    """Flags use of geometry columns from DuckDB gateway models that
    produce NaN/Infinity coordinates when used in PostGIS.

    DuckDB's ``ST_Transform(geometry, 'EPSG:3310')`` produces coordinates
    that PostgreSQL interprets as valid but are actually NaN/Infinity.
    Downstream models computing ``ST_Area`` on these geometries get 0.
    Spatial joins (``ST_Intersects``, ``&&``) produce empty results.
    """

    def check_model(self, model: Model) -> RuleViolation | list[RuleViolation] | None:
        if not isinstance(model, SqlModel):
            return None

        query = model.render_query()
        if query is None:
            return None

        alias_map = _build_alias_table_map(query, model)
        context = getattr(self, "context", None)

        # Track dedup: (model_fqn, column_name) per model.
        reported: set[tuple[str, str]] = set()
        violations: list[RuleViolation] = []

        for func in query.find_all(exp.Func):
            if _func_name(func) not in _ALL_CHECKED_FUNCTIONS:
                continue
            for col in func.find_all(exp.Column):
                self._check_column(col, alias_map, context, reported, violations)

        # Check && operator (ArrayOverlaps).
        for overlaps in query.find_all(exp.ArrayOverlaps):
            for col in overlaps.find_all(exp.Column):
                self._check_column(col, alias_map, context, reported, violations)

        if not violations:
            return None
        if len(violations) == 1:
            return violations[0]
        return violations

    def _check_column(
        self,
        col: exp.Column,
        alias_map: dict[str, str],
        context: object,
        reported: set[tuple[str, str]],
        violations: list[RuleViolation],
    ) -> None:
        """Check a single column reference for DuckDB geometry issues."""
        alias = col.table or ""
        if not alias:
            from_entries = [k for k in alias_map if k]
            if len(from_entries) == 1:
                alias = from_entries[0]
            else:
                return

        fqn = alias_map.get(alias)
        if fqn is None:
            return

        ref_model = _get_model(context, fqn)
        if ref_model is None:
            return
        if getattr(ref_model, "gateway", None) != "duckdb":
            return

        col_name = col.name
        key = (fqn, col_name)
        if key in reported:
            return
        reported.add(key)

        if col_name == "local_geometry":
            violations.append(
                self.violation(
                    f"reference to ``local_geometry`` from DuckDB gateway model"
                    f" ``{fqn}``. DuckDB ST_Transform to EPSG:3310 produces"
                    f" NaN/Infinity. Use ST_Transform(ST_SetSRID("
                    f"{alias}.geometry, 4326), 3310) instead."
                )
            )
        elif col_name == "geometry":
            if self._is_wrapped_in_setsrid_or_transform(col):
                return
            violations.append(
                self.violation(
                    f"use of ``geometry`` from DuckDB gateway model ``{fqn}``"
                    f" without ST_SetSRID. PostGIS sees SRID 0. Wrap with"
                    f" ST_SetSRID({alias}.geometry, 4326)."
                )
            )

    @staticmethod
    def _is_wrapped_in_setsrid_or_transform(col: exp.Column) -> bool:
        """Check if col is directly inside ST_SetSRID or ST_Transform."""
        parent = col.parent
        while parent is not None:
            if isinstance(parent, exp.Func):
                pname = _func_name(parent)
                if pname == "ST_SETSRID" or pname == "ST_TRANSFORM":
                    return True
                break
            parent = parent.parent
        return False


# ── DuckDBTransformWarning ──────────────────────────────────────────────


class DuckDBTransformWarning(Rule):
    """Warns when DuckDB gateway models project geometry to the local SRID.

    DuckDB's ``ST_Transform`` to a projected CRS (specifically EPSG:3310)
    produces NaN/Infinity coordinates when the geometry is materialized in
    PostGIS. This rule flags DuckDB models that do ``ST_Transform(geometry, …3310…)``
    so the developer can verify or move the transformation downstream.
    """

    def check_model(self, model: Model) -> RuleViolation | None:
        if getattr(model, "gateway", None) != "duckdb":
            return None
        if not isinstance(model, SqlModel):
            return None

        try:
            query = model.render_query()
        except Exception:  # noqa: BLE001
            return None
        if query is None:
            return None

        sql = query.sql(dialect="duckdb")
        if re.search(r"ST_Transform\s*\(.*(?:3310|local_srid)", sql, re.IGNORECASE):
            return self.violation(
                "DuckDB gateway model renders local_geometry via ST_Transform"
                " to a projected CRS. This produces NaN/Infinity coordinates"
                " when materialized in PostGIS. Move the ST_Transform to a"
                " downstream PostgreSQL model, or verify the DuckDB proj"
                " database is properly configured."
            )
        return None


# ── DegradingSRIDCast ──────────────────────────────────────────────────


class DegradingSRIDCast(Rule):
    """Warns when ``ST_SetSRID(geometry, 0)`` degrades a properly-typed
    geometry column down to SRID 0 to match an upstream workaround.

    This is a downstream band-aid for the DuckDB SRID 0 problem. Instead
    of casting to SRID 0, the upstream model's geometry should have its
    SRID properly set.
    """

    def check_model(self, model: Model) -> RuleViolation | list[RuleViolation] | None:
        if not isinstance(model, SqlModel):
            return None

        query = model.render_query()
        if query is None:
            return None

        alias_map = _build_alias_table_map(query, model)
        context = getattr(self, "context", None)

        violations: list[RuleViolation] = []

        for func in query.find_all(exp.Func):
            if _func_name(func) != "ST_SETSRID":
                continue

            args = _func_args(func)
            if len(args) < 2:
                continue

            srid_arg = args[1]
            if not isinstance(srid_arg, exp.Literal):
                continue
            try:
                if int(srid_arg.this) != 0:
                    continue
            except (ValueError, TypeError):
                continue

            # ``ST_SetSRID(expr, 0)`` — check first arg.
            first = args[0]
            if not isinstance(first, exp.Column):
                continue  # Not a column ref (e.g., ST_MakePoint).

            alias = first.table or ""
            if not alias:
                from_entries = [k for k in alias_map if k]
                if len(from_entries) == 1:
                    alias = from_entries[0]
                else:
                    continue

            fqn = alias_map.get(alias)
            if fqn is None:
                continue

            ref_model = _get_model(context, fqn)
            if ref_model is None:
                continue
            # Skip DuckDB sources — SRID 0 is the true state.
            if getattr(ref_model, "gateway", None) == "duckdb":
                continue

            violations.append(
                self.violation(
                    f"ST_SetSRID({first}, 0) degrades SRID to 0 from ``{fqn}``."
                    f" Set the correct SRID on the upstream model's geometry"
                    f" column instead of working around missing SRID metadata"
                    f" downstream."
                )
            )

        if not violations:
            return None
        if len(violations) == 1:
            return violations[0]
        return violations
