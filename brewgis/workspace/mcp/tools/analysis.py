"""MCP tools for dbt analysis operations."""

import logging
from typing import Any

from django.shortcuts import get_object_or_404

from brewgis.workspace.analysis.launch import AnalysisLaunchError
from brewgis.workspace.analysis.launch import launch_analysis
from brewgis.workspace.analysis.module_registry import MODULE_DEPENDENCIES
from brewgis.workspace.analysis.module_registry import get_module_label
from brewgis.workspace.analysis.module_registry import get_result_table_names
from brewgis.workspace.analysis.run_health import reconcile_abandoned_run
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace

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
        """Run analysis modules for a scenario.

        Goes through the same launch service as the map view's analysis forms
        (``brewgis/workspace/analysis/launch.py``): the same validation, the same
        rules for storing parameters on the scenario, the same background
        dispatch. The run is returned ``pending``; poll ``get_analysis_status``.

        ``params`` is ``{parameter: value}`` over the analysis parameters
        (``module_registry.ANALYSIS_PARAMETERS``), merged into the scenario's
        stored values. The data each module reads — parcels, built forms, the
        region's constraint layers — comes from the workspace and is built by
        SQLMesh, so there are no tables or columns to pass.
        """
        try:
            ws_pk = int(workspace_slug)
            s_pk = int(scenario_slug)
        except ValueError:
            return {"error": "Invalid slug"}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        scenario = get_object_or_404(Scenario, pk=s_pk, workspace=workspace)

        try:
            run = launch_analysis(
                scenario=scenario,
                modules=modules or list(MODULE_DEPENDENCIES),
                params=params,
            )
        except AnalysisLaunchError as error:
            return {
                "status": "FAILURE",
                "message": f"Analysis not started: {error}",
            }
        return {
            "run_id": run.pk,
            "status": run.status,
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
        # An assistant polling this tool must not be told a run is still going
        # when its worker died; see brewgis.workspace.analysis.run_health.
        reconcile_abandoned_run(run)
        return {
            "id": run.pk,
            "status": run.status,
            "current_module": run.modules[-1] if run.modules else "",
            "completed_modules": run.modules or [],
            "failure_cause": run.failure_cause or None,
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
