"""Pipeline callback API view — single Dagster-to-Django write path.

Dagster asset ops call this at completion via httpx.post() (loopback to
Django on the internal Docker network). This is the single Dagster-to-Django
write path. Testable, auditable, easy to replace if ORM writes move to SQL.
"""

from __future__ import annotations

import json
import logging

from django.http import HttpRequest
from django.http import HttpResponse
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import Layer

logger = logging.getLogger(__name__)


@require_POST
@csrf_exempt  # Dagster loopback on internal Docker network — not user-facing
def pipeline_callback(request: HttpRequest) -> HttpResponse:
    """Accept pipeline completion callbacks from Dagster.

    Expected JSON payload:
        run_id (int): AnalysisRun primary key
        status (str): "completed" | "failed"
        result (dict, optional): Additional result data
        layer_info (list[dict], optional): Layers to register
            Each dict: {"schema": str, "table": str, "name": str, "description": str}
        error (str, optional): Error message if failed
    """
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    run_id = payload.get("run_id")
    if not run_id:
        return JsonResponse({"error": "run_id is required"}, status=400)

    try:
        run = AnalysisRun.objects.get(pk=run_id)
    except AnalysisRun.DoesNotExist:
        return JsonResponse({"error": f"AnalysisRun {run_id} not found"}, status=404)

    status = payload.get("status", "failed")
    error = payload.get("error")

    # Update AnalysisRun status
    run.status = status
    if status == "completed":
        from django.utils import timezone

        run.completed_at = timezone.now()
    if error:
        run.error_log = error
    run.save(update_fields=["status", "completed_at", "error_log"])

    # Register result layers
    layer_info = payload.get("layer_info", [])
    for info in layer_info:
        schema = info.get("schema", "public")
        table = info.get("table", "")
        name = info.get("name", table)
        description = info.get("description", "")
        if not table:
            continue

        layer, created = Layer.objects.get_or_create(
            key=f"{schema}.{table}",
            workspace_id=run.workspace_id,
            defaults={
                "name": name,
                "db_table": table,
                "description": description,
            },
        )
        if not created:
            logger.info("Layer already exists: %s.%s", schema, table)

    logger.info(
        "Pipeline callback processed for AnalysisRun #%s: status=%s, layers=%d",
        run_id,
        status,
        len(layer_info),
    )

    return JsonResponse({"success": True, "run_id": run_id, "status": status})
