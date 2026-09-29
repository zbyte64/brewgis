"""Give every workspace the four built forms the POI override can assign.

``brewgis.seeds.poi_built_form_map`` maps an OpenStreetMap POI category to the
built form a parcel containing a point of that category takes, and the base
canvas override (``base_canvas/poi_override.sql``) writes that key onto the
parcel. Four of the mapped keys are new entries in the library — ``Transit
Station``, ``Entertainment``, ``Sports/Recreation`` and ``Place of Worship`` —
and a workspace seeded before them holds no row under those names.

That matters beyond the library export: ``core_end_state`` resolves a parcel's
built form by joining the canvas key against the workspace's ``built_forms``
table (normalized on both sides), so a parcel carrying a key the workspace does
not define comes back with no ``built_form_id``, no ``du_type`` and no
``jobs_by_sector`` — jobs that name no sector. The demo canvas already carries
704 such parcels (474 ``Place of Worship``, 178 ``Sports/Recreation``, 29
``Entertainment``, 23 ``Transit Station``).

Runs the same three maintenance functions as ``0065_seed_default_built_forms``
and ``0071_seed_mixed_use_library_entry``: every one of them is idempotent and
none rewrites a row it does not define. The workspace's exported ``built_forms``
table is rebuilt by ``analysis.data_export.ensure_export_exists_isolated`` on the
next analysis run or base-canvas action, which re-exports whenever the workspace
holds rows the table does not.
"""

from __future__ import annotations

from django.db import migrations


def seed_workspaces(apps, schema_editor) -> None:  # noqa: ANN001, ARG001
    """Seed, align and retire every workspace's Building Types."""
    from brewgis.workspace.built_forms.default_library import backfill_library_fields
    from brewgis.workspace.built_forms.default_library import retire_library_entries
    from brewgis.workspace.built_forms.default_library import seed_default_built_forms
    from brewgis.workspace.models import Workspace

    for workspace in Workspace.objects.all():
        seed_default_built_forms(workspace)
        backfill_library_fields(workspace)
        retire_library_entries(workspace)


class Migration(migrations.Migration):
    dependencies = [
        ("workspace", "0071_seed_mixed_use_library_entry"),
    ]

    operations = [
        migrations.RunPython(seed_workspaces, migrations.RunPython.noop),
    ]
