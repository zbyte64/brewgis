"""Canvas SQL view manager — creates/replaces/drops per-scenario canvas views.

Each scenario gets a SQL view ``scenario_{slug}_canvas`` that LEFT JOINs the
base canvas table with pivoted :class:`~brewgis.workspace.models.PaintedCanvas`
overrides, implementing copy-on-write for tile server consumption.

The view uses ``COALESCE(painted, base)`` on every paintable column and
includes an ``uf_is_painted`` boolean flag.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import ProgrammingError
from django.db import connection
from django.db import transaction

from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

if TYPE_CHECKING:
    from brewgis.workspace.models import Scenario

# Paintable columns — sourced from the canonical BaseCanvasSchema.
PAINTABLE_COLUMNS: frozenset[str] = BaseCanvasSchema.PAINTABLE_COLUMNS

# Paintable columns whose override is text (not numeric) — stored in
# PaintedCanvas.painted_text_value instead of painted_value.
TEXT_COLUMNS: frozenset[str] = BaseCanvasSchema.TEXT_COLUMNS


def build_paintable_column_meta() -> list[dict[str, str]]:
    """Build ``{name, label}`` entries for every numeric paintable column.

    Shared by the paint toolbar's Direct Paint dropdown and the
    feature-inspect panel so both surfaces render the same human-readable
    labels. Excludes text-valued columns (``TEXT_COLUMNS``) since that path
    only ever coerces values to ``float``.
    """
    meta: list[dict[str, str]] = []
    for col_name in sorted(PAINTABLE_COLUMNS - TEXT_COLUMNS):
        col_def = BaseCanvasSchema.get(col_name)
        meta.append({"name": col_name, "label": col_def.label if col_def else col_name})
    return meta


_COLUMNS_DISCOVERY_SQL = """
SELECT column_name
FROM information_schema.columns
WHERE table_schema = %s AND table_name = %s
ORDER BY ordinal_position
"""


def _qi(name: str) -> str:
    """Quote a SQL identifier for safe use in dynamic DDL.

    Handles ``schema.table`` by quoting each part independently.
    """
    parts = name.split(".")
    return ".".join(f'"{p}"' for p in parts)


def _fetch_base_columns(base_table: str) -> tuple[str, str, list[str]]:
    """Return ``(schema, table, column_names)`` for *base_table*."""
    parts = base_table.split(".")
    if len(parts) == 2:
        schema, table = parts
    else:
        schema, table = "public", parts[0]

    with connection.cursor() as cursor:
        cursor.execute(_COLUMNS_DISCOVERY_SQL, [schema, table])
        cols: list[str] = [row[0] for row in cursor.fetchall()]

    return schema, table, cols


def _static_columns(all_cols: list[str]) -> list[str]:
    """Return columns passed through verbatim (not painted)."""
    paintable_set = set(PAINTABLE_COLUMNS)
    return [c for c in all_cols if c not in paintable_set and c != "geometry"]


def _build_create_view_sql(
    *,
    view_schema: str,
    view_name: str,
    base_schema: str,
    base_table_name: str,
    all_columns: list[str],
    scenario_id: int,
) -> str:
    """Generate the ``CREATE OR REPLACE VIEW`` statement."""
    # Iterate `all_columns` (a stable, DB-ordered list) rather than the
    # `PAINTABLE_COLUMNS` frozenset directly — Python's per-process string
    # hash randomization makes frozenset iteration order vary from run to
    # run, so the previous `[c for c in PAINTABLE_COLUMNS if ...]` produced
    # a different SELECT column order on every process restart. Postgres'
    # `CREATE OR REPLACE VIEW` cannot rename/reorder existing columns, so
    # the very next refresh_canvas_view() after a restart would 500.
    paintable_in_table = [c for c in all_columns if c in PAINTABLE_COLUMNS]

    q_view = _qi(f"{view_schema}.{view_name}")
    q_base = _qi(f"{base_schema}.{base_table_name}")

    select_parts: list[str] = [
        "bc.id",
        "bc.geometry",
    ]

    # Static (non-paintable, non-geometry) columns
    statics = [c for c in _static_columns(all_columns) if c != "id"]
    select_parts.extend(f"bc.{c}" for c in statics)

    # Painted columns with COALESCE
    select_parts.extend(
        f"COALESCE(pc.{col}, bc.{col}) AS {col}" for col in paintable_in_table
    )

    # uf_is_painted flag
    select_parts.append("(pc._feature_id IS NOT NULL) AS uf_is_painted")
    select_clause = ",\n    ".join(select_parts)

    # Pivot subquery — text columns (e.g. built_form_key) pivot from
    # painted_text_value; every other paintable column pivots from the
    # numeric painted_value.
    pivot_cases = [
        f"        MAX(CASE WHEN column_name = '{col}' THEN "
        f"{'painted_text_value' if col in TEXT_COLUMNS else 'painted_value'} "
        f"END) AS {col}"
        for col in paintable_in_table
    ]
    pivot_clause = ",\n".join(pivot_cases)

    return f"""CREATE OR REPLACE VIEW {q_view} AS
SELECT
    {select_clause}
FROM {q_base} bc
LEFT JOIN (
    SELECT
        feature_id AS _feature_id,
{pivot_clause}
    FROM workspace_paintedcanvas
    WHERE scenario_id = {scenario_id}
    GROUP BY feature_id
) pc ON CAST(bc.id AS text) = pc._feature_id
"""


def create_canvas_view(scenario: Scenario, base_table: str) -> str:
    """Create a canvas view for *scenario* over *base_table*.

    The view is named ``scenario_{slug}_canvas`` and lives in the
    scenario's target schema (``scenario_{slug}``).

    Returns the fully-qualified view name (``schema.view_name``).
    """
    view_name = f"scenario_{scenario.slug}_canvas"
    view_schema = scenario.target_schema

    schema, table_name, all_cols = _fetch_base_columns(base_table)

    sql = _build_create_view_sql(
        view_schema=view_schema,
        view_name=view_name,
        base_schema=schema,
        base_table_name=table_name,
        all_columns=all_cols,
        scenario_id=scenario.pk,
    )

    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {_qi(view_schema)}")
            cursor.execute(sql)
    except ProgrammingError as exc:
        if "cannot change name of view column" not in str(exc):
            raise
        # The existing view's column layout was baked in under a since-
        # changed column order (e.g. a view created before the SELECT
        # list became deterministic) — CREATE OR REPLACE can only add
        # trailing columns, not rename/reorder existing ones, so fall
        # back to a clean drop + recreate.
        q_view = _qi(f"{view_schema}.{view_name}")
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f"DROP VIEW IF EXISTS {q_view} CASCADE")
            cursor.execute(sql)

    return f"{view_schema}.{view_name}"


def refresh_canvas_view(scenario: Scenario, base_table: str) -> str:
    """Recreate the canvas view for *scenario* — after paint operations.

    Same as :func:`create_canvas_view` because we use ``CREATE OR REPLACE VIEW``.
    """
    return create_canvas_view(scenario, base_table)


def drop_canvas_view(scenario: Scenario) -> None:
    """Drop the canvas view for *scenario* (if it exists)."""
    view_name = f"scenario_{scenario.slug}_canvas"
    view_schema = scenario.target_schema
    q_view = _qi(f"{view_schema}.{view_name}")

    with connection.cursor() as cursor:
        cursor.execute(f"DROP VIEW IF EXISTS {q_view} CASCADE")
