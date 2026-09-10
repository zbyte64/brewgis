"""Discovery of sqlmesh-managed tables/views available for import.

SQLMesh's gateway-managed virtual layer exposes each model as a queryable
view named ``<schema>.<table>`` where *schema* is the model's schema segment
(e.g. ``analysis.core_end_state``). Physical, fingerprinted tables live in
``sqlmesh__<schema>`` and are never meant to be queried directly, so this
module only enumerates the virtual-layer schemas.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import connection

from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

_EXCLUDED_SCHEMAS = {"public", "information_schema", "sqlmesh_state"}

_POLYGON_TYPES = {"polygon", "multipolygon"}
_LINE_TYPES = {"linestring", "multilinestring"}


@dataclass(frozen=True)
class SqlmeshTableInfo:
    """One importable sqlmesh-managed table or view."""

    schema: str
    table: str
    has_geometry: bool
    geometry_type: str | None

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.table}"


def _is_excluded_schema(schema: str) -> bool:
    return schema in _EXCLUDED_SCHEMAS or schema.startswith(("pg_", "sqlmesh__"))


def list_sqlmesh_tables() -> list[SqlmeshTableInfo]:
    """Return all tables/views in sqlmesh-managed (virtual-layer) schemas.

    Ordered by schema, then table name, with geometry-bearing tables first
    within each schema so they surface at the top of import pickers.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT t.table_schema, t.table_name
            FROM information_schema.tables t
            WHERE t.table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY t.table_schema, t.table_name
            """
        )
        rows = cursor.fetchall()

        cursor.execute(
            "SELECT f_table_schema, f_table_name, type FROM geometry_columns"
        )
        geometry_rows = cursor.fetchall()

    geometry_by_table = {
        (schema, table): geom_type for schema, table, geom_type in geometry_rows
    }

    results = []
    for schema, table in rows:
        if _is_excluded_schema(schema):
            continue
        raw_geom_type = geometry_by_table.get((schema, table))
        has_geometry = raw_geom_type is not None
        geometry_type = None
        if raw_geom_type:
            lowered = raw_geom_type.lower()
            if lowered in _POLYGON_TYPES:
                geometry_type = "fill"
            elif lowered in _LINE_TYPES:
                geometry_type = "line"
            else:
                geometry_type = "circle"
        results.append(
            SqlmeshTableInfo(
                schema=schema,
                table=table,
                has_geometry=has_geometry,
                geometry_type=geometry_type,
            )
        )

    results.sort(key=lambda info: (info.schema, not info.has_geometry, info.table))
    return results


def _required_base_canvas_columns() -> frozenset[str]:
    """Columns a table must have to stand in as a workspace's base canvas.

    Requires every column in ``BaseCanvasSchema.COLUMN_NAMES`` (not just the
    non-nullable subset) — downstream consumers (painting, canvas views,
    symbology) read a fixed set of column names, so a table with a varied
    subset would break them at query time rather than at import time.
    """
    return frozenset(BaseCanvasSchema.COLUMN_NAMES)


def list_base_canvas_candidates() -> list[SqlmeshTableInfo]:
    """Return sqlmesh tables/views that contain every required base-canvas column.

    A table qualifies as a base canvas candidate when it already has all of
    ``BaseCanvasSchema.COLUMN_NAMES`` (e.g. sqlmesh's own
    ``base_canvas_reconciled`` models) — no further ETL/allocation is needed,
    the table can be adopted as-is.
    """
    required = _required_base_canvas_columns()
    if not required:
        return []

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_schema, table_name, column_name "
            "FROM information_schema.columns"
        )
        rows = cursor.fetchall()

    columns_by_table: dict[tuple[str, str], set[str]] = {}
    for schema, table, column in rows:
        columns_by_table.setdefault((schema, table), set()).add(column)

    return [
        info
        for info in list_sqlmesh_tables()
        if required.issubset(columns_by_table.get((info.schema, info.table), set()))
    ]
