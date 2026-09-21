# Hand-written: replace the implicit auto ``id`` primary key on
# ``public.base_canvas`` with an explicit ``parcel_id``.
#
# ``parcel_id`` is populated from the source parcel identifier by the ETL
# pipeline (or, for rows loaded before this migration, from the old ``id``
# serial). Removing the bare ``id`` keeps a single, explicit parcel key
# across the Django model, the scenario canvas view, the map's promoted
# feature id, and the SQLMesh models.

# ruff: noqa: ANN001, ANN201

from __future__ import annotations

from django.db import migrations, models


def backfill_parcel_id(apps, schema_editor) -> None:  # noqa: ARG001
    """Seed ``parcel_id`` from the legacy serial so the PK is never NULL."""
    schema_editor.execute(
        'UPDATE "base_canvas" SET "parcel_id" = "id" WHERE "parcel_id" IS NULL'
    )


def rename_column_metadata(apps, schema_editor) -> None:  # noqa: ARG001
    """Point the ``BaseCanvasColumn`` metadata row at the new column name."""
    BaseCanvasColumn = apps.get_model("workspace", "BaseCanvasColumn")  # noqa: N806
    BaseCanvasColumn.objects.filter(name="id").update(
        name="parcel_id", pg_type="BIGINT"
    )


def rename_column_metadata_reverse(apps, schema_editor) -> None:  # noqa: ARG001
    """Restore the ``BaseCanvasColumn`` metadata row name."""
    BaseCanvasColumn = apps.get_model("workspace", "BaseCanvasColumn")  # noqa: N806
    BaseCanvasColumn.objects.filter(name="parcel_id").update(
        name="id", pg_type="SERIAL"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("workspace", "0051_built_form_pass_by_trip_pct_range"),
    ]

    operations = [
        # 1. Add the new key as a plain nullable column so it can be filled.
        migrations.AddField(
            model_name="basecanvas",
            name="parcel_id",
            field=models.BigIntegerField(null=True),
        ),
        # 2. Fill it from the legacy serial.
        migrations.RunPython(backfill_parcel_id, migrations.RunPython.noop),
        # 3. Drop the old primary key. Must precede the AlterField below:
        #    Django's ``_alter_field`` emits ``ADD CONSTRAINT ... PRIMARY
        #    KEY`` for a field that *became* the primary key without
        #    dropping the existing one, which Postgres rejects.
        migrations.RemoveField(
            model_name="basecanvas",
            name="id",
        ),
        # 4. Promote ``parcel_id`` to the primary key.
        migrations.AlterField(
            model_name="basecanvas",
            name="parcel_id",
            field=models.BigIntegerField(primary_key=True, serialize=False),
        ),
        # 5. Keep the column metadata catalogue in sync.
        migrations.RunPython(
            rename_column_metadata,
            reverse_code=rename_column_metadata_reverse,
        ),
    ]
