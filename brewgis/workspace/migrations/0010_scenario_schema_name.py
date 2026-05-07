"""Add schema_name field to Scenario model.

schema_name is the canonical source of truth for the PostGIS schema
where dbt creates views for this scenario. It defaults to
``scenario_{slug}`` on save (handled by the model's save() override)
and is independently configurable.

Existing rows get empty string, and ``Scenario.target_schema`` falls
back to ``f"scenario_{self.slug}"`` if ``schema_name`` is blank.
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    """Add schema_name CharField to Scenario."""

    dependencies = [
        ("workspace", "0009_base_canvas_table"),
    ]

    operations = [
        migrations.AddField(
            model_name="scenario",
            name="schema_name",
            field=models.CharField(
                blank=True,
                default="",
                max_length=128,
            ),
        ),
    ]
