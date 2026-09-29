# ruff: noqa: S608
"""Tests for the layer data table and its "Locate on map" bounds endpoint.

Both read a real PostGIS table through raw SQL, so the probe tables are
created explicitly (see ``feature_probe_tables``) rather than borrowed from a
Django-managed model — what is under test is the ``information_schema`` and
PostGIS view of a table, which only a real PostGIS table has. The ``S608``
noqa covers those DDL statements, whose identifiers are module constants.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.db import connection
from django.test import Client
from django.urls import reverse

from brewgis.workspace.models import Layer
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.models import Workspace
from tests.factories import LayerFactory
from tests.factories import ScenarioFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory

if TYPE_CHECKING:
    from collections.abc import Iterator

_PROBE_SCHEMA = "data_table_probe"
# The region's projected CRS: features stored in it must still come back as
# lng/lat, so a transform that never happens shows up as a nonsense box.
_CA_SRID = 3310


@pytest.fixture(autouse=True)
def feature_probe_tables(db) -> Iterator[None]:
    """A schema with a parcel-grain table, a point table, a projected table
    and a table whose id column sits past the table's column cap.

    Autouse: every test in this module reads one of these tables, and naming
    it only for its ordering effect would be a fixture argument no test body
    ever uses.
    """
    with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cursor.execute(f"DROP SCHEMA IF EXISTS {_PROBE_SCHEMA} CASCADE")
        cursor.execute(f"CREATE SCHEMA {_PROBE_SCHEMA}")
        cursor.execute(
            f"CREATE TABLE {_PROBE_SCHEMA}.parcels ("
            "parcel_id varchar, name text, geometry geometry(Polygon, 4326))"
        )
        cursor.execute(
            f"INSERT INTO {_PROBE_SCHEMA}.parcels (parcel_id, name, geometry) "
            "VALUES ('03504002S', 'corner lot', "
            "ST_MakeEnvelope(-119.8, 36.7, -119.7, 36.8, 4326))"
        )
        cursor.execute(
            f"CREATE TABLE {_PROBE_SCHEMA}.pois ("
            "id integer, name text, geometry geometry(Point, 4326))"
        )
        cursor.execute(
            f"INSERT INTO {_PROBE_SCHEMA}.pois (id, name, geometry) VALUES "
            "(7, 'cafe', ST_SetSRID(ST_MakePoint(-119.77, 36.75), 4326))"
        )
        # A row with no geometry at all: it exists, but nothing can be located.
        cursor.execute(
            f"INSERT INTO {_PROBE_SCHEMA}.pois (id, name, geometry) VALUES "
            "(9, 'unmapped', NULL)"
        )
        cursor.execute(
            f"CREATE TABLE {_PROBE_SCHEMA}.projected_parcels ("
            f"parcel_id varchar, name text, geometry geometry(Polygon, {_CA_SRID}))"
        )
        cursor.execute(
            f"INSERT INTO {_PROBE_SCHEMA}.projected_parcels "
            "(parcel_id, name, geometry) VALUES ('31302103T', 'projected', "
            "ST_Transform(ST_MakeEnvelope(-119.8, 36.7, -119.7, 36.8, 4326), "
            f"{_CA_SRID}))"
        )
        wide_columns = ", ".join(f"attr_{i} text" for i in range(28))
        cursor.execute(
            f"CREATE TABLE {_PROBE_SCHEMA}.wide ("
            f"name text, {wide_columns}, gid integer, geometry geometry(Point, 4326))"
        )
        cursor.execute(
            f"INSERT INTO {_PROBE_SCHEMA}.wide (name, gid, geometry) VALUES "
            "('narrow', 4096, ST_SetSRID(ST_MakePoint(-119.77, 36.75), 4326))"
        )
        # Geometry before any attribute column: the row's id then falls back to
        # the first *non-geometry* column, never to the geometry itself.
        cursor.execute(
            f"CREATE TABLE {_PROBE_SCHEMA}.geom_first ("
            "geometry geometry(Point, 4326), label text)"
        )
        cursor.execute(
            f"INSERT INTO {_PROBE_SCHEMA}.geom_first (geometry, label) VALUES "
            "(ST_SetSRID(ST_MakePoint(-119.77, 36.75), 4326), 'pumphouse')"
        )
    yield
    with connection.cursor() as cursor:
        cursor.execute(f"DROP SCHEMA IF EXISTS {_PROBE_SCHEMA} CASCADE")


class DataTableProbe:
    """Fixtures shared by both suites: a workspace, one layer per probe table."""

    @pytest.fixture
    def workspace(self, db) -> Workspace:  # noqa: ARG002
        """A workspace whose schema is the probe schema.

        Depends on ``db`` (never read directly) so the factories below are
        allowed to write. ``resolve_scenario_param`` falls back to the
        workspace's BASE scenario, so every workspace under test needs
        exactly one.
        """
        workspace = WorkspaceFactory(db_schema=_PROBE_SCHEMA)
        ScenarioFactory(workspace=workspace, scenario_type=ScenarioType.BASE)
        return workspace

    @pytest.fixture
    def parcels(self, workspace) -> Layer:
        return LayerFactory(
            workspace=workspace,
            key="parcels",
            db_schema=_PROBE_SCHEMA,
            db_table="parcels",
        )

    @pytest.fixture
    def pois(self, workspace) -> Layer:
        return LayerFactory(
            workspace=workspace,
            key="pois",
            db_schema=_PROBE_SCHEMA,
            db_table="pois",
            geometry_type="circle",
        )

    @pytest.fixture
    def client(self) -> Client:
        client = Client()
        client.force_login(UserFactory())
        return client


@pytest.mark.views
class TestLayerFeatureBounds(DataTableProbe):
    """The box the map's "Locate on map" button zooms to."""

    def test_polygon_bounds_are_lng_lat(self, client, parcels) -> None:
        response = client.get(
            reverse("workspace:layer_feature_bounds", args=[parcels.pk]),
            {"feature_id": "03504002S"},
        )

        assert response.status_code == 200
        assert response.json()["bounds"] == [[-119.8, 36.7], [-119.7, 36.8]]
        # Also the outline the map draws for the row: the same four corners —
        # compared as a set, since which corner a ring starts at is PostGIS's
        # business — in degrees, and closed.
        geometry = response.json()["geometry"]
        assert geometry["type"] == "Polygon"
        ring = geometry["coordinates"][0]
        assert {(round(x, 3), round(y, 3)) for x, y in ring} == {
            (-119.8, 36.7),
            (-119.7, 36.7),
            (-119.7, 36.8),
            (-119.8, 36.8),
        }
        assert ring[0] == ring[-1]

    def test_projected_geometry_is_returned_as_lng_lat(self, client, workspace) -> None:
        layer = LayerFactory(
            workspace=workspace,
            key="projected_parcels",
            db_schema=_PROBE_SCHEMA,
            db_table="projected_parcels",
        )

        body = client.get(
            reverse("workspace:layer_feature_bounds", args=[layer.pk]),
            {"feature_id": "31302103T"},
        ).json()
        bounds = body["bounds"]

        assert [round(value, 3) for value in bounds[0]] == [-119.8, 36.7]
        assert [round(value, 3) for value in bounds[1]] == [-119.7, 36.8]
        # The outline is reprojected too: in the layer's own CRS these numbers
        # would be ~2 million (metres), not degrees.
        ring = body["geometry"]["coordinates"][0]
        assert [round(value, 3) for value in ring[0]] == [-119.8, 36.7]
        assert [round(value, 3) for value in ring[2]] == [-119.7, 36.8]

    def test_point_feature_has_a_degenerate_box(self, client, pois) -> None:
        """A point has no extent, so both corners sit on the point itself."""
        body = client.get(
            reverse("workspace:layer_feature_bounds", args=[pois.pk]),
            {"feature_id": "7"},
        ).json()

        assert body["bounds"] == [[-119.77, 36.75], [-119.77, 36.75]]
        # The point itself is what the map rings — a zero-area box would fit
        # to nothing, and feature-state highlighting never reaches this layer.
        assert body["geometry"] == {"type": "Point", "coordinates": [-119.77, 36.75]}

    def test_row_without_geometry_is_404(self, client, pois) -> None:
        """A row whose geometry is NULL exists but cannot be located."""
        response = client.get(
            reverse("workspace:layer_feature_bounds", args=[pois.pk]),
            {"feature_id": "9"},
        )

        assert response.status_code == 404
        assert "error" in response.json()

    def test_numeric_id_column_accepts_a_numeric_feature_id(self, client, pois) -> None:
        """An integer id never reaches the query as text, so it cannot 500."""
        response = client.get(
            reverse("workspace:layer_feature_bounds", args=[pois.pk]),
            {"feature_id": "8"},
        )

        assert response.status_code == 404

    def test_unknown_feature_is_404(self, client, parcels) -> None:
        response = client.get(
            reverse("workspace:layer_feature_bounds", args=[parcels.pk]),
            {"feature_id": "does-not-exist"},
        )

        assert response.status_code == 404
        assert "error" in response.json()

    def test_missing_feature_id_is_rejected(self, client, parcels) -> None:
        response = client.get(
            reverse("workspace:layer_feature_bounds", args=[parcels.pk])
        )

        assert response.status_code == 400

    def test_unreadable_geometry_does_not_break_the_request(
        self, client, workspace
    ) -> None:
        """A geometry with no SRID cannot be transformed: 400, not a 500.

        The lookup runs in its own savepoint, so the aborted transaction must
        not take any later query on the same connection down with it.
        """
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE TABLE {_PROBE_SCHEMA}.no_srid ("
                "parcel_id varchar, geometry geometry)"
            )
            cursor.execute(
                f"INSERT INTO {_PROBE_SCHEMA}.no_srid (parcel_id, geometry) "
                "VALUES ('00000000', ST_MakePoint(-119.77, 36.75))"
            )
        layer = LayerFactory(
            workspace=workspace,
            key="no_srid",
            db_schema=_PROBE_SCHEMA,
            db_table="no_srid",
        )

        response = client.get(
            reverse("workspace:layer_feature_bounds", args=[layer.pk]),
            {"feature_id": "00000000"},
        )

        assert response.status_code == 400
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)

    def test_geometry_first_table_falls_back_to_its_first_attribute(
        self, client, workspace
    ) -> None:
        """A geometry column can never be the id: the first attribute is used."""
        layer = LayerFactory(
            workspace=workspace,
            key="geom_first",
            db_schema=_PROBE_SCHEMA,
            db_table="geom_first",
            geometry_type="circle",
        )

        response = client.get(
            reverse("workspace:layer_feature_bounds", args=[layer.pk]),
            {"feature_id": "pumphouse"},
        )

        assert response.status_code == 200
        assert response.json()["bounds"] == [[-119.77, 36.75], [-119.77, 36.75]]

    def test_requires_login(self, parcels) -> None:
        response = Client().get(
            reverse("workspace:layer_feature_bounds", args=[parcels.pk]),
            {"feature_id": "03504002S"},
        )

        assert response.status_code == 302


