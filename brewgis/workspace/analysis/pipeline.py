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
import traceback
from typing import Any

import deal
from django.db import connection
from django.utils import timezone

from brewgis.workspace.analysis.layer_registry import register_result_layer
from brewgis.workspace.analysis.module_registry import (
    MODULE_RESULT_TABLES,  # noqa: F401 -- re-exported for import_sacog_demo.py
)
from brewgis.workspace.analysis.module_registry import MODULE_SQLMESH_SELECTORS
from brewgis.workspace.analysis.module_registry import get_vars_for_module
from brewgis.workspace.analysis.module_registry import (
    resolve_module_order as _resolve_module_order,
)
from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.tile_server import restart_martin
from brewgis.workspace.services.tile_server import wait_until_martin_ready

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


def _build_model_vars(base_vars: dict[str, Any], schema: str) -> dict[str, object]:
    """Build SQLMesh plan variables from pipeline base_vars.

    Qualifies unqualified table references with the target schema
    and filters to keys that match SQLMesh model variable names.
    """
    model_vars: dict[str, object] = {}
    target_schema = base_vars.get("target_schema", schema)

    # Qualify table references with schema if not already qualified
    for tbl_key in ("parcel_table", "constraint_table", "built_form_table"):
        val = base_vars.get(tbl_key)
        if val and "." not in str(val):
            model_vars[tbl_key] = f"{target_schema}.{val}"
        elif val:
            model_vars[tbl_key] = val

    # Forward constraints list
    if "constraints" in base_vars:
        model_vars["constraints"] = base_vars["constraints"]

    # Forward canonical column mappings and known model variables
    known_keys = {
        "scenario_schema",
        "scenario_id",
        "scenario_slug",
        "base_canvas_table",
        "base_year",
        "horizon_year",
        "osm_intersection_table",
    }
    model_vars.update(
        {
            k: v
            for k, v in base_vars.items()
            if k.startswith("canonical_") or k in known_keys
        }
    )

    return model_vars


