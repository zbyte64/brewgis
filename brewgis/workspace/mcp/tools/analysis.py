"""MCP tools for dbt analysis operations (Celery-backed)."""

from __future__ import annotations

import logging
from typing import Any

from celery.result import AsyncResult
from django.shortcuts import get_object_or_404

from brewgis.workspace.analysis.module_registry import MODULE_DEPENDENCIES
from brewgis.workspace.analysis.module_registry import get_module_label
from brewgis.workspace.analysis.module_registry import get_result_table_names
from brewgis.workspace.analysis.pipeline import run_analysis_pipeline
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.preflight import check_analysis_prerequisites
from brewgis.workspace.tasks import run_preprocessor_and_dbt

logger = logging.getLogger(__name__)


def register_tools(server: object) -> None:
    """Register analysis tools with the MCP server."""

    @server.tool()  # type: ignore[misc]
    def list_analysis_modules(workspace_slug: str) -> list[dict[str, Any]]:
        """List available analysis modules with prerequisites."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return []
        get_object_or_404(Workspace, pk=ws_pk)

        modules = []
        for module_key in MODULE_DEPENDENCIES:
            modules.append({
                "key": module_key,
                "label": get_module_label(module_key),
                "prerequisites": MODULE_DEPENDENCIES[module_key],
                "result_tables": get_result_table_names(module_key, "{scenario_id}"),
            })
        return modules

    @server.tool()  # type: ignore[misc]
    def run_analysis(
        workspace_slug: str,
        scenario_slug: str,
        modules: list[str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run analysis modules for a scenario."""
        try:
            ws_pk = int(workspace_slug)
            s_pk = int(scenario_slug)
        except ValueError:
            return {"error": "Invalid slug"}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        scenario = get_object_or_404(Scenario, pk=s_pk, workspace=workspace)

        # Check prerequisites
        preflight = check_analysis_prerequisites(scenario, modules=modules)
        if not preflight.get("ready", False):
            return {
                "status": "FAILURE",
                "message": f"Prerequisites not met: {preflight.get('missing', 'unknown')}",
            }

        # Launch Celery task
        task = run_preprocessor_and_dbt.delay(
            scenario_id=scenario.pk,
            modules=modules,
            params=params or {},
        )
        return {
            "task_id": task.id,
            "status": "PENDING",
            "message": f"Analysis launched for scenario '{scenario.name}'",
        }

    @server.tool()  # type: ignore[misc]
    def get_analysis_status(workspace_slug: str, run_id: int) -> dict[str, Any]:
        """Get the current status of an analysis run."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return {"error": "Invalid workspace slug"}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        run = get_object_or_404(AnalysisRun, pk=run_id, workspace=workspace)
        return {
            "id": run.pk,
            "status": run.status,
            "current_module": run.current_module or "",
            "completed_modules": run.completed_modules or [],
            "error": run.error_message or None,
            "created_at": str(run.created_at),
        }

    @server.tool()  # type: ignore[misc]
    def get_analysis_results(workspace_slug: str, run_id: int) -> dict[str, Any]:
        """Get results for a completed analysis run."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return {"error": "Invalid workspace slug"}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        run = get_object_or_404(AnalysisRun, pk=run_id, workspace=workspace)
        return {
            "id": run.pk,
            "status": run.status,
            "modules": run.modules or [],
            "result_summary": run.result_summary or {},
        }
