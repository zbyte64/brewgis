"""MCP tools for dbt analysis operations."""

import logging
from typing import Any

from django.shortcuts import get_object_or_404

from brewgis.workspace.analysis.module_registry import MODULE_DEPENDENCIES
from brewgis.workspace.analysis.module_registry import get_module_label
from brewgis.workspace.analysis.module_registry import get_result_table_names
from brewgis.workspace.analysis.pipeline import run_analysis_pipeline
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.preflight import check_analysis_prerequisites

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

        ``params`` accepts the same per-run parameters the map view's analysis
        forms collect — ``constraints`` (list of
        ``{table, discount_pct, geom_col}``) and ``column_mapping``
        (``{canonical_name: user_column}``). They are persisted on the scenario
        before the plan, because that is where the scenario's analysis models
        read them from (see ``sqlmesh/macros/analysis_blueprints.py``).
        """
        try:
            ws_pk = int(workspace_slug)
            s_pk = int(scenario_slug)
        except ValueError:
            return {"error": "Invalid slug"}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        scenario = get_object_or_404(Scenario, pk=s_pk, workspace=workspace)

        # The models derive their parcel source from the scenario itself (its
        # canvas view for an ALTERNATIVE scenario, the workspace's base canvas
        # otherwise — ``Scenario.base_layer_table``), so the prerequisites are
        # checked against exactly those.
        preflight = check_analysis_prerequisites(
            schema=workspace.db_schema,
            parcel_table=scenario.base_layer_table,
            built_form_table="built_forms",
            base_canvas_table=workspace.base_table,
        )
        if preflight:
            errors_str = "; ".join(e.message for e in preflight)
            return {
                "status": "FAILURE",
                "message": f"Prerequisites not met: {errors_str}",
            }

        p_params = dict(params or {})
        if "constraints" in p_params:
            scenario.constraints = p_params["constraints"]
        if "column_mapping" in p_params:
            scenario.column_mapping = p_params["column_mapping"]
        scenario.save(update_fields=["constraints", "column_mapping"])

        from brewgis.workspace.analysis.module_registry import resolve_module_order

        ordered = resolve_module_order(modules or list(MODULE_DEPENDENCIES))

        run = run_analysis_pipeline(
            scenario_id=scenario.pk,
            module_names=ordered,
        )
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
