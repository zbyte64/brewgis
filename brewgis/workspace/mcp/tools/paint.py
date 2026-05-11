"""MCP tools for paint read/write operations."""

from __future__ import annotations

import json
import logging
from typing import Any

from django.shortcuts import get_object_or_404
from django.utils.timezone import now as tz_now

from brewgis.workspace.models import PaintedCanvas
from brewgis.workspace.models import PaintConstraint
from brewgis.workspace.models import PaintEvent
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.canvas_view_manager import PAINTABLE_COLUMNS
from brewgis.workspace.services.paint_constraints import check_paint_batch

logger = logging.getLogger(__name__)


def register_tools(server: object) -> None:
    """Register paint tools with the MCP server."""

    @server.tool()  # type: ignore[misc]
    def paint_features(
        workspace_slug: str,
        scenario_slug: str,
        feature_ids: list[str],
        column: str,
        value: float,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Paint a value onto features in a scenario."""
        try:
            ws_pk = int(workspace_slug)
            s_pk = int(scenario_slug)
        except ValueError:
            return {"error": "Invalid slug"}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        scenario = get_object_or_404(Scenario, pk=s_pk, workspace=workspace)

        if column not in PAINTABLE_COLUMNS:
            return {
                "error": f"Invalid column '{column}'. Valid: {sorted(PAINTABLE_COLUMNS)}",
                "painted": 0,
            }

        painted = 0
        errors = []
        for fid in feature_ids:
            try:
                obj, created = PaintedCanvas.objects.update_or_create(
                    scenario=scenario,
                    feature_id=fid,
                    defaults={column: value},
                )
                painted += 1
            except Exception as e:
                errors.append({"feature_id": fid, "error": str(e)})

        if note:
            PaintEvent.objects.create(
                scenario=scenario,
                action="paint",
                details=json.dumps(
                    {
                        "features": feature_ids,
                        "column": column,
                        "value": value,
                        "note": note,
                    }
                ),
            )

        return {"painted": painted, "errors": errors}

    @server.tool()  # type: ignore[misc]
    def clear_paint(
        workspace_slug: str,
        scenario_slug: str,
        feature_ids: list[str] | None = None,
        column: str | None = None,
    ) -> dict[str, Any]:
        """Clear painted values from features."""
        try:
            ws_pk = int(workspace_slug)
            s_pk = int(scenario_slug)
        except ValueError:
            return {"error": "Invalid slug", "cleared": 0}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        scenario = get_object_or_404(Scenario, pk=s_pk, workspace=workspace)

        qs = PaintedCanvas.objects.filter(scenario=scenario)
        if feature_ids:
            qs = qs.filter(feature_id__in=feature_ids)
        if column:
            qs = qs.filter(**{f"{column}__isnull": False})

        count, _ = qs.delete()
        return {"cleared": count}

    @server.tool()  # type: ignore[misc]
    def get_painted_values(
        workspace_slug: str,
        scenario_slug: str,
        feature_ids: list[str] | None = None,
        columns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get painted values for a scenario."""
        try:
            ws_pk = int(workspace_slug)
            s_pk = int(scenario_slug)
        except ValueError:
            return []
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        scenario = get_object_or_404(Scenario, pk=s_pk, workspace=workspace)

        qs = PaintedCanvas.objects.filter(scenario=scenario)
        if feature_ids:
            qs = qs.filter(feature_id__in=feature_ids)

        results = []
        for pc in qs:
            row = {"feature_id": pc.feature_id}
            if columns:
                for col in columns:
                    if hasattr(pc, col):
                        row[col] = getattr(pc, col)
            else:
                for col in PAINTABLE_COLUMNS:
                    if hasattr(pc, col):
                        row[col] = getattr(pc, col)
            results.append(row)
        return results

    @server.tool()  # type: ignore[misc]
    def undo_paint(
        workspace_slug: str,
        scenario_slug: str,
        count: int = 1,
    ) -> dict[str, Any]:
        """Undo the last N paint events."""
        try:
            ws_pk = int(workspace_slug)
            s_pk = int(scenario_slug)
        except ValueError:
            return {"error": "Invalid slug", "reverted": 0}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        scenario = get_object_or_404(Scenario, pk=s_pk, workspace=workspace)

        events = PaintEvent.objects.filter(scenario=scenario, action="paint").order_by(
            "-created_at"
        )[:count]

        reverted = 0
        for event in events:
            try:
                details = json.loads(event.details)
                feature_ids = details.get("features", [])
                column = details.get("column")
                if feature_ids and column:
                    PaintedCanvas.objects.filter(
                        scenario=scenario,
                        feature_id__in=feature_ids,
                    ).delete()
                    reverted += 1
            except Exception:
                pass
        return {"reverted": reverted}

    @server.tool()  # type: ignore[misc]
    def list_paint_constraints(workspace_slug: str) -> list[dict[str, Any]]:
        """List paint constraints for a workspace."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return []
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        constraints = PaintConstraint.objects.filter(workspace=workspace)
        return [
            {
                "id": c.pk,
                "column": c.column,
                "min_value": c.min_value,
                "max_value": c.max_value,
                "description": c.description,
            }
            for c in constraints
        ]

    @server.tool()  # type: ignore[misc]
    def validate_paint_batch(
        workspace_slug: str,
        scenario_slug: str,
        features: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Validate a batch of paint operations without applying them."""
        try:
            ws_pk = int(workspace_slug)
            s_pk = int(scenario_slug)
        except ValueError:
            return {"error": "Invalid slug"}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        scenario = get_object_or_404(Scenario, pk=s_pk, workspace=workspace)

        try:
            validation = check_paint_batch(scenario, features)
            return {
                "valid": validation.get("valid", True),
                "errors": validation.get("errors", []),
            }
        except Exception as e:
            return {"valid": False, "errors": [str(e)]}
