"""Dagster GraphQL client for triggering and monitoring pipeline runs.

This service wraps :class:`dagster_graphql.DagsterGraphQLClient` to submit
imputation runs to the Dagster webserver from Django views and MCP tools.
"""

from __future__ import annotations

from typing import Any
from typing import cast

import dagster_graphql

# The dagster-webserver container is reachable on this host:port
# from within the Django container (Docker Compose network).
_DAGSTER_HOST = "dagster-webserver"
_DAGSTER_PORT = 3000

_client: dagster_graphql.DagsterGraphQLClient | None = None


def _get_client() -> dagster_graphql.DagsterGraphQLClient:
    """Return a cached DagsterGraphQLClient connected to the webserver."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = dagster_graphql.DagsterGraphQLClient(
            hostname=_DAGSTER_HOST,
            port_number=_DAGSTER_PORT,
        )
    return _client


def _validate_submission(result: object) -> str:
    """Extract run_id from a submission result, raising on failure."""
    # dagster_graphql.DagsterGraphQLClient.submit_job_execution returns a
    # namedtuple-like object with .success, .message, .run_id.  mypy can't
    # resolve it because dagster_graphql has no stubs, so we duck-type.
    success = getattr(result, "success", False)
    if not success:
        message = getattr(result, "message", None)
        msg = (
            f"Dagster job submission failed: {message}"
            if message
            else "Dagster job submission returned unsuccessful result"
        )
        raise RuntimeError(msg)

    run_id = getattr(result, "run_id", None)
    if run_id is None:
        msg = "Dagster job submission succeeded but no run_id was returned"
        raise RuntimeError(msg)

    return cast("str", run_id)


def submit_impute_run(config: dict[str, Any]) -> str:
    """Submit an ``impute_area_proportional`` Dagster run.

    Args:
        config: Configuration dict matching ``ImputeAreaProportionalConfig``
            fields (``source_schema``, ``source_table``, etc.).

    Returns:
        The Dagster run ID string.

    Raises:
        RuntimeError: If the job submission fails.
    """
    client = _get_client()

    run_config = {
        "ops": {
            "impute_area_proportional_asset": {
                "config": config,
            },
        },
    }

    result = client.submit_job_execution(
        job_name="impute_area_proportional",
        repository_location_name="brewgis",
        repository_name="__repository__",
        run_config=run_config,
    )

    return _validate_submission(result)


def get_run_status(run_id: str) -> dict[str, Any]:
    """Poll Dagster for run status via GraphQL.

    Args:
        run_id: The Dagster run ID returned by :func:`submit_impute_run`.

    Returns:
        Dict with keys ``status``, ``success``, and optionally ``error``.
    """
    client = _get_client()
    status = client.get_run_status(run_id)

    return {
        "status": status.status.value if hasattr(status, "status") else str(status),
        "success": getattr(status, "is_finished", False)
        and getattr(status, "is_success", False),
    }
