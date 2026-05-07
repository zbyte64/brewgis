# ruff: noqa: ANN001, ARG001
"""Celery tasks for analysis pipeline execution."""
from __future__ import annotations

from celery import shared_task
from celery.utils.log import get_task_logger

from brewgis.workspace.analysis.dbt_runner import DbtRunnerWrapper

logger = get_task_logger(__name__)


@shared_task(
    bind=True,
    name="run_env_constraint",
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def run_env_constraint(
    self,
    workspace_id: int,
    vars_: dict | None = None,
) -> dict:
    """Run the Environmental Constraint dbt model.

    Args:
        workspace_id: Workspace primary key (used for layer registration).
        vars_: dbt variables dict. Expected keys:
            - source_schema: Schema containing source tables.
            - parcel_table: Table name for parcels.
            - constraints: JSON list of constraint layer definitions.
            - target_schema: Schema for output.
            - scenario_id: Unique scenario identifier.

    Returns:
        Dict with keys: success, results, error, layer_schema, layer_table.
    """
    resolved_vars = vars_ or {}
    logger.info(
        "Running env_constraint for workspace %s with vars: %s",
        workspace_id,
        resolved_vars,
    )

    runner = DbtRunnerWrapper()
    dbt_result = runner.run(
        select=["env_constraint"],
        vars_=resolved_vars,
        full_refresh=True,
    )

    if dbt_result.success:
        target_schema = resolved_vars.get("target_schema", "public")
        scenario_id = resolved_vars.get("scenario_id", "default")
        logger.info(
            "env_constraint completed for workspace %s (scenario %s)",
            workspace_id,
            scenario_id,
        )
        return {
            "success": True,
            "results": dbt_result.results,
            "error": None,
            "layer_schema": target_schema,
            "layer_table": f"env_constraint_{scenario_id}",
        }

    error_msg = dbt_result.error or "Unknown dbt error"
    logger.error(
        "env_constraint failed for workspace %s: %s",
        workspace_id,
        error_msg,
    )
    return {
        "success": False,
        "results": [],
        "error": error_msg,
        "layer_schema": None,
        "layer_table": None,
    }


@shared_task(
    bind=True,
    name="run_core_module",
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def run_core_module(
    self,
    workspace_id: int,
    vars_: dict | None = None,
) -> dict:
    """Run the Core / Scenario Builder dbt models (end_state + increment).

    Args:
        workspace_id: Workspace primary key.
        vars_: dbt variables dict.

    Returns:
        Dict with keys: success, results, error, end_state_table, increment_table.
    """
    resolved_vars = vars_ or {}
    logger.info(
        "Running core module for workspace %s with vars: %s",
        workspace_id,
        resolved_vars,
    )

    runner = DbtRunnerWrapper()
    dbt_result = runner.run(
        select=["core_end_state", "core_increment"],
        vars_=resolved_vars,
        full_refresh=True,
    )

    if dbt_result.success:
        target_schema = resolved_vars.get("target_schema", "public")
        scenario_id = resolved_vars.get("scenario_id", "default")
        logger.info(
            "Core module completed for workspace %s (scenario %s)",
            workspace_id,
            scenario_id,
        )
        return {
            "success": True,
            "results": dbt_result.results,
            "error": None,
            "end_state_table": f"end_state_{scenario_id}",
            "increment_table": f"increment_{scenario_id}",
            "layer_schema": target_schema,
        }

    error_msg = dbt_result.error or "Unknown dbt error"
    logger.error(
        "Core module failed for workspace %s: %s",
        workspace_id,
        error_msg,
    )
    return {
        "success": False,
        "results": [],
        "error": error_msg,
        "end_state_table": None,
        "increment_table": None,
        "layer_schema": None,
    }
