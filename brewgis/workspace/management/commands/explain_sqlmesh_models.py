"""SQLMesh model EXPLAIN audit — safe-for-CI query-plan analysis.

Usage:
    python manage.py explain_sqlmesh_models
    python manage.py explain_sqlmesh_models --models dasymetric_intersections sacog_correlations
    python manage.py explain_sqlmesh_models --max-depth 1

Discovers SQLMesh .sql model files, parses MODEL() blocks, resolves the
dependency graph, runs EXPLAIN (COSTS, VERBOSE, FORMAT JSON) on each model's
SQL body, and emits a diagnostic terminal report.

Always exits 0 — this is a human-review tool, not a CI gate.
"""

from __future__ import annotations

import argparse  # noqa: TC003
import logging
import sys
from collections import deque
from dataclasses import dataclass
from dataclasses import field
from typing import IO

from django.conf import settings
from django.core.management.base import BaseCommand
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from brewgis.workspace.services._db import get_engine

logger = logging.getLogger(__name__)

# ── Data types ────────────────────────────────────────────────────────────


@dataclass
class ModelInfo:
    """Wraps a SQLMesh model with metadata for the audit."""

    name: str
    schema: str
    kind: str  # "FULL" or "VIEW"
    qualified: str  # e.g. "brewgis.comparison.sacog_parcel_shim"
    deps: set[str] = field(default_factory=set)
    error: str | None = None


@dataclass
class PlanNode:
    """A node in the PostgreSQL plan tree."""

    node_type: str
    relation_name: str | None
    alias: str | None
    startup_cost: float
    total_cost: float
    plan_rows: float
    join_type: str | None
    index_name: str | None
    subplans: list[PlanNode] = field(default_factory=list)


@dataclass
class PlanAnalysis:
    """Extracted diagnostic info from an EXPLAIN JSON plan."""

    total_cost: float
    startup_cost: float
    plan_rows: float
    node_count: int
    max_depth: int
    seq_scans: list[str]
    nested_loops: int
    plan_tree: PlanNode | None = None


# ── Discovery ─────────────────────────────────────────────────────────────


def _normalise_fqn(fqn: str) -> str:
    """Strip SQL quoting from a model FQN.

    ``"brewgis"."comparison"."foo"`` → ``brewgis.comparison.foo``.
    """
    return fqn.replace('"', "")


def _unqualify(fqn: str) -> str:
    """Return the short name from a possibly-quoted FQN."""
    return _normalise_fqn(fqn).rsplit(".", 1)[-1]


def _extract_schema(fqn: str) -> str:
    """Extract schema (second component) from a model FQN."""
    parts = _normalise_fqn(fqn).split(".")
    return parts[1] if len(parts) >= 2 else ""


def discover_models_from_sqlmesh() -> dict[str, ModelInfo]:
    """Load SQLMesh context and build ModelInfo dict."""
    ctx = _get_sqlmesh_context()
    models: dict[str, ModelInfo] = {}
    for fqn, sqlmodel in ctx.models.items():
        normalised = _normalise_fqn(fqn)
        parts = normalised.split(".")
        # Only include brewgis-catalog models (skip DuckDB gateway models)
        if len(parts) < 3 or parts[0] != "brewgis":
            continue
        _schema, _name = parts[1], parts[2]

        kind = "VIEW" if sqlmodel.view_name else "FULL"

        deps: set[str] = set()
        for dep_fqn in sqlmodel.depends_on:
            dep_normalised = _normalise_fqn(str(dep_fqn))
            parts_d = dep_normalised.split(".")
            if (
                len(parts_d) >= 3
                and parts_d[0] == "brewgis"
                and parts_d[1]
                in (
                    "comparison",
                    "base_canvas",
                    "assessor",
                    "staging",
                    "nlcd",
                    "seeds",
                )
            ):
                deps.add(dep_normalised)

        models[normalised] = ModelInfo(
            name=_name,
            schema=_schema,
            kind=kind,
            qualified=normalised,
            deps=deps,
        )
    return models


# ── Dependency resolver ───────────────────────────────────────────────────


