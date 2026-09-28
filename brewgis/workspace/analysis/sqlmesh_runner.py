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
from typing import TYPE_CHECKING
from typing import Any

from django.db import connection
from sqlmesh.core.context import Context
from sqlmesh.utils.errors import ConflictingPlanError

from brewgis.sqlmesh.config import config_factory

if TYPE_CHECKING:
    from sqlmesh.core.plan import Plan
    from sqlmesh.core.plan import PlanBuilder
    from sqlmesh.core.snapshot import SnapshotTableInfo

logger = logging.getLogger(__name__)

SQLMESH_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent / "sqlmesh"

# How many times a plan is rebuilt while the models it would publish unbuilt are
# added to its plan. Every pass can only add models to that set, so one pass
# covers everything a plan can report and the second merely confirms the plan is
# clean.
_MAX_REBUILD_PASSES = 2


def get_context(cache_dir: str | None = None, **variables) -> Context:
    """Return a SQLMesh Context for the BrewGIS project.

    The context loads all models, macros, seeds, and audits from the
    ``brewgis/sqlmesh/`` directory.  Callers should cache the result
    when making multiple calls within the same process lifetime.

    ``cache_dir`` overrides SQLMesh's on-disk cache of rendered model
    definitions. Pass a private, empty directory when the models' *contents* are
    derived from database rows the cache cannot see — see
    ``workspace.analysis.pipeline.run_modules_sync`` for why an analysis run
    does.
    """
    config = config_factory(cache_dir=cache_dir, **variables)
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


def _release_shared_duckdb(context: Context) -> None:
    """Release the shared DuckDB file the plan's gateway adapters hold open.

    SQLMesh caches one adapter per DuckDB data file for the life of the process,
    and that adapter keeps the file's exclusive lock for as long as its
    connection is open — it is closed on the success path by SQLMesh's own
    recycler, but a plan that *raises* leaves ``duckdb_cache.db`` locked inside
    whichever long-lived process ran it. In the Celery worker, that is a daemonic
    child that goes on to serve later tasks, so every later plan from another
    process (a one-off ``manage.py`` run, the MCP server, another worker child)
    fails with "Could not set lock on file … duckdb_cache.db" — the failure that
    then hides the original one.

    ``Context.close()`` is not enough on its own: it closes the snapshot
    evaluator's adapters, not the gateway adapters a plan reaches through. Close
    those explicitly first. The pooled connection reconnects lazily on next use,
    so a later plan in this process is unaffected.

    A failure here propagates rather than being swallowed — it is chained to
    whatever the plan raised, which ``describe_run_failure`` still walks.
    """
    for adapter in (context.engine_adapters or {}).values():
        adapter.close()
    context.close()


def _published_snapshots(context: Context, plan: Plan) -> list[SnapshotTableInfo]:
    """Snapshots whose views this plan's promotion stage will (re)create.

    Mirrors SQLMesh's own promotion set (``PlanStagesBuilder``): the target
    environment's promoted snapshots minus the ones the stored environment
    already promotes under the same fingerprint — and only when SQLMesh would
    partially promote at all. An environment that is not finalized, which is
    what a plan that died in its promotion stage leaves behind, is re-promoted
    whole.
    """
    target = plan.environment.promoted_snapshots
    stored = context.state_reader.get_environment(plan.environment.name)
    if stored is None or not plan.environment.can_partially_promote(stored):
        return list(target)
    already = {info.name: info for info in stored.promoted_snapshots}
    return [info for info in target if already.get(info.name) != info]


def _existing_relations(tables: Iterable[str]) -> set[str]:
    """Which of *tables* — ``schema.table`` — exist in the PostGIS database."""
    wanted = sorted(set(tables))
    if not wanted:
        return set()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT n.nspname || '.' || c.relname FROM pg_class c"
            " JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE (n.nspname || '.' || c.relname) = ANY(%s::text[])",
            [wanted],
        )
        return {row[0] for row in cursor.fetchall()}


def unbuilt_published_models(context: Context, plan: Plan) -> list[str]:
    """FQNs *plan* would publish without a physical table to publish.

    SQLMesh decides what to materialize (``models_to_backfill``) and what to
    publish (the environment's promoted snapshots) from two different inputs.
    ``models_to_backfill`` is derived from the plan's *selection* — a selection
    narrows it to the selected models and their downstream graph, and
    ``restate_models`` narrows it again to the restated models — while promotion
    covers every snapshot the environment changes. A snapshot that lands in the
    second set but not the first is promoted into a view over a physical table
    nothing built: a dependency the plan re-versions (its own parent changed)
    that it never selected, e.g. the region road network a module routes over.
    The promotion stage then fails with ``UndefinedTable: relation
    "sqlmesh__…" does not exist`` — after everything else in the run has already
    been backfilled.

    Returns the snapshots' own (quoted) FQNs, which is the spelling SQLMesh's
    ``backfill_models`` and ``restate_models`` both accept. Only the default
    gateway's models are judged: a DuckDB gateway materializes its models inside
    the DuckDB file, where an existence check against Postgres would report a
    false miss.
    """
    gateway = context.config.default_gateway
    candidates: list[tuple[str, str]] = []
    for info in _published_snapshots(context, plan):
        snapshot = plan.snapshots.get(info.snapshot_id)
        if snapshot is None or not snapshot.is_model or not snapshot.evaluatable:
            continue
        if (snapshot.model_gateway or gateway) != gateway:
            continue
        # The plan is going to build this one itself.
        if plan.is_selected_for_backfill(snapshot.name):
            continue
        # ``table_name()`` is ``catalog.schema.table`` and the catalog is the
        # project's logical one, which the plan's own connection rewrites to the
        # real database — only the schema and table name a relation on disk.
        physical = ".".join(snapshot.table_name().split(".")[-2:])
        candidates.append((snapshot.name, physical))
    if not candidates:
        return []
    existing = _existing_relations(table for _, table in candidates)
    return [name for name, table in candidates if table not in existing]


