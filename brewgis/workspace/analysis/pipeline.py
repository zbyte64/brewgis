"""Analysis pipeline orchestrator — dispatches module execution.

Manages the dependency graph between analysis modules and executes
them in dependency order via SQLMesh. The pipeline:

1. Creates an AnalysisRun record to track execution
2. Resolves dependencies between requested modules
3. Runs all modules through a single SQLMesh plan
4. Registers result Layers after the plan completes
5. On failure, the AnalysisRun is marked as failed
"""

from __future__ import annotations

import logging
from typing import Any

import deal
from django.utils import timezone

from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan, SqlmeshResult
from brewgis.workspace.analysis.layer_registry import register_result_layer
from brewgis.workspace.analysis.module_registry import MODULE_RESULT_TABLES
from brewgis.workspace.analysis.module_registry import get_vars_for_module
from brewgis.workspace.analysis.module_registry import (
    resolve_module_order as _resolve_module_order,
)
from brewgis.workspace.models import AnalysisRun

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


def run_analysis_pipeline(
    workspace_id: int,
    module_names: list[str],
    vars_: dict[str, Any] | None = None,
    scenario_id: int | None = None,
) -> AnalysisRun:
    """Create an AnalysisRun record and execute via SQLMesh.

    SQLMesh handles DAG traversal automatically — all modules run
    in a single plan call.
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

    run_modules_sync(
        modules=ordered_modules,
        base_vars=base_vars,
        target_schema=base_vars.get("target_schema", "public"),
        workspace_id=workspace_id,
        scenario_id=str(scenario_id),
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
    """Run analysis modules via SQLMesh, registering result layers.

    Args:
        modules: Module names to run (e.g. ["env_constraint", "core", "water_demand"]).
        base_vars: Base vars dict (scenario_id, target_schema, etc.).
        target_schema: Schema where result tables are created.
        workspace_id: Workspace PK for layer registration.
        scenario_id: Scenario slug/ID for table name formatting.
        module_selects: Optional per-module SQLMesh select overrides.
            If omitted, each module name is used as the select.

    Returns:
        Dict with keys:
            "success": bool — whether all modules completed
            "completed": list[str] — modules that succeeded
    """
    ordered = resolve_module_order(modules)
    environment = f"scenario_{scenario_id}"
    result = run_sqlmesh_plan(
        environment=environment,
        select=ordered,
        skip_tests=True,
    )
    if result.success:
        for module in ordered:
            for table_name in MODULE_RESULT_TABLES.get(module, []):
                table = table_name.format(scenario_id=scenario_id)
                register_result_layer(
                    workspace_id=workspace_id,
                    schema=target_schema,
                    table=table,
                )
    return {
        "success": result.success,
        "completed": ordered if result.success else [],
        "results": [],
    }
