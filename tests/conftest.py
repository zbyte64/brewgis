"""Shared pytest fixtures for Brew GIS tests."""

from __future__ import annotations

import os

import deal
import hypothesis
from hypothesis import HealthCheck

# Conditionally enable deal contract checking.
# Only enabled when DEAL_ENABLED=1 (set by `make test-deal`).
if os.environ.get("DEAL_ENABLED") == "1":
    deal.enable()
else:
    deal.disable()

# Hypothesis profile selection.
# Set HYPOTHESIS_PROFILE env var, or auto-detect CI environment.
_HYPOTHESIS_PROFILE = os.environ.get(
    "HYPOTHESIS_PROFILE",
    "ci" if os.environ.get("CI") else "local",
)

hypothesis.settings.register_profile(
    "ci",
    deadline=2000,
    max_examples=10,
    suppress_health_check=[HealthCheck.too_slow],
)
hypothesis.settings.register_profile(
    "local",
    deadline=None,
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
)
hypothesis.settings.load_profile(_HYPOTHESIS_PROFILE)
from typing import TYPE_CHECKING

import pytest
from django.db import connection

from tests.factories import BuildingTypeFactory
from tests.factories import LayerFactory
from tests.factories import PlaceTypeBuildingTypeMixFactory
from tests.factories import PlaceTypeFactory
from tests.factories import ScenarioFactory
from tests.factories import SymbologyConfigFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from brewgis.workspace.built_forms.models import BuildingType
    from brewgis.workspace.built_forms.models import PlaceType
    from brewgis.workspace.built_forms.models import PlaceTypeBuildingTypeMix
    from brewgis.workspace.models import Layer
    from brewgis.workspace.models import Scenario
    from brewgis.workspace.models import SymbologyConfig
    from brewgis.workspace.models import Workspace


# NOTE: This fixture differs from brewgis/conftest.py's `user` fixture.
#
# brewgis/conftest.py creates a user directly:
#   UserModel.objects.create_user(username="testuser", password="testpass")
#
# This fixture uses UserFactory (from tests/factories.py), which sets password
# via _generate and may set email differently.
#
# These are intentionally separate — the brewgis fixture is used by management
# commands and production-like workflows; the tests fixture is the standard for
# pytest-based tests. If email-related issues arise with allauth, migrate both
# to a shared factory pattern.
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
def mix(
    db, place_type: PlaceType, building_type: BuildingType
) -> PlaceTypeBuildingTypeMix:
    return PlaceTypeBuildingTypeMixFactory(
        place_type=place_type, building_type=building_type
    )


@pytest.fixture
def base_canvas_table(db) -> str:
    """Create a base canvas table with the full schema + synthetic data.

    Creates ``public.base_canvas`` using
    :class:`~brewgis.workspace.services.base_canvas_manager.BaseCanvasManager`,
    then inserts two rows of synthetic data for tests that query the table
    (canvas view manager, scenario cloning).

    .. note::

        Requires PostgreSQL + PostGIS. The extension is enabled explicitly
        because Django's test database template may not include it.
    """
    from brewgis.workspace.services.base_canvas_manager import BaseCanvasManager
    from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

    BaseCanvasManager.create_table()

    # Build column list for INSERT — all non-geometry columns, include id for stable ids
    insert_cols = [name for name in BaseCanvasSchema.COLUMN_NAMES if name != "geometry"]
    col_list = ", ".join(insert_cols)
    placeholders = ", ".join(f"%({name})s" for name in insert_cols)

    def _row(*, du: float, pop: float, hh: float, ldc: str = "urban") -> dict:
        """Build a row dict with defaults for all non-null columns."""
        row: dict[str, object] = {
            "land_development_category": ldc,
            "du": du,
            "pop": pop,
            "hh": hh,
            "intersection_density": 12.5,
            "area_gross": 10.0,
            "area_parcel": 8.0,
            "area_dev_condition": 6.0,
            "area_row": 2.0,
            "area_parcel_res_detsf": 3.0,
            "area_parcel_res_detsf_sl": 1.5,
            "area_parcel_res_detsf_ll": 1.5,
            "area_parcel_res_attsf": 1.0,
            "area_parcel_res_mf": 2.0,
            "area_parcel_res": 5.0,
            "area_parcel_emp": 2.0,
            "area_parcel_emp_ret": 0.5,
            "area_parcel_emp_off": 0.5,
            "area_parcel_emp_pub": 0.3,
            "area_parcel_emp_ind": 0.5,
            "area_parcel_emp_ag": 0.1,
            "area_parcel_emp_military": 0.0,
            "area_parcel_mixed_use": 1.0,
            "area_parcel_no_use": 0.0,
            "pop_groupquarter": 0.0,
            "du_detsf": 80.0,
            "du_detsf_sl": 40.0,
            "du_detsf_ll": 40.0,
            "du_attsf": 10.0,
            "du_mf": 10.0,
            "du_mf2to4": 4.0,
            "du_mf5p": 6.0,
            "emp": 50.0,
            "emp_ret": 10.0,
            "emp_retail_services": 5.0,
            "emp_restaurant": 3.0,
            "emp_accommodation": 1.0,
            "emp_arts_entertainment": 1.0,
            "emp_other_services": 2.0,
            "emp_off": 15.0,
            "emp_office_services": 8.0,
            "emp_medical_services": 5.0,
            "emp_pub": 10.0,
            "emp_public_admin": 4.0,
            "emp_education": 5.0,
            "emp_ind": 15.0,
            "emp_manufacturing": 5.0,
            "emp_wholesale": 3.0,
            "emp_transport_warehousing": 3.0,
            "emp_utilities": 1.0,
            "emp_construction": 2.0,
            "emp_ag": 1.0,
            "emp_agriculture": 0.5,
            "emp_extraction": 0.0,
            "emp_military": 0.0,
            "bldg_area_detsf_sl": 8000.0,
            "bldg_area_detsf_ll": 6000.0,
            "bldg_area_attsf": 4000.0,
            "bldg_area_mf": 5000.0,
            "bldg_area_retail_services": 2000.0,
            "bldg_area_restaurant": 1500.0,
            "bldg_area_accommodation": 1000.0,
            "bldg_area_arts_entertainment": 800.0,
            "bldg_area_other_services": 600.0,
            "bldg_area_office_services": 3000.0,
            "bldg_area_public_admin": 2000.0,
            "bldg_area_education": 4000.0,
            "bldg_area_medical_services": 2500.0,
            "bldg_area_transport_warehousing": 3000.0,
            "bldg_area_wholesale": 2000.0,
            "residential_irrigated_area": 0.5,
            "commercial_irrigated_area": 0.2,
        }
        # Nullable columns
        row["id_source"] = None
        row["geometry_key"] = None
        row["built_form_key"] = None
        return row

    row1 = _row(du=100.0, pop=250.0, hh=80.0)
    row1["id"] = 1
    row2 = _row(du=50.0, pop=120.0, hh=40.0)
    row2["id"] = 2

    with connection.cursor() as cursor:
        for row in [row1, row2]:
            stmt = (
                f"INSERT INTO public.base_canvas (geometry, {col_list}) "
                f"VALUES (ST_SetSRID(ST_MakeEnvelope(0, 0, 1, 1), 4326)::GEOMETRY(POLYGON, 4326), {placeholders})"
            )
            cursor.execute(stmt, row)

    yield "public.base_canvas"
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS public.base_canvas CASCADE")


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
