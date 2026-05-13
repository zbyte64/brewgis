"""MCP tools for workspace CRUD operations."""



import logging
from typing import Any

from django.shortcuts import get_object_or_404
from pydantic import BaseModel

from brewgis.workspace.models import Workspace

logger = logging.getLogger(__name__)


# ── Output Schemas ────────────────────────────────────────────


class WorkspaceSummary(BaseModel):
    slug: str
    name: str
    scenario_count: int
    layer_count: int
    created_at: str


class WorkspaceDetail(BaseModel):
    slug: str
    name: str
    db_schema: str
    county_fips_list: list[dict[str, str]]
    scenario_count: int
    layer_count: int
    analysis_run_count: int
    created_at: str


# ── Tool Registration ─────────────────────────────────────────


def register_tools(server: object) -> None:
    """Register workspace tools with the MCP server."""

    @server.tool()  # type: ignore[attr-defined]
    def list_workspaces(query: str | None = None) -> list[dict[str, Any]]:
        """List workspaces accessible to the authenticated user."""
        qs = Workspace.objects.all()
        if query:
            qs = qs.filter(name__icontains=query)
        results = []
        for w in qs.prefetch_related("layers", "analysis_runs"):
            results.append(
                WorkspaceSummary(
                    slug=str(w.pk),
                    name=w.name,
                    scenario_count=w.scenarios.count(),
                    layer_count=w.layers.count(),
                    created_at=str(w.pk),
                ).model_dump()
            )
        return results

    @server.tool()  # type: ignore[attr-defined]
    def get_workspace(slug: str) -> dict[str, Any]:
        """Get detailed workspace information by slug (pk as string)."""
        try:
            pk = int(slug)
        except ValueError:
            return {"error": f"Invalid workspace slug: {slug}"}
        w = get_object_or_404(Workspace, pk=pk)
        return WorkspaceDetail(
            slug=str(w.pk),
            name=w.name,
            db_schema=w.db_schema,
            county_fips_list=w.county_fips_list,
            scenario_count=w.scenarios.count(),
            layer_count=w.layers.count(),
            analysis_run_count=w.analysis_runs.count(),
            created_at=str(w.pk),
        ).model_dump()
