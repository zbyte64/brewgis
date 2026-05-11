"""MCP tools for scenario CRUD and comparison operations."""

from __future__ import annotations

import logging
from typing import Any

from django.shortcuts import get_object_or_404
from pydantic import BaseModel

from brewgis.workspace.models import Scenario
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.scenario_cloner import clone_scenario

logger = logging.getLogger(__name__)


# ── Output Schemas ────────────────────────────────────────────


class ScenarioSummary(BaseModel):
    slug: str
    name: str
    scenario_type: str
    base_year: int | None
    horizon_year: int | None
    paint_count: int
    analysis_run_count: int
    is_published: bool


class ScenarioDetail(BaseModel):
    slug: str
    name: str
    description: str
    scenario_type: str
    base_year: int | None
    horizon_year: int | None
    total_population: float | None
    total_du: float | None
    total_employment: float | None
    paint_count: int
    last_analysis_status: str | None
    is_published: bool
    public_token: str | None


# ── Tool Registration ─────────────────────────────────────────


def register_tools(server: object) -> None:
    """Register scenario tools with the MCP server."""

    @server.tool()  # type: ignore[misc]
    def list_scenarios(workspace_slug: str) -> list[dict[str, Any]]:
        """List scenarios for a workspace."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return []
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        scenarios = Scenario.objects.filter(workspace=workspace)
        results = []
        for s in scenarios:
            results.append(
                ScenarioSummary(
                    slug=str(s.pk),
                    name=s.name,
                    scenario_type=s.scenario_type,
                    base_year=s.base_year,
                    horizon_year=s.horizon_year,
                    paint_count=s.painted_canvas.count(),
                    analysis_run_count=s.analysis_runs.count(),
                    is_published=s.published if hasattr(s, "published") else False,
                ).model_dump()
            )
        return results

    @server.tool()  # type: ignore[misc]
    def get_scenario(workspace_slug: str, scenario_slug: str) -> dict[str, Any]:
        """Get detailed scenario information."""
        try:
            ws_pk = int(workspace_slug)
            s_pk = int(scenario_slug)
        except ValueError:
            return {"error": "Invalid slug"}
        s = get_object_or_404(Scenario, pk=s_pk, workspace_id=ws_pk)
        last_run = s.analysis_runs.order_by("-created_at").first()
        return ScenarioDetail(
            slug=str(s.pk),
            name=s.name,
            description=s.description,
            scenario_type=s.scenario_type,
            base_year=s.base_year,
            horizon_year=s.horizon_year,
            total_population=None,
            total_du=None,
            total_employment=None,
            paint_count=s.painted_canvas.count(),
            last_analysis_status=last_run.status if last_run else None,
            is_published=s.published if hasattr(s, "published") else False,
            public_token=str(s.public_token)
            if hasattr(s, "public_token") and s.public_token
            else None,
        ).model_dump()

    @server.tool()  # type: ignore[misc]
    def compare_scenarios(
        workspace_slug: str,
        scenario_slugs: list[str],
        metrics: list[str] | None = None,
    ) -> dict[str, Any]:
        """Compare multiple scenarios. Metrics default to all available."""
        try:
            ws_pk = int(workspace_slug)
            s_pks = [int(s) for s in scenario_slugs]
        except ValueError:
            return {"error": "Invalid slug"}
        scenarios = Scenario.objects.filter(pk__in=s_pks, workspace_id=ws_pk)
        result: dict[str, Any] = {}
        for s in scenarios:
            result[s.name] = {
                "slug": str(s.pk),
                "type": s.scenario_type,
                "base_year": s.base_year,
                "horizon_year": s.horizon_year,
            }
        return result

    @server.tool()  # type: ignore[misc]
    def create_scenario(
        workspace_slug: str,
        name: str,
        description: str = "",
        base_year: int = 2020,
        horizon_year: int = 2050,
        clone_from_slug: str | None = None,
    ) -> dict[str, Any]:
        """Create a new scenario in a workspace."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return {"error": "Invalid workspace slug"}
        workspace = get_object_or_404(Workspace, pk=ws_pk)

        if clone_from_slug:
            try:
                source_pk = int(clone_from_slug)
            except ValueError:
                return {"error": "Invalid clone_from_slug"}
            source = get_object_or_404(Scenario, pk=source_pk, workspace=workspace)
            new_scenario = clone_scenario(
                source=source, name=name, description=description
            )
        else:
            new_scenario = Scenario.objects.create(
                workspace=workspace,
                name=name,
                description=description,
                scenario_type=ScenarioType.ALTERNATIVE,
                base_year=base_year,
                horizon_year=horizon_year,
            )

        return {
            "slug": str(new_scenario.pk),
            "name": new_scenario.name,
            "scenario_type": new_scenario.scenario_type,
            "base_year": new_scenario.base_year,
            "horizon_year": new_scenario.horizon_year,
        }

    @server.tool()  # type: ignore[misc]
    def delete_scenario(workspace_slug: str, scenario_slug: str) -> dict[str, Any]:
        """Delete a scenario."""
        try:
            ws_pk = int(workspace_slug)
            s_pk = int(scenario_slug)
        except ValueError:
            return {"error": "Invalid slug", "deleted": False}
        s = get_object_or_404(Scenario, pk=s_pk, workspace_id=ws_pk)
        s.delete()
        return {"deleted": True, "slug": scenario_slug}

    @server.tool()  # type: ignore[misc]
    def rename_scenario(
        workspace_slug: str, scenario_slug: str, new_name: str
    ) -> dict[str, Any]:
        """Rename a scenario."""
        try:
            ws_pk = int(workspace_slug)
            s_pk = int(scenario_slug)
        except ValueError:
            return {"error": "Invalid slug"}
        s = get_object_or_404(Scenario, pk=s_pk, workspace_id=ws_pk)
        s.name = new_name
        s.save()
        return {"slug": str(s.pk), "name": s.name}
