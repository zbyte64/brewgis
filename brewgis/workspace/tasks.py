# ruff: noqa: ANN001, ARG001
"""Celery tasks for analysis pipeline execution."""
from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from celery.utils.log import get_task_logger

from brewgis.workspace.analysis.data_export import export_building_types
from brewgis.workspace.analysis.dbt_runner import DbtRunnerWrapper
from brewgis.workspace.analysis.layer_registry import register_result_layer
from brewgis.workspace.models import AnalysisRun

logger = get_task_logger(__name__)
_plain_logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────
#  Data export (prerequisite for core module)
# ────────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    name="export_building_types",
    autoretry_for=(RuntimeError,),
    max_retries=2,
    default_retry_delay=30,
)
def export_building_types_task(
    self,
    schema: str = "public",
    table: str = "built_forms",
    **kwargs: Any,
) -> dict:
    """Export BuildingType Django records to a flat PostGIS table for dbt.

    Creates ``{schema}.{table}`` with columns matching the
    ``core_end_state`` dbt model's expectations.

    Returns:
        Dict with keys: success, count, error.
    """
    try:
        count = export_building_types(schema=schema, table=table)
        logger.info(
            "Built form export complete: %d rows in %s.%s",
            count,
            schema,
            table,
        )
        return {"success": True, "count": count, "error": None}
    except Exception as e:
        logger.exception("Built form export failed")
        return {"success": False, "count": 0, "error": str(e)}