def _list_tables(schema: str) -> list[str]:
    """List table/view names actually present in *schema*.

    Used to discover which analysis result views a SQLMesh plan really
    promoted into a scenario environment, rather than trusting the module
    registries' static (and drift-prone) table-name lists.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            [schema],
        )
        return [row[0] for row in cursor.fetchall()]


def _build_sqlmesh_selectors(modules: list[str]) -> list[str]:
    """Build SQLMesh model FQN selectors from analysis module names.

    Converts module names (e.g. "core", "water_demand") to their
    corresponding SQLMesh model FQNs (e.g. "brewgis.analysis.core_end_state",
    "brewgis.analysis.water_demand") using MODULE_SQLMESH_SELECTORS.
    """
    selects: list[str] = []
    for module in modules:
        patterns = MODULE_SQLMESH_SELECTORS.get(module, [module])
        selects.extend(f"brewgis.analysis.{p}" for p in patterns)
    return selects


def _create_analysis_run(
    workspace_id: int,
    module_names: list[str],
    vars_: dict[str, Any] | None,
    scenario_id: int | None,
) -> AnalysisRun:
    """Resolve dependencies and create a ``pending`` AnalysisRun record."""
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
    return run


def _execute_analysis_run(run: AnalysisRun) -> None:
    """Run a ``pending``/``running`` AnalysisRun's modules via SQLMesh in place.

    Mutates and saves ``run``'s status as it goes, so both the synchronous
    caller (:func:`run_analysis_pipeline`) and the Celery task that backs
    :func:`launch_analysis_run` can share the exact same execution logic.
    """
    run.status = "running"
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])

    base_vars = run.vars
    workspace_id = run.workspace_id
    scenario_id = run.scenario_id

    try:
        result = run_modules_sync(
            modules=run.modules,
            base_vars=base_vars,
            target_schema=base_vars.get("target_schema", "public"),
            workspace_id=workspace_id,
            scenario_id=str(scenario_id),
            module_selects=base_vars.get("module_selects"),
        )
    except Exception:
        logger.exception("AnalysisRun #%s failed", run.pk)
        run.status = "failed"
        run.error_log = traceback.format_exc()
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "error_log", "completed_at"])
        return

    run.status = "completed"
    run.completed_at = timezone.now()
    run.save(update_fields=["status", "completed_at"])

    # New analysis__scenario_<id> tables are invisible to Martin until it
    # restarts (see brewgis.workspace.services.tile_server) — only relevant
    # if this workspace actually renders tiles through Martin. Block until
    # Martin has actually finished re-scanning (not just restarted) so the
    # map is correct the moment this run shows as "completed" — otherwise
    # the user can land on a map that briefly renders wrong/blank tiles.
    if Workspace.objects.filter(pk=workspace_id, tile_server_backend="martin").exists():
        restart_martin()
        wait_until_martin_ready(result.get("fqtns", []))


def run_analysis_pipeline(
    workspace_id: int,
    module_names: list[str],
    vars_: dict[str, Any] | None = None,
    scenario_id: int | None = None,
) -> AnalysisRun:
    """Create an AnalysisRun record and execute it synchronously via SQLMesh.

    SQLMesh handles DAG traversal automatically — all modules run in a
    single plan call. Blocks the caller until the run finishes; used by the
    MCP tool and the full-page multi-module launcher, where a synchronous
    result is expected. For a non-blocking launch (e.g. the map view's
    Analysis panel), use :func:`launch_analysis_run` instead.
    """
    run = _create_analysis_run(workspace_id, module_names, vars_, scenario_id)
    _execute_analysis_run(run)
    return run


def launch_analysis_run(
    workspace_id: int,
    module_names: list[str],
    vars_: dict[str, Any] | None = None,
    scenario_id: int | None = None,
) -> AnalysisRun:
    """Create an AnalysisRun and dispatch its execution to Celery.

    Returns as soon as the run is recorded (``status="pending"``) — it does
    not wait for the analysis to finish. ``CELERY_TASK_ALWAYS_EAGER`` (the
    dev/test default) still runs the task inline before ``.delay()``
    returns, so the run is already ``completed``/``failed`` by the time this
    function returns in those environments; the real behavior of returning
    immediately only takes effect where Celery workers are running async.
    """
    from brewgis.workspace.tasks import run_analysis_task

    run = _create_analysis_run(workspace_id, module_names, vars_, scenario_id)
    run_analysis_task.delay(run.pk)
    run.refresh_from_db()
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

    # Build SQLMesh model selectors from module names.
    # Convert module names to model FQNs via MODULE_SQLMESH_SELECTORS.
    if module_selects:
        selects = []
        for module in ordered:
            selects.extend(module_selects.get(module, []))
    else:
        selects = _build_sqlmesh_selectors(ordered)

    # Build and forward model variables from base_vars to the SQLMesh plan
    model_vars = _build_model_vars(base_vars, target_schema)

    run_sqlmesh_plan(
        environment=environment,
        select=selects or None,
        skip_tests=True,
        variables=model_vars,
        # Launching an analysis must always recompute the selected models,
        # never trust SQLMesh's own snapshot-fingerprint staleness check.
        # Upstream reference data (e.g. BuildingType/built_forms exports)
        # can change without the model's SQL or vars changing at all, which
        # SQLMesh has no way to detect on its own — without this, a rerun
        # can silently keep serving a stale physical table with results
        # computed against data that no longer exists.
        restate_models=selects or None,
    )
    # SQLMesh promotes each plan into its own environment (scenario_<id>)
    # rather than materializing results directly into the workspace's own
    # schema. With the default environment_suffix_target (SCHEMA), that
    # means every brewgis.analysis.* model's virtual-layer view lives under
    # "analysis__scenario_<id>", under its own bare model name — not in the
    # workspace's schema, and not under the MODULE_RESULT_TABLES
    # scenario-suffixed names. Discover the views actually promoted into
    # that environment rather than trusting the module registries (which
    # have drifted out of sync with the real model set on both counts —
    # some listed models no longer exist, some real ones aren't listed).
    env_schema = f"analysis__scenario_{scenario_id}"
    fqtns = []
    for model_name in _list_tables(env_schema):
        register_result_layer(
            workspace_id=workspace_id,
            schema=env_schema,
            table=model_name,
            key=f"{model_name}_{scenario_id}",
            name=f"{model_name.replace('_', ' ').title()} {scenario_id}",
            group_name="Analysis Results",
        )
        fqtns.append(f"{env_schema}.{model_name}")
    return {
        "success": True,
        "completed": ordered,
        "results": [],
        "fqtns": fqtns,
    }
