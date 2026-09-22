"""Canvas SQL view manager — builds the SELECT body for per-scenario canvas views.

Each ALTERNATIVE scenario gets a SQL view ``scenario_{slug}_canvas`` that
LEFT JOINs the base canvas table with pivoted
:class:`~brewgis.workspace.models.PaintedCanvas` overrides, implementing
copy-on-write for tile server consumption. The view uses
``COALESCE(painted, base)`` on every paintable column and includes an
``uf_is_painted`` boolean flag.

This module only *generates* that SELECT. SQLMesh owns the view: the
blueprinted ``models/scenarios/scenario_canvas.py`` model wraps the output of
:func:`build_canvas_view_select` in the ``kind VIEW`` DDL and creates the
scenario-named view itself, so a ``sqlmesh plan`` that rebuilds a base canvas
recreates the scenarios' canvas views as its downstreams instead of
CASCADE-dropping them. Django never issues the DDL (see
``brewgis.workspace.services.scenario_canvas``).
"""

from __future__ import annotations

from django.db import connection

from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

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


def build_canvas_view_select(
    *,
    base_ref: str,
    all_columns: list[str],
    scenario_id: int,
) -> str:
    """Generate the SELECT body of a scenario's canvas view.

    *base_ref* is the caller-supplied reference the view selects from, used
    verbatim: the SQLMesh model passes a bare model FQN
    (``brewgis.fresno.base_canvas_reconciled``), which SQLMesh
    snapshot-resolves when rendering the query — that is what ties the view's
    ``data_hash`` to the base layer's snapshot, and so makes the view get
    recreated when the base changes. For a base table outside SQLMesh the
    caller passes the raw ``schema.table``.
    """
    # Iterate `all_columns` (a stable, DB-ordered list) rather than the
    # `PAINTABLE_COLUMNS` frozenset directly — Python's per-process string
    # hash randomization makes frozenset iteration order vary from run to
    # run, so the previous `[c for c in PAINTABLE_COLUMNS if ...]` produced
    # a different SELECT column order on every process restart.
    paintable_in_table = [c for c in all_columns if c in PAINTABLE_COLUMNS]

    select_parts: list[str] = [
        "bc.parcel_id",
        "bc.geometry",
    ]

    # Static (non-paintable, non-geometry) columns
    statics = [c for c in _static_columns(all_columns) if c != "parcel_id"]
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

    return f"""SELECT
    {select_clause}
FROM {base_ref} bc
LEFT JOIN (
    SELECT
        feature_id AS _feature_id,
{pivot_clause}
    FROM workspace_paintedcanvas
    WHERE scenario_id = {scenario_id}
    GROUP BY feature_id
) pc ON CAST(bc.parcel_id AS text) = pc._feature_id
"""
