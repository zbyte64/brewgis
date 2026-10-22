# ruff: noqa: ANN201, ARG002
"""Workspace packages: what a package carries, and what an import refuses.

A package is the only way a workspace's base layer reaches another server, so
the round trip has to be exact (every parcel, every contract column, the
Building Type library with its mixes) and a package this server cannot use has
to be refused before it creates a workspace.
"""

from __future__ import annotations

import json
import zipfile
from typing import TYPE_CHECKING

import duckdb
import pytest
from django.contrib.gis.geos import Polygon
from django.core.files import File
from django.db import connection
from django.urls import reverse

from brewgis.sqlmesh.macros.workspace_blueprints import workspace_profiles
from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.built_forms.models import PlaceType
from brewgis.workspace.built_forms.models import PlaceTypeBuildingTypeMix
from brewgis.workspace.models import DataImportRun
from brewgis.workspace.models import Workspace
from brewgis.workspace.models import WorkspaceExport
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema
from brewgis.workspace.services.workspace_package import MANIFEST_NAME
from brewgis.workspace.services.workspace_package import PackageError
from brewgis.workspace.services.workspace_package import export_workspace_package
from brewgis.workspace.services.workspace_package import import_workspace_package
from tests.factories import BuildingTypeFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory

if TYPE_CHECKING:
    from pathlib import Path

# Transactional: the export reads PostGIS through DuckDB's own connection, which
# sees only committed rows — and would wait forever on the lock a test
# transaction's TRUNCATE of ``public.base_canvas`` holds.
pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]

_EXTENT = Polygon.from_bbox((-121.6, 38.4, -121.3, 38.7))


@pytest.fixture
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    return tmp_path / "media"


@pytest.fixture
def source_workspace(base_canvas_table):
    """A workspace on the two-parcel ``public.base_canvas`` with a small library."""
    workspace = WorkspaceFactory(
        name="Source", base_table="public.base_canvas", extent=_EXTENT, local_srid=2226
    )
    detached = BuildingTypeFactory(
        workspace=workspace, name="Detached", du_per_acre=6.0
    )
    retail = BuildingTypeFactory(workspace=workspace, name="Retail", emp_per_acre=20.0)
    place = PlaceType.objects.create(workspace=workspace, name="Town Center")
    PlaceTypeBuildingTypeMix.objects.create(
        place_type=place, building_type=detached, percentage=60.0
    )
    PlaceTypeBuildingTypeMix.objects.create(
        place_type=place, building_type=retail, percentage=40.0
    )
    return workspace


@pytest.fixture
def package(source_workspace, tmp_path) -> Path:
    return export_workspace_package(
        source_workspace,
        include_public_data=False,
        destination=tmp_path / "source.brewgis.zip",
    )


def _rewrite_manifest(path: Path, edit) -> Path:
    """Copy the package at *path* with its manifest passed through *edit*."""
    target = path.with_name("edited.brewgis.zip")
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(target, "w") as out:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == MANIFEST_NAME:
                manifest = json.loads(data)
                edit(manifest)
                data = json.dumps(manifest).encode()
            out.writestr(item, data)
    return target


