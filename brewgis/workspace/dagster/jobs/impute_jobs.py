"""Dagster job definitions for data imputation operations."""

from dagster import job

from brewgis.workspace.dagster.assets.impute_assets import (
    impute_area_proportional_asset,
)


@job(
    name="impute_area_proportional",
    description="Run area-proportional imputation via dbt.",
)
def impute_area_proportional_job() -> None:
    """Execute the impute_area_proportional dbt model.

    Creates a PostGIS view that COALESCEs original values with
    area-weighted allocation from intersecting source features.
    """
    impute_area_proportional_asset()
