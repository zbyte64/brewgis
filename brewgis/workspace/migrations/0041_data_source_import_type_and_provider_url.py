"""Fill in DataSource.import_type and provider_url for the seeded catalog rows.

Both fields were left blank by the original seed migration:
- Blank ``import_type`` meant the Data Catalog's "Import" button never
  appeared for any source, even ones marked ``is_importable=True``.
- Blank ``provider_url`` meant the provider column rendered a dead
  ``<a href="">`` link for every row.
"""

from __future__ import annotations

from django.db import migrations

# (name, import_type, provider_url) — import_type only set for sources that
# already have a real import view wired up; provider_url left blank when
# there's no external org to link to (e.g. user-uploaded data).
_UPDATES: list[tuple[str, str, str]] = [
    ("Census ACS", "census", "https://www.census.gov/programs-surveys/acs"),
    ("LEHD Employment", "lehd", "https://lehd.ces.census.gov/"),
    ("OSM Points of Interest", "poi", "https://www.openstreetmap.org/"),
    ("Parcel Fabric", "upload", ""),
    ("Floodplains", "", "https://www.fema.gov/flood-maps"),
    ("Wetlands", "", "https://www.fws.gov/program/national-wetlands-inventory"),
    ("Steep Slopes", "", "https://www.usgs.gov/"),
    (
        "County Boundary",
        "",
        "https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html",
    ),
]


def forwards(apps, schema_editor):
    DataSource = apps.get_model("workspace", "DataSource")
    for name, import_type, provider_url in _UPDATES:
        DataSource.objects.filter(name=name).update(
            import_type=import_type, provider_url=provider_url
        )


def backwards(apps, schema_editor):
    DataSource = apps.get_model("workspace", "DataSource")
    for name, _import_type, _provider_url in _UPDATES:
        DataSource.objects.filter(name=name).update(
            import_type="", provider_url=""
        )


class Migration(migrations.Migration):

    dependencies = [
        ('workspace', '0040_building_place_type_workspace_required'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
