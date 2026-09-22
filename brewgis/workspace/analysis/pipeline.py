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

from brewgis.workspace.analysis import module_registry
from brewgis.workspace.analysis.layer_registry import register_result_layer
from brewgis.workspace.analysis.log_capture import capture_run_log
from brewgis.workspace.analysis.log_capture import extract_plan_failure
from brewgis.workspace.analysis.log_capture import truncate_log
from brewgis.workspace.analysis.module_registry import (
    MODULE_RESULT_TABLES,  # noqa: F401 -- re-exported for import_sacog_demo.py
)
from brewgis.workspace.analysis.module_registry import MODULE_SQLMESH_SELECTORS
from brewgis.workspace.analysis.module_registry import get_vars_for_module
from brewgis.workspace.analysis.module_registry import (
    resolve_module_order as _resolve_module_order,
)
from brewgis.workspace.analysis.sqlmesh_runner import model_fqns_built_in
from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.tile_server import restart_martin
from brewgis.workspace.services.tile_server import wait_until_martin_ready

logger = logging.getLogger(__name__)


class MissingAnalysisResultsError(RuntimeError):
    """A run's plan finished without publishing some requested module's results.

    Raised by :func:`run_modules_sync` after the plan, from the result views
    that actually exist — the module registries cannot tell a module that ran
    from one that produced nothing, and a plan reports success either way.
    """

    def __init__(self, modules: dict[str, list[str]], schema: str) -> None:
        self.modules = modules
        self.schema = schema
        detail = "; ".join(
            f"{module} -> {', '.join(tables)}"
            for module, tables in sorted(modules.items())
        )
        super().__init__(
            f"The plan published no result view in {schema} for: {detail}. "
            f"Each analysis model owns a view named after it, so these models "
            f"were not materialized."
        )


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


