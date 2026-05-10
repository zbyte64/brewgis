"""dbt runner wrapper — invokes dbt via dbt-core Python API.
# ruff: noqa: I001

Generates profiles.yml dynamically from Django DATABASES settings,
injects runtime variables (source schema, table names, scenario params),
and returns structured results for Celery task consumption.
"""

from __future__ import annotations

from brewgis.workspace.analysis.module_registry import get_column_mapping_vars

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from urllib.parse import urlparse

from dbt.cli.main import dbtRunner
from django.conf import settings

if TYPE_CHECKING:
    from dbt.contracts.results import RunResultsArtifact

# Path to the dbt project directory relative to this project root
DBT_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent / "dbt_project"


class DbtResult:
    """Structured result from a dbt invocation."""

    def __init__(
        self,
        *,
        success: bool,
        results: list[dict[str, Any]] | None = None,
        error: str | None = None,
    ) -> None:
        self.success = success
        self.results = results or []
        self.error = error


def _build_profiles_yaml() -> str:
    """Generate a dbt profiles.yml string from Django DATABASES settings.

    Reads DATABASE_URL and produces a single 'brewgis' profile targeting
    the default PostGIS connection.
    """
    db_config = settings.DATABASES["default"]

    # Parse the database connection components
    engine = db_config.get("ENGINE", "django.db.backends.postgresql")
    if "postgresql" not in engine and "postgis" not in engine:
        msg = f"Unsupported database engine for dbt: {engine}"
        raise ValueError(msg)

    host = db_config.get("HOST", "localhost")
    port = db_config.get("PORT", "5432")
    name = db_config.get("NAME", "brewgis")
    user = db_config.get("USER", "")
    password = db_config.get("PASSWORD", "")

    # Fall back to DATABASE_URL parsing if individual fields are empty
    if not user:
        db_url = _env_db_url()
        if db_url:
            parsed = urlparse(db_url)
            user = parsed.username or ""
            password = parsed.password or ""
            host = parsed.hostname or host
            port = str(parsed.port) if parsed.port else port
            name = parsed.path.lstrip("/") if parsed.path else name

    return f"""brewgis:
  target: dev
  outputs:
    dev:
      type: postgres
      threads: 1
      host: {host}
      port: {port}
      user: {user}
      pass: {password}
      dbname: {name}
      schema: public
      keepalives_idle: 0
      connect_timeout: 10
"""


def _env_db_url() -> str | None:
    """Return DATABASE_URL from environment, if set."""
    return os.environ.get("DATABASE_URL")


class DbtRunnerWrapper:
    """Wraps dbt-core's dbtRunner for programmatic invocation.

    Usage::

        runner = DbtRunnerWrapper()
        result = runner.run(
            select=["env_constraint"],
            vars_={
                "source_schema": "public",
                "parcel_table": "parcels_sacog",
                "target_schema": "public",
                "scenario_id": "test_001",
            },
        )
        print(result.success, result.results)
    """

    def __init__(self, project_dir: str | Path | None = None) -> None:
        self.project_dir = Path(project_dir) if project_dir else DBT_PROJECT_DIR

    def _parse_results(self, result: Any) -> DbtResult:
        """Extract structured results from a dbtRunner result object."""
        if not hasattr(result, "result") or result.result is None:
            return DbtResult(success=False, error=str(result))

        artifact: RunResultsArtifact | None = getattr(result.result, "results", None)
        if artifact is None:
            return DbtResult(success=False, error="No results artifact in dbt output")

        rows = [
            {
                "node_name": getattr(r, "node_name", ""),
                "status": getattr(r, "status", "unknown"),
                "execution_time": getattr(r, "timing", None),
                "message": str(getattr(r, "message", "")),
            }
            for r in artifact
        ]
        return DbtResult(success=True, results=rows)

    def run(
        self,
        select: list[str] | None = None,
        vars_: dict[str, Any] | None = None,
        *,
        full_refresh: bool = False,
    ) -> DbtResult:
        """Run dbt models with the given selectors and variables.

        Args:
            select: List of model selectors (e.g. ["env_constraint"]).
            vars_: Dictionary of dbt variables.
            full_refresh: If True, pass --full-refresh to rebuild materialized views.

        Returns:
            DbtResult with success flag, results list, or error message.
        """
        if not self.project_dir.exists():
            return DbtResult(
                success=False,
                error=f"dbt project directory not found: {self.project_dir}",
            )

        # Build CLI args
        args = ["run", "--project-dir", str(self.project_dir)]
        if select:
            args.append("--select")
            args.extend(select)
        if full_refresh:
            args.append("--full-refresh")
        # Expand column_mapping into canonical_{name} vars for dbt
        if vars_ and "column_mapping" in vars_:
            column_mapping = vars_.pop("column_mapping")
            if column_mapping:
                canonical_vars = get_column_mapping_vars(column_mapping)
                vars_.update(canonical_vars)

        if vars_:
            args.extend(["--vars", json.dumps(vars_)])

        # Create temporary profiles.yml
        profiles_content = _build_profiles_yaml()
        profiles_dir = Path(tempfile.mkdtemp(prefix="dbt_profiles_"))
        profiles_path = profiles_dir / "profiles.yml"
        profiles_path.write_text(profiles_content)
        args.extend(["--profiles-dir", str(profiles_dir)])

        dbt = dbtRunner()
        try:
            return self._parse_results(dbt.invoke(args))
        finally:
            shutil.rmtree(profiles_dir, ignore_errors=True)


def run_dbt_local(
    select: list[str] | None = None,
    vars_: dict[str, Any] | None = None,
    *,
    full_refresh: bool = False,
) -> DbtResult:
    """Convenience function for invoking dbt from Celery tasks."""
    runner = DbtRunnerWrapper()
    return runner.run(select=select, vars_=vars_, full_refresh=full_refresh)
