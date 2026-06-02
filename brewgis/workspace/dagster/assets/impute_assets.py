"""Dagster assets for data imputation/stitching operations.

These assets wrap SQLMesh model execution for area-proportional
imputation. They are standalone, config-driven assets — they do not
participate in the broader asset graph (no upstream/downstream
dependencies).
"""

from dagster import AssetExecutionContext
from dagster import MaterializeResult
from dagster import asset

from brewgis.workspace.dagster.configs import ImputeAreaProportionalConfig


@asset(
    group_name="stitching",
    compute_kind="python",
)
def impute_area_proportional_asset(
    context: AssetExecutionContext,
    config: ImputeAreaProportionalConfig,
) -> MaterializeResult:
    """Run area-proportional imputation via SQLMesh.

    Delegates to SQLMesh for area-proportional imputation.
    """
    from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_run

    env = "dev"
    context.log.info(
        "Running imputation for %s.%s via SQLMesh (env=%s)",
        config.target_schema,
        config.target_table,
        env,
    )

    result = run_sqlmesh_run(
        environment=env,
        select=["impute_area_proportional"],
    )

    view_name = f"impute_area_proportional_{config.scenario_id}"
    return MaterializeResult(
        metadata={
            "view": f"{config.target_schema}.{view_name}",
            "source": (
                f"{config.source_schema}.{config.source_table}.{config.source_column}"
                if config.source_schema
                else ""
            ),
            "target": (
                f"{config.target_schema}.{config.target_table}.{config.target_column}"
            ),
            "success": result.success,
        },
    )