def _rebuild_unbuilt_published(
    context: Context,
    plan_kwargs: dict[str, Any],
    builder: PlanBuilder,
    *,
    always_include_local_changes: bool | None,
) -> tuple[PlanBuilder, dict[str, Any]]:
    """Rebuild *builder* until nothing its plan publishes is missing a table.

    Every model that is missing one is named in ``backfill_models`` — SQLMesh's
    "materialize these too" selector — which makes it eligible to be scheduled at
    all. Passing that set replaces the one SQLMesh derives from the selection and
    from ``restate_models``, so the caller's own restatements are named in it as
    well: a restated model missing from it would silently stop being recomputed.

    A model whose snapshot *has* intervals — the state calls it built, or partly
    built — is restated on top of that. A snapshot is only ever scheduled for the
    intervals it is missing, so a table that a plan recorded as built before
    publishing it as missing (a promotion that died, a table dropped since) has
    nothing left to schedule: restating drops the intervals it holds, which is
    what makes SQLMesh build it again. Its downstream is restated with it, since
    their results were computed from the table that went missing — the one case
    where the cheap repair is not enough.
    """
    restate = set(plan_kwargs.get("restate_models") or ())
    rebuilt = set(restate)
    for _ in range(_MAX_REBUILD_PASSES):
        plan = builder.build()
        unbuilt = [
            name
            for name in unbuilt_published_models(context, plan)
            if name not in rebuilt
        ]
        if not unbuilt:
            break
        snapshots = {snapshot.name: snapshot for snapshot in plan.snapshots.values()}
        restate.update(
            name for name in unbuilt if name in snapshots and snapshots[name].intervals
        )
        rebuilt.update(unbuilt)
        logger.warning(
            "Plan would publish %s with no physical table — rebuilding them in the same plan",
            ", ".join(sorted(unbuilt)),
        )
        plan_kwargs = {
            **plan_kwargs,
            # An empty list is SQLMesh's "selector matched nothing" error.
            "restate_models": sorted(restate) or None,
            "backfill_models": sorted(rebuilt),
        }
        builder = context.plan_builder(
            **plan_kwargs, always_include_local_changes=always_include_local_changes
        )
    return builder, plan_kwargs


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
    cache_dir: str | None = None,
    repair_unbuilt_promotions: bool = False,
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
        cache_dir: SQLMesh cache directory to load models through (see
            ``get_context``). Threaded into the follow-up plans a conflicting
            restatement is split into, so those render from the same source.
        repair_unbuilt_promotions: Rebuild the plan until nothing it publishes
            is missing a physical table (see :func:`unbuilt_published_models`).
            Requires the ``plan_builder`` path, which is the only one that
            exposes the plan before it is applied.

    ``Context.plan`` hard-wires that rule for a restating plan and exposes no
    way to override it, so a plan that asks for ``always_include_local_changes``
    is built through the same ``plan_builder`` that ``Context.plan`` builds and
    applies (SQLMesh's own console does no more than
    ``plan_builder.apply()`` when it is told to auto-apply) — it only passes the
    flag through. The cost is the plan summary the console would have printed.
    """
    if repair_unbuilt_promotions and always_include_local_changes is None:
        msg = "repair_unbuilt_promotions needs the plan_builder path: pass always_include_local_changes"
        raise ValueError(msg)
    context = get_context(cache_dir=cache_dir, **variables)
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
        try:
            return context.plan(
                **plan_kwargs, no_prompts=no_prompts, auto_apply=auto_apply
            ), context
        finally:
            _release_shared_duckdb(context)

    # `plan_builder` takes the flag but neither `no_prompts` nor `auto_apply` —
    # those two only steer the console flow this path stands in for.
    builder = context.plan_builder(
        **plan_kwargs, always_include_local_changes=always_include_local_changes
    )
    try:
        if repair_unbuilt_promotions:
            builder, plan_kwargs = _rebuild_unbuilt_published(
                context,
                plan_kwargs,
                builder,
                always_include_local_changes=always_include_local_changes,
            )
            # The split below re-plans through ``restate_models``; it has to name
            # everything this repair added, not just the caller's own list.
            restate = plan_kwargs["restate_models"]
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
                "cache_dir": cache_dir,
                "repair_unbuilt_promotions": repair_unbuilt_promotions,
            }
            run_sqlmesh_plan(**deploy_kwargs)
            return run_sqlmesh_plan(**deploy_kwargs, restate_models=restate), context
        return builder.build(), context
    finally:
        _release_shared_duckdb(context)


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
