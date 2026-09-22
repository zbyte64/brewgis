"""SQLMesh runner — orchestrates BrewGIS analysis pipelines via the Python API.

Uses the SQLMesh Python API (sqlmesh.core.context.Context) for tight
Django integration — not subprocess. Automatically resolves the DAG
from table references, eliminating the need for manual MODULE_DEPENDENCIES
management during execution.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlmesh.core.context import Context
from sqlmesh.utils.errors import ConflictingPlanError

from brewgis.sqlmesh.config import config_factory

logger = logging.getLogger(__name__)

SQLMESH_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent / "sqlmesh"


def get_context(**variables) -> Context:
    """Return a SQLMesh Context for the BrewGIS project.

    The context loads all models, macros, seeds, and audits from the
    ``brewgis/sqlmesh/`` directory.  Callers should cache the result
    when making multiple calls within the same process lifetime.
    """
    config = config_factory(**variables)
    return Context(paths=str(SQLMESH_PROJECT_DIR), config=config)


def get_state_context(**variables) -> Context:
    """Return a Context that reads/rewrites SQLMesh state without loading models.

    Needed when a model listed in state can no longer be evaluated — loading the
    project would raise on it, so state hygiene (see
    ``services.scenario_canvas``) has to work without parsing any model.
    """
    config = config_factory(**variables)
    return Context(paths=str(SQLMESH_PROJECT_DIR), config=config, load=False)


def _models_in_environment(context: Context, environment: str) -> list[str]:
    """Return FQNs of models materialized in *environment*.

    Queries SQLMesh's state for the promoted snapshots in the given
    environment and extracts the display name (model FQN) for each.
    """
    env = context.state_reader.get_environment(environment)
    if env is None:
        return []
    snapshots = getattr(env, "promoted_snapshots", None) or []
    # s.name is the quoted FQN (e.g. '"brewgis"."sacog"."acs_block_group"');
    # strip quotes for selector compatibility (brewgis.sacog.acs_block_group).
    return [s.name.replace('"', "") for s in snapshots]


def snapshot_name(entry: object) -> str:
    """Name of an environment snapshot entry (object or mapping).

    SQLMesh stores these fully quoted (``"brewgis"."ascn7"."core_end_state"``),
    so anything comparing one against a model FQN must normalise it with
    :func:`normalize_fqn` first.
    """
    name = getattr(entry, "name", None)
    if name is None and isinstance(entry, dict):
        name = entry.get("name")
    return str(name)


def normalize_fqn(name: str) -> str:
    """Return *name* without its identifier quotes, for comparing against FQNs."""
    return name.replace('"', "")


def model_fqns_built_in(environment: str, model_fqns: Iterable[str]) -> list[str]:
    """Return the subset of *model_fqns* that *environment* has already built.

    ``restate_models`` refuses a model SQLMesh has no snapshot for ("Cannot
    restate model '<fqn>'. Model does not exist.") — a plan cannot restate
    something it has never materialized. Callers that always want the selected
    models recomputed therefore have to ask for restatement only of the ones
    that already exist: everything else is new to the plan and gets built
    because of that.

    No-op (empty list) when the environment doesn't exist yet.
    """
    state = get_state_context().state_reader.get_environment(environment)
    if state is None:
        return []

    built = {normalize_fqn(snapshot_name(entry)) for entry in state.snapshots_}
    return [fqn for fqn in model_fqns if normalize_fqn(fqn) in built]


def purge_models_from_environments(model_fqns: Iterable[str]) -> list[str]:
    """Remove *model_fqns* from every SQLMesh environment.

    Used when a model leaves the project without a plan (a deleted scenario's
    blueprinted analysis models, a dropped scenario canvas): the stored
    environment would still list that snapshot, and a later plan that promotes
    such a stale entry points it at a physical object the plan never creates,
    failing the whole plan.

    Returns the names of the environments that listed any of them. Their own
    physical/virtual objects are left to SQLMesh's janitor: with the snapshots
    no longer referenced by an environment they are expired state.

    No-op under tests — the SQLMesh state schema belongs to the running stack,
    not to the test database a test process builds scenarios in.
    """
    from django.conf import settings

    wanted = {normalize_fqn(fqn) for fqn in model_fqns}
    if not wanted or settings.TESTING:
        return []

    import uuid

    context = get_state_context()
    touched: list[str] = []
    for environment in context.state_sync.get_environments():
        entries = [
            (entry, normalize_fqn(snapshot_name(entry)))
            for entry in environment.snapshots_
        ]
        if not any(name in wanted for _, name in entries):
            continue
        updated = environment.copy(deep=True)
        updated.snapshots_ = [entry for entry, name in entries if name not in wanted]
        if environment.previous_finalized_snapshots_:
            updated.previous_finalized_snapshots_ = [
                entry
                for entry in environment.previous_finalized_snapshots_
                if normalize_fqn(snapshot_name(entry)) not in wanted
            ]
        # ``promote`` refuses to rewrite an environment whose plan chain moved on.
        updated.previous_plan_id = environment.plan_id
        updated.plan_id = uuid.uuid4().hex
        context.state_sync.promote(updated, no_gaps_snapshot_names=set())
        touched.append(environment.name)
    if touched:
        logger.info(
            "Removed model(s) %s from environment(s) %s",
            sorted(wanted),
            touched,
        )
    return touched


# deprecated
def run_sqlmesh_plan(  # noqa: PLR0913
    environment: str = "prod",
    *,
    select: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    skip_tests: bool = True,
    forward_only: bool = False,
    no_prompts: bool = True,
    auto_apply: bool = True,
    create_from: str | None = None,
    variables: dict[str, object] = {},
    restate_models: Iterable[str] | bool = False,
    always_include_local_changes: bool | None = None,
):
    """Run ``sqlmesh plan`` for the given environment via the Python API.

    Args:
        environment: Target environment name (e.g. ``scenario_<pk>``).
        select: Optional list of model selectors to restrict the plan.
        start: Start date for the plan interval.
        end: End date for the plan interval.
        skip_tests: Skip audit execution (default True — audits run on run).
        forward_only: Use forward-only model changes (avoid backfill).
        no_prompts: Auto-approve without interactive prompts.
        auto_apply: Apply the plan immediately after creation.
        create_from: Source environment to create from (virtual environment).
        variables: Model variable overrides (e.g. ``parcel_table``, ``constraints``).
        restate_models: If True, re-evaluate the selected models even if unchanged.
        always_include_local_changes: Whether the plan sees the models in the
            project as they are on disk. Default (``None``) is SQLMesh's own
            rule: **any** ``restate_models`` makes the plan read its model
            definitions from state alone and ignore the filesystem, so a model
            that has been added since this environment was last planned is not
            part of the plan at all — it neither materializes nor reports
            anything. Pass ``True`` whenever the selection can contain such a
            model; pass ``False`` never.

    ``Context.plan`` hard-wires that rule for a restating plan and exposes no
    way to override it, so a plan that asks for ``always_include_local_changes``
    is built through the same ``plan_builder`` that ``Context.plan`` builds and
    applies (SQLMesh's own console does no more than
    ``plan_builder.apply()`` when it is told to auto-apply) — it only passes the
    flag through. The cost is the plan summary the console would have printed.
    """
    context = get_context(**variables)
    restate = _resolve_restatements(
        context, environment=environment, restate_models=restate_models
    )
    plan_kwargs: dict[str, Any] = {
        "environment": environment,
        "start": start,
        "end": end,
        "skip_tests": skip_tests,
        "forward_only": forward_only,
        "select_models": select,
        "create_from": create_from,
        "restate_models": restate,
    }
    logger.info("SQLMesh plan applied for environment '%s'", environment)
    if always_include_local_changes is None:
        return context.plan(
            **plan_kwargs, no_prompts=no_prompts, auto_apply=auto_apply
        ), context

    # `plan_builder` takes the flag but neither `no_prompts` nor `auto_apply` —
    # those two only steer the console flow this path stands in for.
    builder = context.plan_builder(
        **plan_kwargs, always_include_local_changes=always_include_local_changes
    )
    try:
        if auto_apply:
            builder.apply()
    except ConflictingPlanError:
        if not auto_apply or not restate:
            raise
        # SQLMesh refuses a plan that restates a model it is also redeploying
        # ("Another plan deployed new versions ... while they were being
        # restated"), and its advice — re-apply the plan — cannot work here:
        # the promotion stage it aborts at is exactly what a second attempt
        # would need to see. Neither half is droppable (a rerun must not serve
        # results computed against data that changed underneath the models, and
        # a changed model has to be deployed), so the two run as separate
        # plans: deploy everything — which materializes what is new or changed,
        # plus their downstreams — then restate, by which point every model the
        # restatement covers is deployed at the version being restated.
        logger.warning(
            "Plan restates models it also redeploys — deploying first, then restating",
        )
        deploy_kwargs: dict[str, Any] = {
            "environment": environment,
            "select": select,
            "start": start,
            "end": end,
            "skip_tests": skip_tests,
            "forward_only": forward_only,
            "no_prompts": no_prompts,
            "auto_apply": auto_apply,
            "create_from": create_from,
            "variables": variables,
            "always_include_local_changes": always_include_local_changes,
        }
        run_sqlmesh_plan(**deploy_kwargs)
        return run_sqlmesh_plan(**deploy_kwargs, restate_models=restate), context
    return builder.build(), context


def _resolve_restatements(
    context: Context, *, environment: str, restate_models: Iterable[str] | bool
) -> list[str] | None:
    """Resolve the plan's ``restate_models`` argument to a concrete model list.

    ``True`` means "every model this environment has built" (see
    ``_models_in_environment``). Materialized into a list so the plan can be
    built more than once from the same argument — a generator would be spent
    after the first one.
    """
    if restate_models is True:
        return _models_in_environment(context, environment)
    return list(restate_models) if restate_models else None


def run_sqlmesh_run(
    environment: str | None = None,
    *,
    select: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
):
    """Run ``sqlmesh run`` for the given environment.

    Executes any models that have not yet been run for the specified
    interval (or directly if no environment is specified).
    Audits are checked during execution as part of the model DDL ``audits`` clause.

    Args:
        environment: Target environment name (None = execute directly).
        select: Optional list of model selectors.
        start: Start date.
        end: End date.
    """
    context = get_context()
    logger.info("SQLMesh running for environment '%s'", environment)
    return context.run(
        environment=environment,
        start=start,
        end=end,
        select_models=select,
    )


def run_sqlmesh_test(
    *,
    models: list[str] | None = None,
    verbose: bool = False,
):
    """Run SQLMesh unit tests.

    Args:
        models: Optional list of model names to test.
        verbose: Enable verbose test output.
    """
    context = get_context()
    result = context.test(models=models, verbose=verbose)
    passed = result.count("FAILED") == 0 if isinstance(result, str) else True
    logger.info("SQLMesh test completed")
    return passed


def run_sqlmesh_table_diff(
    source_env: str,
    target_env: str,
    model: str | None = None,
):
    """Compare tables between two SQLMesh environments.

    Args:
        source_env: Source environment name.
        target_env: Target environment name.
        model: Optional model name to compare (compares all if None).

    Returns:
        Dict with diff results.
    """
    context = get_context()
    return context.table_diff(
        source=source_env,
        target=target_env,
        model=model,
    )


def evaluate_model(
    model_name: str,
    environment: str | None = None,
    limit: int = 10,
):
    """Evaluate a single model and return its output.

    Useful for ad-hoc verification during migration.

    Args:
        model_name: Fully qualified model name.
        environment: Optional environment to evaluate in.
        limit: Row limit.

    Returns:
        DataFrame with model output.
    """
    context = get_context()
    return context.evaluate(
        start=None,
        end=None,
        execution_time=None,
        model_or_snapshot="snapshot",
        model_name=model_name,
        environment=environment,
        limit=limit,
    )
