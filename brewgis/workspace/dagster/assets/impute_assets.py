"""Dagster assets for data imputation/stitching operations.

This module contains assets that wrap dbt models for data imputation
(area-proportional allocation, constant fill, built-form defaults).
These are standalone, config-driven assets — they do not participate in
the broader asset graph (no upstream/downstream dependencies).
"""

from dagster import AssetExecutionContext
from dagster import MaterializeResult
from dagster import asset

from brewgis.workspace.dagster.configs import ImputeAreaProportionalConfig
from brewgis.workspace.dagster.resources.dbt_resource import DbtCliResource


@asset(
    group_name="stitching",
    compute_kind="dbt",
)
def impute_area_proportional_asset(
    context: AssetExecutionContext,  # noqa: ARG001
    config: ImputeAreaProportionalConfig,
    dbt_cli: DbtCliResource,
) -> MaterializeResult:
    """Run area-proportional imputation via dbt.

    Creates a PostGIS view (``impute_area_proportional_{scenario_id}``) that
    COALESCEs original values with area-weighted allocation from intersecting
    source features.  Downstream consumers read the view directly.
    """
    result = dbt_cli.run(
        select=["impute_area_proportional"],
        vars_={
            "source_schema": config.source_schema,
            "source_table": config.source_table,
            "source_column": config.source_column,
            "target_schema": config.target_schema,
            "target_table": config.target_table,
            "target_column": config.target_column,
            "source_geom_col": config.source_geom_col,
            "target_geom_col": config.target_geom_col,
            "scenario_id": config.scenario_id,
        },
    )
    if not result.success:
        msg = f"impute_area_proportional failed: {result.error}"
        raise RuntimeError(msg)

    view_name = f"impute_area_proportional_{config.scenario_id}"
    return MaterializeResult(
        metadata={
            "view": f"{config.target_schema}.{view_name}",
            "source": f"{config.source_schema}.{config.source_table}.{config.source_column}",
            "target": f"{config.target_schema}.{config.target_table}.{config.target_column}",
        },
    )
