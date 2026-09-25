"""Bring every pre-existing workspace onto the default Building Type library.

New workspaces are seeded at creation
(``brewgis.workspace.views.workspace_create``); this migration brings the ones
that already existed onto the same library: ``seed_default_built_forms`` adds
the entries a workspace is missing (and never rewrites a row it already holds),
and ``backfill_library_fields`` gives the workspaces' own Building Types their
category and employment-sector mix where their name matches a library entry.

Both are idempotent, so re-running the migration is a no-op.
"""

from __future__ import annotations

from django.db import migrations


def seed_workspaces(apps, schema_editor) -> None:  # noqa: ARG001
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
        ("workspace", "0064_buildingtype_land_development_category"),
    ]

    operations = [
        migrations.RunPython(seed_workspaces, migrations.RunPython.noop),
    ]
