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

import logging
from typing import Any

import deal
from django.utils import timezone

from brewgis.workspace.analysis.layer_registry import register_result_layer
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.tasks import handle_module_completed
from brewgis.workspace.tasks import run_agriculture
from brewgis.workspace.tasks import run_core_module
from brewgis.workspace.tasks import run_energy_demand
from brewgis.workspace.tasks import run_env_constraint
from brewgis.workspace.tasks import run_fiscal
from brewgis.workspace.tasks import run_land_consumption
from brewgis.workspace.tasks import run_water_demand
from brewgis.workspace.tasks import run_trip_generation
from brewgis.workspace.tasks import run_trip_distribution
from brewgis.workspace.tasks import run_mode_choice
from brewgis.workspace.tasks import run_vmt

logger = logging.getLogger(__name__)

# Module dependency graph: later modules depend on earlier ones
MODULE_DEPENDENCIES: dict[str, list[str]] = {
    "env_constraint": [],
    "core": ["env_constraint"],
    "water_demand": ["core"],
    "energy_demand": ["core"],
    "land_consumption": ["core"],
    "fiscal": ["core"],
    "agriculture": ["core"],
    "trip_generation": ["core"],
    "trip_distribution": ["trip_generation"],
    "mode_choice": ["trip_distribution"],
    "vmt": ["mode_choice"],
}

# Module → Celery task mapping
MODULE_TASKS = {
    "env_constraint": run_env_constraint,
    "core": run_core_module,
    "water_demand": run_water_demand,
    "energy_demand": run_energy_demand,
    "land_consumption": run_land_consumption,
    "fiscal": run_fiscal,
    "agriculture": run_agriculture,
    "trip_generation": run_trip_generation,
    "trip_distribution": run_trip_distribution,
    "mode_choice": run_mode_choice,
    "vmt": run_vmt,
}
MODULE_RESULT_TABLES = {
    "env_constraint": "env_constraint_{scenario_id}",
    "core": ["end_state_{scenario_id}", "increment_{scenario_id}"],
    "water_demand": "water_demand_{scenario_id}",
    "energy_demand": "energy_demand_{scenario_id}",
    "land_consumption": [
        "land_consumption_{scenario_id}",
        "impervious_surface_{scenario_id}",
    ],
    "fiscal": [
        "fiscal_property_tax_{scenario_id}",
        "fiscal_sales_tax_{scenario_id}",
        "fiscal_service_costs_{scenario_id}",
        "fiscal_net_impact_{scenario_id}",
    ],
    "agriculture": "agriculture_{scenario_id}",
    "trip_generation": "trip_generation_{scenario_id}",
    "trip_distribution": "trip_distribution_{scenario_id}",
    "mode_choice": "mode_choice_{scenario_id}",
    "vmt": "vmt_{scenario_id}",
}


@deal.ensure(lambda module_names, result: set(result) == set(module_names))
@deal.raises(ValueError)
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
            target_schema = base_vars.get("target_schema", "public")
            vars_["constraints_output"] = f"{target_schema}.env_constraint_{scenario_id}"

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
    """Create an AnalysisRun record and dispatch the first module via Celery.

    This is the entry point called from views. The actual execution
    happens asynchronously via Celery tasks. Returns immediately with
    the AnalysisRun in 'pending' status; the htmx frontend polls for
    status updates.

    Args:
        workspace_id: Workspace primary key.
        module_names: Modules to execute.
        vars_: dbt variables dict.

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
        # All modules complete
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
