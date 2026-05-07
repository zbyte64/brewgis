"""Analysis pipeline orchestrator — chains Celery tasks for module execution.

Manages the dependency graph between analysis modules and dispatches
Celery tasks in the correct order. Currently supports:

    env_constraint → core

The pipeline:
1. Creates an AnalysisRun record to track execution
2. Resolves dependencies between requested modules
3. Chains Celery tasks (env_constraint first, then core)
4. Updates AnalysisRun status on completion/failure
5. Auto-registers result views as Layers
"""

from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone

from brewgis.workspace.analysis.layer_registry import register_result_layer
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.tasks import run_core_module
from brewgis.workspace.tasks import run_env_constraint

logger = logging.getLogger(__name__)

# Module dependency graph: later modules depend on earlier ones
MODULE_DEPENDENCIES: dict[str, list[str]] = {
    "env_constraint": [],
    "core": ["env_constraint"],
}

# Module → Celery task mapping
MODULE_TASKS = {
    "env_constraint": run_env_constraint,
    "core": run_core_module,
}

# Module → result table name template (for layer registration)
MODULE_RESULT_TABLES = {
    "env_constraint": "env_constraint_{scenario_id}",
    "core": ["end_state_{scenario_id}", "increment_{scenario_id}"],
}


def resolve_module_order(module_names: list[str]) -> list[str]:
    """Resolve requested modules into execution order respecting dependencies.

    If module A depends on module B, B must run first. Missing dependencies
    are automatically prepended.

    Args:
        module_names: List of requested module names.

    Returns:
        Ordered list of modules in execution sequence.

    Raises:
        ValueError: If an unknown module name is provided.
    """
    unknown = set(module_names) - set(MODULE_DEPENDENCIES)
    if unknown:
        msg = f"Unknown modules: {', '.join(sorted(unknown))}"
        raise ValueError(msg)

    ordered: list[str] = []
    seen: set[str] = set()

    for module in module_names:
        # Add dependencies first
        for dep in MODULE_DEPENDENCIES.get(module, []):
            if dep not in seen:
                ordered.append(dep)
                seen.add(dep)

        if module not in seen:
            ordered.append(module)
            seen.add(module)

    return ordered


def _get_vars_for_module(module: str, base_vars: dict[str, Any]) -> dict[str, Any]:
    """Prepare the vars dict for a specific module, inheriting global vars.

    For modules that depend on env_constraint, inject the constraint output
    table name so the core module can reference it.
    """
    vars_ = dict(base_vars)

    if module == "core":
        scenario_id = base_vars.get("scenario_id", "default")
        # If env_constraint ran first, reference its output
        if "env_constraint" in base_vars.get("completed_modules", []):
            vars_["constraints_output"] = f"env_constraint_{scenario_id}"

    return vars_


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

    table_templates = MODULE_RESULT_TABLES.get(module, [])
    if isinstance(table_templates, str):
        table_templates = [table_templates]

    for template in table_templates:
        table_name = template.format(scenario_id=scenario_id)
        register_result_layer(
            workspace_id=workspace_id,
            schema=layer_schema,
            table=table_name,
            name=f"{module.replace('_', ' ').title()} — {scenario_id}",
            description=f"Analysis result for module '{module}' (scenario: {scenario_id})",
        )


def run_analysis_pipeline(
    workspace_id: int,
    module_names: list[str],
    vars_: dict[str, Any] | None = None,
) -> AnalysisRun:
    """Create an AnalysisRun record and dispatch the pipeline.

    This is the entry point called from views. The actual execution
    happens asynchronously via Celery tasks.

    Args:
        workspace_id: Workspace primary key.
        module_names: Modules to execute.
        vars: dbt variables dict.

    Returns:
        The AnalysisRun instance (status: pending).
    """
    base_vars = vars_ or {}
    scenario_id = base_vars.get("scenario_id", f"run_{timezone.now().strftime('%Y%m%d_%H%M%S')}")
    base_vars.setdefault("scenario_id", scenario_id)

    # Resolve execution order
    ordered_modules = resolve_module_order(module_names)

    run = AnalysisRun.objects.create(
        workspace_id=workspace_id,
        modules=ordered_modules,
        status="pending",
        vars=base_vars,
    )

    logger.info(
        "AnalysisRun #%s created for workspace %s, modules: %s",
        run.pk,
        workspace_id,
        ordered_modules,
    )

    # Dispatch the first module in the chain
    _dispatch_next(run, ordered_modules, base_vars, completed_modules=[])

    return run


def _dispatch_next(
    run: AnalysisRun,
    remaining: list[str],
    base_vars: dict[str, Any],
    completed_modules: list[str],
) -> None:
    """Dispatch the next module in the chain, or mark as completed.

    Each module task is called with the updated vars (including completed_modules).
    The Celery task is executed synchronously (for now — future enhancement
    would use Celery chains for async execution).
    """
    if not remaining:
        # All modules complete
        run.status = "completed"
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at"])
        logger.info("AnalysisRun #%s completed successfully", run.pk)
        return

    module = remaining[0]
    module_vars = _get_vars_for_module(module, {**base_vars, "completed_modules": completed_modules})

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

    try:
        # Execute the Celery task synchronously
        result = task_func(workspace_id=run.workspace_id, vars_=module_vars)

        if result["success"]:
            # Register result layers
            scenario_id = base_vars.get("scenario_id", "default")
            _register_results(run.workspace_id, module, result, scenario_id)

            # Dispatch next module
            _dispatch_next(run, remaining[1:], base_vars, [*completed_modules, module])
        else:
            run.status = "failed"
            run.error_log = result.get("error", "Unknown error")
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_log", "completed_at"])
            logger.error(
                "AnalysisRun #%s: module %s failed: %s",
                run.pk,
                module,
                run.error_log,
            )
    except Exception as e:
        run.status = "failed"
        run.error_log = str(e)
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "error_log", "completed_at"])
        logger.exception(
            "AnalysisRun #%s: exception in module %s",
            run.pk,
            module,
        )
