"""Paint views — direct column painting, built form painting, paint history, and undo/redo.

Painting can touch a large number of parcels at once (a big box/polygon
selection), and each of the four "apply" operations below does real work per
feature (constraint checks, ``AllocationEngine`` calls, canvas-view
refreshes) that scales with selection size. To keep the request from
blocking on that, ``paint_features``/``paint_built_form``/``match_built_form``/
``fill_built_form`` only validate the request synchronously; the actual work
runs in ``run_paint_operation`` (a Celery task, see ``brewgis.workspace.tasks``)
tracked by a ``PaintRun`` row. The view responds immediately with either the
finished result (if the task already completed — always true in eager-mode
tests/dev, per ``CELERY_TASK_ALWAYS_EAGER``) or a 202 + poll URL for the
frontend to watch via ``paint_status``.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING
from typing import Any

from celery import current_app
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.timezone import now as tz_now
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from brewgis.workspace.built_forms.allocation import AllocationEngine
from brewgis.workspace.built_forms.allocation import AllocationResult
from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.built_forms.models import PlaceType
from brewgis.workspace.models import PaintedCanvas
from brewgis.workspace.models import PaintEvent
from brewgis.workspace.models import PaintRun
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.canvas_view_manager import PAINTABLE_COLUMNS
from brewgis.workspace.services.canvas_view_manager import TEXT_COLUMNS
from brewgis.workspace.services.canvas_view_manager import refresh_canvas_view
from brewgis.workspace.services.paint_constraints import ConstraintResult
from brewgis.workspace.services.paint_constraints import check_paint_batch

if TYPE_CHECKING:
    from django.http import HttpRequest


# ─── Paint Operations ────────────────────────────────────────────
#
# Each of these views does cheap, request-shape validation (JSON parsing,
# required fields, enum checks) synchronously, then hands off to a
# background PaintRun — see ``_enqueue`` below.


@require_POST
@login_required
def paint_features(
    request: HttpRequest, workspace_pk: int, scenario_pk: int
) -> JsonResponse:
    """Paint a single column's value on the selected features.

    Accepts JSON body::
        {"features": ["1", "2"], "column": "du", "value": 100.0}

    Runs as a background ``PaintRun`` (see module docstring) — validates the
    request shape here, then hands off to :func:`run_direct_paint`.
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
    value = body.get("value", None)

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

    if column in TEXT_COLUMNS:
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    f"Column '{column}' is text-valued and can't be painted a "
                    "number — use the Built Form paint actions instead."
                ),
            },
            status=400,
        )

    if value is not None:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return JsonResponse(
                {
                    "status": "error",
                    "message": f"Invalid value '{value}'. Must be a number or null.",
                },
                status=400,
            )

    return _enqueue(
        workspace,
        scenario,
        request.user,
        "direct",
        {"features": features, "column": column, "value": value},
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
            ).values("feature_id", "column_name", "painted_value", "painted_text_value")
        )

        deleted_count, _ = PaintedCanvas.objects.filter(
            scenario=scenario,
            feature_id__in=features,
        ).delete()

        # Log clear events
        if old_paints:
            batch_id = uuid.uuid4().hex
            PaintEvent.objects.bulk_create(
                [
                    PaintEvent(
                        scenario=scenario,
                        feature_id=p["feature_id"],
                        column_name=p["column_name"],
                        old_value=p["painted_value"],
                        new_value=None,
                        old_text_value=p["painted_text_value"],
                        new_text_value=None,
                        operation_type="clear",
                        batch_id=batch_id,
                    )
                    for p in old_paints
                ]
            )

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

    Runs as a background ``PaintRun`` (see module docstring) — validates the
    request shape (including resolving ``bf_id`` to a real Building/Place
    Type, so an unknown id still 404s immediately) here, then hands off to
    :func:`run_built_form_paint`.
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

    # Resolve now (scoped to this workspace's own library) so an unknown id
    # 404s immediately instead of surfacing as a failed background run.
    if bf_type == "building":
        get_object_or_404(BuildingType, pk=bf_id, workspace=workspace)
    else:
        get_object_or_404(PlaceType, pk=bf_id, workspace=workspace)

    return _enqueue(
        workspace,
        scenario,
        request.user,
        "built_form",
        {"features": features, "bf_type": bf_type, "bf_id": bf_id},
    )