def find_terminal_refs(models: dict[str, ModelInfo]) -> set[str]:
    """brewgis-qualified refs that are NOT SQLMesh models."""
    all_models = set(models)
    referenced: set[str] = set()
    for info in models.values():
        referenced.update(info.deps)
    return referenced - all_models


def topology_order(
    models: dict[str, ModelInfo],
    seeds: set[str],
) -> list[ModelInfo]:
    """Topological sort via Kahn's algorithm, limited to models reachable from *seeds*."""
    # Expand seeds to include all transitive dependencies
    expanded: set[str] = set(seeds)
    queue = deque(seeds)
    while queue:
        qname = queue.popleft()
        info = models.get(qname)
        if info is None:
            continue
        for dep in info.deps:
            if dep in models and dep not in expanded:
                expanded.add(dep)
                queue.append(dep)

    # Build reverse deps: model → models that depend on it
    reverse_deps: dict[str, set[str]] = {m: set() for m in expanded}
    for qname in expanded:
        info = models.get(qname)
        if info is None:
            continue
        for dep in info.deps:
            if dep in models:
                reverse_deps.setdefault(dep, set()).add(qname)

    # In-degree = number of deps within expanded set
    in_degree: dict[str, int] = {}
    for qname in expanded:
        info = models.get(qname)
        if info is None:
            continue
        in_degree[qname] = sum(1 for d in info.deps if d in models)

    available = deque(q for q, d in in_degree.items() if d == 0)
    result: list[ModelInfo] = []
    visited: set[str] = set()

    while available:
        qname = available.popleft()
        if qname in visited:
            continue
        visited.add(qname)
        result.append(models[qname])
        for dependent in reverse_deps.get(qname, set()):
            if dependent in visited:
                continue
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                available.append(dependent)

    remaining = expanded - visited
    if remaining:
        logger.warning("Cycle or unreachable models: %s", ", ".join(sorted(remaining)))
        for qname in sorted(remaining):
            result.append(models[qname])
    return result


# ── SQLMesh logical views ────────────────────────────────────────────────────


