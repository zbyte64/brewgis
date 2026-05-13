"""MCP tools for dbt analysis operations (Celery-backed)."""



import logging
from typing import Any

from django.shortcuts import get_object_or_404

from brewgis.workspace.analysis.module_registry import MODULE_DEPENDENCIES
from brewgis.workspace.analysis.module_registry import get_module_label
from brewgis.workspace.analysis.module_registry import get_result_table_names
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.preflight import check_analysis_prerequisites
from brewgis.workspace.tasks import run_preprocessor_and_dbt

logger = logging.getLogger(__name__)


def register_tools(server: object) -> None:
    """Register analysis tools with the MCP server."""

    @server.tool()  # type: ignore[attr-defined]
    def list_analysis_modules(workspace_slug: str) -> list[dict[str, Any]]:
        """List available analysis modules with prerequisites."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return []
        get_object_or_404(Workspace, pk=ws_pk)

        modules = []
        for module_key in MODULE_DEPENDENCIES:
            modules.append(
                {
                    "key": module_key,
                    "label": get_module_label(module_key),
                    "prerequisites": MODULE_DEPENDENCIES[module_key],
                    "result_tables": get_result_table_names(
                        module_key, "{scenario_id}"
                    ),
                }
            )
        return modules

    @server.tool()  # type: ignore[attr-defined]
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
        p_params = params or {}
        preflight = check_analysis_prerequisites(
            schema=workspace.db_schema,
            parcel_table=p_params.get("parcel_table", ""),
            built_form_table=p_params.get("built_form_table"),
            base_canvas_table=p_params.get("base_canvas_table"),
        )
        if preflight:
            errors_str = "; ".join(e.message for e in preflight)
            return {
                "status": "FAILURE",
                "message": f"Prerequisites not met: {errors_str}",
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

    @server.tool()  # type: ignore[attr-defined]
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
            "current_module": run.modules[-1] if run.modules else "",
            "completed_modules": run.modules or [],
            "error": run.error_log or None,
            "created_at": str(run.created_at),
        }

    @server.tool()  # type: ignore[attr-defined]
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
            "result_summary": {},
        }
