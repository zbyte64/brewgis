"""Shared pytest fixtures for Brew GIS tests."""
from __future__ import annotations

import deal

deal.enable()

from typing import TYPE_CHECKING

import pytest
from django.db import connection

from tests.factories import BuildingTypeFactory
from tests.factories import LayerFactory
from tests.factories import PlaceTypeBuildingTypeMixFactory
from tests.factories import PlaceTypeFactory
from tests.factories import SymbologyConfigFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory
from tests.factories import ScenarioFactory

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from brewgis.workspace.built_forms.models import BuildingType
    from brewgis.workspace.built_forms.models import PlaceType
    from brewgis.workspace.built_forms.models import PlaceTypeBuildingTypeMix
    from brewgis.workspace.models import Layer
    from brewgis.workspace.models import SymbologyConfig
    from brewgis.workspace.models import Workspace
    from brewgis.workspace.models import Scenario


@pytest.fixture
def user(db) -> User:
    return UserFactory()


@pytest.fixture
def workspace(db) -> Workspace:
    return WorkspaceFactory()


@pytest.fixture
def scenario(db, workspace: Workspace) -> Scenario:
    return ScenarioFactory(workspace=workspace)


@pytest.fixture
def layer(db, workspace: Workspace) -> Layer:
    return LayerFactory(workspace=workspace)


@pytest.fixture
def symbology_config(db, layer: Layer) -> SymbologyConfig:
    return SymbologyConfigFactory(layer=layer)


@pytest.fixture
def building_type(db) -> BuildingType:
    return BuildingTypeFactory()


@pytest.fixture
def place_type(db) -> PlaceType:
    return PlaceTypeFactory()


@pytest.fixture
def mix(db, place_type: PlaceType, building_type: BuildingType) -> PlaceTypeBuildingTypeMix:
    return PlaceTypeBuildingTypeMixFactory(
        place_type=place_type, building_type=building_type
    )


@pytest.fixture
def base_canvas_table(db) -> str:
    """Create a minimal base canvas table with static + paintable columns.

    Creates a PostGIS-enabled table in the public schema with geometry, du,
    pop, hh, and status columns. Returns the qualified table name.

    .. note::

        Requires PostgreSQL + PostGIS. The extension is enabled explicitly
        because Django's test database template may not include it.
    """
    with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS test_base_canvas (
                id SERIAL PRIMARY KEY,
                geometry GEOMETRY(POLYGON, 4326),
                du DOUBLE PRECISION,
                pop DOUBLE PRECISION,
                hh DOUBLE PRECISION,
                status VARCHAR(32)
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO test_base_canvas (geometry, du, pop, hh, status)
            VALUES
                (ST_SetSRID(ST_MakeEnvelope(0, 0, 1, 1), 4326), 100.0, 250.0, 80.0, 'active'),
                (ST_SetSRID(ST_MakeEnvelope(1, 0, 2, 1), 4326), 50.0, 120.0, 40.0, 'active')
            """
        )
    yield "public.test_base_canvas"
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS test_base_canvas CASCADE")


@pytest.fixture
def geometry_table(db) -> str:
    """Create a bare PostGIS geometry table for testing.

    A lighter alternative to ``base_canvas_table`` — creates a table with
    just id + geometry columns. Useful for tests that only need a PostGIS-
    enabled table without paint-able columns.

    .. note::

        Requires PostgreSQL + PostGIS. The extension is enabled explicitly.
    """
    with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS test_geometry_table (
                id SERIAL PRIMARY KEY,
                geometry GEOMETRY(POLYGON, 4326)
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO test_geometry_table (geometry)
            VALUES
                (ST_SetSRID(ST_MakeEnvelope(0, 0, 1, 1), 4326)),
                (ST_SetSRID(ST_MakeEnvelope(1, 0, 2, 1), 4326))
            """
        )
    yield "public.test_geometry_table"
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS test_geometry_table CASCADE")