# ────────────────────────────────────────────────────────────
#  Analysis module tasks
# ────────────────────────────────────────────────────────────


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

    Before running dbt, ensures the built_forms export table exists by
    calling :func:`export_building_types`.

    Args:
        workspace_id: Workspace primary key.
        vars_: dbt variables dict.

    Returns:
        Dict with keys: success, results, error, end_state_table,
        increment_table, layer_schema.
    """
    resolved_vars = vars_ or {}
    logger.info(
        "Running core module for workspace %s with vars: %s",
        workspace_id,
        resolved_vars,
    )

    # Ensure the built_forms export table exists before running dbt
    source_schema = resolved_vars.get("source_schema", "public")
    built_form_table = resolved_vars.get("built_form_table", "built_forms")
    try:
        export_building_types(schema=source_schema, table=built_form_table)
    except Exception:
        logger.exception(
            "Built form export failed before core module run (workspace %s)",
            workspace_id,
        )
        return {
            "success": False,
            "results": [],
            "error": "Failed to export built form data from Django models",
            "end_state_table": None,
            "increment_table": None,
            "layer_schema": None,
        }

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


# ────────────────────────────────────────────────────────────
#  Water & Energy Demand tasks
# ────────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    name="run_water_demand",
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def run_water_demand(
    self,
    workspace_id: int,
    vars_: dict | None = None,
) -> dict:
    """Run the Water Demand dbt model.

    Computes residential and non-residential water demand from the
    end-state allocation table.

    Args:
        workspace_id: Workspace primary key.
        vars_: dbt variables dict.

    Returns:
        Dict with keys: success, results, error, layer_schema, layer_table.
    """
    resolved_vars = vars_ or {}
    logger.info(
        "Running water_demand for workspace %s with vars: %s",
        workspace_id,
        resolved_vars,
    )

    runner = DbtRunnerWrapper()
    dbt_result = runner.run(
        select=["water_demand"],
        vars_=resolved_vars,
        full_refresh=True,
    )

    if dbt_result.success:
        target_schema = resolved_vars.get("target_schema", "public")
        scenario_id = resolved_vars.get("scenario_id", "default")
        logger.info(
            "water_demand completed for workspace %s (scenario %s)",
            workspace_id,
            scenario_id,
        )
        return {
            "success": True,
            "results": dbt_result.results,
            "error": None,
            "layer_schema": target_schema,
            "layer_table": f"water_demand_{scenario_id}",
        }

    error_msg = dbt_result.error or "Unknown dbt error"
    logger.error(
        "water_demand failed for workspace %s: %s",
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
    name="run_energy_demand",
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def run_energy_demand(
    self,
    workspace_id: int,
    vars_: dict | None = None,
) -> dict:
    """Run the Energy Demand dbt model.

    Computes residential and non-residential energy demand (electricity + gas)
    from the end-state allocation table.

    Args:
        workspace_id: Workspace primary key.
        vars_: dbt variables dict.

    Returns:
        Dict with keys: success, results, error, layer_schema, layer_table.
    """
    resolved_vars = vars_ or {}
    logger.info(
        "Running energy_demand for workspace %s with vars: %s",
        workspace_id,
        resolved_vars,
    )

    runner = DbtRunnerWrapper()
    dbt_result = runner.run(
        select=["energy_demand"],
        vars_=resolved_vars,
        full_refresh=True,
    )

    if dbt_result.success:
        target_schema = resolved_vars.get("target_schema", "public")
        scenario_id = resolved_vars.get("scenario_id", "default")
        logger.info(
            "energy_demand completed for workspace %s (scenario %s)",
            workspace_id,
            scenario_id,
        )
        return {
            "success": True,
            "results": dbt_result.results,
            "error": None,
            "layer_schema": target_schema,
            "layer_table": f"energy_demand_{scenario_id}",
        }

    error_msg = dbt_result.error or "Unknown dbt error"
    logger.error(
        "energy_demand failed for workspace %s: %s",
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


# ────────────────────────────────────────────────────────────
#  Pipeline chain callback
# ────────────────────────────────────────────────────────────


@shared_task(
    name="handle_module_completed",
    max_retries=0,
)
def handle_module_completed(
    task_result: dict,
    run_id: int,
    workspace_id: int,
    remaining: list[str],
    base_vars: dict[str, Any],
    completed_modules: list[str],
    scenario_id: str,
) -> None:
    """Callback fired after each module task completes successfully.

    Receives the parent task's return value as ``task_result`` (the first
    positional argument from the Celery ``link``), plus keyword args
    from the :meth:`celery.s` signature in ``_dispatch_next``.

    If the module succeeded, result layers are registered and the next
    module is dispatched.  On failure, the AnalysisRun is marked as
    failed.
    """
    try:
        run = AnalysisRun.objects.get(pk=run_id)
    except AnalysisRun.DoesNotExist:
        _plain_logger.error(
            "handle_module_completed: AnalysisRun #%s not found",
            run_id,
        )
        return

    if not task_result.get("success"):
        run.status = "failed"
        run.error_log = task_result.get("error", "Module task returned failure")
        run.completed_at = __import__("django").utils.timezone.now()
        run.save(update_fields=["status", "error_log", "completed_at"])
        _plain_logger.error(
            "AnalysisRun #%s: module %s failed: %s",
            run_id,
            completed_modules[-1] if completed_modules else "unknown",
            run.error_log,
        )
        return

    # Register result layers for the completed module
    module = completed_modules[-1] if completed_modules else "unknown"
    _register_module_results(workspace_id, module, task_result, scenario_id)

    # Dispatch the next module
    _dispatch_next_in_task(run, remaining, base_vars, completed_modules)


def _register_module_results(
    workspace_id: int,
    module: str,
    task_result: dict,
    scenario_id: str,
) -> None:
    """Register dbt result views as Layers (lightweight, no django import cycle)."""
    layer_schema = task_result.get("layer_schema")
    if not layer_schema:
        return

    # Module → result table name templates (mirrors pipeline.MODULE_RESULT_TABLES)
    table_templates: list[str] = []
    if module == "env_constraint":
        table_templates = [f"env_constraint_{scenario_id}"]
    elif module == "core":
        table_templates = [
            f"end_state_{scenario_id}",
            f"increment_{scenario_id}",
        ]
    elif module == "water_demand":
        table_templates = [f"water_demand_{scenario_id}"]
    elif module == "energy_demand":
        table_templates = [f"energy_demand_{scenario_id}"]

    for table_name in table_templates:
        register_result_layer(
            workspace_id=workspace_id,
            schema=layer_schema,
            table=table_name,
            name=f"{module.replace('_', ' ').title()} — {scenario_id}",
            description=f"Analysis result for module '{module}' (scenario: {scenario_id})",
        )


def _dispatch_next_in_task(
    run: AnalysisRun,
    remaining: list[str],
    base_vars: dict[str, Any],
    completed_modules: list[str],
) -> None:
    """Dispatch the next module from within a Celery task context.

    Mirrors :func:`pipeline._dispatch_next` but operates on a fresh
    AnalysisRun instance loaded from the database (no stale object).
    """
    if not remaining:
        run.status = "completed"
        run.completed_at = __import__("django").utils.timezone.now()
        run.save(update_fields=["status", "completed_at"])
        _plain_logger.info("AnalysisRun #%s completed successfully", run.pk)
        return

    # Avoid circular import: tasks → pipeline → tasks
    from brewgis.workspace.analysis.pipeline import (  # noqa: PLC0415, I001
        _get_vars_for_module,
        MODULE_TASKS,
    )

    module = remaining[0]
    module_vars = _get_vars_for_module(
        module,
        {**base_vars, "completed_modules": list(completed_modules)},
    )

    run.status = "running"
    run.started_at = __import__("django").utils.timezone.now()
    run.save(update_fields=["status", "started_at"])

    scenario_id = base_vars.get("scenario_id", "default")

    task_func = MODULE_TASKS.get(module)
    if task_func is None:
        run.status = "failed"
        run.error_log = f"Unknown module: {module}"
        run.completed_at = __import__("django").utils.timezone.now()
        run.save(update_fields=["status", "error_log", "completed_at"])
        return

    _plain_logger.info(
        "Dispatching next module '%s' for AnalysisRun #%s",
        module,
        run.pk,
    )

    task_func.apply_async(
        kwargs={
            "workspace_id": run.workspace_id,
            "vars_": module_vars,
        },
        link=handle_module_completed.s(
            run_id=run.pk,
            workspace_id=run.workspace_id,
            remaining=remaining[1:],
            base_vars=base_vars,
            completed_modules=[*completed_modules, module],
            scenario_id=scenario_id,
        ),
    )
