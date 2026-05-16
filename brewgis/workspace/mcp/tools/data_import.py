"""MCP tools for data import operations (Celery-backed) and job management."""

import logging
from typing import Any

from celery.result import AsyncResult
from django.shortcuts import get_object_or_404

from brewgis.workspace.models import DataImportRun
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.dagster_client import submit_impute_run
from brewgis.workspace.tasks import run_census_fetch
from brewgis.workspace.tasks import run_column_stitching
from brewgis.workspace.tasks import run_lehd_fetch
from brewgis.workspace.tasks import run_poi_fetch
from brewgis.workspace.tasks import run_raster_fetch
from brewgis.workspace.tasks import run_spatial_allocation

logger = logging.getLogger(__name__)


def _get_workspace(workspace_slug: str) -> Workspace | None:
    """Resolve workspace from slug (string pk)."""
    try:
        return get_object_or_404(Workspace, pk=int(workspace_slug))
    except (ValueError, TypeError):
        return None


def _create_import_run(
    workspace: Workspace,
    import_type: str,
    params: dict[str, Any],
) -> DataImportRun:
    """Create a DataImportRun record and return it."""
    return DataImportRun.objects.create(
        workspace=workspace,
        import_type=import_type,
        params=params,
        status="pending",
    )


def register_tools(server: object) -> None:
    """Register data import tools with the MCP server."""

    # ── Job Management ──────────────────────────────────────────

    @server.tool()  # type: ignore[attr-defined]
    def get_job_status(task_id: str) -> dict[str, Any]:
        """Get the status of a Celery task by task ID."""
        try:
            result = AsyncResult(task_id)
            status = result.status
            info = {
                "task_id": task_id,
                "status": status,
            }
            if result.successful():
                info["result"] = str(result.result)
            elif result.failed():
                info["error"] = str(result.result)
            return info
        except Exception as e:
            return {"task_id": task_id, "status": "UNKNOWN", "error": str(e)}

    @server.tool()  # type: ignore[attr-defined]
    def cancel_job(task_id: str) -> dict[str, Any]:
        """Cancel a running Celery task."""
        try:
            AsyncResult(task_id).revoke(terminate=True)
            return {"task_id": task_id, "cancelled": True}
        except Exception as e:
            return {"task_id": task_id, "cancelled": False, "error": str(e)}

    # ── Data Import Tools ───────────────────────────────────────

    @server.tool()  # type: ignore[attr-defined]
    def run_census_fetch_tool(
        workspace_slug: str,
        state_fips: str,
        county_fips: str,
        year: int = 2022,
    ) -> dict[str, Any]:
        """Fetch Census ACS data for a geography. Creates a DataImportRun and dispatches a Celery task."""
        workspace = _get_workspace(workspace_slug)
        if workspace is None:
            return {"error": "Invalid workspace slug"}

        run = _create_import_run(
            workspace=workspace,
            import_type="census",
            params={
                "state_fips": state_fips,
                "county_fips": county_fips,
                "year": year,
            },
        )

        task = run_census_fetch.delay(
            run_pk=run.pk,
            state_fips=state_fips,
            county_fips=county_fips,
            schema=workspace.db_schema,
            year=year,
        )
        return {
            "task_id": task.id,
            "run_id": run.pk,
            "status": run.status,
            "message": f"Census fetch launched for state {state_fips}, county {county_fips}",
        }

    @server.tool()  # type: ignore[attr-defined]
    def run_lehd_fetch_tool(
        workspace_slug: str,
        state_fips: str,
        county_fips: str,
        year: int = 2022,
    ) -> dict[str, Any]:
        """Fetch LEHD/LODES employment data for a geography. Creates a DataImportRun and dispatches a Celery task."""
        workspace = _get_workspace(workspace_slug)
        if workspace is None:
            return {"error": "Invalid workspace slug"}

        run = _create_import_run(
            workspace=workspace,
            import_type="lehd",
            params={
                "state_fips": state_fips,
                "county_fips": county_fips,
                "year": year,
            },
        )

        task = run_lehd_fetch.delay(
            run_pk=run.pk,
            state_fips=state_fips,
            county_fips=county_fips,
            schema=workspace.db_schema,
            year=year,
        )
        return {
            "task_id": task.id,
            "run_id": run.pk,
            "status": run.status,
            "message": f"LEHD fetch launched for state {state_fips}, county {county_fips}",
        }

    @server.tool()  # type: ignore[attr-defined]
    def run_poi_fetch_tool(
        workspace_slug: str,
        min_lng: float,
        min_lat: float,
        max_lng: float,
        max_lat: float,
        categories: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch POIs from OpenStreetMap for an area. Creates a DataImportRun and dispatches a Celery task."""
        workspace = _get_workspace(workspace_slug)
        if workspace is None:
            return {"error": "Invalid workspace slug"}

        run = _create_import_run(
            workspace=workspace,
            import_type="poi",
            params={
                "min_lng": min_lng,
                "min_lat": min_lat,
                "max_lng": max_lng,
                "max_lat": max_lat,
                "categories": categories,
            },
        )

        task = run_poi_fetch.delay(
            run_pk=run.pk,
            min_lng=min_lng,
            min_lat=min_lat,
            max_lng=max_lng,
            max_lat=max_lat,
            categories=categories,
            schema=workspace.db_schema,
        )
        return {
            "task_id": task.id,
            "run_id": run.pk,
            "status": run.status,
            "message": "POI fetch launched for area",
        }

    @server.tool()  # type: ignore[attr-defined]
    def run_raster_fetch_tool(
        workspace_slug: str,
        file_path: str,
    ) -> dict[str, Any]:
        """Extract raster metadata and band statistics from a GeoTIFF
        file. Creates a DataImportRun and dispatches a Celery task."""
        workspace = _get_workspace(workspace_slug)
        if workspace is None:
            return {"error": "Invalid workspace slug"}

        run = _create_import_run(
            workspace=workspace,
            import_type="raster",
            params={
                "file_path": file_path,
            },
        )

        task = run_raster_fetch.delay(
            run_pk=run.pk,
            file_path=file_path,
            schema=workspace.db_schema,
        )
        return {
            "task_id": task.id,
            "run_id": run.pk,
            "status": run.status,
            "message": f"Raster fetch launched for {file_path}",
        }

    @server.tool()  # type: ignore[attr-defined]
    def run_spatial_allocation_tool(
        workspace_slug: str,
        source_schema: str,
        source_table: str,
        target_schema: str,
        target_table: str,
        columns: list[str],
        column_prefix: str = "",
        source_geom_col: str = "geom",
        target_geom_col: str = "geom",
    ) -> dict[str, Any]:
        """Run spatial allocation from source to target layer. Creates a DataImportRun and dispatches a Celery task."""
        workspace = _get_workspace(workspace_slug)
        if workspace is None:
            return {"error": "Invalid workspace slug"}

        run = _create_import_run(
            workspace=workspace,
            import_type="allocate",
            params={
                "source_schema": source_schema,
                "source_table": source_table,
                "target_schema": target_schema,
                "target_table": target_table,
                "columns": columns,
                "column_prefix": column_prefix,
                "source_geom_col": source_geom_col,
                "target_geom_col": target_geom_col,
            },
        )

        task = run_spatial_allocation.delay(
            run_pk=run.pk,
            source_schema=source_schema,
            source_table=source_table,
            target_schema=target_schema,
            target_table=target_table,
            columns=columns,
            column_prefix=column_prefix,
            source_geom_col=source_geom_col,
            target_geom_col=target_geom_col,
        )
        return {
            "task_id": task.id,
            "run_id": run.pk,
            "status": run.status,
            "message": (
                f"Spatial allocation launched from "
                f"{source_schema}.{source_table} to "
                f"{target_schema}.{target_table}"
            ),
        }

    @server.tool()  # type: ignore[attr-defined]
    def run_column_stitching_tool(
        workspace_slug: str,
        schema: str,
        table: str,
        target_column: str,
        strategy: str,
        default_value: float | None = None,
        source_table: str | None = None,
        source_column: str | None = None,
    ) -> dict[str, Any]:
        """Run column stitching/imputation on a target table. Creates
        a DataImportRun and dispatches a Celery task."""
        workspace = _get_workspace(workspace_slug)
        if workspace is None:
            return {"error": "Invalid workspace slug"}

        run = _create_import_run(
            workspace=workspace,
            import_type="stitch",
            params={
                "schema": schema,
                "table": table,
                "target_column": target_column,
                "strategy": strategy,
                "default_value": default_value,
                "source_table": source_table,
                "source_column": source_column,
            },
        )

        if strategy == "area_proportional":
            dagster_run_id = submit_impute_run(
                {
                    "source_schema": schema,
                    "source_table": source_table,
                    "source_column": source_column,
                    "target_schema": schema,
                    "target_table": table,
                    "target_column": target_column,
                    "scenario_id": f"stitch_{run.pk}",
                }
            )
            run.params["dagster_run_id"] = dagster_run_id
            run.save(update_fields=["params"])
            return {
                "dagster_run_id": dagster_run_id,
                "run_id": run.pk,
                "status": run.status,
                "message": f"Area-proportional stitching launched for {schema}.{table}.{target_column}",
            }
        task = run_column_stitching.delay(
            run_pk=run.pk,
            schema=schema,
            table=table,
            target_column=target_column,
            strategy=strategy,
            default_value=default_value,
            source_table=source_table,
            source_column=source_column,
        )
        return {
            "task_id": task.id,
            "run_id": run.pk,
            "status": run.status,
            "message": f"Column stitching launched for {schema}.{table}.{target_column} ({strategy})",
        }

    @server.tool()  # type: ignore[attr-defined]
    def get_import_status(workspace_slug: str, import_run_id: int) -> dict[str, Any]:
        """Get import operation status."""
        workspace = _get_workspace(workspace_slug)
        if workspace is None:
            return {"error": "Invalid workspace slug"}
        try:
            run = DataImportRun.objects.get(pk=import_run_id, workspace=workspace)
            return {
                "id": run.pk,
                "status": run.status,
                "rows_imported": run.result.get("row_count") if run.result else None,
                "error": run.error_log or None,
                "created_at": str(run.created_at),
            }
        except DataImportRun.DoesNotExist:
            return {"error": "Import run not found"}
