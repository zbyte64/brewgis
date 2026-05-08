"""Paint views — direct column painting and built form painting for scenarios."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from brewgis.workspace.built_forms.allocation import AllocationEngine
from brewgis.workspace.built_forms.allocation import AllocationResult
from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.built_forms.models import PlaceType
from brewgis.workspace.models import PaintedCanvas
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.canvas_view_manager import PAINTABLE_COLUMNS
from brewgis.workspace.services.canvas_view_manager import refresh_canvas_view

if TYPE_CHECKING:
    from django.http import HttpRequest


@require_POST
@login_required
def paint_features(
    request: HttpRequest, workspace_pk: int, scenario_pk: int
) -> JsonResponse:
    """Paint a single column's value on the selected features.

    Accepts JSON body::
        {"features": ["1", "2"], "column": "du", "value": 100.0}

    Validates column name against PAINTABLE_COLUMNS, bulk-upserts
    PaintedCanvas rows, then refreshes the canvas view.
    """
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    scenario = get_object_or_404(Scenario, pk=scenario_pk, workspace=workspace)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON body."}, status=400
        )

    features: list[str] = body.get("features", [])
    column: str = body.get("column", "")
    value: float | None = body.get("value", None)

    if not features:
        return JsonResponse(
            {"status": "error", "message": "No features selected."}, status=400
        )

    if column not in PAINTABLE_COLUMNS:
        return JsonResponse(
            {
                "status": "error",
                "message": f"Invalid column '{column}'. Valid columns: {sorted(PAINTABLE_COLUMNS)}",
            },
            status=400,
        )

    # Coerce value to float or None
    painted_value: float | None
    if value is None:
        painted_value = None
    else:
        try:
            painted_value = float(value)
        except (TypeError, ValueError):
            return JsonResponse(
                {
                    "status": "error",
                    "message": f"Invalid value '{value}'. Must be a number or null.",
                },
                status=400,
            )

    now = request.user

    with transaction.atomic():
        pc_rows = [
            PaintedCanvas(
                scenario=scenario,
                feature_id=fid,
                column_name=column,
                painted_value=painted_value,
                painted_by=now,
            )
            for fid in features
        ]

        PaintedCanvas.objects.bulk_create(
            pc_rows,
            update_conflicts=True,
            update_fields=["painted_value", "painted_by", "painted_at"],
            unique_fields=["scenario", "feature_id", "column_name"],
        )

        # Find base canvas table from scenario
        base_table = _resolve_base_table(scenario)
        refresh_canvas_view(scenario, base_table)

    return JsonResponse(
        {
            "status": "ok",
            "painted_count": len(features),
            "painted_features": features,
        }
    )


@require_POST
@login_required
def clear_paint(
    request: HttpRequest, workspace_pk: int, scenario_pk: int
) -> JsonResponse:
    """Clear painted values for the selected features.

    Accepts JSON body::
        {"features": ["1", "2"]}

    Deletes all PaintedCanvas rows for those features within the scenario,
    then refreshes the canvas view.
    """
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    scenario = get_object_or_404(Scenario, pk=scenario_pk, workspace=workspace)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON body."}, status=400
        )

    features: list[str] = body.get("features", [])

    if not features:
        return JsonResponse(
            {"status": "error", "message": "No features selected."}, status=400
        )

    with transaction.atomic():
        deleted_count, _ = PaintedCanvas.objects.filter(
            scenario=scenario,
            feature_id__in=features,
        ).delete()

        # Find base canvas table from scenario
        base_table = _resolve_base_table(scenario)
        refresh_canvas_view(scenario, base_table)

    return JsonResponse(
        {
            "status": "ok",
            "cleared_count": deleted_count,
        }
    )


@require_POST
@login_required
def paint_built_form(
    request: HttpRequest, workspace_pk: int, scenario_pk: int
) -> JsonResponse:
    """Paint built form attributes on the selected features.

    Accepts JSON body::
        {"features": ["1", "2"], "bf_type": "building", "bf_id": 1}
    or::
        {"features": ["1", "2"], "bf_type": "place", "bf_id": 1}

    Loads base canvas data for selected features, runs AllocationEngine,
    writes computed fields as PaintedCanvas rows, refreshes canvas view.
    """
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    scenario = get_object_or_404(Scenario, pk=scenario_pk, workspace=workspace)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON body."}, status=400
        )

    features: list[str] = body.get("features", [])
    bf_type: str = body.get("bf_type", "")
    bf_id: int | None = body.get("bf_id", None)

    if not features:
        return JsonResponse(
            {"status": "error", "message": "No features selected."}, status=400
        )

    if bf_type not in ("building", "place"):
        return JsonResponse(
            {"status": "error", "message": "bf_type must be 'building' or 'place'."},
            status=400,
        )

    if bf_id is None:
        return JsonResponse(
            {"status": "error", "message": "bf_id is required."}, status=400
        )

    # Resolve built form instance
    if bf_type == "building":
        built_form = get_object_or_404(BuildingType, pk=bf_id)
    else:
        built_form = get_object_or_404(PlaceType, pk=bf_id)

    # Load base canvas data for selected features
    base_table = _resolve_base_table(scenario)
    feature_data = _fetch_feature_data(base_table, features)
    if not feature_data:
        return JsonResponse(
            {
                "status": "error",
                "message": "No base canvas data found for selected features.",
            },
            status=400,
        )

    with transaction.atomic():
        all_pc_rows: list[PaintedCanvas] = []

        for fid, row in feature_data.items():
            parcel_acres = float(row.get("area_gross", row.get("area_parcel", 1.0)))

            if bf_type == "building":
                result = AllocationEngine.allocation_building_type(
                    parcel_acres=parcel_acres,
                    building_type=built_form,
                    row_allocation_pct=0.0,  # ROW already reflected in base data
                )
            else:
                result = AllocationEngine.allocation_place_type(
                    parcel_acres=parcel_acres,
                    place_type=built_form,
                )

            # Map allocation result → canvas columns
            pc_rows = _allocation_to_painted_rows(
                scenario=scenario,
                feature_id=fid,
                result=result,
                painted_by=request.user,
            )
            all_pc_rows.extend(pc_rows)

        # Bulk upsert all painted rows
        PaintedCanvas.objects.bulk_create(
            all_pc_rows,
            update_conflicts=True,
            update_fields=["painted_value", "painted_by", "painted_at"],
            unique_fields=["scenario", "feature_id", "column_name"],
        )

        refresh_canvas_view(scenario, base_table)

    return JsonResponse(
        {
            "status": "ok",
            "painted_count": len(all_pc_rows),
            "painted_features": features,
        }
    )


# ─── Helpers ────────────────────────────────────────────────


def _resolve_base_table(scenario: Scenario) -> str:  # noqa: ARG001
    """Resolve the base canvas table name for a scenario."""
    return "public.base_canvas"


def _fetch_feature_data(base_table: str, feature_ids: list[str]) -> dict[str, dict]:
    """Fetch base canvas data for given feature IDs.

    Returns a dict mapping feature_id → row dict (with string keys).
    Uses parameterized query to avoid SQL injection.
    """
    if not feature_ids:
        return {}

    placeholders = ", ".join("%s" for _ in feature_ids)
    query = f"SELECT id, area_gross, area_parcel FROM {base_table} WHERE CAST(id AS text) IN ({placeholders})"  # noqa: S608

    with connection.cursor() as cursor:
        cursor.execute(query, feature_ids)
        rows = cursor.fetchall()

    # Get column names
    col_names = [desc[0] for desc in cursor.description]

    return {str(row[0]): dict(zip(col_names, row, strict=True)) for row in rows}


def _allocation_to_painted_rows(
    *,
    scenario: Scenario,
    feature_id: str,
    result: AllocationResult,
    painted_by: object,
) -> list[PaintedCanvas]:
    """Convert an AllocationResult to a list of PaintedCanvas rows.

    Maps allocation output fields to canvas column names.
    """
    rows: list[PaintedCanvas] = []

    # Map of allocation result fields → canvas column names
    field_map: dict[str, float] = {
        "du": result.total_dwelling_units,
        "pop": result.total_population,
        "hh": result.total_households,
        "emp": result.total_employment,
    }

    # Distribute dwelling units by building type categories
    if result.per_building_type_breakdown:
        for breakdown in result.per_building_type_breakdown:
            bt_name = breakdown.get("building_type_name", "")
            bt_du = breakdown.get("dwelling_units", 0.0)

            if "detached" in bt_name.lower() or "sf" in bt_name.lower():
                field_map["du_detsf"] = field_map.get("du_detsf", 0.0) + bt_du
            elif "attsf" in bt_name.lower() or "townhouse" in bt_name.lower():
                field_map["du_attsf"] = field_map.get("du_attsf", 0.0) + bt_du
            elif (
                "mf" in bt_name.lower()
                or "multi" in bt_name.lower()
                or "apartment" in bt_name.lower()
            ):
                field_map["du_mf"] = field_map.get("du_mf", 0.0) + bt_du

    for column_name in sorted(PAINTABLE_COLUMNS):
        if column_name in field_map:
            value = field_map[column_name]
            rows.append(
                PaintedCanvas(
                    scenario=scenario,
                    feature_id=feature_id,
                    column_name=column_name,
                    painted_value=value,
                    painted_by=painted_by,
                )
            )

    return rows
