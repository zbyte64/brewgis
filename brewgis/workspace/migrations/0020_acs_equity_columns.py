# ruff: noqa: ANN001, ARG001
"""Add equity & environmental quality columns to ``public.base_canvas``.

Adds 5 new columns for ACS-derived equity indicators:
- median_income: Median household income (B19013)
- rent_burden_pct: Rent-burdened households % (B25070)
- pct_minority: People of color % (B03002)
- pct_college_educated: College-educated % (B15003)
- cost_burden_pct: Cost-burdened households % (B25070)
"""

from __future__ import annotations

from django.db import migrations


def add_equity_columns(apps, schema_editor) -> None:
    """Add equity columns to public.base_canvas."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
        ALTER TABLE public.base_canvas
        ADD COLUMN IF NOT EXISTS cost_burden_pct DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        ADD COLUMN IF NOT EXISTS median_income DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        ADD COLUMN IF NOT EXISTS pct_college_educated DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        ADD COLUMN IF NOT EXISTS pct_minority DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        ADD COLUMN IF NOT EXISTS rent_burden_pct DOUBLE PRECISION NOT NULL DEFAULT 0.0;
        """)


def drop_equity_columns(apps, schema_editor) -> None:
    """Drop equity columns from public.base_canvas."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
        ALTER TABLE public.base_canvas
        DROP COLUMN IF EXISTS cost_burden_pct,
        DROP COLUMN IF EXISTS median_income,
        DROP COLUMN IF EXISTS pct_college_educated,
        DROP COLUMN IF EXISTS pct_minority,
        DROP COLUMN IF EXISTS rent_burden_pct;
        """)


class Migration(migrations.Migration):
    """Add 5 equity columns to the base canvas table."""

    dependencies = [
        ("workspace", "0019_seed_default_data_sources"),
    ]

    operations = [
        migrations.RunPython(add_equity_columns, drop_equity_columns),
    ]
