"""MCP tools for data import operations (Celery-backed) and job management."""

from __future__ import annotations

import logging
from typing import Any

from celery.result import AsyncResult
from django.shortcuts import get_object_or_404

from brewgis.workspace.models import DataImportRun
from brewgis.workspace.models import Workspace
from brewgis.workspace.tasks import run_census_fetch
from brewgis.workspace.tasks import run_column_stitching
from brewgis.workspace.tasks import run_lehd_fetch
from brewgis.workspace.tasks import run_poi_fetch
from brewgis.workspace.tasks import run_spatial_allocation

logger = logging.getLogger(__name__)


def _get_workspace(workspace_slug: str) -> Workspace | None:
    """Resolve workspace from slug (string pk)."""
    try:
        return get_object_or_404(Workspace, pk=int(workspace_slug))
    except (ValueError, TypeError):
        return None


def register_tools(server: object) -> None:
    """Register data import tools with the MCP server."""

    # ── Job Management ──────────────────────────────────────────

    @server.tool()  # type: ignore[misc]
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

    @server.tool()  # type: ignore[misc]
    def cancel_job(task_id: str) -> dict[str, Any]:
        """Cancel a running Celery task."""
        try:
            AsyncResult(task_id).revoke(terminate=True)
            return {"task_id": task_id, "cancelled": True}
        except Exception as e:
            return {"task_id": task_id, "cancelled": False, "error": str(e)}

    # ── Data Import Tools ───────────────────────────────────────

    @server.tool()  # type: ignore[misc]
    def run_census_fetch_tool(
        workspace_slug: str,
        state_fips: str,
        tables: list[str] | None = None,
        year: int | None = None,
        geography: str | None = None,
    ) -> dict[str, Any]:
        """Fetch Census ACS data for a geography."""
        workspace = _get_workspace(workspace_slug)
        if workspace is None:
            return {"error": "Invalid workspace slug"}

        task = run_census_fetch.delay(
            state_fips=state_fips,
            county_fips=None,
            tables=tables,
            year=year,
            geography=geography or "block group",
        )
        return {
            "task_id": task.id,
            "status": "PENDING",
            "message": f"Census fetch launched for state {state_fips}",
        }

    @server.tool()  # type: ignore[misc]
    def run_lehd_fetch_tool(
        workspace_slug: str,
        state_fips: str,
        job_types: list[str] | None = None,
        year: int | None = None,
    ) -> dict[str, Any]:
        """Fetch LEHD/LODES employment data for a geography."""
        workspace = _get_workspace(workspace_slug)
        if workspace is None:
            return {"error": "Invalid workspace slug"}

        task = run_lehd_fetch.delay(
            state_fips=state_fips,
            county_fips=None,
            job_types=job_types,
            year=year,
        )
        return {
            "task_id": task.id,
            "status": "PENDING",
            "message": f"LEHD fetch launched for state {state_fips}",
        }

    @server.tool()  # type: ignore[misc]
    def run_poi_fetch_tool(
        workspace_slug: str,
        geometry_wkt: str,
        categories: list[str] | None = None,
        radius_m: int | None = None,
    ) -> dict[str, Any]:
        """Fetch POIs from OpenStreetMap for an area."""
        workspace = _get_workspace(workspace_slug)
        if workspace is None:
            return {"error": "Invalid workspace slug"}

        task = run_poi_fetch.delay(
            geometry_wkt=geometry_wkt,
            categories=categories,
            radius_m=radius_m,
        )
        return {
            "task_id": task.id,
            "status": "PENDING",
            "message": f"POI fetch launched for area",
        }

    @server.tool()  # type: ignore[misc]
    def run_spatial_allocation_tool(
        workspace_slug: str,
        source_layer_key: str,
        target_layer_key: str,
        method: str = "area_weighted",
        columns: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run spatial allocation from source to target layer."""
        workspace = _get_workspace(workspace_slug)
        if workspace is None:
            return {"error": "Invalid workspace slug"}

        task = run_spatial_allocation.delay(
            source_layer_key=source_layer_key,
            target_layer_key=target_layer_key,
            method=method,
            columns=columns,
        )
        return {
            "task_id": task.id,
            "status": "PENDING",
            "message": f"Spatial allocation launched",
        }

    @server.tool()  # type: ignore[misc]
    def run_column_stitching_tool(
        workspace_slug: str,
        target_table: str,
        mappings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run column stitching/imputation on a target table."""
        workspace = _get_workspace(workspace_slug)
        if workspace is None:
            return {"error": "Invalid workspace slug"}

        task = run_column_stitching.delay(
            target_table=target_table,
            mappings=mappings,
        )
        return {
            "task_id": task.id,
            "status": "PENDING",
            "message": f"Column stitching launched for {target_table}",
        }

    @server.tool()  # type: ignore[misc]
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
                "rows_imported": run.rows_imported,
                "error": run.error_message or None,
                "created_at": str(run.created_at),
            }
        except DataImportRun.DoesNotExist:
            return {"error": "Import run not found"}