def ensure_logical_views(ctx) -> int:
    """Create logical-name views for all materialized SQLMesh snapshots.

    SQLMesh stores physical tables in versioned schemas
    (e.g. ``sqlmesh__assessor.assessor__modelname__hash``) but renders
    queries referencing logical names (e.g. ``brewgis.assessor.modelname``).
    This function creates ``CREATE OR REPLACE VIEW`` mappings so that
    EXPLAIN can resolve the logical names against the live physical tables.

    Returns the number of views created.
    """
    from sqlalchemy import text as _text

    engine = get_engine()
    snaps = ctx._snapshots()  # noqa: SLF001
    created = 0

    for snap in snaps.values():
        name = snap.name
        logical = name.replace('"', "")
        parts = logical.split(".")
        if len(parts) < 3:
            continue
        schema, model_name = parts[1], parts[2]

        # Skip public tables — they come from dlt, not SQLMesh
        if schema in ("public", "shared", "tests"):
            continue

        pschema = snap.physical_schema
        version = snap.version
        phys_table = f"{schema}__{model_name}__{version}"

        try:
            with engine.connect() as conn, conn.begin():
                # Check both pg_tables and pg_views (some SQLMesh physical
                # snapshots are views, e.g. DuckDB-staging models)
                row = conn.execute(
                    _text(
                        "SELECT 1 FROM pg_tables "
                        "WHERE schemaname = :s AND tablename = :t "
                        "UNION ALL "
                        "SELECT 1 FROM pg_views "
                        "WHERE schemaname = :s AND viewname = :t "
                        "LIMIT 1"
                    ),
                    {"s": pschema, "t": phys_table},
                ).fetchone()
                if not row:
                    continue
                conn.execute(_text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
                conn.execute(
                    _text(
                        f'CREATE OR REPLACE VIEW "{schema}"."{model_name}" AS '
                        f'SELECT * FROM "{pschema}"."{phys_table}"'
                    )
                )
                created += 1
        except Exception:  # noqa: BLE001
            logger.debug("Failed to create view %s.%s", schema, model_name)

    return created


def _sqlglot_to_pg_type(raw_type: str, column_name: str = "") -> str:
    """Map a sqlglot type string to a PostgreSQL DDL type.

    *column_name* is used as a hint for UNKNOWN types — columns named
    ``geometry``, ``local_geometry``, or ending in ``_geom``/``_geometry``
    are assigned ``GEOMETRY`` rather than the default ``TEXT``.
    """
    t = raw_type.upper().strip()
    # Geometry / PostGIS
    if t.startswith("GEOMETRY") or t.startswith("GEOGRAPHY"):
        return raw_type  # keep as-is (includes SRID qualifiers)
    # Standard mappings
    mapping = {
        "TEXT": "TEXT",
        "STRING": "TEXT",
        "VARCHAR": "TEXT",
        "CHAR": "TEXT",
        "INT": "INTEGER",
        "INTEGER": "INTEGER",
        "BIGINT": "BIGINT",
        "SMALLINT": "SMALLINT",
        "FLOAT": "DOUBLE PRECISION",
        "FLOAT8": "DOUBLE PRECISION",
        "FLOAT64": "DOUBLE PRECISION",
        "DOUBLE": "DOUBLE PRECISION",
        "REAL": "REAL",
        "NUMERIC": "NUMERIC",
        "DECIMAL": "NUMERIC",
        "BOOLEAN": "BOOLEAN",
        "BOOL": "BOOLEAN",
        "DATE": "DATE",
        "TIMESTAMP": "TIMESTAMP",
        "TIMESTAMPTZ": "TIMESTAMPTZ",
        "TIMESTAMP WITH TIME ZONE": "TIMESTAMPTZ",
        "JSONB": "JSONB",
        "JSON": "JSON",
        "UUID": "UUID",
    }
    # Handle parameterized types (NUMERIC(10,2), VARCHAR(255), etc.)
    if "(" in t and ")" in t:
        base = t.split("(")[0]
        params = t[t.index("(") :]
        mapped_base = mapping.get(base)
        if mapped_base:
            return f"{mapped_base}{params}"
        if base in (
            "GEOMETRY",
            "TEXT",
            "VARCHAR",
            "CHARACTER VARYING",
        ):
            return raw_type  # keep original
    base_type = mapping.get(t)
    if base_type:
        return base_type
    # Fallback for UNKNOWN / unresolvable
    if t in ("UNKNOWN", "NULL_TYPE", ""):
        cn = column_name.lower()
        # Geometry columns
        if cn in ("geometry", "local_geometry") or cn.endswith(("_geom", "_geometry")):
            return "GEOMETRY"
        # TEXT-hint column names (identifiers, codes, categories)
        if cn.endswith(
            (
                "_key",
                "_type",
                "_category",
                "_code",
                "_name",
                "_subtype",
                "_class",
            )
        ):
            return "TEXT"
        # ID columns — "parcel_id" → TEXT, but beware of area column names
        # like "area_parcel_no_use" which end in "_id" or "_use" but are numeric.
        if cn.endswith("_id") or cn in ("apn", "parcel_id"):
            return "TEXT"
        # Everything else defaults to DOUBLE PRECISION (the dominant
        # numeric type in this codebase).  This handles PostGIS function
        # outputs like ST_Area, ST_Intersection, etc.
        return "DOUBLE PRECISION"
    return raw_type


def materialize_empty_tables(ctx) -> int:
    """Create empty physical tables + views for ALL models that lack them.

    Uses ``columns_to_types`` from each snapshot to build ``CREATE TABLE``
    DDL.  No data is loaded — rows stay zero.  This lets EXPLAIN resolve
    every model reference in the dependency graph regardless of pipeline
    state.

    Returns the number of tables/views created.
    """
    from sqlalchemy import text as _text

    engine = get_engine()
    snaps = ctx._snapshots()  # noqa: SLF001
    created = 0

    for snap in snaps.values():
        name = snap.name
        logical = name.replace('"', "")
        parts = logical.split(".")
        if len(parts) < 3:
            continue
        schema, model_name = parts[1], parts[2]

        # Skip public tables — they come from dlt, not SQLMesh
        if schema in ("public", "shared"):
            continue
        pschema = snap.physical_schema
        version = snap.version
        phys_table = f"{schema}__{model_name}__{version}"

        try:
            with engine.connect() as conn, conn.begin():
                # Check if physical table already exists
                has_table = conn.execute(
                    _text(
                        "SELECT 1 FROM pg_tables "
                        "WHERE schemaname = :s AND tablename = :t"
                    ),
                    {"s": pschema, "t": phys_table},
                ).fetchone()

                if has_table:
                    # If the model has been applied (has intervals), the table is
                    # real pipeline data — preserve it.
                    if snap.intervals:
                        continue
                    # Our empty table from a previous run with wrong types — drop it.
                    conn.execute(
                        _text(
                            f'DROP TABLE IF EXISTS "{pschema}"."{phys_table}" CASCADE'
                        )
                    )
                    # Also drop the logical view if it exists
                    conn.execute(
                        _text(f'DROP VIEW IF EXISTS "{schema}"."{model_name}" CASCADE')
                    )

                cols = (
                    snap.model.columns_to_types
                    if hasattr(snap.model, "columns_to_types")
                    else {}
                )
                if not cols:
                    continue

                if snap.is_view:
                    # For VIEW models, create a view that selects NULLs.
                    # Use DROP + CREATE instead of CREATE OR REPLACE because
                    # PostgreSQL cannot change column types via REPLACE.
                    null_exprs = []
                    for cname, ctype in cols.items():
                        pg_type = _sqlglot_to_pg_type(str(ctype), cname)
                        null_exprs.append(f'NULL::{pg_type} AS "{cname}"')
                    conn.execute(_text(f'CREATE SCHEMA IF NOT EXISTS "{pschema}"'))
                    conn.execute(
                        _text(f'DROP VIEW IF EXISTS "{pschema}"."{phys_table}" CASCADE')
                    )
                    conn.execute(
                        _text(
                            f'CREATE VIEW "{pschema}"."{phys_table}" AS '
                            f"SELECT {', '.join(null_exprs)} LIMIT 0"
                        )
                    )
                else:
                    # For FULL/INCREMENTAL models, create empty physical table
                    col_defs = []
                    for cname, ctype in cols.items():
                        pg_type = _sqlglot_to_pg_type(str(ctype), cname)
                        col_defs.append(f'"{cname}" {pg_type}')
                    conn.execute(_text(f'CREATE SCHEMA IF NOT EXISTS "{pschema}"'))
                    conn.execute(
                        _text(
                            f'CREATE TABLE IF NOT EXISTS "{pschema}"."{phys_table}" '
                            f"({', '.join(col_defs)})"
                        )
                    )

                # Create the logical-name view
                conn.execute(_text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
                conn.execute(
                    _text(
                        f'CREATE OR REPLACE VIEW "{schema}"."{model_name}" AS '
                        f'SELECT * FROM "{pschema}"."{phys_table}"'
                    )
                )
                created += 1
        except Exception:  # noqa: BLE001
            logger.debug("Failed to materialize %s.%s", schema, model_name)

    return created


def materialize_external_tables() -> int:
    """Create empty tables for external (non-SQLMesh) tables referenced by models.

    Reads ``external_models/*.yaml`` definitions and creates empty tables
    for any that don't already exist.  These tables (e.g. ``public.parcels``)
    are created by dlt/DuckDB pipelines and may not be present.

    Returns the number of tables created.
    """
    import yaml
    from sqlalchemy import text as _text

    ext_dir = settings.BASE_DIR / "brewgis" / "sqlmesh" / "external_models"
    if not ext_dir.is_dir():
        return 0

    engine = get_engine()
    created = 0

    for yaml_path in sorted(ext_dir.glob("*.yaml")):
        with open(yaml_path) as f:
            definitions = yaml.safe_load(f) or []
        for entry in definitions:
            name: str = entry.get("name", "")
            columns: list = entry.get("columns", [])
            if not name or not columns:
                continue
            parts = name.split(".")
            if len(parts) != 2:
                continue
            schema, table = parts

            col_defs = []
            if isinstance(columns, dict):
                # Dict format: {name: type, ...}
                for cname, ctype in columns.items():
                    pg_type = _sqlglot_to_pg_type(str(ctype), str(cname))
                    col_defs.append(f'"{cname}" {pg_type}')
            elif isinstance(columns, list):
                # List format: [{name: ..., type: ...}, ...]
                for col_entry in columns:
                    if not isinstance(col_entry, dict):
                        continue
                    cname = col_entry.get("name", "") or next(
                        iter(col_entry.keys()), ""
                    )
                    ctype = col_entry.get("type", "") or next(
                        iter(col_entry.values()), ""
                    )
                    if not cname or not ctype:
                        continue
                    pg_type = _sqlglot_to_pg_type(str(ctype), str(cname))
                    col_defs.append(f'"{cname}" {pg_type}')

            if not col_defs:
                continue

            try:
                with engine.connect() as conn, conn.begin():
                    row = conn.execute(
                        _text(
                            "SELECT 1 FROM pg_tables "
                            "WHERE schemaname = :s AND tablename = :t"
                        ),
                        {"s": schema, "t": table},
                    ).fetchone()
                    if row:
                        created += 1  # already exists
                    else:
                        conn.execute(_text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
                        conn.execute(
                            _text(
                                f'CREATE TABLE IF NOT EXISTS "{schema}"."{table}" '
                                f"({', '.join(col_defs)})"
                            )
                        )
                        created += 1

                    # Some models reference dot-named external tables as a
                    # single identifier (e.g. "public.parcels" instead of
                    # "public"."parcels") via @VAR interpolation.
                    single_name = f"{schema}.{table}"
                    row_single = conn.execute(
                        _text("SELECT 1 FROM pg_tables WHERE tablename = :t"),
                        {"t": single_name},
                    ).fetchone()
                    if not row_single:
                        conn.execute(
                            _text(
                                f"CREATE TABLE IF NOT EXISTS "
                                f'"{single_name}" ({", ".join(col_defs)})'
                            )
                        )
            except Exception:  # noqa: BLE001
                logger.debug("Failed to create external table %s.%s", schema, table)

    return created


# ── EXPLAIN runner ────────────────────────────────────────────────────────


_SQLMESH_CONTEXT: object | None = None


def _get_sqlmesh_context():
    """Lazy-loaded, cached SQLMesh Context singleton."""
    global _SQLMESH_CONTEXT
    if _SQLMESH_CONTEXT is None:
        import sys as _sys

        _sys.path.insert(0, str(settings.BASE_DIR / "brewgis" / "sqlmesh"))
        from sqlmesh.core.context import Context

        _SQLMESH_CONTEXT = Context(
            paths=str(settings.BASE_DIR / "brewgis" / "sqlmesh"),
            gateway="postgis",
        )
    return _SQLMESH_CONTEXT


def run_explain(
    model_info: ModelInfo,
) -> tuple[dict | None, str | None]:
    """Run EXPLAIN (COSTS, VERBOSE, FORMAT JSON) on a model's rendered query."""
    model_key = _qualify(model_info)
    ctx = _get_sqlmesh_context()
    sqlmodel = ctx.models.get(model_key)
    if sqlmodel is None:
        return None, f"Model {model_key} not found in SQLMesh context"

    try:
        if model_info.kind == "VIEW":
            rendered = sqlmodel.render_query()
            if rendered is None:
                return None, "render_query returned None for VIEW model"
            # For views, EXPLAIN the view's own query (it's already a SELECT)
            explain_sql = (
                f"EXPLAIN (COSTS true, VERBOSE true, FORMAT JSON)"
                f" {rendered.sql(dialect='postgres')}"
            )
        else:
            rendered = sqlmodel.render_query()
            if rendered is None:
                return None, "render_query returned None"
            explain_sql = (
                f"EXPLAIN (COSTS true, VERBOSE true, FORMAT JSON)"
                f" {rendered.sql(dialect='postgres')}"
            )
    except Exception as exc:
        return None, f"render_query failed: {exc}"

    engine = get_engine()
    try:
        with engine.connect() as conn, conn.begin():
            result = conn.execute(text(explain_sql))
            row = result.fetchone()
    except ProgrammingError as exc:
        err_msg = str(exc)
        if "does not exist" in err_msg:
            return None, err_msg  # blocked by unmet dependency
        return None, f"EXPLAIN SQL error: {exc}"
    except Exception as exc:
        return None, f"EXPLAIN failed: {exc}"

    if row and row[0]:
        return row[0], None
    return None, "No plan returned"


def _qualify(info: ModelInfo) -> str:
    """Return the SQLMesh-quoted FQN for a model."""
    parts = info.qualified.replace("-", "_").split(".")
    return ".".join(f'"{p}"' for p in parts)


# ── Plan analyzer ─────────────────────────────────────────────────────────


def parse_plan_tree(node: dict) -> PlanNode:
    """Recursively parse a PostgreSQL plan tree JSON node."""
    subplans = [
        parse_plan_tree(child)
        for key in ("Plans", "Subplans")
        for child in (node.get(key) or ())
    ]
    return PlanNode(
        node_type=node.get("Node Type", "?") or "?",
        relation_name=node.get("Relation Name"),
        alias=node.get("Alias"),
        startup_cost=float(node.get("Startup Cost", 0)),
        total_cost=float(node.get("Total Cost", 0)),
        plan_rows=float(node.get("Plan Rows", 0)),
        join_type=node.get("Join Type"),
        index_name=node.get("Index Name"),
        subplans=subplans,
    )


def analyze_plan(plan_json: dict | list) -> PlanAnalysis:
    """Extract diagnostics from an EXPLAIN JSON plan."""
    if isinstance(plan_json, list):
        # PostgreSQL may return a list of plan statements
        plan_json = plan_json[0] if plan_json else plan_json
    root = parse_plan_tree(plan_json.get("Plan", plan_json))

    seq_scans: list[str] = []
    nested_loops = 0
    max_depth = 0
    node_count = 0

    queue: list[tuple[PlanNode, int]] = [(root, 1)]
    while queue:
        node, depth = queue.pop(0)
        node_count += 1
        max_depth = max(max_depth, depth)
        if "Seq Scan" in node.node_type and node.relation_name is not None:
            if node.plan_rows > 10_000:
                seq_scans.append(
                    f"{node.relation_name} (est. {int(node.plan_rows):,} rows)"
                )
        if "Nested Loop" in node.node_type:
            nested_loops += 1
        for sub in node.subplans:
            queue.append((sub, depth + 1))

    return PlanAnalysis(
        total_cost=root.total_cost,
        startup_cost=root.startup_cost,
        plan_rows=root.plan_rows,
        node_count=node_count,
        max_depth=max_depth,
        seq_scans=seq_scans,
        nested_loops=nested_loops,
        plan_tree=root,
    )


# ── Report formatter ──────────────────────────────────────────────────────


def _color(value: float, low: float = 1000, high: float = 100_000) -> str:
    if value < low:
        return f"\033[92m{value:,.2f}\033[0m"
    if value < high:
        return f"\033[93m{value:,.2f}\033[0m"
    return f"\033[91m{value:,.2f}\033[0m"


def _warning(msg: str) -> str:
    return f"\033[93m⚠ {msg}\033[0m"


def _error(msg: str) -> str:
    return f"\033[91m✗ {msg}\033[0m"


def _bold(msg: str) -> str:
    return f"\033[1m{msg}\033[0m"


def _render_plan(node: PlanNode, max_depth: int = 5, indent: int = 0) -> str:
    """Format plan tree up to *max_depth* levels."""
    if indent >= max_depth:
        return ""
    prefix = "  " * indent + "└─ "
    parts = [f"{prefix}{node.node_type}"]
    if node.relation_name:
        parts.append(f"on {node.relation_name}")
    if node.join_type:
        parts.append(f"({node.join_type})")
    parts.append(f"cost={_color(node.total_cost)} rows={int(node.plan_rows):,}")
    lines = [" ".join(parts)]
    for sub in node.subplans:
        sub_lines = _render_plan(sub, max_depth, indent + 1)
        if sub_lines:
            lines.append(sub_lines)
    return "\n".join(lines)


def emit_report(
    ordered_models: list[ModelInfo],
    analysis: dict[str, PlanAnalysis | None],
    errors: dict[str, str],
    terminal_refs: set[str],
    max_depth: int = 5,
    out: IO = sys.stdout,
) -> None:
    """Write the diagnostic report."""
    sep = "═" * 60
    analyzed_count = sum(1 for a in analysis.values() if a is not None)
    skipped_count = sum(1 for a in analysis.values() if a is None)
    blocked_count = sum(1 for e in errors.values() if "does not exist" in e)
    failed_count = len(errors) - blocked_count

    print(sep, file=out)
    print(_bold("═══ SQLMesh EXPLAIN Audit ═══"), file=out)
    print(
        f"Models: {len(ordered_models)} total, "
        f"{analyzed_count} analyzed, "
        f"{skipped_count} skipped, "
        f"{blocked_count} blocked (pipe not applied), "
        f"{failed_count} failed",
        file=out,
    )
    if terminal_refs:
        print(
            f"External refs: {', '.join(sorted(terminal_refs))}",
            file=out,
        )
    print(sep, file=out)

    total_cost = 0.0
    total_seq_scans = 0
    total_nested_loops = 0
    most_expensive: tuple[str, float] = ("", 0.0)

    for info in ordered_models:
        print(file=out)

        err = errors.get(info.qualified)
        if err:
            if "does not exist" in err:
                label = _warning("BLOCKED — upstream table not materialized")
            elif any(
                kw in err for kw in ("InvalidTextRepresentation", "DatatypeMismatch")
            ):
                label = _warning("BLOCKED — pipeline data quality issue")
            else:
                label = _error(err)
            print(_bold(f"── {info.qualified} ({info.kind})"), file=out)
            print(f"   {label}", file=out)
            continue

        pa = analysis.get(info.qualified)
        if pa is None:
            print(_bold(f"── {info.qualified} ({info.kind})"), file=out)
            print(f"   {_warning('Skipped (no plan returned)')}", file=out)
            continue

        total_cost += pa.total_cost
        total_seq_scans += len(pa.seq_scans)
        total_nested_loops += pa.nested_loops
        if pa.total_cost > most_expensive[1]:
            most_expensive = (info.qualified, pa.total_cost)

        print(_bold(f"── {info.qualified} ({info.kind})"), file=out)
        print(f"   Estimated cost: {_color(pa.total_cost)}", file=out)
        for scan in pa.seq_scans:
            print(f"   {_warning(f'Seq Scan: {scan}')}", file=out)
        if pa.nested_loops > 0:
            print(
                f"   {_warning(f'Nested Loop join: {pa.nested_loops} occurrence(s)')}",
                file=out,
            )
        print(
            f"   Plan ({pa.node_count} nodes, depth {pa.max_depth}):",
            file=out,
        )
        if pa.plan_tree:
            plan_text = _render_plan(pa.plan_tree, max_depth, indent=1)
            for line in plan_text.split("\n"):
                print(f"     {line.strip()}", file=out)

    non_skipped = sum(1 for a in analysis.values() if a is not None)
    print(file=out)
    print("─" * 60, file=out)
    print(_bold("Summary"), file=out)
    print("─" * 60, file=out)
    print(
        f"  Total estimated cost:              {_color(total_cost)}",
        file=out,
    )
    print(f"  Seq scans (large tables):          {total_seq_scans}", file=out)
    print(
        f"  Nested loop joins:                 {total_nested_loops}",
        file=out,
    )
    print(f"  Models analyzed:                   {non_skipped}", file=out)
    blocked_in_summary = sum(1 for e in errors.values() if "does not exist" in e)
    if blocked_in_summary:
        print(
            f"  Models blocked (unmaterialized):    {blocked_in_summary}",
            file=out,
        )
    if most_expensive[0]:
        print(
            f"  Most expensive:                    {most_expensive[0]} "
            f"({most_expensive[1]:,.2f})",
            file=out,
        )
    print(sep, file=out)


# ── Command ───────────────────────────────────────────────────────────────


class Command(BaseCommand):
    help = "Run EXPLAIN audit on SQLMesh models for query plan diagnostics"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--models",
            nargs="*",
            default=None,
            help=(
                "Specific model short names to audit (default: all comparison/ models)"
            ),
        )
        parser.add_argument(
            "--max-depth",
            type=int,
            default=0,
            help="Limit plan tree depth in report (0=full)",
        )
        parser.add_argument(
            "--materialize-empty",
            action="store_true",
            default=False,
            help="Create empty physical tables + views for all models (no data loaded)",
        )

    def handle(self, **options: object) -> str | None:
        model_names: list[str] | None = options.get("models")  # type: ignore[assignment]
        max_depth: int = options.get("max-depth") or 0  # type: ignore[assignment]
        self._materialize_empty: bool = options.get("materialize_empty", False)  # type: ignore[assignment]
        if max_depth <= 0:
            max_depth = 5
        try:
            self._run_audit(model_names, max_depth)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Audit crashed: {exc}"))
        self.stdout.write("\nAudit complete — always exits 0 (diagnostic tool).")

    def _run_audit(
        self,
        model_names: list[str] | None,
        max_depth: int,
    ) -> None:
        self.stdout.write("Loading SQLMesh context ... ", ending="")
        self.stdout.flush()
        models = discover_models_from_sqlmesh()
        self.stdout.write(f"done ({len(models)} models)")

        # Create logical views for materialized SQLMesh snapshots
        n_views = ensure_logical_views(_get_sqlmesh_context())
        if n_views:
            self.stdout.write(
                self.style.SUCCESS(f"Created {n_views} logical views for EXPLAIN")
            )

        # If --materialize-empty, create empty tables for all missing models
        if getattr(self, "_materialize_empty", False):
            n_empty = materialize_empty_tables(_get_sqlmesh_context())
            if n_empty:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Created {n_empty} empty tables + views (no data)"
                    )
                )
            n_ext = materialize_external_tables()
            if n_ext:
                self.stdout.write(
                    self.style.SUCCESS(f"Created {n_ext} external placeholder tables")
                )

        if not models:
            self.stdout.write(self.style.ERROR("No SQLMesh models discovered."))
            return

        if model_names:
            seeds: set[str] = set()
            for short_name in model_names:
                found = False
                for qname in models:
                    if qname.endswith(f".{short_name}"):
                        seeds.add(qname)
                        found = True
                        break
                if not found:
                    self.stdout.write(
                        self.style.WARNING(f"Model '{short_name}' not found; skipping.")
                    )
        else:
            seeds = {q for q in models if q.startswith("brewgis.comparison.")}

        if not seeds:
            self.stdout.write(self.style.ERROR("No seed models to audit."))
            return

        ordered = topology_order(models, seeds)
        terminal_refs = find_terminal_refs(models)

        analysis: dict[str, PlanAnalysis | None] = {}
        errors: dict[str, str] = {}

        for info in ordered:
            self.stdout.write(f"EXPLAIN {info.qualified} ... ", ending="")
            self.stdout.flush()

            if info.schema in ("staging", "seeds", "tests"):
                analysis[info.qualified] = None
                self.stdout.write(self.style.WARNING("skip (staging/seed — DuckDB)"))
                continue

            if info.error:
                errors[info.qualified] = info.error
                self.stdout.write(self.style.WARNING("skip (parse error)"))
                continue

            try:
                plan_json, err = run_explain(info)
                if err:
                    errors[info.qualified] = err
                    self.stdout.write(self.style.ERROR("FAIL"))
                    self.stdout.write(f"  {err}")
                    continue
            except Exception as exc:
                errors[info.qualified] = str(exc)
                self.stdout.write(self.style.ERROR("FAIL"))
                self.stdout.write(f"  {exc}")
                continue

            if plan_json is None:
                analysis[info.qualified] = None
                self.stdout.write(self.style.WARNING("skip (no plan)"))
                continue

            try:
                pa = analyze_plan(plan_json)
                analysis[info.qualified] = pa
                self.stdout.write(
                    f"done ({_color(pa.total_cost)} cost, {pa.node_count} nodes)"
                )
            except Exception as exc:
                errors[info.qualified] = f"plan analysis failed: {exc}"
                self.stdout.write(self.style.ERROR("FAIL"))
                self.stdout.write(f"  {exc}")

        emit_report(ordered, analysis, errors, terminal_refs, max_depth)
