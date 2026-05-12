"""MCP tools for report generation and GIS file import."""



import base64
import logging
import tempfile
from pathlib import Path
from typing import Any

import geopandas as gpd
from django.shortcuts import get_object_or_404
from sqlalchemy import create_engine

from brewgis.workspace.models import ScenarioReport
from brewgis.workspace.models import Workspace
from brewgis.workspace.symbology.auto import auto_generate_symbology
from brewgis.workspace.tasks import generate_report_task

logger = logging.getLogger(__name__)


def _get_workspace(workspace_slug: str) -> Workspace | None:
    """Resolve workspace from slug (string pk)."""
    try:
        return get_object_or_404(Workspace, pk=int(workspace_slug))
    except (ValueError, TypeError):
        return None


def _get_engine() -> create_engine:
    """Build a SQLAlchemy engine from Django DB settings."""
    from django.conf import settings

    db = settings.DATABASES["default"]
    return create_engine(
        f"postgresql://{db['USER']}:{db['PASSWORD']}@{db['HOST']}:{db['PORT']}/{db['NAME']}"
    )


def register_tools(server: object) -> None:
    """Register report tools with the MCP server."""

    @server.tool()  # type: ignore[misc]
    def list_report_templates(workspace_slug: str) -> list[dict[str, Any]]:
        """List available report types."""
        _get_workspace(workspace_slug)
        return [
            {"key": "scenario_comparison", "label": "Scenario Comparison"},
            {"key": "paint_tracking", "label": "Paint Tracking"},
            {"key": "map_export", "label": "Map Export"},
        ]

    @server.tool()  # type: ignore[misc]
    def generate_report(
        workspace_slug: str,
        scenario_slug: str | None = None,
        report_type: str = "scenario_comparison",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate a report."""
        workspace = _get_workspace(workspace_slug)
        if workspace is None:
            return {"error": "Invalid workspace slug"}

        options_dict = options or {}
        report = ScenarioReport.objects.create(
            workspace=workspace,
            name=options_dict.get("name", f"Report - {workspace.name}"),
            report_type=report_type,
            status=ScenarioReport.ReportStatus.PENDING,
            created_by=None,
        )

        task = generate_report_task.delay(
            report_pk=report.pk,
            options=options_dict,
        )
        return {
            "task_id": task.id,
            "report_id": report.pk,
            "status": "PENDING",
            "message": f"Report '{report.name}' generation launched",
        }

    @server.tool()  # type: ignore[misc]
    def get_report_download_url(workspace_slug: str, report_id: int) -> dict[str, Any]:
        """Get the download URL for a completed report."""
        workspace = _get_workspace(workspace_slug)
        if workspace is None:
            return {"error": "Invalid workspace slug"}
        try:
            report = ScenarioReport.objects.get(pk=report_id, workspace=workspace)
            if report.report_file:
                return {
                    "url": report.report_file.url,
                    "filename": report.report_file.name,
                    "status": report.status,
                }
            return {"status": report.status, "message": "Report not yet completed"}
        except ScenarioReport.DoesNotExist:
            return {"error": "Report not found"}

    @server.tool()  # type: ignore[misc]
    def list_reports(workspace_slug: str, limit: int = 10) -> list[dict[str, Any]]:
        """List recent reports for a workspace."""
        workspace = _get_workspace(workspace_slug)
        if workspace is None:
            return []
        reports = ScenarioReport.objects.filter(workspace=workspace).order_by(
            "-created_at"
        )[:limit]
        return [
            {
                "id": r.pk,
                "name": r.name,
                "report_type": r.report_type,
                "status": r.status,
                "created_at": str(r.created_at),
            }
            for r in reports
        ]

    @server.tool()  # type: ignore[misc]
    def import_gis_file(
        workspace_slug: str,
        file_data_base64: str,
        file_name: str,
        layer_name: str | None = None,
        srid: int | None = None,
    ) -> dict[str, Any]:
        """Import a GIS file (GeoJSON, Shapefile, GeoPackage, CSV) as a new layer."""
        workspace = _get_workspace(workspace_slug)
        if workspace is None:
            return {"error": "Invalid workspace slug"}

        from django.conf import settings

        from brewgis.workspace.models import Layer

        # Validate extension
        ext = Path(file_name).suffix.lower()
        allowed = settings.GIS_FILE_EXTENSIONS
        if ext not in allowed and ext not in [".zip", ".gpkg"]:
            return {"error": f"File extension '{ext}' not allowed. Allowed: {allowed}"}

        # Decode and write to temp file
        try:
            raw = base64.b64decode(file_data_base64)
        except Exception as e:
            return {"error": f"Invalid base64 data: {e}"}

        if len(raw) > settings.MAX_UPLOAD_SIZE:
            return {
                "error": f"File too large. Max size: {settings.MAX_UPLOAD_SIZE / 1024 / 1024:.0f}MB"
            }

        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name

        try:
            gdf = gpd.read_file(tmp_path)
            layer_key = (layer_name or Path(file_name).stem).lower().replace(" ", "_")
            schema = workspace.db_schema
            table_name = layer_key

            engine = _get_engine()
            gdf.to_postgis(
                name=table_name,
                schema=schema,
                con=engine,
                if_exists="replace",
                index=False,
            )
            engine.dispose()

            # Determine geometry type
            geom_types = gdf.geometry.type.unique()
            if "Polygon" in geom_types or "MultiPolygon" in geom_types:
                geo_type = "fill"
            elif "LineString" in geom_types or "MultiLineString" in geom_types:
                geo_type = "line"
            else:
                geo_type = "circle"

            layer = Layer.objects.create(
                workspace=workspace,
                key=layer_key,
                name=layer_name or Path(file_name).stem,
                layer_source=f"MCP import: {file_name}",
                db_table=table_name,
                geometry_type=geo_type,
            )

            try:
                auto_generate_symbology(layer)
            except Exception:
                pass

            return {
                "layer_key": layer.key,
                "layer_name": layer.name,
                "feature_count": len(gdf),
                "geometry_type": geo_type,
            }

        except Exception as e:
            return {"error": f"Import failed: {e}"}
        finally:
            Path(tmp_path).unlink(missing_ok=True)
