"""Service-layer Dagster assets for spatial allocation, imputation, and ETL.

These assets wrap the existing service-layer functions (spatial allocator,
stitcher/imputation, canvas ETL) as software-defined assets for orchestration
within Dagster's asset graph.
"""

from __future__ import annotations

from typing import Any

from dagster import AssetIn
from dagster import AssetKey
from dagster import MaterializeResult
from dagster import asset

from brewgis.workspace.dagster.resources.postgres_resource import PostgresResource


@asset(
    group_name="etl",
    compute_kind="python",
    ins={
        "raw_parcels": AssetIn(key=AssetKey("raw_parcels")),
    },
)
def spatial_allocation(
    context: Any,
    postgres: PostgresResource,
    raw_parcels: Any,  # noqa: ANN401
) -> MaterializeResult:
    """Run the spatial allocator to allocate attributes to parcels.

    Consumes the raw parcels asset (from file upload or base canvas ETL)
    and produces allocated parcel attributes.
    """
    # Placeholder — Phase 2 will wire the actual service
    # from brewgis.workspace.services.spatial_allocator import allocate_attributes
    context.log.info("spatial_allocation asset invoked (not yet wired)")
    return MaterializeResult(metadata={"status": "placeholder"})


@asset(
    group_name="etl",
    compute_kind="python",
    ins={
        "allocated_parcels": AssetIn(key=AssetKey("spatial_allocation")),
    },
)
def imputation(
    context: Any,
    postgres: PostgresResource,
    allocated_parcels: Any,  # noqa: ANN401
) -> MaterializeResult:
    """Run imputation engine to fill missing attribute values.

    Chains after spatial allocation to apply area-proportional and
    built-form-default imputation strategies.
    """
    context.log.info("imputation asset invoked (not yet wired)")
    return MaterializeResult(metadata={"status": "placeholder"})


@asset(
    group_name="etl",
    compute_kind="python",
)
def base_canvas_etl(context: Any, postgres: PostgresResource) -> MaterializeResult:
    """ETL pipeline for base canvas data import and validation.

    Orchestrates reading source data, validating against the BaseCanvasSchema,
    and writing to the base canvas staging table.
    """
    context.log.info("base_canvas_etl asset invoked (not yet wired)")
    return MaterializeResult(metadata={"status": "placeholder"})
