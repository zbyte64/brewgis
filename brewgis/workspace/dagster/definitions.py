"""Dagster ``Definitions`` object — the top-level configuration.

Registers all assets, resources, schedules, and sensors for the Brew GIS
data orchestration platform.
"""

from __future__ import annotations

from dagster import AssetSpec
from dagster import Definitions
from dagster import ScheduleDefinition
from dagster_embedded_elt.dlt import DagsterDltResource

from brewgis.workspace.dagster.assets.comparison_assets import sacog_generate_report
from brewgis.workspace.dagster.assets.comparison_assets import sacog_load_parcels
from brewgis.workspace.dagster.assets.comparison_assets import (
    sacog_populate_acs_block_group,
)
from brewgis.workspace.dagster.assets.comparison_assets import (
    sacog_populate_geography_id,
)
from brewgis.workspace.dagster.assets.comparison_assets import sacog_populate_wac_block
from brewgis.workspace.dagster.assets.comparison_assets import sacog_verify_geometry
from brewgis.workspace.dagster.assets.comparison_assets import tiger_bg_asset
from brewgis.workspace.dagster.assets.dlt_assets import census_acs_assets
from brewgis.workspace.dagster.assets.dlt_assets import lehd_lodes_assets
from brewgis.workspace.dagster.assets.dlt_assets import overpass_poi_assets
from brewgis.workspace.dagster.assets.dlt_assets import raster_band_assets
from brewgis.workspace.dagster.assets.dlt_assets import raster_metadata_assets
from brewgis.workspace.dagster.assets.download_assets import fresno_demo_data
from brewgis.workspace.dagster.assets.impute_assets import (
    impute_area_proportional_asset,
)
from brewgis.workspace.dagster.assets.service_assets import assign_built_forms
from brewgis.workspace.dagster.assets.service_assets import base_canvas_etl
from brewgis.workspace.dagster.assets.service_assets import create_fresno_scenario
from brewgis.workspace.dagster.assets.service_assets import fresno_constraints
from brewgis.workspace.dagster.assets.service_assets import imputation
from brewgis.workspace.dagster.assets.service_assets import onboard_geography
from brewgis.workspace.dagster.assets.service_assets import spatial_allocation
from brewgis.workspace.dagster.jobs.fresno_demo import fresno_demo_setup
from brewgis.workspace.dagster.jobs.impute_jobs import impute_area_proportional_job
from brewgis.workspace.dagster.resources.postgres_resource import PostgresResource
from brewgis.workspace.dagster.schedules import SCHEDULES

# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

_postgres_resource = PostgresResource()
_dlt_resource = DagsterDltResource()

_RESOURCES = {
    "dlt": _dlt_resource,
    "postgres": _postgres_resource,
}

# ---------------------------------------------------------------------------
# Assets — full list of all software-defined assets
# ---------------------------------------------------------------------------

_ASSETS = [
    # dlt extraction assets
    AssetSpec(key="raw_parcels"),
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
    impute_area_proportional_asset,
    base_canvas_etl,
    onboard_geography,
    fresno_constraints,
    assign_built_forms,
    create_fresno_scenario,
    # comparison assets
    sacog_load_parcels,
    tiger_bg_asset,
    sacog_populate_acs_block_group,
    sacog_populate_wac_block,
    sacog_verify_geometry,
    sacog_populate_geography_id,
    sacog_generate_report,
]

# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

_JOBS = [
    impute_area_proportional_job,
    fresno_demo_setup,
]

# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

_SCHEDULES: list[ScheduleDefinition] = list(SCHEDULES)

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
