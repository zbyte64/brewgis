"""Paint views — direct column painting, built form painting, paint history, and undo/redo."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING
from typing import Any

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.timezone import now as tz_now
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from brewgis.workspace.built_forms.allocation import AllocationEngine
from brewgis.workspace.built_forms.allocation import AllocationResult
from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.built_forms.models import PlaceType
from brewgis.workspace.models import PaintedCanvas
from brewgis.workspace.models import PaintEvent
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.canvas_view_manager import PAINTABLE_COLUMNS
from brewgis.workspace.services.canvas_view_manager import refresh_canvas_view
from brewgis.workspace.services.paint_constraints import ConstraintResult
from brewgis.workspace.services.paint_constraints import check_paint_batch

if TYPE_CHECKING:
    from django.http import HttpRequest


# ─── Paint Operations ────────────────────────────────────────────


@require_POST
@login_required
def paint_features(
    request: HttpRequest, workspace_pk: int, scenario_pk: int
) -> JsonResponse:
    """Paint a single column's value on the selected features.

    Accepts JSON body::
        {"features": ["1", "2"], "column": "du", "value": 100.0}

    Validates column name against PAINTABLE_COLUMNS, bulk-upserts
    PaintedCanvas rows, logs PaintEvents, then refreshes the canvas view.
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
    now_user = request.user

    # ── Constraint checking ──────────────────────────────
    paint_map: dict[str, dict[str, float | None]] = {
        fid: {column: painted_value} for fid in features
    }
    block_response = _enforce_paint_constraints(workspace, paint_map)
    if block_response is not None:
        return block_response
    # ─────────────────────────────────────────────────────

    with transaction.atomic():
        # Capture old values before upsert
        old_values = _fetch_painted_old_values(scenario, features, column)

        pc_rows = [
            PaintedCanvas(
                scenario=scenario,
                feature_id=fid,
                column_name=column,
                painted_value=painted_value,
                painted_by=now_user,
            )
            for fid in features
        ]

        PaintedCanvas.objects.bulk_create(
            pc_rows,
            update_conflicts=True,
            update_fields=["painted_value", "painted_by", "painted_at"],
            unique_fields=["scenario", "feature_id", "column_name"],
        )

        # Log paint events
        batch_id = uuid.uuid4().hex
        PaintEvent.objects.bulk_create([
            PaintEvent(
                scenario=scenario,
                feature_id=fid,
                column_name=column,
                old_value=old_values.get(fid),
                new_value=painted_value,
                painted_by=now_user,
                operation_type="paint",
                batch_id=batch_id,
            )
            for fid in features
        ])

        # Refresh the canvas view
        base_table = _resolve_base_table(scenario)
        refresh_canvas_view(scenario, base_table)

    warnings = _collect_warnings()
    return JsonResponse(
        {
            "status": "ok",
            "painted_count": len(features),
            "painted_features": features,
            "batch_id": batch_id,
            "warnings": warnings,
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
    logs PaintEvents for undo support, then refreshes the canvas view.
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
        # Capture old values before deleting
        old_paints = list(
            PaintedCanvas.objects.filter(
                scenario=scenario,
                feature_id__in=features,
            ).values("feature_id", "column_name", "painted_value")
        )

        deleted_count, _ = PaintedCanvas.objects.filter(
            scenario=scenario,
            feature_id__in=features,
        ).delete()

        # Log clear events
        if old_paints:
            batch_id = uuid.uuid4().hex
            PaintEvent.objects.bulk_create([
                PaintEvent(
                    scenario=scenario,
                    feature_id=p["feature_id"],
                    column_name=p["column_name"],
                    old_value=p["painted_value"],
                    new_value=None,
                    painted_by=request.user,
                    operation_type="clear",
                    batch_id=batch_id,
                )
                for p in old_paints
            ])

        # Refresh the canvas view
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
    writes computed fields as PaintedCanvas rows, logs PaintEvents,
    refreshes canvas view.
    """
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    scenario = get_object_or_404(Scenario, pk=scenario_pk, workspace=workspace)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON body."}, status=400
        )

    return _execute_built_form_paint(
        workspace, scenario, body, request.user,
    )


# ─── Undo / Redo ─────────────────────────────────────────────────


@require_POST
@login_required
def undo_paint(
    request: HttpRequest, workspace_pk: int, scenario_pk: int
) -> JsonResponse:
    """Undo a specific paint event by restoring its old value.

    Accepts JSON body::
        {"event_id": 42}
    or::
        {"batch_id": "abc123"}

    If ``event_id`` is given, undoes that single event.
    If ``batch_id`` is given, undoes all non-undone events in that batch.
    Sets ``undone_at`` on reverted events and creates a new PaintEvent
    recording the undo.
    """
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    scenario = get_object_or_404(Scenario, pk=scenario_pk, workspace=workspace)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON body."}, status=400
        )

    event_id: int | None = body.get("event_id")
    batch_id: str | None = body.get("batch_id")

    if not event_id and not batch_id:
        return JsonResponse(
            {
                "status": "error",
                "message": "Provide either 'event_id' or 'batch_id'.",
            },
            status=400,
        )

    with transaction.atomic():
        # Resolve events to undo
        if event_id:
            events = list(
                PaintEvent.objects.filter(
                    id=event_id,
                    scenario=scenario,
                    undone_at__isnull=True,
                ).select_related("scenario")
            )
            if not events:
                return JsonResponse(
                    {
                        "status": "error",
                        "message": "Event not found or already undone.",
                    },
                    status=404,
                )
        else:
            events = list(
                PaintEvent.objects.filter(
                    batch_id=batch_id,
                    scenario=scenario,
                    undone_at__isnull=True,
                ).select_related("scenario")
            )
            if not events:
                return JsonResponse(
                    {
                        "status": "error",
                        "message": "No non-undone events found for this batch.",
                    },
                    status=404,
                )

        now_user = request.user
        undo_now = tz_now()
        undo_batch_id = uuid.uuid4().hex

        # Process each event: restore old_value
        for evt in events:
            if evt.operation_type == "clear":
                # Recreate the PaintedCanvas row that was deleted
                PaintedCanvas.objects.update_or_create(
                    scenario=scenario,
                    feature_id=evt.feature_id,
                    column_name=evt.column_name,
                    defaults={
                        "painted_value": evt.old_value,
                        "painted_by": now_user,
                    },
                )
            elif evt.operation_type == "paint":
                if evt.old_value is None:
                    # Old value was base canvas — delete our override
                    PaintedCanvas.objects.filter(
                        scenario=scenario,
                        feature_id=evt.feature_id,
                        column_name=evt.column_name,
                    ).delete()
                else:
                    # Restore the old painted value
                    PaintedCanvas.objects.update_or_create(
                        scenario=scenario,
                        feature_id=evt.feature_id,
                        column_name=evt.column_name,
                        defaults={
                            "painted_value": evt.old_value,
                            "painted_by": now_user,
                        },
                    )
            elif evt.operation_type == "built_form":
                if evt.old_value is None:
                    PaintedCanvas.objects.filter(
                        scenario=scenario,
                        feature_id=evt.feature_id,
                        column_name=evt.column_name,
                    ).delete()
                else:
                    PaintedCanvas.objects.update_or_create(
                        scenario=scenario,
                        feature_id=evt.feature_id,
                        column_name=evt.column_name,
                        defaults={
                            "painted_value": evt.old_value,
                            "painted_by": now_user,
                        },
                    )

            # Mark as undone
            PaintEvent.objects.filter(id=evt.id).update(undone_at=undo_now)

        # Log the undo event(s)
        undo_events = [
            PaintEvent(
                scenario=scenario,
                feature_id=evt.feature_id,
                column_name=evt.column_name,
                old_value=evt.new_value,
                new_value=evt.old_value,
                painted_by=now_user,
                operation_type="undo",
                batch_id=undo_batch_id,
            )
            for evt in events
        ]
        PaintEvent.objects.bulk_create(undo_events)

        # Refresh canvas view
        base_table = _resolve_base_table(scenario)
        refresh_canvas_view(scenario, base_table)

    return JsonResponse(
        {
            "status": "ok",
            "undone_count": len(events),
            "undo_batch_id": undo_batch_id,
        }
    )


# ─── Paint History ───────────────────────────────────────────────


@require_GET
@login_required
def paint_history(
    request: HttpRequest, workspace_pk: int, scenario_pk: int
) -> JsonResponse:
    """Return paint event history for a scenario.

    Query params::

        ?limit=50&offset=0&feature_id=parcel-001

    Returns JSON with event list and total count.
    """
    scenario = get_object_or_404(Scenario, pk=scenario_pk, workspace__pk=workspace_pk)

    try:
        limit = int(request.GET.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = int(request.GET.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0

    feature_id = request.GET.get("feature_id")

    qs = PaintEvent.objects.filter(scenario=scenario)
    if feature_id:
        qs = qs.filter(feature_id=feature_id)

    total = qs.count()
    events_qs = qs.select_related("painted_by").order_by("-painted_at")[
        offset : offset + limit
    ]

    return JsonResponse(
        {
            "status": "ok",
            "total": total,
            "offset": offset,
            "limit": limit,
            "events": [
                {
                    "id": e.id,
                    "feature_id": e.feature_id,
                    "column_name": e.column_name,
                    "old_value": e.old_value,
                    "new_value": e.new_value,
                    "painted_by": e.painted_by_id,
                    "painted_by_name": e.painted_by.get_full_name()
                    or e.painted_by.username
                    if e.painted_by
                    else None,
                    "painted_at": e.painted_at.isoformat(),
                    "operation_type": e.operation_type,
                    "batch_id": e.batch_id,
                    "undone_at": e.undone_at.isoformat() if e.undone_at else None,
                }
                for e in events_qs
            ],
        }
    )


# ─── Helpers ─────────────────────────────────────────────────────


_PAINT_CONSTRAINT_RESULT: list[ConstraintResult | None] = [None]
"""Last constraint result, cached for warning collection (mutable container for in-module mutation)."""


def _resolve_base_table(scenario: Scenario) -> str:  # noqa: ARG001
    """Resolve the base canvas table name for a scenario."""
    return "public.base_canvas"


def _fetch_painted_old_values(
    scenario: Scenario,
    feature_ids: list[str],
    column_name: str,
) -> dict[str, float | None]:
    """Fetch current PaintedCanvas values for (scenario, features, column).

    Returns a dict mapping feature_id -> painted_value (or None if no paint exists).
    """
    qs = PaintedCanvas.objects.filter(
        scenario=scenario,
        feature_id__in=feature_ids,
        column_name=column_name,
    ).values("feature_id", "painted_value")
    result: dict[str, float | None] = {}
    for row in qs:
        result[row["feature_id"]] = row["painted_value"]
    # Features without paint get None (they fall through to base canvas)
    for fid in feature_ids:
        result.setdefault(fid, None)
    return result


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
    painted_by: Any,
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


def _enforce_paint_constraints(
    workspace: Workspace,
    paint_map: dict[str, dict[str, float | None]],
) -> JsonResponse | None:
    """Check paint constraints; return a blocking JsonResponse or None.

    Violations are cached on the function for later retrieval via
    :func:`_collect_warnings`.
    """
    constraint_result = check_paint_batch(workspace, paint_map)
    _PAINT_CONSTRAINT_RESULT[0] = constraint_result
    if constraint_result.blocked:
        return JsonResponse(
            {
                "status": "error",
                "message": "Paint operation blocked by workspace constraints.",
                "violations": [v.to_dict() for v in constraint_result.violations],
            },
            status=409,
        )
    return None


def _collect_warnings() -> list[dict]:
    """Collect warning violations from the last constraint check."""
    last_result = _PAINT_CONSTRAINT_RESULT[0]
    if last_result is None:
        return []
    return [
        v.to_dict()
        for v in last_result.violations
        if v.severity == "warn"
    ]


def _execute_built_form_paint(
    workspace: Workspace,
    scenario: Scenario,
    body: dict,
    user: Any,
) -> JsonResponse:
    """Execute built form painting after request validation."""
    features: list[str] = body.get("features", [])
    bf_type: str = body.get("bf_type", "")
    bf_id: int | None = body.get("bf_id")

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
    built_form: BuildingType | PlaceType
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
        # Track which feature+column combos are being painted for old-value lookup
        feature_columns: set[tuple[str, str]] = set()

        for fid, row in feature_data.items():
            parcel_acres = float(row.get("area_gross", row.get("area_parcel", 1.0)))

            if bf_type == "building":
                assert isinstance(built_form, BuildingType)
                result = AllocationEngine.allocation_building_type(
                    parcel_acres=parcel_acres,
                    building_type=built_form,
                    row_allocation_pct=0.0,  # ROW already reflected in base data
                )
            else:
                assert isinstance(built_form, PlaceType)
                result = AllocationEngine.allocation_place_type(
                    parcel_acres=parcel_acres,
                    place_type=built_form,
                )

            # Map allocation result → canvas columns
            pc_rows = _allocation_to_painted_rows(
                scenario=scenario,
                feature_id=fid,
                result=result,
                painted_by=user,
            )

            # Track which columns we're painting for old-value lookup
            for pc_row in pc_rows:
                feature_columns.add((fid, pc_row.column_name))

            all_pc_rows.extend(pc_rows)

        # ── Constraint checking ──────────────────────────
        paint_map: dict[str, dict[str, float | None]] = {}
        for pc_row in all_pc_rows:
            paint_map.setdefault(pc_row.feature_id, {})[
                pc_row.column_name
            ] = pc_row.painted_value
        block_response = _enforce_paint_constraints(workspace, paint_map)
        if block_response is not None:
            return block_response
        bf_warnings = _collect_warnings()
        # ─────────────────────────────────────────────────

        # Fetch old values before upsert
        old_values_map: dict[tuple[str, str], float | None] = {}
        for fid, col in feature_columns:
            old = _fetch_painted_old_values(scenario, [fid], col)
            old_values_map[(fid, col)] = old.get(fid)

        # Bulk upsert all painted rows
        PaintedCanvas.objects.bulk_create(
            all_pc_rows,
            update_conflicts=True,
            update_fields=["painted_value", "painted_by", "painted_at"],
            unique_fields=["scenario", "feature_id", "column_name"],
        )

        # Log built_form paint events
        batch_id = uuid.uuid4().hex
        PaintEvent.objects.bulk_create([
            PaintEvent(
                scenario=scenario,
                feature_id=pc.feature_id,
                column_name=pc.column_name,
                old_value=old_values_map.get((pc.feature_id, pc.column_name)),
                new_value=pc.painted_value,
                painted_by=user,
                operation_type="built_form",
                batch_id=batch_id,
            )
            for pc in all_pc_rows
        ])

        refresh_canvas_view(scenario, base_table)

    return JsonResponse(
        {
            "status": "ok",
            "painted_count": len(all_pc_rows),
            "painted_features": features,
            "batch_id": batch_id,
            "warnings": bf_warnings,
        }
    )