class TestRoundTrip:
    def test_the_import_reads_every_parcel_the_export_wrote(self, package, media_root):
        workspace = import_workspace_package(package, name="Imported")
        root = workspace.package_root()
        assert root is not None

        parquet = root / "base_canvas.parquet"
        columns = [name for name in BaseCanvasSchema.COLUMN_NAMES if name != "geometry"]
        imported = (
            duckdb.connect()
            .execute(
                f"SELECT {', '.join(columns)} FROM read_parquet(?) ORDER BY parcel_id",  # noqa: S608
                [str(parquet)],
            )
            .fetchall()
        )
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {', '.join(columns)} FROM public.base_canvas ORDER BY parcel_id"  # noqa: S608
            )
            source = cursor.fetchall()
        assert len(source) == 2
        assert [tuple(row) for row in imported] == [tuple(row) for row in source]

    def test_the_new_workspace_carries_the_packages_settings(
        self, package, media_root, source_workspace
    ):
        workspace = import_workspace_package(package)

        assert workspace.pk != source_workspace.pk
        assert workspace.name == "Source"
        assert workspace.local_srid == 2226
        assert workspace.extent.extent == pytest.approx(_EXTENT.extent)
        assert workspace.base_table == f"wsp{workspace.pk}.base_canvas"
        # Public inputs were not shipped, so they are fetched over the extent.
        assert (
            workspace.constraint_source,
            workspace.trip_length_source,
            workspace.public_data_source,
        ) == ("public", "gravity", "fetch")
        assert workspace.scenarios.filter(scenario_type="base").count() == 1

    def test_the_library_arrives_whole(self, package, media_root):
        workspace = import_workspace_package(package)

        library = dict(
            BuildingType.objects.filter(workspace=workspace).values_list(
                "name", "du_per_acre"
            )
        )
        assert sorted(library) == ["Detached", "Retail"]
        assert library["Detached"] == 6.0
        mixes = sorted(
            PlaceTypeBuildingTypeMix.objects.filter(
                place_type__workspace=workspace
            ).values_list("place_type__name", "building_type__name", "percentage")
        )
        assert mixes == [
            ("Town Center", "Detached", 60.0),
            ("Town Center", "Retail", 40.0),
        ]

    def test_a_local_srid_override_wins(self, package, media_root):
        workspace = import_workspace_package(package, local_srid=3310)
        assert workspace.local_srid == 3310


class TestRefusals:
    """A package this server cannot use creates no workspace."""

    def _assert_refused(self, path: Path, match: str) -> None:
        before = Workspace.objects.count()
        with pytest.raises(PackageError, match=match):
            import_workspace_package(path)
        assert Workspace.objects.count() == before

    def test_an_unknown_part_kind(self, package, media_root):
        def add_part(manifest):
            manifest["parts"].append(
                {"kind": "scenarios", "path": "scenarios.json", "sha256": "", "rows": 0}
            )

        self._assert_refused(_rewrite_manifest(package, add_part), "does not know")

    def test_a_newer_format_version(self, package, media_root):
        def bump(manifest):
            manifest["format_version"] = 2

        self._assert_refused(_rewrite_manifest(package, bump), "not supported")

    def test_a_base_canvas_missing_a_contract_column(self, package, media_root):
        def drop_du(manifest):
            for part in manifest["parts"]:
                if part["kind"] == "base_canvas":
                    part["columns"] = [c for c in part["columns"] if c["name"] != "du"]

        self._assert_refused(_rewrite_manifest(package, drop_du), "du")

    def test_a_paintable_column_shipped_as_text(self, package, media_root):
        def du_as_text(manifest):
            for part in manifest["parts"]:
                for column in part.get("columns", []):
                    if column["name"] == "du":
                        column["type"] = "VARCHAR"

        self._assert_refused(_rewrite_manifest(package, du_as_text), "wrong type")

    def test_a_geographic_crs(self, package, media_root):
        def geographic(manifest):
            manifest["local_srid"] = 4326

        self._assert_refused(_rewrite_manifest(package, geographic), "local_srid")

    def test_a_corrupt_part(self, package, media_root):
        def wrong_checksum(manifest):
            for part in manifest["parts"]:
                if part["kind"] == "base_canvas":
                    part["sha256"] = "0" * 64

        self._assert_refused(_rewrite_manifest(package, wrong_checksum), "corrupt")
        # Nothing is left behind for the workspace that was never created.
        assert not any(
            (media_root / "workspace_packages").glob("*/*/base_canvas.parquet")
        )


