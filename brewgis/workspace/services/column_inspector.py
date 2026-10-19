"""Column inspector — discovers PostGIS table columns and detects ID columns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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


def _quote_identifier(name: str) -> str:
    """Quote a PostgreSQL identifier (schema.table)."""
    parts = name.split(".")
    return ".".join(f'"{part}"' for part in parts)


def get_table_schema(schema: str, table_name: str) -> list[dict[str, Any]]:
    """Return column metadata for a PostGIS table.

    Returns a list of dicts with keys: name, data_type, nullable, sample_values.
    Returns an empty list if the table does not exist.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            [schema, table_name],
        )
        rows = cursor.fetchall()
        if not rows:
            return []

        columns: list[dict[str, Any]] = []
        for name, data_type, nullable in rows:
            col_info: dict[str, Any] = {
                "name": name,
                "data_type": data_type,
                "nullable": nullable == "YES",
                "sample_values": [],
            }
            # Fetch sample values for non-geometry columns
            if data_type not in ("USER-DEFINED", "geometry", "geography"):
                cursor.execute(
                    f"""
                    SELECT DISTINCT {_quote_identifier(name)}
                    FROM {_quote_identifier(f"{schema}.{table_name}")}
                    WHERE {_quote_identifier(name)} IS NOT NULL
                    LIMIT 5
                    """,
                )
                samples = cursor.fetchall()
                col_info["sample_values"] = [
                    row[0] for row in samples if row[0] is not None
                ]
            columns.append(col_info)
    return columns
