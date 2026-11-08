"""Move a workspace's analysis inputs onto the workspace itself.

The analysis used to read its CRS from one project-wide ``local_srid`` and its
constraint layers, trip-length zones, food outlets and road network from the
*region* its base table's schema named. Those are now workspace fields, resolved
into per-workspace ``wsp<pk>`` models by ``sqlmesh/macros/workspace_blueprints.py``:

- ``local_srid`` — every existing workspace was analyzed in CA Albers (3310),
  the old project-wide value, so that is what they keep; new workspaces must
  name their own (there is no default);
- ``extent`` — the bounding box of the base table, the area public inputs are
  fetched over, computed here for every workspace whose base table exists;
- ``constraint_source`` / ``trip_length_source`` / ``public_data_source`` — the
  public-data defaults every region workspace used. The SACOG v1 snapshot
  workspace moves to its package's layers when ``import_sacog_demo`` attaches
  its package.

Also adds ``WorkspaceExport`` (the export tracking row) and the ``package``
``DataImportRun`` type (a package import's base-canvas build).
"""

import django.db.models.deletion
from django.conf import settings
from django.contrib.gis.db.models.fields import PolygonField
from django.db import migrations
from django.db import models

import brewgis.workspace.models

_EXISTING_LOCAL_SRID = 3310


def backfill_extents(apps, schema_editor):  # noqa: ANN001, ANN201, ARG001
    from brewgis.workspace.services.workspace_extent import base_table_extent  # noqa: PLC0415

    Workspace = apps.get_model("workspace", "Workspace")
    for workspace in Workspace.objects.all():
        extent = base_table_extent(workspace.base_table)
        if extent is not None:
            workspace.extent = extent
            workspace.save(update_fields=["extent"])


class Migration(migrations.Migration):
    dependencies = [
        ("workspace", "0076_remove_poicache"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="workspace",
            name="local_srid",
            field=models.PositiveIntegerField(
                default=_EXISTING_LOCAL_SRID,
                help_text=(
                    "EPSG code of the projected CRS this workspace's distances and areas "
                    "are measured in (e.g. 3310 California Albers, or the UTM zone of the "
                    "area). Must be projected, with one linear unit."
                ),
                validators=[brewgis.workspace.models.validate_projected_srid],
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="workspace",
            name="extent",
            field=PolygonField(
                blank=True,
                help_text=(
                    "Bounding box of the base layer (EPSG:4326): the area public analysis "
                    "inputs are fetched over. Set from the base table when it is adopted, "
                    "or from the package manifest on import."
                ),
                null=True,
                srid=4326,
            ),
        ),
        migrations.AddField(
            model_name="workspace",
            name="constraint_source",
            field=models.CharField(
                choices=[
                    (
                        "public",
                        "FEMA flood zones and NWI wetlands, fetched over the extent",
                    ),
                    ("package", "Shipped in the workspace package"),
                ],
                default="public",
                help_text="Where env_constraint's constraint layers come from.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="workspace",
            name="trip_length_source",
            field=models.CharField(
                choices=[
                    ("gravity", "Gravity model rescaled to the target regional mean"),
                    (
                        "package",
                        "Reference trip-length zones shipped in the workspace package",
                    ),
                ],
                default="gravity",
                help_text="Where the vmt trip lengths come from.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="workspace",
            name="public_data_source",
            field=models.CharField(
                choices=[
                    ("fetch", "Fetched over the extent when an analysis needs it"),
                    ("package", "Shipped in the workspace package"),
                ],
                default="fetch",
                help_text="Where the food outlets and the road network come from.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="workspace",
            name="package_dir",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Directory under MEDIA_ROOT holding the unpacked workspace package this "
                    "workspace was imported from; blank when it was not imported."
                ),
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="dataimportrun",
            name="import_type",
            field=models.CharField(
                choices=[
                    ("allocate", "Spatial Allocation"),
                    ("census", "Census ACS Demographics"),
                    ("ejscreen", "EJScreen Environmental Justice"),
                    ("health_rankings", "County Health Rankings"),
                    ("lehd", "LEHD Employment"),
                    ("package", "Workspace Package"),
                    ("parkserve", "ParkServe Park Data"),
                    ("poi", "Points of Interest"),
                    ("raster", "Raster Data"),
                    ("stitch", "Column Stitching"),
                    ("svi", "Social Vulnerability Index"),
                ],
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name="WorkspaceExport",
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
                (
                    "include_public_data",
                    models.BooleanField(
                        default=False,
                        help_text=(
                            "Ship the workspace's food outlets and road network in the package, "
                            "so the importing server never fetches them."
                        ),
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("file", models.FileField(blank=True, upload_to="workspace_exports/")),
                ("error_log", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="exports",
                        to="workspace.workspace",
                    ),
                ),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.RunPython(backfill_extents, migrations.RunPython.noop),
    ]
