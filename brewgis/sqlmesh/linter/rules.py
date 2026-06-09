"""Custom SQLMesh linter rules for BrewGIS.

Rules in this directory are auto-discovered by SQLMesh and run during
``sqlmesh lint`` and ``sqlmesh plan`` when enabled in config.
"""

from __future__ import annotations

import re
from pathlib import Path

import sqlglot.expressions as exp
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
