"""Column inspector — discovers PostGIS table columns and detects ID columns."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import connection


@dataclass
class TableColumnInfo:
    """Discovered metadata about an imported PostGIS table."""

    columns: dict[str, str]  # column_name -> pg_type
    id_column: str | None  # detected integer PK or ID-like column
    has_geom: bool
    has_built_form_key: bool
    has_intersection_density: bool
    has_land_development_category: bool


# Common ID column names, ordered by preference.
_ID_COLUMN_CANDIDATES = (
    "id",
    "gid",
    "fid",
    "objectid",
    "ogc_fid",
    "parcel_id",
)


def inspect_table(schema: str, table_name: str) -> TableColumnInfo | None:
    """Inspect a PostGIS table and return column metadata.

    Returns ``None`` if the table does not exist.
    """
    with connection.cursor() as cursor:
        # Check the table exists
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
            )
            """,
            [schema, table_name],
        )
        (exists,) = cursor.fetchone()
        if not exists:
            return None

        # Get column names and types
        cursor.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            [schema, table_name],
        )
        columns = dict(cursor.fetchall())

        # Detect ID column - look for an exact match in candidates first,
        # then fall back to the first INTEGER column that is a PK.
        id_column: str | None = None
        for candidate in _ID_COLUMN_CANDIDATES:
            if candidate in columns:
                id_column = candidate
                break

        if id_column is None:
            # Fallback: first INTEGER or BIGINT column that is a PK constraint
            cursor.execute(
                """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = %s
                    AND tc.table_name = %s
                    AND tc.constraint_type = 'PRIMARY KEY'
                    AND kcu.ordinal_position = 1
                """,
                [schema, table_name],
            )
            row = cursor.fetchone()
            if row:
                pk_col = row[0]
                if pk_col in columns and columns.get(pk_col, "").startswith(
                    ("integer", "bigint", "serial", "bigserial"),
                ):
                    id_column = pk_col

    lower_names = {name.lower() for name in columns}

    return TableColumnInfo(
        columns=columns,
        id_column=id_column,
        has_geom="geom" in lower_names or "geometry" in lower_names,
        has_built_form_key="built_form_key" in lower_names,
        has_intersection_density="intersection_density" in lower_names,
        has_land_development_category="land_development_category" in lower_names,
    )


def _quote_identifier(name: str) -> str:
    """Quote a PostgreSQL identifier (schema.table)."""
    parts = name.split(".")
    return ".".join(f'"{part}"' for part in parts)
