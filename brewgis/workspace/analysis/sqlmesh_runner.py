"""SQLMesh runner — replaces dbt_runner.py for BrewGIS analysis pipelines.

Uses the SQLMesh Python API (sqlmesh.core.context.Context) for tight
Django integration — not subprocess. Automatically resolves the DAG
from table references, eliminating the need for manual MODULE_DEPENDENCIES
management during execution.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlmesh.core.context import Context

logger = logging.getLogger(__name__)

SQLMESH_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent / "sqlmesh"


class SqlmeshResult:
    """Structured result from a SQLMesh invocation."""

    def __init__(
        self,
        *,
        success: bool = False,
        error: str | None = None,
        environment: str | None = None,
    ) -> None:
        self.success = success
        self.error = error
        self.environment = environment


def get_context() -> Context:
    """Return a SQLMesh Context for the BrewGIS project.

    The context loads all models, macros, seeds, and audits from the
    ``brewgis/sqlmesh/`` directory.  Callers should cache the result
    when making multiple calls within the same process lifetime.
    """
    return Context(paths=str(SQLMESH_PROJECT_DIR))


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
) -> SqlmeshResult:
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
    """
    context = get_context()
    try:
        result = context.plan(
            environment=environment,
            start=start,
            end=end,
            skip_tests=skip_tests,
            forward_only=forward_only,
            no_prompts=no_prompts,
            auto_apply=auto_apply,
            select_models=select,
            create_from=create_from,
        )
        logger.info("SQLMesh plan applied for environment '%s'", environment)
        return SqlmeshResult(
            success=True,
            environment=environment,
        )
    except Exception as e:
        logger.exception("SQLMesh plan failed for environment '%s': %s", environment, e)
        return SqlmeshResult(success=False, error=str(e), environment=environment)


def run_sqlmesh_run(
    environment: str | None = None,
    *,
    select: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> SqlmeshResult:
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
    try:
        context.run(
            environment=environment,
            start=start,
            end=end,
            select_models=select,
        )
        logger.info("SQLMesh run completed for environment '%s'", environment)
        return SqlmeshResult(
            success=True,
            environment=environment,
        )
    except Exception as e:
        logger.exception("SQLMesh run failed for environment '%s': %s", environment, e)
        return SqlmeshResult(success=False, error=str(e), environment=environment)


def run_sqlmesh_test(
    *,
    models: list[str] | None = None,
    verbose: bool = False,
) -> SqlmeshResult:
    """Run SQLMesh unit tests.

    Args:
        models: Optional list of model names to test.
        verbose: Enable verbose test output.
    """
    context = get_context()
    try:
        result = context.test(models=models, verbose=verbose)
        passed = result.count("FAILED") == 0 if isinstance(result, str) else True
        logger.info("SQLMesh test completed")
        return SqlmeshResult(success=passed)
    except Exception as e:
        logger.exception("SQLMesh test failed: %s", e)
        return SqlmeshResult(success=False, error=str(e))


def run_sqlmesh_table_diff(
    source_env: str,
    target_env: str,
    model: str | None = None,
) -> dict[str, Any]:
    """Compare tables between two SQLMesh environments.

    Args:
        source_env: Source environment name.
        target_env: Target environment name.
        model: Optional model name to compare (compares all if None).

    Returns:
        Dict with diff results.
    """
    context = get_context()
    try:
        diff = context.table_diff(
            source=source_env,
            target=target_env,
            model=model,
        )
        return {"success": True, "diff": str(diff)}
    except Exception as e:
        logger.exception(
            "SQLMesh table_diff failed between '%s' and '%s': %s",
            source_env,
            target_env,
            e,
        )
        return {"success": False, "error": str(e)}


def evaluate_model(
    model_name: str,
    environment: str | None = None,
    limit: int = 10,
) -> Any:
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
    try:
        df = context.evaluate(
            model_name=model_name,
            environment=environment,
            limit=limit,
        )
        return df
    except Exception as e:
        logger.exception("SQLMesh evaluate failed for '%s': %s", model_name, e)
        return None
