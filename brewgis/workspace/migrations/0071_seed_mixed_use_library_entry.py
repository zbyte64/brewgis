"""Bring every workspace onto the library's "Mixed Use" entry.

The canvas has a mixed-use placeholder key (``mixed_use``, normalized to the
display name "Mixed Use" by ``built_forms.built_form_keys``) that the library
never defined, so the workspaces holding one carry a row nobody maintains — and
it is not a rare form: in the Fresno workspace it covers 30,316 parcels and
1.24M dwelling units, and it declares 12 jobs/acre while naming no employment
sector at all.

That last part is what this migration fixes. Trip generation prices employment
by sector, and a built form with jobs and no sector mix falls back to the
unattributed retail rate — the traffic-generating extreme — so a form this size
deciding the region's whole non-residential trip count by omission is not
something to leave in place. The entry added to the library carries SACOG's own
mid-rise mixed-use sector vector, which is data, not a guess.

Runs the same three maintenance functions as ``0065_seed_default_built_forms``:
every one of them is idempotent and none rewrites a row it does not define.
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
        ("workspace", "0070_buildingtype_du_type"),
    ]

    operations = [
        migrations.RunPython(seed_workspaces, migrations.RunPython.noop),
    ]
