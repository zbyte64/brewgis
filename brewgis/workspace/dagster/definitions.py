"""Dagster ``Definitions`` object — the top-level configuration.

Registers all assets, resources, schedules, and sensors for the Brew GIS
data orchestration platform.
"""

from __future__ import annotations

from dagster import Definitions
from dagster import ScheduleDefinition

from brewgis.workspace.dagster.assets.calibration_assets import sacog_comparison
from brewgis.workspace.dagster.assets.dbt_assets import ANALYSIS_ASSETS
from brewgis.workspace.dagster.assets.dbt_assets import acs_equity_preprocessor
from brewgis.workspace.dagster.assets.dbt_assets import building_types_export
from brewgis.workspace.dagster.assets.dbt_assets import dbt_staging_models
from brewgis.workspace.dagster.assets.dbt_assets import food_access_preprocessor
from brewgis.workspace.dagster.assets.dbt_assets import internal_capture_preprocessor
from brewgis.workspace.dagster.assets.dlt_assets import census_acs_assets
from brewgis.workspace.dagster.assets.dlt_assets import lehd_lodes_assets
from brewgis.workspace.dagster.assets.dlt_assets import overpass_poi_assets
from brewgis.workspace.dagster.assets.dlt_assets import raster_band_assets
from brewgis.workspace.dagster.assets.dlt_assets import raster_metadata_assets
from brewgis.workspace.dagster.assets.download_assets import fresno_demo_data
from brewgis.workspace.dagster.assets.service_assets import assign_built_forms
from brewgis.workspace.dagster.assets.service_assets import base_canvas_etl
from brewgis.workspace.dagster.assets.service_assets import create_fresno_scenario
from brewgis.workspace.dagster.assets.service_assets import fresno_constraints
from brewgis.workspace.dagster.assets.service_assets import imputation
from brewgis.workspace.dagster.assets.service_assets import onboard_geography
from brewgis.workspace.dagster.assets.service_assets import spatial_allocation
from brewgis.workspace.dagster.jobs.fresno_demo import fresno_demo_setup
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
    # download assets
    fresno_demo_data,
    # service-layer ETL assets
    spatial_allocation,
    imputation,
    base_canvas_etl,
    onboard_geography,
    fresno_constraints,
    assign_built_forms,
    create_fresno_scenario,
    # calibration assets
    sacog_comparison,
    # preprocessing assets
    building_types_export,
    internal_capture_preprocessor,
    food_access_preprocessor,
    acs_equity_preprocessor,
    # dbt model assets
    dbt_staging_models,
    *ANALYSIS_ASSETS,
]

# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

_JOBS = [
    fresno_demo_setup,
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
    jobs=_JOBS,
    schedules=_SCHEDULES,
    sensors=_SENSORS,
)
