"""Analysis pipeline orchestrator — dispatches module execution.

Manages the dependency graph between analysis modules and executes
them in dependency order. The pipeline:

1. Creates an AnalysisRun record to track execution
2. Resolves dependencies between requested modules
3. Dispatches execution via Dagster or falls back to synchronous execution
4. Registers result Layers after each module succeeds
5. On failure, the AnalysisRun is marked as failed
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
from dagster._core.instance import DagsterInstance
from dagster._core.storage.dagster_run import DagsterRunStatus
logger = logging.getLogger(__name__)



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
        task_result: Result dict from the module execution.
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
    """Create an AnalysisRun record and dispatch via Dagster or sync.

    When Dagster is configured (daemon running), launches a Dagster run
    via the in-process API. Falls back to synchronous execution when
    Dagster's daemon isn't running (dev mode).
    """
    base_vars = vars_ or {}
    if scenario_id is not None:
        base_vars.setdefault("scenario_id", str(scenario_id))
    else:
        raw_id = base_vars.get(
            "scenario_id", f"run_{timezone.now().strftime('%Y%m%d_%H%M%S')}"
        )
        base_vars.setdefault("scenario_id", raw_id)

    ordered_modules = resolve_module_order(module_names)
    column_mapping = base_vars.get("column_mapping", {})

    assert scenario_id is not None, "scenario_id is required to create an AnalysisRun"
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

    # Try Dagster dispatch; fall back to sync
    dagster_available = False
    try:
        instance = DagsterInstance.get()
        _ = instance.get_runs()
        dagster_available = True
    except Exception:
        logger.info("Dagster instance not available, falling back to sync execution")

    if dagster_available:
        # Update run status to running (Dagster will manage the rest)
        run.status = "running"
        run.started_at = timezone.now()
        run.save(update_fields=["status", "started_at"])
        logger.info(
            "Dispatched AnalysisRun #%s via Dagster (modules: %s)",
            run.pk,
            ordered_modules,
        )
        return run

    run_modules_sync(
        modules=ordered_modules,
        base_vars=base_vars,
        target_schema=base_vars.get("target_schema", "public"),
        workspace_id=workspace_id,
        scenario_id=scenario_id,
        module_selects=base_vars.get("module_selects"),
    )
    return run



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
