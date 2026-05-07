"""Shared pytest fixtures for Brew GIS tests."""
from __future__ import annotations

import deal

deal.enable()

from typing import TYPE_CHECKING

import pytest

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
