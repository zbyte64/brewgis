# ruff: noqa: ANN001, ARG001
"""Equity columns are now part of the ``BaseCanvas`` model definition.

This migration is a no-op because all equity columns (median_income,
rent_burden_pct, pct_minority, pct_college_educated, cost_burden_pct)
are created directly by the ``BaseCanvas`` model (migration 0032) rather
than retrofitted via ALTER TABLE.
"""

from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):
    """No-op — equity columns are now in the BaseCanvas model."""

    dependencies = [
        ("workspace", "0019_seed_default_data_sources"),
    ]

    operations = [
        migrations.RunSQL("SELECT 1", "SELECT 1"),
    ]
