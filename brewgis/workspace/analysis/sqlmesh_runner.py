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

from sqlmesh.core.context import Context

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


def _models_in_environment(context: Context, environment: str) -> list[str]:
    """Return FQNs of models materialized in *environment*.

    Queries SQLMesh's state for the promoted snapshots in the given
    environment and extracts the display name (model FQN) for each.
    """
    env = context.state_reader.get_environment(environment)
    if env is None:
        return []
    snapshots = getattr(env, "promoted_snapshots", None) or []
    # s.name is the quoted FQN (e.g. '"brewgis"."staging"."acs_block_group"');
    # strip quotes for selector compatibility (brewgis.staging.acs_block_group).
    return [s.name.replace('"', "") for s in snapshots]


def run_sqlmesh_plan(  # noqa: PLR0913
    environment: str,
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
    """
    context = get_context(**variables)
    logger.info("SQLMesh plan applied for environment '%s'", environment)
    return context.plan(
        environment=environment,
        start=start,
        end=end,
        skip_tests=skip_tests,
        forward_only=forward_only,
        no_prompts=no_prompts,
        auto_apply=auto_apply,
        select_models=select,
        create_from=create_from,
        restate_models=_models_in_environment(context, environment)
        if restate_models is True
        else (restate_models or None),
    ), context


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