@require_POST
@login_required
def match_built_form(
    request: HttpRequest, workspace_pk: int, scenario_pk: int
) -> JsonResponse:
    """Auto-assign each selected feature the closest-matching Building Type.

    Accepts JSON body::
        {"features": ["1", "2"]}

    Runs as a background ``PaintRun`` (see module docstring) — for each
    feature, :func:`run_match_built_form` reads its current ``du``/``emp``
    value (from the scenario's canvas view, i.e. base canvas + any existing
    paint overlay), computes the implied per-acre density, and picks
    whichever workspace ``BuildingType`` has the numerically closest
    ``du_per_acre``/``emp_per_acre``, then runs the same allocation pipeline
    as :func:`paint_built_form` using the matched Building Type, per feature.
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

    return _enqueue(workspace, scenario, request.user, "match", {"features": features})


@require_POST
@login_required
def fill_built_form(
    request: HttpRequest, workspace_pk: int, scenario_pk: int
) -> JsonResponse:
    """Fill in du/emp stats for selected features from their current built form.

    Accepts JSON body::
        {"features": ["1", "2"]}

    Runs as a background ``PaintRun`` (see module docstring). For each
    feature, :func:`run_fill_built_form` reads its ``built_form_key`` as
    currently in effect for this scenario (base layer, COALESCEd with any
    existing PaintedCanvas override — e.g. one just set by Match Closest or
    a manual Built Form paint), resolves it to a workspace ``BuildingType``
    by (loosely normalized) name match, and runs the allocation pipeline to
    derive du/emp/pop/hh — without requiring the user to re-pick a Building
    Type. Features with no ``built_form_key`` or no matching Building Type
    are skipped and reported back as ``unmatched``.
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

    return _enqueue(workspace, scenario, request.user, "fill", {"features": features})


@require_GET
@login_required
def paint_status(
    request: HttpRequest,  # noqa: ARG001
    workspace_pk: int,
    scenario_pk: int,
    run_pk: int,
) -> JsonResponse:
    """Poll a background paint run's status.

    Returns the same JSON body the "apply" endpoints return once a run
    finishes (``{"status": "ok"/"error", "painted_count": ..., ...}``), or
    ``{"status": "pending"/"running"}`` while it's still in progress.
    """
    run = get_object_or_404(
        PaintRun, pk=run_pk, workspace_id=workspace_pk, scenario_id=scenario_pk
    )
    return _respond_for_run(run)


# ─── Undo / Redo ─────────────────────────────────────────────────


