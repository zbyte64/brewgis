# Generated manually for PaintEvent model
"""Add PaintEvent model for paint history & undo tracking."""

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspace", "0012_paintedcanvas_approval_status_mergeaudit"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PaintEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("feature_id", models.CharField(max_length=128)),
                ("column_name", models.CharField(max_length=128)),
                (
                    "old_value",
                    models.FloatField(blank=True, null=True),
                ),
                (
                    "new_value",
                    models.FloatField(blank=True, null=True),
                ),
                (
                    "painted_at",
                    models.DateTimeField(auto_now_add=True, db_index=True),
                ),
                (
                    "operation_type",
                    models.CharField(
                        choices=[
                            ("paint", "Paint"),
                            ("clear", "Clear"),
                            ("built_form", "Built Form Paint"),
                            ("undo", "Undo"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "batch_id",
                    models.CharField(db_index=True, max_length=64),
                ),
                (
                    "undone_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "painted_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "scenario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="paint_events",
                        to="workspace.scenario",
                    ),
                ),
            ],
            options={
                "verbose_name": "Paint Event",
                "verbose_name_plural": "Paint Events",
                "ordering": ["-painted_at"],
                "indexes": [
                    models.Index(
                        fields=["scenario", "-painted_at"],
                        name="workspace_p_scenari_0968af_idx",
                    ),
                    models.Index(
                        fields=["batch_id"],
                        name="workspace_p_batch_i_0b2d9e_idx",
                    ),
                ],
            },
        ),
    ]