@pytest.mark.views
class TestDataTableFeatureId(DataTableProbe):
    """Every row's locate button carries that row's own feature id."""

    def test_row_feature_id_is_the_parcels_id(self, client, parcels) -> None:
        html = client.get(
            reverse("workspace:layer_data_table", args=[parcels.pk])
        ).content.decode()

        assert 'data-feature-id="03504002S"' in html
        assert "feature-bounds" in html

    def test_id_column_past_the_column_cap_is_still_read_from_the_row(
        self, client, workspace
    ) -> None:
        """``gid`` sits past the 20-column cap, so it is force-included.

        Without that the row index would point at a neighbouring column, and
        the button would locate whatever value happened to sit at index 19.
        """
        layer = LayerFactory(
            workspace=workspace,
            key="wide",
            db_schema=_PROBE_SCHEMA,
            db_table="wide",
        )

        html = client.get(
            reverse("workspace:layer_data_table", args=[layer.pk])
        ).content.decode()

        assert 'data-feature-id="4096"' in html

    def test_scenario_param_reaches_the_locate_url(self, client, parcels) -> None:
        scenario = ScenarioFactory(
            workspace=parcels.workspace, scenario_type=ScenarioType.BASE
        )

        html = client.get(
            reverse("workspace:layer_data_table", args=[parcels.pk]),
            {"scenario": scenario.pk},
        ).content.decode()

        assert f"feature-bounds/?scenario={scenario.pk}" in html
