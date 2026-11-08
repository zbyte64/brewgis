"""MCP tools for workspace CRUD operations."""

import base64
import logging
import tempfile
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from pydantic import BaseModel

from brewgis.workspace.models import Workspace
from brewgis.workspace.models import WorkspaceExport
from brewgis.workspace.services import workspace_package
from brewgis.workspace.services.workspace_package import PackageError
from brewgis.workspace.tasks import export_workspace_package_task
from brewgis.workspace.tasks import start_package_build

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

    # ── Workspace packages (services/workspace_package.py) ────────────
    # The same service calls as the hub's export button and the Import
    # Center's package import, so an MCP client cannot export or import a
    # workspace any differently.

    @server.tool()  # type: ignore[attr-defined]
    def export_workspace_package(
        workspace_slug: str, include_public_data: bool = False
    ) -> dict[str, Any]:
        """Export a workspace as a workspace package; poll get_workspace_export_status."""
        workspace = get_object_or_404(Workspace, pk=int(workspace_slug))
        export = WorkspaceExport.objects.create(
            workspace=workspace, include_public_data=include_public_data
        )
        transaction.on_commit(lambda: export_workspace_package_task.delay(export.pk))
        return {"export_id": export.pk, "status": export.status}

    @server.tool()  # type: ignore[attr-defined]
    def get_workspace_export_status(
        workspace_slug: str, export_id: int
    ) -> dict[str, Any]:
        """Get a workspace package export's status and, once complete, its file."""
        export = get_object_or_404(
            WorkspaceExport, pk=export_id, workspace_id=int(workspace_slug)
        )
        return {
            "export_id": export.pk,
            "status": export.status,
            "file": export.file.path if export.file else None,
            "error": export.error_log or None,
        }

    @server.tool()  # type: ignore[attr-defined]
    def import_workspace_package(
        file_data_base64: str,
        name: str | None = None,
        local_srid: int | None = None,
    ) -> dict[str, Any]:
        """Import a workspace package zip (base64) as a new workspace; poll get_import_status."""
        raw = base64.b64decode(file_data_base64)
        if len(raw) > settings.MAX_WORKSPACE_PACKAGE_SIZE:
            return {"error": "Package too large."}
        with tempfile.TemporaryDirectory(prefix="brewgis-mcp-package-") as tmp:
            path = Path(tmp) / "package.zip"
            path.write_bytes(raw)
            try:
                workspace = workspace_package.import_workspace_package(
                    path, name=name, local_srid=local_srid
                )
            except PackageError as error:
                return {"error": str(error)}
        run = start_package_build(workspace, params={"source": "mcp"})
        return {"workspace_slug": str(workspace.pk), "import_run_id": run.pk}