class TestWorkspaceInputs:
    """Which input models a workspace's profile points its analysis at."""

    def test_an_imported_workspace_reads_its_packaged_base(self, package, media_root):
        workspace = import_workspace_package(package)

        (profile,) = [
            p for p in workspace_profiles() if p["workspace_pk"] == workspace.pk
        ]

        assert profile["base_canvas_parquet"] == str(
            workspace.package_root() / "base_canvas.parquet"
        )
        assert profile["local_srid"] == 2226
        assert (
            profile["constraint_input"],
            profile["trip_length_input"],
            profile["food_pois_input"],
        ) == ("constraints_public", "trip_zones_none", "food_pois_fetch_raw")

    def test_packaged_inputs_are_read_from_the_package(self, db, media_root):
        workspace = WorkspaceFactory(
            extent=_EXTENT,
            package_dir="workspace_packages/1/abc",
            constraint_source="package",
            trip_length_source="package",
            public_data_source="package",
        )

        (profile,) = [
            p for p in workspace_profiles() if p["workspace_pk"] == workspace.pk
        ]

        root = workspace.package_root()
        assert root is not None
        assert profile["constraint_input"] == "constraints_package_raw"
        assert profile["constraint_layers_parquet"] == str(
            root / "constraint_layers.parquet"
        )
        assert profile["trip_length_input"] == "trip_zones_package_raw"
        assert profile["road_subsegments_input"] == "road_subsegments_package_raw"
        assert profile["road_subsegments_parquet"] == str(
            root / "road_subsegments.parquet"
        )

    def test_a_workspace_without_an_extent_has_no_inputs(self, db):
        workspace = WorkspaceFactory(extent=None)
        assert workspace.pk not in {p["workspace_pk"] for p in workspace_profiles()}


class TestViews:
    """The hub's export endpoints and the Import Center's package form."""

    def test_a_refused_upload_creates_no_workspace(self, client, media_root, tmp_path):
        client.force_login(UserFactory())
        bogus = tmp_path / "bogus.zip"
        with zipfile.ZipFile(bogus, "w") as archive:
            archive.writestr("readme.txt", "not a package")
        before = Workspace.objects.count()

        with bogus.open("rb") as handle:
            response = client.post(
                reverse("workspace:import_workspace_package"), {"package": handle}
            )

        assert response.status_code == 200
        assert b"no manifest.json" in response.content
        assert Workspace.objects.count() == before

    def test_an_upload_becomes_a_workspace_with_its_build_queued(
        self, client, package, media_root, monkeypatch
    ):
        queued: list[int] = []
        monkeypatch.setattr(
            "brewgis.workspace.tasks.build_package_base_task.delay", queued.append
        )
        client.force_login(UserFactory())

        with package.open("rb") as handle:
            response = client.post(
                reverse("workspace:import_workspace_package"),
                {"package": handle, "name": "From the form"},
            )

        workspace = Workspace.objects.get(name="From the form")
        assert response.status_code == 302
        assert response.url == reverse(
            "workspace:workspace_detail", args=[workspace.pk]
        )
        (run,) = DataImportRun.objects.filter(
            workspace=workspace, import_type="package"
        )
        assert queued == [run.pk]

    def test_only_a_finished_export_downloads(self, client, source_workspace, package):
        client.force_login(UserFactory())
        pending = WorkspaceExport.objects.create(workspace=source_workspace)
        url = reverse(
            "workspace:workspace_export_download",
            args=[source_workspace.pk, pending.pk],
        )
        assert client.get(url).status_code == 404

        done = WorkspaceExport.objects.create(
            workspace=source_workspace, status=WorkspaceExport.Status.COMPLETED
        )
        with package.open("rb") as handle:
            done.file.save(f"{done.pk}/source.brewgis.zip", File(handle))
        response = client.get(
            reverse(
                "workspace:workspace_export_download",
                args=[source_workspace.pk, done.pk],
            )
        )
        assert response.status_code == 200
        assert response["Content-Type"] == "application/zip"
        assert b"".join(response.streaming_content) == package.read_bytes()
