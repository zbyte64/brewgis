"""dbt model assets for the analysis pipeline.

Wraps dbt model execution within Dagster's asset graph using the
:class:`~brewgis.workspace.dagster.resources.dbt_resource.DbtCliResource`.
All 40 existing dbt models (SQL + 2 Python) are available for
Dagster-managed materialization.
"""

from __future__ import annotations

from typing import Any

from dagster import AssetExecutionContext
from dagster import MaterializeResult
from dagster import asset

from brewgis.workspace.dagster.resources.dbt_resource import DbtCliResource


@asset(
    group_name="dbt_staging",
    compute_kind="dbt",
)
def dbt_staging_models(context: AssetExecutionContext, dbt_cli: DbtCliResource) -> MaterializeResult:
    """Materialize all dbt staging models (``staging.*``).

    These wrap imported tables (parcels, base canvas, census, LEHD, POI)
    with clean column names and types.
    """
    result = dbt_cli.run(select=["staging"])
    if not result.success:
        raise RuntimeError(f"dbt staging run failed: {result.error}")
    return MaterializeResult(metadata={"success": True})


@asset(
    group_name="dbt_analysis",
    compute_kind="dbt",
)
def dbt_env_constraint(context: AssetExecutionContext, dbt_cli: DbtCliResource) -> MaterializeResult:
    """Run the ``env_constraint`` dbt model (environmental constraint layer)."""
    result = dbt_cli.run(select=["env_constraint"])
    if not result.success:
        raise RuntimeError(f"dbt env_constraint failed: {result.error}")
    return MaterializeResult(metadata={"success": True})


@asset(
    group_name="dbt_analysis",
    compute_kind="dbt",
)
def dbt_core_allocation(context: AssetExecutionContext, dbt_cli: DbtCliResource) -> MaterializeResult:
    """Run core allocation dbt models (``core_end_state``, ``core_increment``)."""
    result = dbt_cli.run(select=["core_end_state", "core_increment"])
    if not result.success:
        raise RuntimeError(f"dbt core allocation failed: {result.error}")
    return MaterializeResult(metadata={"success": True})


@asset(
    group_name="dbt_analysis",
    compute_kind="dbt",
)
def dbt_transport(
    context: AssetExecutionContext,
    dbt_cli: DbtCliResource,
) -> MaterializeResult:
    """Run transport chain dbt models (trip generation, distribution, mode choice)."""
    result = dbt_cli.run(select=["transport_trip_generation", "transport_trip_distribution"])
    if not result.success:
        raise RuntimeError(f"dbt transport chain failed: {result.error}")
    return MaterializeResult(metadata={"success": True})


@asset(
    group_name="dbt_analysis",
    compute_kind="dbt",
)
def dbt_impact_modules(
    context: AssetExecutionContext,
    dbt_cli: DbtCliResource,
) -> MaterializeResult:
    """Run downstream impact dbt models (land, energy, water, fiscal, GHG, health)."""
    result = dbt_cli.run(
        select=[
            "land",
            "energy_demand",
            "water_demand",
            "fiscal_impact",
            "ghg_emissions",
            "health",
            "stormwater",
        ],
    )
    if not result.success:
        raise RuntimeError(f"dbt impact modules failed: {result.error}")
    return MaterializeResult(metadata={"success": True})