def _list_tables(schema: str) -> list[str]:
    """List table/view names actually present in *schema*.

    Used to discover which analysis result views a SQLMesh plan really
    published for a scenario, rather than trusting the module registries'
    static (and drift-prone) table-name lists.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            [schema],
        )
        return [row[0] for row in cursor.fetchall()]


def _create_analysis_run(
    scenario_id: int,
    module_names: list[str],
    vars_: dict[str, Any] | None,
) -> AnalysisRun:
    """Resolve dependencies and create a ``pending`` AnalysisRun record."""
    scenario = Scenario.objects.get(pk=scenario_id)
    ordered_modules = resolve_module_order(module_names)

    run = AnalysisRun.objects.create(
        workspace_id=scenario.workspace_id,
        scenario_id=scenario_id,
        modules=ordered_modules,
        status="pending",
        vars=vars_ or {},
        # Recorded for history only — the plan itself reads the mapping off the
        # Scenario, which is where a run's parameters are now persisted.
        column_mapping=scenario.column_mapping,
    )

    logger.info(
        "AnalysisRun #%s created for workspace %s, modules: %s",
        run.pk,
        scenario.workspace_id,
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
    # A retry reuses the same record — don't let an earlier attempt's cause
    # stick to a run that is now running again.
    run.failure_cause = ""
    run.save(update_fields=["status", "started_at", "failure_cause"])

    with capture_run_log() as log_stream:
        try:
            result = run_modules_sync(
                modules=run.modules,
                workspace_id=run.workspace_id,
                scenario_id=run.scenario_id,
            )
        except Exception as exc:
            # SQLMesh's own exception here (PlanError("Plan application
            # failed.")) discards the actual per-node cause — the captured
            # log is often the only place that's still visible (e.g. a
            # psycopg2/duckdb error several frames below where SQLMesh
            # catches and re-raises generically).
            log_output = truncate_log(log_stream.getvalue())
            failure = extract_plan_failure(log_output)
            if failure is not None:
                cause = failure.format()
            elif isinstance(exc, MissingAnalysisResultsError):
                # Raised below the plan, so its message *is* the cause — there
                # is no SQLMesh node to recover one from.
                cause = str(exc)
            else:
                cause = ""
            # The plan's own traceback above names no model and no database
            # error, so log the recovered cause alongside it — that is the
            # difference between a worker log that says "failed" and one that
            # says which model failed against what.
            if cause:
                logger.exception("AnalysisRun #%s failed: %s", run.pk, cause)
            else:
                logger.exception("AnalysisRun #%s failed", run.pk)
            run.status = "failed"
            run.error_log = traceback.format_exc()
            run.failure_cause = cause
            run.log_output = log_output
            run.completed_at = timezone.now()
            run.save(
                update_fields=[
                    "status",
                    "error_log",
                    "failure_cause",
                    "log_output",
                    "completed_at",
                ]
            )
            return
        run.log_output = truncate_log(log_stream.getvalue())

    run.status = "completed"
    run.completed_at = timezone.now()
    run.save(update_fields=["status", "completed_at", "log_output"])

    # New analysis__scenario_<id> tables are invisible to Martin until it
    # restarts (see brewgis.workspace.services.tile_server) — only relevant
    # if this workspace actually renders tiles through Martin. Block until
    # Martin has actually finished re-scanning (not just restarted) so the
    # map is correct the moment this run shows as "completed" — otherwise
    # the user can land on a map that briefly renders wrong/blank tiles.
    if Workspace.objects.filter(
        pk=run.workspace_id, tile_server_backend="martin"
    ).exists():
        restart_martin()
        wait_until_martin_ready(result.get("fqtns", []))


def run_analysis_pipeline(
    scenario_id: int,
    module_names: list[str],
    vars_: dict[str, Any] | None = None,
) -> AnalysisRun:
    """Create an AnalysisRun record and execute it synchronously via SQLMesh.

    SQLMesh handles DAG traversal automatically — all modules run in a
    single plan call. Blocks the caller until the run finishes; used by the
    MCP tool and the full-page multi-module launcher, where a synchronous
    result is expected. For a non-blocking launch (e.g. the map view's
    Analysis panel), use :func:`launch_analysis_run` instead.
    """
    run = _create_analysis_run(scenario_id, module_names, vars_)
    _execute_analysis_run(run)
    return run


def launch_analysis_run(
    scenario_id: int,
    module_names: list[str],
    vars_: dict[str, Any] | None = None,
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

    run = _create_analysis_run(scenario_id, module_names, vars_)
    run_analysis_task.delay(run.pk)
    run.refresh_from_db()
    return run


def run_modules_sync(
    *,
    modules: list[str],
    workspace_id: int,
    scenario_id: int,
) -> dict[str, Any]:
    """Run analysis modules via SQLMesh, registering result layers.

    Selects the scenario's *blueprinted* models (one instance per scenario, see
    ``sqlmesh/macros/analysis_blueprints.py``) and plans them into ``prod``:
    the models are first-class project models, not per-run environment
    variants, and each one republishes its result view as it is promoted.

    Args:
        modules: Module names to run (e.g. ["core", "water_demand"]).
        workspace_id: Workspace PK for layer registration.
        scenario_id: Scenario PK. Selects that scenario's model instances
            (``module_registry.model_fqn``) and the result schema they publish
            into.

    Returns:
        Dict with keys:
            "success": bool — whether all modules completed
            "completed": list[str] — modules that succeeded
    """
    ordered = resolve_module_order(modules)
    selects = [
        module_registry.model_fqn(model_name, scenario_id)
        for module in ordered
        for model_name in MODULE_SQLMESH_SELECTORS.get(module, [])
    ]

    run_sqlmesh_plan(
        environment="prod",
        select=selects or None,
        skip_tests=True,
        # Launching an analysis must always recompute the models already built
        # for this scenario, never trust SQLMesh's own snapshot-fingerprint
        # staleness check: upstream reference data (e.g. BuildingType/built_forms
        # exports, or paint applied to the scenario's canvas) can change without
        # the model's SQL or blueprints changing, so a rerun can silently keep
        # serving results computed against data that no longer exists. A model
        # this scenario has never built can't be *restated* (SQLMesh refuses
        # that) — it is materialized because it is new.
        restate_models=model_fqns_built_in("prod", selects) or None,
        # ...but restating is exactly what makes SQLMesh plan from state alone,
        # which hides any model this scenario has never built — the case above.
        # Without this, asking for a module the scenario has not run before
        # plans nothing for it and the run still reports the module completed.
        always_include_local_changes=True,
        auto_apply=True,
        no_prompts=True,
    )
    # Each model's on_virtual_update statement publishes its result view at
    # "<result schema>.<bare model name>" — the same location the map, the
    # tile servers and the Layers panel read. Discover the views actually
    # present rather than trusting the module registries (which have drifted
    # out of sync with the real model set on both counts — some listed models
    # no longer exist, some real ones aren't listed).
    env_schema = module_registry.result_schema_name(scenario_id)
    published = set(_list_tables(env_schema))
    missing = _unpublished_modules(ordered, published)
    if missing:
        raise MissingAnalysisResultsError(missing, env_schema)

    fqtns = []
    for model_name in sorted(published):
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


def _unpublished_modules(
    ordered_modules: list[str], published: set[str]
) -> dict[str, list[str]]:
    """Requested modules with at least one model that published no result view.

    Each analysis model owns a result view named after it (its
    ``on_virtual_update`` statement creates it), so a selected model with no
    view in the result schema produced nothing — either the plan skipped it or
    its statement failed. Only the modules this run actually requested are
    reported: the schema also holds results from earlier runs.
    """
    unpublished: dict[str, list[str]] = {}
    for module in ordered_modules:
        missing = [
            model_name
            for model_name in MODULE_SQLMESH_SELECTORS.get(module, [])
            if model_name not in published
        ]
        if missing:
            unpublished[module] = missing
    return unpublished
