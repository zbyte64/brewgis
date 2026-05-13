"""Dagster resource wrapping :class:`DbtRunnerWrapper` for dbt CLI access.

Provides a Dagster-compatible resource that can be injected into
:code:`@dbt_assets` or :code:`@asset` definitions that need to invoke
dbt models programmatically.
"""

from __future__ import annotations

from typing import Any

from dagster import ConfigurableResource
from pydantic import Field

from brewgis.workspace.analysis.dbt_runner import DbtResult
from brewgis.workspace.analysis.dbt_runner import DbtRunnerWrapper


class DbtCliResource(ConfigurableResource):
    """Dagster resource wrapping :class:`DbtRunnerWrapper`.

    Use this resource in assets that need to run dbt models:

    .. code-block:: python

        @asset
        def my_asset(context, dbt_cli: DbtCliResource):
            result = dbt_cli.run(select=["my_model"], vars_={"key": "value"})
            return MaterializeResult(metadata={"success": result.success})
    """

    project_dir: str | None = Field(
        default=None,
        description="Override for dbt project directory. Defaults to DBT_PROJECT_DIR.",
    )

    def _get_runner(self) -> DbtRunnerWrapper:
        return DbtRunnerWrapper(project_dir=self.project_dir)

    def run(
        self,
        select: list[str] | None = None,
        vars_: dict[str, Any] | None = None,
        *,
        full_refresh: bool = False,
        db_name: str | None = None,
    ) -> DbtResult:
        """Invoke ``dbt run`` with the given selectors and variables.

        Args:
            select: Model selectors (e.g. ``["env_constraint"]``).
            vars_: dbt variable overrides.
            full_refresh: Pass ``--full-refresh`` to rebuild materialized
                tables.
            db_name: Target database alias (defaults to Django's default).

        Returns:
            :class:`~brewgis.workspace.analysis.dbt_runner.DbtResult`.
        """
        runner = self._get_runner()
        return runner.run(select=select, vars_=vars_, full_refresh=full_refresh, db_name=db_name)

    def run_dbt_local(
        self,
        select: list[str] | None = None,
        vars_: dict[str, Any] | None = None,
        *,
        full_refresh: bool = False,
        db_name: str | None = None,
    ) -> DbtResult:
        """Convenience method mirroring :func:`run_dbt_local`."""
        return self.run(select=select, vars_=vars_, full_refresh=full_refresh, db_name=db_name)
