"""Create ``public.base_canvas`` table — the base canvas schema.

This is a raw PostGIS table managed outside the ORM. It is the ETL target for
existing-conditions spatial data and the foundation for per-scenario canvas
SQL views (copy-on-write).

See :mod:`brewgis.workspace.services.base_canvas_manager` for the service layer
that manages this table at runtime.
"""

from __future__ import annotations

from django.db import migrations

from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema


def create_base_canvas_table(apps, schema_editor) -> None:  # noqa: ANN001,ARG001
    """Create ``public.base_canvas`` with all 77 columns and indexes."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cursor.execute(BaseCanvasSchema.create_table_sql())
        for idx_sql in BaseCanvasSchema.create_indexes_sql():
            cursor.execute(idx_sql)


def drop_base_canvas_table(apps, schema_editor) -> None:  # noqa: ANN001,ARG001
    """Drop ``public.base_canvas`` (cascades to views)."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS public.base_canvas CASCADE")


class Migration(migrations.Migration):

    dependencies = [
        ("workspace", "0008_painted_canvas"),
    ]

    operations = [
        migrations.RunPython(
            code=create_base_canvas_table,
            reverse_code=drop_base_canvas_table,
            elidable=False,
        ),
    ]
