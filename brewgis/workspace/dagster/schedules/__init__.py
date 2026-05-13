"""Dagster schedule definitions for periodic data pipeline execution."""

from __future__ import annotations

from dagster import ScheduleDefinition
from dagster import DefaultScheduleStatus

from brewgis.workspace.dagster.assets.dlt_assets import census_acs_assets
from brewgis.workspace.dagster.assets.dlt_assets import lehd_lodes_assets
from brewgis.workspace.dagster.assets.dlt_assets import overpass_poi_assets


# Weekly refresh of Census ACS data (Sundays at 2:00 AM)
census_acs_schedule = ScheduleDefinition(
    name="census_acs_weekly",
    target=census_acs_assets,
    cron_schedule="0 2 * * 0",
    default_status=DefaultScheduleStatus.STOPPED,
    description="Weekly refresh of Census ACS data from dlt pipeline.",
)


# Weekly refresh of LEHD LODES data (Sundays at 3:00 AM)
lehd_lodes_schedule = ScheduleDefinition(
    name="lehd_lodes_weekly",
    target=lehd_lodes_assets,
    cron_schedule="0 3 * * 0",
    default_status=DefaultScheduleStatus.STOPPED,
    description="Weekly refresh of LEHD LODES employment data from dlt pipeline.",
)


# Weekly refresh of Overpass POI data (Sundays at 4:00 AM)
overpass_poi_schedule = ScheduleDefinition(
    name="overpass_poi_weekly",
    target=overpass_poi_assets,
    cron_schedule="0 4 * * 0",
    default_status=DefaultScheduleStatus.STOPPED,
    description="Weekly refresh of OpenStreetMap POI data from Overpass API.",
)


# All schedules registered here for import into definitions.py
SCHEDULES = [
    census_acs_schedule,
    lehd_lodes_schedule,
    overpass_poi_schedule,
]
