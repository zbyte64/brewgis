"""Analysis pipeline orchestrator — dispatches Celery tasks for module execution.

Manages the dependency graph between analysis modules and dispatches
Celery tasks in the correct order. The pipeline:

1. Creates an AnalysisRun record to track execution
2. Resolves dependencies between requested modules
3. Dispatches the first module via Celery ``apply_async``
4. A ``handle_module_completed`` callback fires after each module succeeds
5. The callback registers result Layers and dispatches the next module
6. On failure, the AnalysisRun is marked as failed
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

import deal
from django.utils import timezone

from brewgis.workspace.analysis.dbt_runner import run_dbt_local
from brewgis.workspace.analysis.layer_registry import register_result_layer
from brewgis.workspace.analysis.module_registry import MODULE_DEPENDENCIES
from brewgis.workspace.analysis.module_registry import MODULE_RESULT_TABLES
from brewgis.workspace.analysis.module_registry import get_module_label
from brewgis.workspace.analysis.module_registry import get_result_table_names
from brewgis.workspace.analysis.module_registry import get_vars_for_module
from brewgis.workspace.analysis.module_registry import (
    resolve_module_order as _resolve_module_order,
)
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.tasks import handle_module_completed
from brewgis.workspace.tasks import run_dbt_module
from brewgis.workspace.tasks import run_preprocessor_and_dbt

logger = logging.getLogger(__name__)

# All modules use the parameterized ``run_dbt_module`` task by default.
MODULE_TASKS: dict[str, Any] = dict.fromkeys(MODULE_DEPENDENCIES, run_dbt_module)
# Modules that require a preprocessor step before dbt execution.
MODULE_TASKS["internal_capture"] = run_preprocessor_and_dbt
MODULE_TASKS["food_access"] = run_preprocessor_and_dbt
MODULE_TASKS["acs_equity"] = run_preprocessor_and_dbt


@deal.ensure(lambda module_names, result: set(module_names).issubset(set(result)))
@deal.raises(ValueError)
def resolve_module_order(module_names: list[str]) -> list[str]:
    """Resolve requested modules into execution order respecting dependencies.

    This wrapper adds deal contract checking on top of the module_registry
    implementation.
    """
    return _resolve_module_order(module_names)


def _get_vars_for_module(module: str, base_vars: dict[str, Any]) -> dict[str, Any]:
    """Prepare the vars dict for a specific module, inheriting global vars.

    For modules that depend on env_constraint, inject the constraint output
    table name so the core module can reference it.
    """
    return get_vars_for_module(module, base_vars)


def _register_results(
    workspace_id: int,
    module: str,
    task_result: dict[str, Any],
    scenario_id: str,
) -> None:
    """Register dbt result views as Layers in the workspace.

    Args:
        workspace_id: Workspace primary key.
        module: Module name that produced the results.
        task_result: Result dict from the Celery task.
        scenario_id: Scenario identifier for table naming.
    """
    layer_schema = task_result.get("layer_schema")
    if not layer_schema:
        return

    label = get_module_label(module)
    for table_name in get_result_table_names(module, scenario_id):
        register_result_layer(
            workspace_id=workspace_id,
            schema=layer_schema,
            table=table_name,
            name=f"{label} — {scenario_id}",
            description=f"Analysis result for module '{module}' (scenario: {scenario_id})",
        )


def run_analysis_pipeline(
    workspace_id: int,
    module_names: list[str],
    vars_: dict[str, Any] | None = None,
    scenario_id: int | None = None,
) -> AnalysisRun:
    """Create an AnalysisRun record and dispatch the first module via Celery.

    This is the entry point called from views. The actual execution
    happens asynchronously via Celery tasks. Returns immediately with
    the AnalysisRun in 'pending' status; the htmx frontend polls for
    status updates.

    Args:
        workspace_id: Workspace primary key.
        module_names: Modules to execute.
        vars_: dbt variables dict.
        scenario_id: Scenario primary key for the FK binding. When
            provided, also used as fallback for vars_["scenario_id"].

    Returns:
        The AnalysisRun instance (status: pending).
    """
    base_vars = vars_ or {}
    if scenario_id is not None:
        base_vars.setdefault("scenario_id", str(scenario_id))
    else:
        raw_id = base_vars.get(
            "scenario_id", f"run_{timezone.now().strftime('%Y%m%d_%H%M%S')}"
        )
        base_vars.setdefault("scenario_id", raw_id)

    # Resolve execution order
    ordered_modules = resolve_module_order(module_names)
    # Extract column_mapping for separate storage, keep in vars for dbt flow
    column_mapping = base_vars.get("column_mapping", {})

    run = AnalysisRun.objects.create(
        workspace_id=workspace_id,
        scenario_id=scenario_id,
        modules=ordered_modules,
        status="pending",
        vars=base_vars,
        column_mapping=column_mapping,
    )

    logger.info(
        "AnalysisRun #%s created for workspace %s, modules: %s",
        run.pk,
        workspace_id,
        ordered_modules,
    )

    # Dispatch the first module via Celery
    _dispatch_next(run, ordered_modules, base_vars, completed_modules=[])

    return run


def _dispatch_next(
    run: AnalysisRun,
    remaining: list[str],
    base_vars: dict[str, Any],
    completed_modules: list[str],
) -> None:
    """Dispatch the next module via Celery, or mark as completed.

    Each module task is dispatched asynchronously via
    ``apply_async(link=handle_module_completed)``. The link callback
    handles result registration and dispatching subsequent modules.
    """
    if not remaining:
        run.status = "completed"
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at"])
        logger.info("AnalysisRun #%s completed successfully", run.pk)
        return

    module = remaining[0]
    module_vars = _get_vars_for_module(
        module,
        {**base_vars, "completed_modules": list(completed_modules)},
    )

    # Update run status
    run.status = "running"
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])

    task_func = MODULE_TASKS.get(module)
    if task_func is None:
        run.status = "failed"
        run.error_log = f"Unknown module: {module}"
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "error_log", "completed_at"])
        return

    scenario_id = base_vars.get("scenario_id", "default")

    logger.info(
        "Dispatching module '%s' for AnalysisRun #%s",
        module,
        run.pk,
    )

    # Dispatch via Celery with a link callback for the next module
    task_func.apply_async(
        kwargs={
            "workspace_id": run.workspace_id,
            "module": module,
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

def run_modules_sync(  # noqa: PLR0913
    *,
    modules: list[str],
    base_vars: dict[str, Any],
    target_schema: str,
    workspace_id: int,
    scenario_id: str,
    module_selects: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Run dbt modules in dependency order, registering result layers.

    Args:
        modules: Module names to run (e.g. ["env_constraint", "core", "water_demand"]).
        base_vars: Base dbt vars dict (scenario_id, target_schema, etc.).
        target_schema: Schema where result tables are created.
        workspace_id: Workspace PK for layer registration.
        scenario_id: Scenario slug/ID for table name formatting.
        module_selects: Optional per-module dbt select overrides.
            If omitted, each module name is used as the select.

    Returns:
        Dict with keys:
            "success": bool — whether all modules completed
            "completed": list[str] — modules that succeeded
            "results": list[dict] — per-module {module, success, error}
    """
    ordered = resolve_module_order(modules)
    completed: list[str] = []
    results: list[dict[str, Any]] = []

    for module in ordered:
        select = module_selects.get(module, [module]) if module_selects else [module]
        dbt_result = run_dbt_local(
            select=select,
            vars_={**base_vars, "completed_modules": list(completed)},
        )
        if dbt_result.success:
            completed.append(module)
            # Register result layers
            table_names = MODULE_RESULT_TABLES.get(module, [])
            for pattern in table_names:
                table = pattern.format(scenario_id=scenario_id)
                with contextlib.suppress(Exception):
                    register_result_layer(
                        workspace_id=workspace_id,
                        schema=target_schema,
                        table=table,
                    )
        results.append({
            "module": module,
            "success": dbt_result.success,
            "error": dbt_result.error,
        })

    return {
        "success": len(completed) == len(ordered),
        "completed": completed,
        "results": results,
    }
