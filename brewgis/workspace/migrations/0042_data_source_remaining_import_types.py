"""Wire up the remaining non-importable catalog rows to a real import action.

Floodplains/Steep Slopes (raster) and Wetlands/County Boundary (vector) were
left ``is_importable=False`` because no upload path existed for them. A
raster upload view now exists (``workspace:raster_upload``), and the vector
ones fit the same generic GIS file upload already used for Parcel Fabric.
"""

from __future__ import annotations

from django.db import migrations

_UPDATES: list[tuple[str, str]] = [
    ("Floodplains", "raster"),
    ("Steep Slopes", "raster"),
    ("Wetlands", "upload"),
    ("County Boundary", "upload"),
]


def forwards(apps, schema_editor):
    DataSource = apps.get_model("workspace", "DataSource")
    for name, import_type in _UPDATES:
        DataSource.objects.filter(name=name).update(
            import_type=import_type, is_importable=True
        )


def backwards(apps, schema_editor):
    DataSource = apps.get_model("workspace", "DataSource")
    for name, _import_type in _UPDATES:
        DataSource.objects.filter(name=name).update(
            import_type="", is_importable=False
        )


class Migration(migrations.Migration):

    dependencies = [
        ('workspace', '0041_data_source_import_type_and_provider_url'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
