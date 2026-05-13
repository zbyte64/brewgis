"""Dagster ``Definitions`` object — the top-level configuration.

Registers all assets, resources, schedules, and sensors for the Brew GIS
data orchestration platform.
"""

from __future__ import annotations

from dagster import Definitions
from dagster import ScheduleDefinition

from brewgis.workspace.dagster.assets.dbt_assets import dbt_core_allocation
from brewgis.workspace.dagster.assets.dbt_assets import dbt_env_constraint
from brewgis.workspace.dagster.assets.dbt_assets import dbt_impact_modules
from brewgis.workspace.dagster.assets.dbt_assets import dbt_staging_models
from brewgis.workspace.dagster.assets.dbt_assets import dbt_transport
from brewgis.workspace.dagster.assets.dlt_assets import census_acs_assets
from brewgis.workspace.dagster.assets.dlt_assets import lehd_lodes_assets
from brewgis.workspace.dagster.assets.dlt_assets import overpass_poi_assets
from brewgis.workspace.dagster.assets.dlt_assets import raster_band_assets
from brewgis.workspace.dagster.assets.dlt_assets import raster_metadata_assets
from brewgis.workspace.dagster.assets.service_assets import base_canvas_etl
from brewgis.workspace.dagster.assets.service_assets import imputation
from brewgis.workspace.dagster.assets.service_assets import spatial_allocation
from brewgis.workspace.dagster.resources.dbt_resource import DbtCliResource
from brewgis.workspace.dagster.resources.postgres_resource import PostgresResource

# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

_dbt_cli_resource = DbtCliResource()
_postgres_resource = PostgresResource()

_RESOURCES = {
    "dbt_cli": _dbt_cli_resource,
    "postgres": _postgres_resource,
}

# ---------------------------------------------------------------------------
# Assets — full list of all software-defined assets
# ---------------------------------------------------------------------------

_ASSETS = [
    # dlt extraction assets
    census_acs_assets,
    lehd_lodes_assets,
    overpass_poi_assets,
    # raster extraction assets
    raster_metadata_assets,
    raster_band_assets,
    # service-layer ETL assets
    spatial_allocation,
    imputation,
    base_canvas_etl,
    # dbt model assets
    dbt_staging_models,
    dbt_env_constraint,
    dbt_core_allocation,
    dbt_transport,
    dbt_impact_modules,
]

# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

_SCHEDULES: list[ScheduleDefinition] = []

# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------

_SENSORS: list = []

# ---------------------------------------------------------------------------
# Top-level Definitions
# ---------------------------------------------------------------------------

defs = Definitions(
    assets=_ASSETS,
    resources=_RESOURCES,
    schedules=_SCHEDULES,
    sensors=_SENSORS,
)
