"""View for merging PaintedCanvas paint edits between scenarios.

POST /workspace/<pk>/scenario/<source_id>/merge/<target_id>/
    Copies approved PaintedCanvas rows from source scenario to target scenario.
    Skips rows that already exist in the target (duplicate key).
    Creates a MergeAudit record for the operation.
"""

from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.db import transaction
from django.http import HttpRequest
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from brewgis.workspace.models import MergeAudit
from brewgis.workspace.models import PaintedCanvas
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace

logger = logging.getLogger(__name__)


@require_POST
@login_required
def merge_paint_edits(
    request: HttpRequest,
    workspace_pk: int,
    source_pk: int,
    target_pk: int,
) -> JsonResponse:
    """Copy approved PaintedCanvas rows from source to target scenario.

    Args:
        request: The HTTP request.
        workspace_pk: Workspace primary key.
        source_pk: Source scenario primary key.
        target_pk: Target scenario primary key.

    Returns:
        JsonResponse with:
            - success: True/False
            - rows_copied: Number of rows successfully copied
            - rows_skipped: Number of rows skipped (duplicate key)
            - audit_id: Primary key of the created MergeAudit record
            - error: Error message on failure
    """
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    source_scenario = get_object_or_404(Scenario, pk=source_pk)
    target_scenario = get_object_or_404(Scenario, pk=target_pk)

    if source_scenario == target_scenario:
        return JsonResponse(
            {"success": False, "error": "Source and target scenarios must differ"},
            status=400,
        )

    # Query approved PaintedCanvas rows from source
    source_paints = PaintedCanvas.objects.filter(
        scenario=source_scenario,
        approval_status="approved",
    ).values(
        "scenario_id",
        "feature_id",
        "column_name",
        "painted_value",
        "painted_by_id",
    )

    if not source_paints.exists():
        return JsonResponse(
            {
                "success": True,
                "rows_copied": 0,
                "rows_skipped": 0,
                "audit_id": None,
                "message": "No approved paint edits found in source scenario",
            },
        )

    rows_copied = 0
    rows_skipped = 0

    with transaction.atomic():
        for paint in source_paints:
            try:
                with transaction.atomic():
                    PaintedCanvas.objects.create(
                        scenario=target_scenario,
                        feature_id=paint["feature_id"],
                        column_name=paint["column_name"],
                        painted_value=paint["painted_value"],
                        painted_by=request.user if request.user.is_authenticated else None,
                    )
                rows_copied += 1
            except IntegrityError:
                # Duplicate (scenario, feature_id, column_name) — skip
                rows_skipped += 1

        # Create audit record
        audit = MergeAudit.objects.create(
            workspace=workspace,
            source_scenario=source_scenario,
            target_scenario=target_scenario,
            rows_copied=rows_copied,
            rows_skipped=rows_skipped,
            performed_by=request.user if request.user.is_authenticated else None,
        )

    logger.info(
        "Merge %s→%s: %d copied, %d skipped (user=%s)",
        source_scenario.pk,
        target_scenario.pk,
        rows_copied,
        rows_skipped,
        request.user,
    )

    return JsonResponse(
        {
            "success": True,
            "rows_copied": rows_copied,
            "rows_skipped": rows_skipped,
            "audit_id": audit.pk,
        },
    )