@require_POST
@login_required
def undo_paint(  # noqa: C901, PLR0912
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

        # Process each event: restore old_value (or old_text_value, for
        # text-valued columns like built_form_key)
        for evt in events:
            is_text = evt.column_name in TEXT_COLUMNS
            old_val = evt.old_text_value if is_text else evt.old_value

            if evt.operation_type == "clear":
                # Recreate the PaintedCanvas row that was deleted
                defaults: dict[str, Any] = {"painted_by": now_user}
                if is_text:
                    defaults["painted_text_value"] = old_val
                else:
                    defaults["painted_value"] = old_val
                PaintedCanvas.objects.update_or_create(
                    scenario=scenario,
                    feature_id=evt.feature_id,
                    column_name=evt.column_name,
                    defaults=defaults,
                )
            elif evt.operation_type in (
                "paint",
                "built_form",
                "built_form_match",
                "built_form_fill",
            ):
                if old_val is None:
                    PaintedCanvas.objects.filter(
                        scenario=scenario,
                        feature_id=evt.feature_id,
                        column_name=evt.column_name,
                    ).delete()
                else:
                    defaults = {"painted_by": now_user}
                    if is_text:
                        defaults["painted_text_value"] = old_val
                    else:
                        defaults["painted_value"] = old_val
                    PaintedCanvas.objects.update_or_create(
                        scenario=scenario,
                        feature_id=evt.feature_id,
                        column_name=evt.column_name,
                        defaults=defaults,
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
                old_text_value=evt.new_text_value,
                new_text_value=evt.old_text_value,
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


# ─── Background run dispatch ──────────────────────────────────────


_MAX_RESPONSE_ITEMS = 200
"""Cap on per-feature list fields (painted_features/matches/unmatched/
matched/violations/warnings) in a paint run's result.

A full-canvas selection is tens of thousands of features — nothing in this
app (or its tests) reads these lists back for anything other than a first
element/sample, but returning one full-detail dict per feature turned a
whole-scenario Match Closest into a multi-megabyte JSON response, which is
slow to serialize, slow to transfer, and slow for the browser to parse for
no benefit. ``painted_count``/``<field>_total`` carry the real numbers.
"""


def _cap_list(items: list[Any], limit: int = _MAX_RESPONSE_ITEMS) -> list[Any]:
    """Truncate a per-feature list field for the response, if it's large."""
    return items[:limit] if len(items) > limit else items


def _enqueue(
    workspace: Workspace,
    scenario: Scenario,
    user: Any,
    operation: str,
    params: dict[str, Any],
) -> JsonResponse:
    """Create a PaintRun, kick off its Celery task, and respond.

    In eager mode (``CELERY_TASK_ALWAYS_EAGER`` — the default in dev/tests)
    ``.delay()`` runs the task inline before returning, so the run is
    already ``completed``/``failed`` by the time we respond — the caller
    gets the same immediate result it always did. In production, the task
    runs on a worker and the caller gets a 202 + poll URL instead.

    Every view runs inside one transaction (``ATOMIC_REQUESTS``): the
    ``PaintRun`` row created just above isn't actually committed until this
    view returns. A real (non-eager) worker is a separate connection, so
    dispatching ``.delay()`` right here can — and in practice did — race
    the commit and fail with ``PaintRun.DoesNotExist`` the moment the worker
    picks the message up before this transaction lands. Deferring with
    ``transaction.on_commit`` closes that race.

    Eager mode (dev/tests, per ``CELERY_TASK_ALWAYS_EAGER``) is exempted:
    ``on_commit`` there would defer the (synchronous, same-process) task
    until *after* this function has already built and returned its response,
    so ``_respond_for_run`` would always observe the run as still pending
    instead of the finished result callers (and every existing test) expect.
    Since an eager task can't race a commit — it runs inline, on this same
    connection, before ``.delay()`` even returns — calling it immediately is
    both safe and necessary there.
    """
    from brewgis.workspace.tasks import run_paint_operation

    run = PaintRun.objects.create(
        workspace=workspace,
        scenario=scenario,
        operation=operation,
        params=params,
        created_by=user if user.is_authenticated else None,
    )
    if current_app.conf.task_always_eager:
        run_paint_operation.delay(run.pk)
    else:
        transaction.on_commit(lambda: run_paint_operation.delay(run.pk))
    return _respond_for_run(run)


def _respond_for_run(run: PaintRun) -> JsonResponse:
    """Build the JSON response for a PaintRun's current state."""
    run.refresh_from_db()

    if run.status == "completed":
        body = dict(run.result)
        status_code = body.pop("http_status", 200)
        return JsonResponse(body, status=status_code)

    if run.status == "failed":
        body = dict(run.result) if run.result else {}
        body.setdefault("status", "error")
        body.setdefault("message", run.error_log or "Paint operation failed.")
        status_code = body.pop("http_status", 400)
        return JsonResponse(body, status=status_code)

    return JsonResponse(
        {
            "status": "accepted",
            "run_id": run.pk,
            "run_status": run.status,
            "poll_url": reverse(
                "workspace:paint_status",
                kwargs={
                    "workspace_pk": run.workspace_id,
                    "scenario_pk": run.scenario_id,
                    "run_pk": run.pk,
                },
            ),
        },
        status=202,
    )


# ─── Run implementations (executed by the Celery task) ────────────
#
# These do the actual DB/allocation work for each operation. Called from
# ``run_paint_operation`` in ``brewgis.workspace.tasks`` with a PaintRun's
# resolved ``workspace``/``scenario``/``created_by``/``params``.


def run_direct_paint(
    *,
    workspace: Workspace,
    scenario: Scenario,
    user: Any,  # noqa: ARG001 — kept for a uniform run_*() call signature
    params: dict[str, Any],
) -> dict[str, Any]:
    """Paint a single column's value on the selected features."""
    features: list[str] = params["features"]
    column: str = params["column"]
    painted_value = params["value"]

    paint_map: dict[str, dict[str, float | None]] = {
        fid: {column: painted_value} for fid in features
    }
    block = _enforce_paint_constraints(workspace, paint_map)
    if block is not None:
        return block

    with transaction.atomic():
        # Capture old values before upsert
        old_values = _fetch_painted_old_values(scenario, features, column)

        pc_rows = [
            PaintedCanvas(
                scenario=scenario,
                feature_id=fid,
                column_name=column,
                painted_value=painted_value,
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
        PaintEvent.objects.bulk_create(
            [
                PaintEvent(
                    scenario=scenario,
                    feature_id=fid,
                    column_name=column,
                    old_value=old_values.get(fid, (None, None))[0],
                    new_value=painted_value,
                    operation_type="paint",
                    batch_id=batch_id,
                )
                for fid in features
            ]
        )

        # Refresh the canvas view
        base_table = _resolve_base_table(scenario)
        refresh_canvas_view(scenario, base_table)

    warnings = _collect_warnings()
    return {
        "status": "ok",
        "painted_count": len(features),
        "painted_features": _cap_list(features),
        "painted_features_total": len(features),
        "batch_id": batch_id,
        "warnings": _cap_list(warnings),
        "warnings_total": len(warnings),
    }


def run_built_form_paint(
    *,
    workspace: Workspace,
    scenario: Scenario,
    user: Any,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Paint built form attributes on the selected features.

    ``bf_id``/``bf_type`` were already resolved to a real Building/Place
    Type by the view (so an unknown id 404s immediately) — re-resolve here
    from the same (validated) params for the actual allocation work.
    """
    features: list[str] = params["features"]
    bf_type: str = params["bf_type"]
    bf_id: int = params["bf_id"]

    built_form: BuildingType | PlaceType
    if bf_type == "building":
        built_form = get_object_or_404(BuildingType, pk=bf_id, workspace=workspace)
    else:
        built_form = get_object_or_404(PlaceType, pk=bf_id, workspace=workspace)

    base_table = _resolve_base_table(scenario)
    feature_data = _fetch_feature_data(base_table, features)
    if not feature_data:
        return {
            "status": "error",
            "message": "No base canvas data found for selected features.",
            "http_status": 400,
        }

    allocations: dict[str, AllocationResult] = {}
    for fid, row in feature_data.items():
        parcel_acres = float(row.get("area_gross", row.get("area_parcel", 1.0)))

        if bf_type == "building":
            assert isinstance(built_form, BuildingType)
            allocations[fid] = AllocationEngine.allocation_building_type(
                parcel_acres=parcel_acres,
                building_type=built_form,
                row_allocation_pct=0.0,  # ROW already reflected in base data
            )
        else:
            assert isinstance(built_form, PlaceType)
            allocations[fid] = AllocationEngine.allocation_place_type(
                parcel_acres=parcel_acres,
                place_type=built_form,
            )

    return _write_built_form_paint(
        workspace=workspace,
        scenario=scenario,
        user=user,
        base_table=base_table,
        allocations=allocations,
        operation_type="built_form",
        built_form_names=dict.fromkeys(allocations, built_form.name),
    )


def run_match_built_form(
    *,
    workspace: Workspace,
    scenario: Scenario,
    user: Any,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Auto-assign each selected feature the closest-matching Building Type."""
    features: list[str] = params["features"]

    canvas_data = _fetch_canvas_feature_data(scenario, features)
    if not canvas_data:
        return {
            "status": "error",
            "message": "No canvas data found for selected features.",
            "http_status": 400,
        }

    building_types = list(BuildingType.objects.filter(workspace=workspace))
    du_candidates = [bt for bt in building_types if bt.du_per_acre is not None]
    emp_candidates = [bt for bt in building_types if bt.emp_per_acre is not None]

    allocations: dict[str, AllocationResult] = {}
    built_form_names: dict[str, str] = {}
    matches: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []

    for fid, row in canvas_data.items():
        acres = float(row.get("area_gross") or row.get("area_parcel") or 0.0)
        if acres <= 0:
            unmatched.append(
                {"feature_id": fid, "message": "No parcel area available."}
            )
            continue

        du_value = float(row.get("du") or 0.0)
        emp_value = float(row.get("emp") or 0.0)

        candidates: list[BuildingType] = []
        basis = ""
        density = 0.0
        if du_value > 0 and du_candidates:
            candidates, basis, density = du_candidates, "du_per_acre", du_value / acres
        elif emp_value > 0 and emp_candidates:
            candidates, basis, density = (
                emp_candidates,
                "emp_per_acre",
                emp_value / acres,
            )

        if not candidates:
            unmatched.append(
                {
                    "feature_id": fid,
                    "message": (
                        "No du/emp value to match against, or no Building "
                        "Types with that density defined."
                    ),
                }
            )
            continue

        best = min(candidates, key=lambda bt: abs(getattr(bt, basis) - density))
        allocations[fid] = AllocationEngine.allocation_building_type(
            parcel_acres=acres,
            building_type=best,
            row_allocation_pct=0.0,
        )
        built_form_names[fid] = best.name
        matches.append(
            {
                "feature_id": fid,
                "building_type_id": best.pk,
                "building_type_name": best.name,
                "basis": basis,
                "parcel_density": density,
                "matched_density": getattr(best, basis),
            }
        )

    if not allocations:
        return {
            "status": "error",
            "message": "No features could be matched to a Building Type.",
            "unmatched": unmatched,
            "http_status": 400,
        }

    return _write_built_form_paint(
        workspace=workspace,
        scenario=scenario,
        user=user,
        base_table=_resolve_base_table(scenario),
        allocations=allocations,
        operation_type="built_form_match",
        built_form_names=built_form_names,
        extra_response_fields={"matches": matches, "unmatched": unmatched},
        extra_warnings=[
            {"message": f"{u['feature_id']}: {u['message']}"} for u in unmatched
        ],
    )


def run_fill_built_form(
    *,
    workspace: Workspace,
    scenario: Scenario,
    user: Any,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Fill in du/emp stats for selected features from their current built form."""
    features: list[str] = params["features"]

    base_table = _resolve_base_table(scenario)
    feature_data = _fetch_canvas_feature_data(scenario, features)
    if not feature_data:
        return {
            "status": "error",
            "message": "No canvas data found for selected features.",
            "http_status": 400,
        }

    building_types = list(BuildingType.objects.filter(workspace=workspace))
    bt_by_name: dict[str, BuildingType] = {
        _normalize_bf_name(bt.name): bt for bt in building_types
    }

    allocations: dict[str, AllocationResult] = {}
    built_form_names: dict[str, str] = {}
    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []

    for fid, row in feature_data.items():
        built_form_key = row.get("built_form_key")
        if not built_form_key:
            unmatched.append(
                {"feature_id": fid, "message": "No built_form_key set on this parcel."}
            )
            continue

        built_form = bt_by_name.get(_normalize_bf_name(built_form_key))
        if built_form is None:
            unmatched.append(
                {
                    "feature_id": fid,
                    "built_form_key": built_form_key,
                    "message": "No matching Building Type found.",
                }
            )
            continue

        parcel_acres = float(row.get("area_gross") or row.get("area_parcel") or 1.0)
        allocations[fid] = AllocationEngine.allocation_building_type(
            parcel_acres=parcel_acres,
            building_type=built_form,
            row_allocation_pct=0.0,
        )
        built_form_names[fid] = built_form.name
        matched.append(
            {
                "feature_id": fid,
                "built_form_key": built_form_key,
                "building_type_id": built_form.pk,
                "building_type_name": built_form.name,
            }
        )

    if not allocations:
        return {
            "status": "error",
            "message": "No features could be matched to a Building Type.",
            "unmatched": unmatched,
            "http_status": 400,
        }

    return _write_built_form_paint(
        workspace=workspace,
        scenario=scenario,
        user=user,
        base_table=base_table,
        allocations=allocations,
        operation_type="built_form_fill",
        built_form_names=built_form_names,
        extra_response_fields={"matched": matched, "unmatched": unmatched},
        extra_warnings=[
            {"message": f"{u['feature_id']}: {u['message']}"} for u in unmatched
        ],
    )


# ─── Helpers ─────────────────────────────────────────────────────


_PAINT_CONSTRAINT_RESULT: list[ConstraintResult | None] = [None]
"""Last constraint result, cached for warning collection (mutable container for in-module mutation)."""


def _resolve_base_table(scenario: Scenario) -> str:
    """Resolve the base canvas table name for a scenario."""
    return scenario.workspace.base_table


def _fetch_painted_old_values(
    scenario: Scenario,
    feature_ids: list[str],
    column_name: str,
) -> dict[str, tuple[float | None, str | None]]:
    """Fetch current PaintedCanvas values for (scenario, features, column).

    Returns a dict mapping feature_id -> (painted_value, painted_text_value)
    — both None if no paint exists. Callers pick whichever of the pair is
    relevant based on whether ``column_name`` is in ``TEXT_COLUMNS``.
    """
    qs = PaintedCanvas.objects.filter(
        scenario=scenario,
        feature_id__in=feature_ids,
        column_name=column_name,
    ).values("feature_id", "painted_value", "painted_text_value")
    result: dict[str, tuple[float | None, str | None]] = {}
    for row in qs:
        result[row["feature_id"]] = (row["painted_value"], row["painted_text_value"])
    # Features without paint get (None, None) (they fall through to base canvas)
    for fid in feature_ids:
        result.setdefault(fid, (None, None))
    return result


def _fetch_feature_data(base_table: str, feature_ids: list[str]) -> dict[str, dict]:
    """Fetch base canvas data for given feature IDs.

    Returns a dict mapping feature_id → row dict (with string keys).
    Uses parameterized query to avoid SQL injection.
    """
    if not feature_ids:
        return {}

    placeholders = ", ".join("%s" for _ in feature_ids)
    query = (
        f"SELECT id, area_gross, area_parcel, built_form_key FROM {base_table} "  # noqa: S608
        f"WHERE CAST(id AS text) IN ({placeholders})"
    )

    with connection.cursor() as cursor:
        cursor.execute(query, feature_ids)
        col_names = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

    return {str(row[0]): dict(zip(col_names, row, strict=True)) for row in rows}


def _fetch_canvas_feature_data(
    scenario: Scenario, feature_ids: list[str]
) -> dict[str, dict]:
    """Fetch current du/emp/area/built_form_key values from the scenario's canvas view.

    Reads from the per-scenario canvas view (base canvas COALESCEd with any
    PaintedCanvas overlay) rather than the raw base table, so density
    matching and built_form_key lookups reflect values already painted in
    this scenario (e.g. a prior Match Closest or manual Built Form paint).
    """
    if not feature_ids:
        return {}

    view_name = f"{scenario.target_schema}.scenario_{scenario.slug}_canvas"
    placeholders = ", ".join("%s" for _ in feature_ids)
    query = (
        f"SELECT id, du, emp, area_gross, area_parcel, built_form_key "  # noqa: S608
        f"FROM {view_name} WHERE CAST(id AS text) IN ({placeholders})"
    )

    with connection.cursor() as cursor:
        cursor.execute(query, feature_ids)
        col_names = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

    return {str(row[0]): dict(zip(col_names, row, strict=True)) for row in rows}


def _normalize_bf_name(value: str) -> str:
    """Normalize a built-form identifier for loose name matching.

    Strips common ETL key prefixes (e.g. ``"bt__"``) and collapses
    underscores/hyphens to spaces so a base-layer ``built_form_key`` (slug-like)
    can be matched against a workspace's ``BuildingType``/``PlaceType`` display names.
    """
    normalized = value.strip().lower()
    for prefix in ("bt__", "pt__", "bf__"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized.replace("_", " ").replace("-", " ").strip()


def _allocation_to_painted_rows(  # noqa: C901
    *,
    scenario: Scenario,
    feature_id: str,
    result: AllocationResult,
    painted_by: Any,
    built_form_name: str | None = None,
) -> list[PaintedCanvas]:
    """Convert an AllocationResult to a list of PaintedCanvas rows.

    Maps allocation output fields to canvas column names. When
    *built_form_name* is given, also includes a ``built_form_key`` row
    (text-valued, via ``painted_text_value``) recording which Building/Place
    Type produced this allocation.
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
                # Split by MF sub-type
                bt_lower = bt_name.lower()
                if "2-4" in bt_name or "2to4" in bt_lower or "2_to_4" in bt_lower:
                    field_map["du_mf2to4"] = field_map.get("du_mf2to4", 0.0) + bt_du
                elif (
                    "5+" in bt_name
                    or "5p" in bt_lower
                    or "5_plus" in bt_lower
                    or "5plus" in bt_lower
                ):
                    field_map["du_mf5p"] = field_map.get("du_mf5p", 0.0) + bt_du
                else:
                    # Generic MF — default split 40% 2-4, 60% 5+
                    field_map["du_mf2to4"] = (
                        field_map.get("du_mf2to4", 0.0) + bt_du * 0.4
                    )
                    field_map["du_mf5p"] = field_map.get("du_mf5p", 0.0) + bt_du * 0.6
                # Also populate aggregate du_mf for backward compatibility
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

    if built_form_name:
        rows.append(
            PaintedCanvas(
                scenario=scenario,
                feature_id=feature_id,
                column_name="built_form_key",
                painted_text_value=built_form_name,
                painted_by=painted_by,
            )
        )

    return rows


def _enforce_paint_constraints(
    workspace: Workspace,
    paint_map: dict[str, dict[str, float | None]],
) -> dict[str, Any] | None:
    """Check paint constraints; return a blocking result dict or None.

    Violations are cached on the function for later retrieval via
    :func:`_collect_warnings`.
    """
    constraint_result = check_paint_batch(workspace, paint_map)
    _PAINT_CONSTRAINT_RESULT[0] = constraint_result
    if constraint_result.blocked:
        violations = [v.to_dict() for v in constraint_result.violations]
        return {
            "status": "error",
            "message": "Paint operation blocked by workspace constraints.",
            "violations": _cap_list(violations),
            "violations_total": len(violations),
            "http_status": 409,
        }
    return None


def _collect_warnings() -> list[dict]:
    """Collect warning violations from the last constraint check."""
    last_result = _PAINT_CONSTRAINT_RESULT[0]
    if last_result is None:
        return []
    return [v.to_dict() for v in last_result.violations if v.severity == "warn"]


def _paint_event_from_row(  # noqa: PLR0913
    *,
    scenario: Scenario,
    pc: PaintedCanvas,
    old: tuple[float | None, str | None],
    user: Any,
    operation_type: str,
    batch_id: str,
) -> PaintEvent:
    """Build a PaintEvent for one painted row, routing numeric vs text columns."""
    is_text = pc.column_name in TEXT_COLUMNS
    return PaintEvent(
        scenario=scenario,
        feature_id=pc.feature_id,
        column_name=pc.column_name,
        old_value=None if is_text else old[0],
        new_value=None if is_text else pc.painted_value,
        old_text_value=old[1] if is_text else None,
        new_text_value=pc.painted_text_value if is_text else None,
        painted_by=user,
        operation_type=operation_type,
        batch_id=batch_id,
    )


def _write_built_form_paint(  # noqa: C901, PLR0913
    *,
    workspace: Workspace,
    scenario: Scenario,
    user: Any,
    base_table: str,
    allocations: dict[str, AllocationResult],
    operation_type: str,
    built_form_names: dict[str, str] | None = None,
    extra_response_fields: dict[str, Any] | None = None,
    extra_warnings: list[dict] | None = None,
) -> dict[str, Any]:
    """Write allocation results as PaintedCanvas rows and log paint events.

    Shared by :func:`run_built_form_paint`, :func:`run_match_built_form`, and
    :func:`run_fill_built_form` — each computes a ``{feature_id: AllocationResult}``
    map by its own logic, then hands it here for the common
    upsert/constraint-check/event-log/refresh pipeline. When *built_form_names*
    is given (``{feature_id: building/place type name}``), each feature also
    gets its ``built_form_key`` overridden to record which built form produced
    the allocation.
    """
    with transaction.atomic():
        all_pc_rows: list[PaintedCanvas] = []
        # Track which feature+column combos are being painted for old-value lookup
        feature_columns: set[tuple[str, str]] = set()

        for fid, result in allocations.items():
            pc_rows = _allocation_to_painted_rows(
                scenario=scenario,
                feature_id=fid,
                result=result,
                painted_by=user,
                built_form_name=(built_form_names or {}).get(fid),
            )
            for pc_row in pc_rows:
                feature_columns.add((fid, pc_row.column_name))
            all_pc_rows.extend(pc_rows)

        # ── Constraint checking ──────────────────────────
        paint_map: dict[str, dict[str, float | None]] = {}
        for pc_row in all_pc_rows:
            paint_map.setdefault(pc_row.feature_id, {})[pc_row.column_name] = (
                pc_row.painted_value
            )
        block = _enforce_paint_constraints(workspace, paint_map)
        if block is not None:
            return block
        bf_warnings = _collect_warnings()
        if extra_warnings:
            bf_warnings = [*bf_warnings, *extra_warnings]
        # ─────────────────────────────────────────────────

        # Fetch old values before upsert — one query per distinct column
        # (batching all of that column's feature ids together), not one
        # query per (feature, column) pair. A large selection touches the
        # same handful of columns (du, pop, hh, emp, built_form_key, ...)
        # across every feature, so grouping this way turns what would be
        # thousands of near-identical queries into a handful.
        fids_by_column: dict[str, list[str]] = {}
        for fid, col in feature_columns:
            fids_by_column.setdefault(col, []).append(fid)

        old_values_map: dict[tuple[str, str], tuple[float | None, str | None]] = {}
        for col, fids in fids_by_column.items():
            old = _fetch_painted_old_values(scenario, fids, col)
            for fid in fids:
                old_values_map[(fid, col)] = old.get(fid, (None, None))

        # Bulk upsert all painted rows
        PaintedCanvas.objects.bulk_create(
            all_pc_rows,
            update_conflicts=True,
            update_fields=[
                "painted_value",
                "painted_text_value",
                "painted_by",
                "painted_at",
            ],
            unique_fields=["scenario", "feature_id", "column_name"],
        )

        # Log built_form paint events
        batch_id = uuid.uuid4().hex
        PaintEvent.objects.bulk_create(
            [
                _paint_event_from_row(
                    scenario=scenario,
                    pc=pc,
                    old=old_values_map.get(
                        (pc.feature_id, pc.column_name), (None, None)
                    ),
                    user=user,
                    operation_type=operation_type,
                    batch_id=batch_id,
                )
                for pc in all_pc_rows
            ]
        )

        refresh_canvas_view(scenario, base_table)

    painted_features = list(allocations.keys())
    response_body: dict[str, Any] = {
        "status": "ok",
        "painted_count": len(all_pc_rows),
        "painted_features": _cap_list(painted_features),
        "painted_features_total": len(painted_features),
        "batch_id": batch_id,
        "warnings": _cap_list(bf_warnings),
        "warnings_total": len(bf_warnings),
    }
    if extra_response_fields:
        for key, value in extra_response_fields.items():
            if isinstance(value, list):
                response_body[key] = _cap_list(value)
                response_body[f"{key}_total"] = len(value)
            else:
                response_body[key] = value
    return response_body
