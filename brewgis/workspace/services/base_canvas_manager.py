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

    @classmethod
    def qualified_name(cls) -> str:
        """Return the fully-qualified table name."""
        return cls.DEFAULT_TABLE

    @classmethod
    def create_table(cls) -> None:
        """Create ``public.base_canvas`` and its indexes (idempotent).

        Uses ``CREATE TABLE IF NOT EXISTS`` so repeated calls are safe.
        Enables PostGIS extension if not already present.
        """
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            cursor.execute(BaseCanvasSchema.create_table_sql())
            for idx_sql in BaseCanvasSchema.create_indexes_sql():
                cursor.execute(idx_sql)

    @classmethod
    def table_exists(cls) -> bool:
        """Check if ``public.base_canvas`` exists in the database."""
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'base_canvas'
                )
                """
            )
            return bool(cursor.fetchone()[0])

    @classmethod
    def validate_schema(cls) -> list[str]:
        """Diff expected vs actual columns; return missing column names.

        Returns an empty list when all expected columns are present.
        """
        if not cls.table_exists():
            return list(BaseCanvasSchema.COLUMN_NAMES)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'base_canvas'
                ORDER BY ordinal_position
                """
            )
            actual_cols = {row[0] for row in cursor.fetchall()}

        expected_cols = set(BaseCanvasSchema.COLUMN_NAMES)
        missing = expected_cols - actual_cols
        return sorted(missing)

    @classmethod
    def drop_table(cls) -> None:
        """Drop ``public.base_canvas`` if it exists (cascades to views)."""
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS public.base_canvas CASCADE")

    @classmethod
    def ensure_table(cls) -> str:
        """Idempotent create-or-validate.

        Creates the table if it does not exist, then validates the schema.
        Raises ``RuntimeError`` if expected columns are missing.

        Returns the qualified table name.
        """
        cls.create_table()
        missing = cls.validate_schema()
        if missing:
            msg = (
                f"Base canvas table is missing {len(missing)} expected column(s): "
                f"{', '.join(missing)}"
            )
            raise RuntimeError(msg)
        return cls.qualified_name()
