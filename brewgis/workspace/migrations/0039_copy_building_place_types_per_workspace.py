"""Copy the (formerly global) BuildingType/PlaceType library into every workspace.

Building Types and Place Types are becoming workspace-scoped. Rather than
assign the existing rows to a single workspace (which would take them away
from everyone else), each existing row is duplicated once per current
workspace so nobody loses access to what's already defined. New workspaces
created after this migration start with an empty library.
"""

from __future__ import annotations

from django.db import migrations


def _field_values(instance, exclude):
    values = {}
    for field in instance._meta.concrete_fields:
        if field.name in exclude or field.attname in exclude:
            continue
        values[field.attname] = getattr(instance, field.attname)
    return values


def copy_per_workspace(apps, schema_editor):
    Workspace = apps.get_model("workspace", "Workspace")
    BuildingType = apps.get_model("workspace", "BuildingType")
    PlaceType = apps.get_model("workspace", "PlaceType")
    Mix = apps.get_model("workspace", "PlaceTypeBuildingTypeMix")

    workspaces = list(Workspace.objects.all())
    if not workspaces:
        return

    source_building_types = list(BuildingType.objects.filter(workspace__isnull=True))
    source_place_types = list(PlaceType.objects.filter(workspace__isnull=True))
    source_mixes = list(
        Mix.objects.filter(
            place_type__workspace__isnull=True,
            building_type__workspace__isnull=True,
        )
    )

    for workspace in workspaces:
        bt_id_map = {}
        for bt in source_building_types:
            values = _field_values(bt, exclude={"id", "workspace_id"})
            copy = BuildingType.objects.create(workspace=workspace, **values)
            bt_id_map[bt.id] = copy.id

        pt_id_map = {}
        for pt in source_place_types:
            values = _field_values(pt, exclude={"id", "workspace_id"})
            copy = PlaceType.objects.create(workspace=workspace, **values)
            pt_id_map[pt.id] = copy.id

        for mix in source_mixes:
            new_place_type_id = pt_id_map.get(mix.place_type_id)
            new_building_type_id = bt_id_map.get(mix.building_type_id)
            if new_place_type_id is None or new_building_type_id is None:
                continue
            Mix.objects.create(
                place_type_id=new_place_type_id,
                building_type_id=new_building_type_id,
                percentage=mix.percentage,
            )

    # The original unscoped rows have been copied into every workspace —
    # delete them (cascades to their now-redundant Mix rows) so every
    # remaining row belongs to exactly one workspace.
    BuildingType.objects.filter(workspace__isnull=True).delete()
    PlaceType.objects.filter(workspace__isnull=True).delete()


def noop_reverse(apps, schema_editor):
    """Irreversible — the pre-copy state cannot be reconstructed."""


class Migration(migrations.Migration):

    dependencies = [
        ('workspace', '0038_building_place_type_workspace_nullable'),
    ]

    operations = [
        migrations.RunPython(copy_per_workspace, noop_reverse),
    ]
