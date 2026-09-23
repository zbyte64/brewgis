"""Canvas SQL view manager — builds the SELECT body for per-scenario canvas views.

Each ALTERNATIVE scenario gets a SQL view ``scenario_{slug}_canvas`` that
UNIONs the base canvas table with the scenario's edited parcels
(:class:`~brewgis.workspace.models.ParcelGeometryEdit` — paint mode's grid and
merge results) and LEFT JOINs the result with the pivoted
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

# Django's table name for ParcelGeometryEdit — the edit rows the canvas view
# UNIONs in. Referenced from generated SQL, so Django never has to own the DDL.
GEOMETRY_EDIT_TABLE = "workspace_parcelgeometryedit"


def _qi(name: str) -> str:
    """Quote a SQL identifier for safe use in dynamic DDL.

    Handles ``schema.table`` by quoting each part independently.
    """
    parts = name.split(".")
    return ".".join(f'"{p}"' for p in parts)


def _split_base_table(base_table: str) -> tuple[str, str]:
    """Return ``(schema, table)`` for a ``schema.table`` (or bare ``table``)."""
    parts = base_table.split(".")
    if len(parts) == 2:
        return parts[0], parts[1]
    return "public", parts[0]


def _fetch_base_columns(base_table: str) -> tuple[str, str, list[str]]:
    """Return ``(schema, table, column_names)`` for *base_table*."""
    schema, table = _split_base_table(base_table)

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

    The body is the base's rows minus every parcel some
    :class:`~brewgis.workspace.models.ParcelGeometryEdit` replaces (grid or
    merge), UNION ALL'd with those edits' own rows, and the paint pivot applied
    once over the union:

    * ``claims`` maps each parcel a geometry edit replaces (its
      ``source_parcel_ids``) to the newest edit claiming it. A base row is
      dropped whenever anything claims its id. An edit row is dropped only when
      a *newer* edit claims its id, which is what makes edits compose — gridding
      an already-gridded cell drops that cell's row and adds its grandchildren —
      while leaving a merge's own row visible: a merge's survivor is one of its
      own sources (it is the parcel the merged geometry keeps the id of), so a
      plain "drop every claimed id" rule would filter the result out along with
      the rows it replaces.
    * ``edit_template`` borrows one base row's composite type so
      ``jsonb_populate_record`` can cast an edit's ``values`` object to the
      base's *exact* column types — including ``parcel_id``, which is the
      parcel key and not uniformly typed (the published ``public.base_canvas``
      keys parcels on ``BIGINT``, a SQLMesh base on the APN *string*). Casting
      each column to a type this module guesses instead (``BaseCanvasSchema``'s
      declared types) does not survive contact with real bases:
      ``is_residential`` is ``integer`` in ``fresno.base_canvas_reconciled`` but
      ``BOOLEAN`` in the schema, which Postgres rejects outright as a UNION type
      mismatch, and a ``bigint`` parcel key receiving grid's negative-integer
      *string* ids fails the same way. The template CTE keeps every column's
      type identical to the base's and costs one ``LIMIT 1`` scan; ``LEFT JOIN``
      (not ``CROSS JOIN``) keeps edited rows visible when the base is empty, the
      record type coming from the joined column's declared type either way.

    The edited branch's geometry comes from the edit row itself and is the one
    column whose declared type can differ from the base's: Postgres resolves the
    union of ``geometry`` with ``geometry(MultiPolygon, 4326)`` to plain
    ``geometry``, which no consumer of the view depends on.

    ``_is_edited`` feeds only ``uf_is_painted`` — an edited parcel is as
    "painted" as a column-painted one — and is not otherwise emitted.
    """
    # Iterate `all_columns` (a stable, DB-ordered list) rather than the
    # `PAINTABLE_COLUMNS` frozenset directly — Python's per-process string
    # hash randomization makes frozenset iteration order vary from run to
    # run, so the previous `[c for c in PAINTABLE_COLUMNS if ...]` produced
    # a different SELECT column order on every process restart.
    paintable_in_table = [c for c in all_columns if c in PAINTABLE_COLUMNS]

    # Static (non-paintable, non-geometry) columns
    statics = [c for c in _static_columns(all_columns) if c != "parcel_id"]

    # Every column both union branches carry, in the base table's own order:
    # the edited branch reads all of them out of ParcelGeometryEdit.values.
    value_columns = [c for c in all_columns if c not in ("parcel_id", "geometry")]

    select_parts: list[str] = [
        "src.parcel_id",
        "src.geometry",
    ]
    select_parts.extend(f"src.{c}" for c in statics)
    select_parts.extend(
        f"COALESCE(pc.{col}, src.{col}) AS {col}" for col in paintable_in_table
    )
    select_parts.append(
        "(pc._feature_id IS NOT NULL OR src._is_edited) AS uf_is_painted"
    )
    select_clause = ",\n    ".join(select_parts)

    base_values = ",\n           ".join(f"bc.{c}" for c in value_columns)
    edited_values = ",\n           ".join(f"(rec).{c}" for c in value_columns)

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

    return f"""WITH claims AS (
    SELECT s.src_id AS parcel_id, MAX(e.id) AS claimant_id
    FROM {GEOMETRY_EDIT_TABLE} e,
         LATERAL jsonb_array_elements_text(e.source_parcel_ids::jsonb) AS s(src_id)
    WHERE e.scenario_id = {scenario_id} AND s.src_id IS NOT NULL
    GROUP BY s.src_id
),
edit_template AS MATERIALIZED (
    SELECT b FROM {base_ref} b LIMIT 1
)
SELECT
    {select_clause}
FROM (
    SELECT bc.parcel_id, bc.geometry,
           {base_values}, FALSE AS _is_edited
    FROM {base_ref} bc
    WHERE CAST(bc.parcel_id AS text) NOT IN (SELECT parcel_id FROM claims)
    UNION ALL
    SELECT (rec).parcel_id, e.geometry,
           {edited_values}, TRUE AS _is_edited
    FROM {GEOMETRY_EDIT_TABLE} e
    LEFT JOIN claims c ON c.parcel_id = e.parcel_id
    LEFT JOIN edit_template t ON TRUE
    CROSS JOIN LATERAL jsonb_populate_record(
        t.b, e.values::jsonb || jsonb_build_object('parcel_id', e.parcel_id)
    ) rec
    WHERE e.scenario_id = {scenario_id}
      AND (c.claimant_id IS NULL OR c.claimant_id <= e.id)
) src
LEFT JOIN (
    SELECT
        feature_id AS _feature_id,
{pivot_clause}
    FROM workspace_paintedcanvas
    WHERE scenario_id = {scenario_id}
    GROUP BY feature_id
) pc ON CAST(src.parcel_id AS text) = pc._feature_id
"""
