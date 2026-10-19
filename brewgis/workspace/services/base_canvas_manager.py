"""Base Canvas Table Manager — lifecycle management for the base canvas table.

The base canvas table (``public.base_canvas``) is a hand-crafted PostGIS table
that stores the "existing conditions" spatial layer. It is **not** a Django
model — it is managed via raw SQL DDL through this service.

Responsibilities:
    - Create the table and indexes (idempotent)
    - Check existence
    - Validate schema vs expected columns
    - Drop the table (for teardown / reset)
"""

from __future__ import annotations

from django.db import connection

from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

DEFAULT_BASE_CANVAS_TABLE = "public.base_canvas"


class BaseCanvasManager:
    """Idempotent lifecycle manager for ``public.base_canvas``."""

    DEFAULT_TABLE = DEFAULT_BASE_CANVAS_TABLE

    MAX_PARTS = 2

    @classmethod
    def _parse_table(cls, target_table: str | None = None) -> tuple[str, str]:
        """Split ``schema.table`` into (schema, table), defaulting schema to ``'public'``.

        When *target_table* is ``None``, ``cls.DEFAULT_TABLE`` is used.
        """
        table = cls.DEFAULT_TABLE if target_table is None else target_table
        parts = table.split(".")
        if len(parts) == cls.MAX_PARTS:
            return parts[0], parts[1]
        return "public", parts[0]

    @classmethod
    def table_exists(cls, target_table: str | None = None) -> bool:
        """Check if the target table exists in the database.

        Args:
            target_table: Fully qualified target table name (default ``public.base_canvas``).
        """
        schema, table = cls._parse_table(target_table)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s
                )
                """,
                [schema, table],
            )
            return bool(cursor.fetchone()[0])

    @classmethod
    def validate_schema(cls, target_table: str | None = None) -> list[str]:
        """Diff expected vs actual columns; return missing column names.

        Returns an empty list when all expected columns are present.

        Args:
            target_table: Fully qualified target table name (default ``public.base_canvas``).
        """
        if not cls.table_exists(target_table):
            return list(BaseCanvasSchema.COLUMN_NAMES)

        schema, table = cls._parse_table(target_table)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                [schema, table],
            )
            actual_cols = {row[0] for row in cursor.fetchall()}

        expected_cols = set(BaseCanvasSchema.COLUMN_NAMES)
        missing = expected_cols - actual_cols
        return sorted(missing)

    @classmethod
    def drop_table(cls, target_table: str | None = None) -> None:
        """Drop the target table if it exists (cascades to views).

        Args:
            target_table: Fully qualified target table name (default ``public.base_canvas``).
        """
        schema, table = cls._parse_table(target_table)
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {schema}.{table} CASCADE")
