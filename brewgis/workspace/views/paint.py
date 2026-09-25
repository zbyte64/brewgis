"""Paint views — direct column painting, built form painting, geometry edits, history, and undo/redo.

Painting can touch a large number of parcels at once (a big box/polygon
selection), and each of the "apply" operations below does real work per feature
(constraint checks, ``AllocationEngine`` calls, canvas-view refreshes) that
scales with selection size. To keep the request from blocking on that,
``paint_features``/``paint_built_form``/``match_built_form``/``fill_built_form``/
``grid_parcels``/``merge_parcels`` only validate the request synchronously; the
actual work runs in ``run_paint_operation`` (a Celery task, see
``brewgis.workspace.tasks``) tracked by a ``PaintRun`` row. The view responds
immediately with either the finished result (if the task already completed —
always true in eager-mode tests/dev, per ``CELERY_TASK_ALWAYS_EAGER``) or a
202 + poll URL for the frontend to watch via ``paint_status``.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from math import ceil
from math import cos
from math import radians
from math import sin
from typing import TYPE_CHECKING
from typing import Any

import deal
from celery import current_app
from django.contrib.auth.decorators import login_required
from django.contrib.gis.geos import GEOSGeometry
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
from brewgis.workspace.built_forms.matching import dominant_employment_sector
from brewgis.workspace.built_forms.matching import prefer_same_category
from brewgis.workspace.built_forms.matching import prefer_same_sector
from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.built_forms.models import PlaceType
from brewgis.workspace.models import GEOMETRY_EDIT_ID_SEQUENCE
from brewgis.workspace.models import PaintedCanvas
from brewgis.workspace.models import PaintEvent
from brewgis.workspace.models import PaintRun
from brewgis.workspace.models import ParcelGeometryEdit
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import ScenarioNotPaintableError
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.base_canvas_schema import EMPLOYMENT_SECTORS
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema
from brewgis.workspace.services.built_form_keys import normalize_built_form_key
from brewgis.workspace.services.canvas_view_manager import PAINTABLE_COLUMNS
from brewgis.workspace.services.canvas_view_manager import TEXT_COLUMNS
from brewgis.workspace.services.canvas_view_manager import _fetch_base_columns
from brewgis.workspace.services.paint_constraints import ConstraintResult
from brewgis.workspace.services.paint_constraints import check_paint_batch
from brewgis.workspace.services.scenario_canvas import purge_scenario_canvas_tiles

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
        scenario.ensure_paintable()
    except ScenarioNotPaintableError as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=400)

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
        scenario.ensure_paintable()
    except ScenarioNotPaintableError as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=400)

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

        # Purge the tile server's cache for the canvas view
        purge_scenario_canvas_tiles(scenario)

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
        scenario.ensure_paintable()
    except ScenarioNotPaintableError as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=400)

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
        scenario.ensure_paintable()
    except ScenarioNotPaintableError as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=400)

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

    return _enqueue(scenario, request.user, "match", {"features": features})


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
        scenario.ensure_paintable()
    except ScenarioNotPaintableError as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=400)

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

    return _enqueue(scenario, request.user, "fill", {"features": features})


def _parse_geometry_edit_body(
    request: HttpRequest, workspace_pk: int, scenario_pk: int
) -> tuple[Scenario, list[str], dict[str, Any]] | JsonResponse:
    """Resolve the scenario and validate the shared part of a geometry-edit body.

    Both grid and merge take ``{"features": [...]}`` and differ only in the grid
    extras, so the workspace/scenario lookup, the paintable check and the
    feature-list validation are shared. Returns either the resolved parts or the
    error response to send back verbatim.
    """
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    scenario = get_object_or_404(Scenario, pk=scenario_pk, workspace=workspace)
    try:
        scenario.ensure_paintable()
    except ScenarioNotPaintableError as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=400)

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

    return scenario, features, body


@require_POST
@login_required
def grid_parcels(
    request: HttpRequest, workspace_pk: int, scenario_pk: int
) -> JsonResponse:
    """Split the selected parcels into a square grid of smaller parcels.

    Accepts JSON body::
        {"features": ["1", "2"], "cell_size_ft": 100}

    or, with an explicit grid origin offset::
        {"features": ["1", "2"], "cell_size_ft": 100, "offset_x_ft": 50, "offset_y_ft": 0}

    or, with the cell grid rotated clockwise by an angle in degrees::
        {"features": ["1", "2"], "cell_size_ft": 100, "rotation_deg": 15}

    The selected parcels are unioned into one site and the site is cut into
    square cells of *cell_size_ft* feet, the grid aligned to the offset (zero,
    i.e. the projected origin, by default) and rotated by *rotation_deg* about
    the selection's centre (zero, i.e. the projected axes, by default). Column
    values are allocated to each cell from the parcels it covers, conserving
    totals — see :func:`_allocate_grid_cell`.

    Runs as a background ``PaintRun`` (see module docstring) — validates the
    request shape here, then hands off to :func:`run_grid_parcels`.
    """
    resolved = _parse_geometry_edit_body(request, workspace_pk, scenario_pk)
    if isinstance(resolved, JsonResponse):
        return resolved
    scenario, features, body = resolved

    try:
        cell_size_ft = float(body["cell_size_ft"])
        offset_x_ft = float(body.get("offset_x_ft") or 0.0)
        offset_y_ft = float(body.get("offset_y_ft") or 0.0)
        rotation_deg = float(body.get("rotation_deg") or 0.0)
    except (KeyError, TypeError, ValueError):
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "cell_size_ft is required and must be a number; "
                    "offset_x_ft/offset_y_ft/rotation_deg are optional numbers."
                ),
            },
            status=400,
        )

    return _enqueue(
        scenario,
        request.user,
        "grid",
        {
            "features": features,
            "cell_size_ft": cell_size_ft,
            "offset_x_ft": offset_x_ft,
            "offset_y_ft": offset_y_ft,
            "rotation_deg": rotation_deg,
        },
    )


@require_POST
@login_required
def merge_parcels(
    request: HttpRequest, workspace_pk: int, scenario_pk: int
) -> JsonResponse:
    """Merge the selected parcels into one.

    Accepts JSON body::
        {"features": ["1", "2", "3"]}

    The parcels' geometry is dissolved into a single multi-polygon and one of
    them (the lowest id, so the result is deterministic) survives as the merged
    parcel, carrying the union of their values — see :func:`_allocate_merge`.

    Runs as a background ``PaintRun`` (see module docstring) — validates the
    request shape here, then hands off to :func:`run_merge_parcels`.
    """
    resolved = _parse_geometry_edit_body(request, workspace_pk, scenario_pk)
    if isinstance(resolved, JsonResponse):
        return resolved
    scenario, features, _body = resolved

    return _enqueue(scenario, request.user, "merge", {"features": features})


@require_POST
@login_required
def grid_preview(
    request: HttpRequest, workspace_pk: int, scenario_pk: int
) -> JsonResponse:
    """Return the cells a grid request *would* produce, without writing anything.

    Accepts the same JSON body as :func:`grid_parcels`::

        {"features": ["1", "2"], "cell_size_ft": 100, "rotation_deg": 15}

    Draws the pending geometry edit as a temporary overlay in paint mode, so the
    user can judge a cell size/offset/rotation before committing to it. Never
    writes: no ``ParcelGeometryEdit`` rows, no ``PaintRun``, no tile purge — it
    shares :func:`_compute_grid_cells` with the write path, so the preview and
    the grid it precedes are the same cells.
    """
    resolved = _parse_geometry_edit_body(request, workspace_pk, scenario_pk)
    if isinstance(resolved, JsonResponse):
        return resolved
    scenario, features, body = resolved

    try:
        cell_size_ft = float(body["cell_size_ft"])
        offset_x_ft = float(body.get("offset_x_ft") or 0.0)
        offset_y_ft = float(body.get("offset_y_ft") or 0.0)
        rotation_deg = float(body.get("rotation_deg") or 0.0)
    except (KeyError, TypeError, ValueError):
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "cell_size_ft is required and must be a number; "
                    "offset_x_ft/offset_y_ft/rotation_deg are optional numbers."
                ),
            },
            status=400,
        )

    cells, _sources, error = _compute_grid_cells(
        scenario,
        features,
        cell_size_ft=cell_size_ft,
        offset_x_ft=offset_x_ft,
        offset_y_ft=offset_y_ft,
        rotation_deg=rotation_deg,
    )
    if error is not None:
        return JsonResponse({"status": "error", "message": error[0]}, status=error[1])

    geojson = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {}, "geometry": json.loads(cell_geojson)}
            for (cell_geojson, _area, _overlap) in cells
        ],
    }
    return JsonResponse({"status": "ok", "geojson": geojson})


@require_POST
@login_required
def merge_preview(
    request: HttpRequest, workspace_pk: int, scenario_pk: int
) -> JsonResponse:
    """Return the union a merge request *would* write, without writing anything.

    Accepts the same JSON body as :func:`merge_parcels`::

        {"features": ["1", "2", "3"]}

    Shares :func:`_merge_union_geojson` with the write path, so the overlay the
    user approves is exactly the geometry the merge then persists.
    """
    resolved = _parse_geometry_edit_body(request, workspace_pk, scenario_pk)
    if isinstance(resolved, JsonResponse):
        return resolved
    scenario, features, _body = resolved

    unique_features = list(dict.fromkeys([str(feature) for feature in features]))
    if len(unique_features) < _MIN_MERGE_PARCELS:
        return JsonResponse(
            {
                "status": "error",
                "message": "Select at least two distinct parcels to merge.",
            },
            status=400,
        )

    schema, table = scenario.base_layer_source()
    quoted_view = _quote_qualified_table(schema, table)

    # Every base column comes back because which columns a canvas exposes is
    # per-workspace; the preview only needs the ids to resolve, but the fetch
    # that proves that is the same one the write path uses.
    rows = _fetch_canvas_feature_data(scenario, unique_features, include_geometry=True)
    missing = [feature for feature in unique_features if feature not in rows]
    if missing:
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "Parcels not found in this scenario's canvas: "
                    f"{', '.join(missing[:10])}."
                ),
            },
            status=404,
        )

    union_geojson = _merge_union_geojson(quoted_view, unique_features)
    if union_geojson is None:
        return JsonResponse(
            {
                "status": "error",
                "message": "No geometry found for the selected parcels.",
            },
            status=404,
        )

    return JsonResponse(
        {
            "status": "ok",
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": json.loads(union_geojson),
                    }
                ],
            },
        }
    )


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
        scenario.ensure_paintable()
    except ScenarioNotPaintableError as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=400)

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

        # Grid/merge batches keep their state in ParcelGeometryEdit rows rather
        # than in PaintedCanvas, so undoing them means deleting those rows: the
        # canvas view only hides a parcel for as long as an edit still claims it
        # as a source, so the replaced parcels come straight back (including an
        # earlier edit's cells if this grid was applied to them). Any paint
        # applied to features that disappear with the edit goes too — an
        # override on a parcel that no longer exists is unreachable — but a
        # merge's result id is its own survivor, a parcel that is still there
        # after the undo, and its overrides are restored by this batch's clear
        # events instead.
        edits = list(
            ParcelGeometryEdit.objects.filter(
                scenario=scenario,
                batch_id__in={evt.batch_id for evt in events},
            )
        )
        if edits:
            vanishing_ids = [
                str(edit.parcel_id)
                for edit in edits
                if str(edit.parcel_id) not in set(edit.source_parcel_ids)
            ]
            ParcelGeometryEdit.objects.filter(
                pk__in=[edit.pk for edit in edits]
            ).delete()
            PaintedCanvas.objects.filter(
                scenario=scenario, feature_id__in=vanishing_ids
            ).delete()

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

        # Purge the tile server's cache for the canvas view
        purge_scenario_canvas_tiles(scenario)

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
        workspace=scenario.workspace,
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
    block = _enforce_paint_constraints(scenario.workspace, paint_map)
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

        # Purge the tile server's cache for the canvas view
        purge_scenario_canvas_tiles(scenario)

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
    workspace = scenario.workspace

    built_form: BuildingType | PlaceType
    if bf_type == "building":
        built_form = get_object_or_404(BuildingType, pk=bf_id, workspace=workspace)
    else:
        built_form = get_object_or_404(PlaceType, pk=bf_id, workspace=workspace)

    base_table = workspace.base_table
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
        allocations=allocations,
        operation_type="built_form",
        built_form_names=dict.fromkeys(allocations, built_form.name),
    )


def run_match_built_form(
    *,
    scenario: Scenario,
    user: Any,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Auto-assign each selected feature the closest-matching Building Type."""
    features: list[str] = params["features"]
    workspace = scenario.workspace

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

        # Two narrowing preferences on top of the density basis — never bases
        # of their own, and each falling back to the list it was given: the
        # sector the parcel's jobs are in first, then its land development
        # category. A workspace whose types carry neither matches exactly as it
        # did before they existed.
        candidates = list(
            prefer_same_sector(candidates, dominant_employment_sector(row))
        )
        candidates = list(
            prefer_same_category(candidates, row.get("land_development_category"))
        )

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
    scenario: Scenario,
    user: Any,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Fill in du/emp stats for selected features from their current built form."""
    features: list[str] = params["features"]
    workspace = scenario.workspace

    feature_data = _fetch_canvas_feature_data(scenario, features)
    if not feature_data:
        return {
            "status": "error",
            "message": "No canvas data found for selected features.",
            "http_status": 400,
        }

    building_types = list(BuildingType.objects.filter(workspace=workspace))
    bt_by_name: dict[str, BuildingType] = {
        normalize_built_form_key(bt.name): bt for bt in building_types
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

        built_form = bt_by_name.get(normalize_built_form_key(built_form_key))
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
        allocations=allocations,
        operation_type="built_form_fill",
        built_form_names=built_form_names,
        extra_response_fields={"matched": matched, "unmatched": unmatched},
        extra_warnings=[
            {"message": f"{u['feature_id']}: {u['message']}"} for u in unmatched
        ],
    )


# ─── Geometry edits (grid / merge) ───────────────────────────────
#
# Paint mode's two parcel-boundary tools. Both are copy-on-write over the
# workspace's base canvas: they write ParcelGeometryEdit rows for the *result*
# features and the scenario's canvas view — the single source both the tile
# servers and the analysis models read — UNIONs those rows in and hides the
# parcels they replace (see
# ``services.canvas_view_manager.build_canvas_view_select``). Neither tool ever
# writes to the base canvas table.

_FT_TO_M = 0.3048
"""Feet per metre — grid cell sizes and offsets are entered in feet."""

_MIN_CELL_AREA_M2 = 1.0
"""Cells smaller than this (m²) are dropped as slivers of a clipped parcel."""

_MAX_GRID_CELLS = 50_000
"""Refuse a grid whose envelope would need more cells than this.

Cells are generated over the selection's *envelope*, so a small cell size over
a large or diagonally sparse selection would ask Postgres for millions of them
before anything is clipped away. Comparing the envelope's area to the cell area
is cheap and rejects the request up front with an actionable message instead.
"""

_MIN_MERGE_PARCELS = 2
"""Parcels a merge needs before there is anything to merge."""

_EDIT_AUX_KEYS: frozenset[str] = frozenset(
    {"parcel_id", "geometry", "geometry_geojson", "area_m2"}
)
"""Source-dict keys that are not ParcelGeometryEdit.values columns.

``parcel_id``/``geometry`` have dedicated model fields, and
``geometry_geojson``/``area_m2`` are fetch-time decorations the canvas view
never reads back out of ``values``.
"""

_EXTENSIVE_METATYPES: frozenset[str] = frozenset({"count", "area", "currency"})
_INTENSIVE_METATYPES: frozenset[str] = frozenset({"density", "percentage"})
_COPY_METATYPES: frozenset[str] = frozenset({"identity", "geometry", "classification"})


def _all_numeric(values: list[Any]) -> bool:
    """True when every non-null value is a real number (booleans excluded).

    ``bool`` is an ``int`` subclass in Python, so it is excluded explicitly: a
    flag column like ``is_residential`` reads as numeric otherwise and would be
    summed into 3 for a parcel covering three sources.
    """
    seen = False
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            return False
        seen = True
    return seen


def _allocatable_columns(sources: dict[str, dict[str, Any]]) -> set[str]:
    """Every column an edit row has to carry: the sources' keys minus the aux ones."""
    columns: set[str] = set()
    for row in sources.values():
        columns.update(row)
    return columns - _EDIT_AUX_KEYS


def _column_basis(column: str, values: list[Any]) -> str:
    """Return how *column* combines when one or more parcels become several.

    One of ``"extensive"`` (summed in proportion to the area taken from each
    source), ``"intensive"`` (averaged over the sources' areas) or ``"copy"``
    (taken from a single source). ``BaseCanvasSchema``'s metatype decides, with
    two type-safety fallbacks that keep its ``"count"`` default from being
    summed where it does not apply: a column the schema has no definition for
    (a base canvas may expose columns the base-canvas model does not, e.g.
    ``county``) and a column whose values are not numbers (``du_subtype`` is
    text, ``is_residential`` is boolean) are copied instead.
    """
    col_def = BaseCanvasSchema.get(column)
    metatype = col_def.metatype if col_def is not None else ""
    numeric = _all_numeric(values)
    if metatype in _INTENSIVE_METATYPES and numeric:
        return "intensive"
    if metatype in _COPY_METATYPES or not numeric:
        return "copy"
    if metatype in _EXTENSIVE_METATYPES:
        return "extensive"
    return "extensive" if numeric else "copy"


def _intensive_mean(
    sources: dict[str, dict[str, Any]],
    weights: dict[str, float],
    column: str,
) -> float:
    """Area-weighted mean of *column* over *weights*.

    Nulls drop out of both sides of the ratio, so a source that has no value
    for *column* cannot drag the average toward zero. A zero total weight has no
    meaningful mean and reads as 0.
    """
    weighted = 0.0
    total = 0.0
    for src_id, weight in weights.items():
        value = sources[src_id].get(column)
        if value is None:
            continue
        weighted += float(value) * weight
        total += weight
    return weighted / total if total else 0.0


def _extensive_sum(
    sources: dict[str, dict[str, Any]],
    weights: dict[str, float],
    column: str,
) -> float | int:
    """Sum *column* over *weights* — a fraction of each source, or 1 per source.

    Nulls contribute nothing. A column whose source values are all plain ``int``
    — which is what the driver returns for the base canvas's ``bigint``/
    ``integer`` columns, ``building_count`` among them — is rounded back to an
    int: a grid cell holding 0.4 of a building is not representable, and the
    base's column type would reject the fraction outright. Rounding is the only
    option for those columns, so a split conserves an integral column's total
    only to within one unit per cell; every fractional column (``du``, the
    areas, the building square footages) conserves exactly.
    """
    total = 0.0
    integral = False
    fractional = False
    for src_id, weight in weights.items():
        value = sources[src_id].get(column)
        if value is None:
            continue
        if isinstance(value, int) and not isinstance(value, bool):
            integral = True
        else:
            fractional = True
        total += float(value) * weight
    return round(total) if integral and not fractional else total


@deal.pre(lambda _sources, overlap_m2, _cell_id: bool(overlap_m2))
@deal.pre(lambda sources, overlap_m2, _cell_id: set(overlap_m2).issubset(sources))
@deal.ensure(
    lambda sources, _overlap_m2, _cell_id, result: (
        set(result) == _allocatable_columns(sources)
    )
)
@deal.ensure(
    lambda _sources, _overlap_m2, cell_id, result: result["geometry_key"] == cell_id
)
def _allocate_grid_cell(
    sources: dict[str, dict[str, Any]],
    overlap_m2: dict[str, float],
    cell_id: str,
) -> dict[str, Any]:
    """Allocate one grid cell's attributes from the parcels it covers.

    Total-conserving: a cell takes each source's extensive values in proportion
    to the part of that source's area it covers (``overlap / area``), and the
    cells partition every source exactly, so the shares over one source sum to
    1. Densities and percentages are averaged over the cell's own source
    composition, and identity/classification columns come from whichever source
    covers most of the cell.
    """
    columns = _allocatable_columns(sources)
    overlap = {src: float(area) for src, area in overlap_m2.items() if area}
    dominant = max(overlap, key=lambda src: overlap[src])

    values: dict[str, Any] = {}
    for column in sorted(columns):
        if column == "geometry_key":
            values[column] = cell_id
            continue
        basis = _column_basis(column, [sources[src].get(column) for src in overlap])
        if basis == "copy":
            values[column] = sources[dominant].get(column)
        elif basis == "intensive":
            values[column] = _intensive_mean(sources, overlap, column)
        else:
            shares = {
                src: area / float(sources[src]["area_m2"])
                for src, area in overlap.items()
            }
            values[column] = _extensive_sum(sources, shares, column)
    return values


@deal.pre(lambda sources, survivor, _merged_geometry_key: survivor in sources)
@deal.ensure(
    lambda sources, _survivor, _merged_geometry_key, result: (
        set(result) == _allocatable_columns(sources)
    )
)
@deal.ensure(
    lambda _sources, _survivor, merged_geometry_key, result: (
        result["geometry_key"] == merged_geometry_key
    )
)
def _allocate_merge(
    sources: dict[str, dict[str, Any]],
    survivor: str,
    merged_geometry_key: str,
) -> dict[str, Any]:
    """Allocate the merged parcel's attributes from the parcels merged into it.

    Extensive values are summed — the merged parcel holds the whole of each —
    densities and percentages are averaged weighted by the sources' areas, and
    identity/classification columns come from the surviving parcel.
    """
    columns = _allocatable_columns(sources)
    weights = {src: float(row.get("area_m2") or 0.0) for src, row in sources.items()}

    values: dict[str, Any] = {}
    for column in sorted(columns):
        if column == "geometry_key":
            values[column] = merged_geometry_key
            continue
        basis = _column_basis(column, [row.get(column) for row in sources.values()])
        if basis == "copy":
            values[column] = sources[survivor].get(column)
        elif basis == "intensive":
            values[column] = _intensive_mean(sources, weights, column)
        else:
            values[column] = _extensive_sum(
                sources, dict.fromkeys(sources, 1.0), column
            )
    return values


def _json_object(value: Any) -> dict[str, Any]:
    """Normalize a ``jsonb`` column read through a raw cursor into a dict.

    psycopg2 hands ``jsonb`` back as a parsed dict; psycopg 3 hands it back as
    its text form unless json loaders are registered on the connection. Both
    drivers are supported in this project, and this is read with a raw cursor.
    ``None`` — a ``jsonb`` column that is null — reads as an empty object.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed: dict[str, Any] = json.loads(value)
        return parsed
    return {}


def _next_geometry_edit_ids(count: int) -> list[str]:
    """Reserve *count* synthetic feature ids from the edit id sequence.

    Negative integers, so they cannot collide with a real parcel id in either
    key flavour — the published base canvas keys on a positive ``BIGINT``, a
    SQLMesh base on an APN string; the canvas view hands them to
    ``jsonb_populate_record``, which casts them to whichever type that key
    actually is. ``nextval`` is deliberately non-transactional: a rolled-back
    grid leaves gaps, which costs nothing and keeps the ids unique.
    """
    if count <= 0:
        return []
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT nextval('{GEOMETRY_EDIT_ID_SEQUENCE}') "  # noqa: S608
            f"FROM generate_series(1, %s)",
            [count],
        )
        return [str(-row[0]) for row in cursor.fetchall()]


def _geojson_geometry(geojson: str) -> GEOSGeometry:
    """Build a 4326 GEOS geometry from ``ST_AsGeoJSON`` output."""
    # GEOSGeometry parses a GeoJSON object passed as a string directly (the
    # WKT/HEX parsers are tried first and fail on a leading '{').
    geometry = GEOSGeometry(geojson)
    geometry.srid = 4326
    return geometry


def _grid_cell_estimate(
    quoted_view: str,
    sources: list[str],
    size_m: float,
    *,
    angle_rad: float = 0.0,
) -> int:
    """Cells a grid of *size_m* would generate over *sources*' envelope.

    With *angle_rad* set, the grid is built over the envelope's axis-aligned
    bounding box *in the rotated frame* (see :func:`_grid_cells`), so the
    envelope is inflated by ``w·|cos| + h·|sin|`` on each axis first — otherwise
    a rotated grid would slip past the cell-count guard.
    """
    query = (
        f"SELECT ST_XMax(e) - ST_XMin(e), ST_YMax(e) - ST_YMin(e) "  # noqa: S608
        f"FROM (SELECT ST_Extent(ST_Transform(geometry, 3857)) AS e "
        f"FROM {quoted_view} WHERE CAST(parcel_id AS text) = ANY(%s)) s"
    )
    with connection.cursor() as cursor:
        cursor.execute(query, [sources])
        width, height = cursor.fetchone()
    if width is None or height is None:
        return 0
    width, height = float(width), float(height)
    if angle_rad:
        c, s = abs(cos(angle_rad)), abs(sin(angle_rad))
        width, height = width * c + height * s, width * s + height * c
    return ceil(width / size_m) * ceil(height / size_m)


def _grid_cells(  # noqa: PLR0913 — the grid is defined by four independent knobs
    quoted_view: str,
    sources: list[str],
    *,
    size_m: float,
    ox_m: float,
    oy_m: float,
    angle_rad: float = 0.0,
) -> list[tuple[str, float, dict[str, float]]]:
    """Cut the union of *sources* into square cells of *size_m* metres.

    Returns ``[(cell_geojson, cell_area_m2, {source_id: overlap_m2}), ...]``.

    One round trip. The grid is generated in Web Mercator so a "100 ft" cell is
    square in metres rather than in degrees, then each cell is transformed back
    to 4326 and intersected with the parcels it overlaps. Grouping those
    intersections by grid index yields both the cell's geometry and its
    per-source overlap areas in true m² — the shares the allocation divides by.
    Because the cells that touch a parcel partition it exactly, those shares
    always add up to the parcel's whole area (the total-conservation property
    :func:`_allocate_grid_cell` relies on).

    *angle_rad* rotates the cell lattice clockwise about the selection
    envelope's centroid, so a site can be cut on a parcel-line angle rather
    than on the projected axes. The rotation is applied by rotating the
    *sources* into a frame where the lattice is axis-aligned, generating the
    grid there with the usual offsets, then rotating each cell back out — so
    the lattice, the offsets and the clipping behave exactly as they do at an
    angle of zero.
    """
    query = f"""
WITH srcs AS MATERIALIZED (
    SELECT parcel_id, ST_MakeValid(geometry) AS geometry
    FROM {quoted_view}
    WHERE CAST(parcel_id AS text) = ANY(%(sources)s)
),
bounds AS (
    SELECT ST_SetSRID(ST_Extent(ST_Transform(geometry, 3857))::geometry, 3857) AS geometry
    FROM srcs
),
origin AS (
    SELECT ST_Centroid(geometry) AS geom FROM bounds
),
rot_srcs AS (
    SELECT s.parcel_id,
           ST_Rotate(ST_Transform(s.geometry, 3857), -%(angle_rad)s, o.geom) AS geometry
    FROM srcs s CROSS JOIN origin o
),
rot_bounds AS (
    SELECT ST_SetSRID(ST_Extent(geometry)::geometry, 3857) AS geometry
    FROM rot_srcs
),
cells AS (
    SELECT ST_Transform(
               ST_Rotate(ST_Translate(g.geom, %(ox)s, %(oy)s), %(angle_rad)s, o.geom),
               4326
           ) AS cell, g.i, g.j
    FROM rot_bounds b
    CROSS JOIN origin o
    CROSS JOIN LATERAL ST_SquareGrid(
        %(size)s, ST_Translate(b.geometry, -%(ox)s, -%(oy)s)
    ) AS g
),
parts AS (
    SELECT c.i, c.j, src.parcel_id AS src_id,
           ST_Intersection(c.cell, src.geometry) AS geometry
    FROM cells c
    JOIN srcs src ON ST_Intersects(c.cell, src.geometry)
),
cell_shapes AS (
    SELECT i, j,
           ST_CollectionExtract(ST_MakeValid(ST_Union(geometry)), 3) AS geometry,
           jsonb_object_agg(
               CAST(src_id AS text), ST_Area(geometry::geography)
           ) AS overlap
    FROM parts
    GROUP BY i, j
)
SELECT ST_AsGeoJSON(geometry) AS cell_geojson,
       ST_Area(geometry::geography) AS cell_area_m2,
       overlap
FROM cell_shapes
WHERE ST_Area(geometry::geography) > %(min_area)s
"""  # noqa: S608 — quoted_view is a quoted identifier pair
    with connection.cursor() as cursor:
        cursor.execute(
            query,
            {
                "sources": sources,
                "size": size_m,
                "ox": ox_m,
                "oy": oy_m,
                "angle_rad": angle_rad,
                "min_area": _MIN_CELL_AREA_M2,
            },
        )
        rows = cursor.fetchall()
    return [(row[0], float(row[1]), _json_object(row[2])) for row in rows]


def _merge_union_geojson(quoted_view: str, sources: list[str]) -> str | None:
    """GeoJSON of the MultiPolygon dissolving *sources*' geometry, or ``None``.

    The shared half of merge: the write path (:func:`run_merge_parcels`)
    persists this geometry as the survivor's ``ParcelGeometryEdit``, and the
    preview endpoint hands the very same geometry to the map as a temporary
    overlay, so what the user sees before applying is what gets written.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT ST_AsGeoJSON("  # noqa: S608
            f"ST_Multi(ST_UnaryUnion(ST_Collect(ST_MakeValid(geometry))))) "
            f"FROM {quoted_view} WHERE CAST(parcel_id AS text) = ANY(%s)",
            [sources],
        )
        return cursor.fetchone()[0]


def _compute_grid_cells(  # noqa: PLR0913 — mirrors the grid request's knobs
    scenario: Scenario,
    features: list[str],
    *,
    cell_size_ft: float,
    offset_x_ft: float,
    offset_y_ft: float,
    rotation_deg: float,
) -> tuple[
    list[tuple[str, float, dict[str, float]]], dict[str, dict], tuple[str, int] | None
]:
    """Validate a grid request and cut the selection into its cells.

    Shared by the write path (:func:`run_grid_parcels`, which turns the cells
    into ``ParcelGeometryEdit`` rows) and the preview endpoint, which returns
    the same cells as GeoJSON and writes nothing — so a preview can never
    disagree with the grid the user then applies.

    Returns ``(cells, sources, error)``: the cells, the canvas row of every
    selected parcel (which the caller needs for the per-cell allocation and
    would otherwise have to fetch a second time), and the ``(message,
    http_status)`` to return verbatim on failure — ``error`` is ``None`` when
    the grid was computed, and ``([], {}, error)`` otherwise.
    """
    # Ids arrive as strings from the map and may repeat (a box selection can
    # report a parcel twice); one id per parcel is what the grid math assumes.
    unique_features = list(dict.fromkeys([str(feature) for feature in features]))
    if not unique_features:
        return [], {}, ("No features selected.", 400)
    if cell_size_ft <= 0:
        return [], {}, ("Cell size must be positive.", 400)

    schema, table = scenario.base_layer_source()
    quoted_view = _quote_qualified_table(schema, table)

    sources = _fetch_canvas_feature_data(
        scenario, unique_features, include_geometry=True
    )
    missing = [feature for feature in unique_features if feature not in sources]
    if missing:
        message = (
            f"Parcels not found in this scenario's canvas: {', '.join(missing[:10])}."
        )
        return [], {}, (message, 404)

    size_m = cell_size_ft * _FT_TO_M
    ox_m = offset_x_ft * _FT_TO_M
    oy_m = offset_y_ft * _FT_TO_M
    angle_rad = radians(rotation_deg)
    estimate = _grid_cell_estimate(
        quoted_view, unique_features, size_m, angle_rad=angle_rad
    )
    if estimate > _MAX_GRID_CELLS:
        message = (
            f"A {cell_size_ft:g} ft grid over this selection needs about "
            f"{estimate} cells (limit {_MAX_GRID_CELLS}) — use a larger cell "
            "size or select a smaller area."
        )
        return [], {}, (message, 400)

    cells = _grid_cells(
        quoted_view,
        unique_features,
        size_m=size_m,
        ox_m=ox_m,
        oy_m=oy_m,
        angle_rad=angle_rad,
    )
    if not cells:
        return [], {}, ("Grid produced no cells — choose a smaller cell size.", 400)
    return cells, sources, None


def run_grid_parcels(
    *,
    scenario: Scenario,
    user: Any,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Split the selected parcels into a square grid of smaller parcels."""
    features = [str(feature) for feature in params["features"]]
    cell_size_ft = float(params["cell_size_ft"])
    offset_x_ft = float(params.get("offset_x_ft") or 0.0)
    offset_y_ft = float(params.get("offset_y_ft") or 0.0)
    rotation_deg = float(params.get("rotation_deg") or 0.0)

    cells, sources, error = _compute_grid_cells(
        scenario,
        features,
        cell_size_ft=cell_size_ft,
        offset_x_ft=offset_x_ft,
        offset_y_ft=offset_y_ft,
        rotation_deg=rotation_deg,
    )
    if error is not None:
        return {"status": "error", "message": error[0], "http_status": error[1]}

    unique_features = list(dict.fromkeys(features))

    with transaction.atomic():
        batch_id = uuid.uuid4().hex
        cell_ids = _next_geometry_edit_ids(len(cells))
        ParcelGeometryEdit.objects.bulk_create(
            [
                ParcelGeometryEdit(
                    scenario=scenario,
                    parcel_id=cell_id,
                    geometry=_geojson_geometry(cell_geojson),
                    values=_allocate_grid_cell(sources, overlap, cell_id),
                    source_parcel_ids=sorted(unique_features),
                    operation=ParcelGeometryEdit.Operation.GRID,
                    batch_id=batch_id,
                    created_by=user,
                )
                for (cell_geojson, _area, overlap), cell_id in zip(
                    cells, cell_ids, strict=True
                )
            ]
        )

        # One event per grid, not per cell: a 5000-cell grid would otherwise
        # bury every other operation in the history, and undo works per batch.
        PaintEvent.objects.create(
            scenario=scenario,
            feature_id=cell_ids[0],
            column_name="geometry",
            operation_type="grid",
            batch_id=batch_id,
            painted_by=user,
        )

        purge_scenario_canvas_tiles(scenario)

    return {
        "status": "ok",
        "grid_count": len(cell_ids),
        "painted_features": _cap_list(cell_ids),
        "painted_features_total": len(cell_ids),
        "batch_id": batch_id,
    }


def run_merge_parcels(
    *,
    scenario: Scenario,
    user: Any,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Merge the selected parcels into one."""
    features = [str(feature) for feature in params["features"]]
    unique_features = list(dict.fromkeys(features))
    if len(unique_features) < _MIN_MERGE_PARCELS:
        return {
            "status": "error",
            "message": "Select at least two distinct parcels to merge.",
            "http_status": 400,
        }

    schema, table = scenario.base_layer_source()
    quoted_view = _quote_qualified_table(schema, table)

    rows = _fetch_canvas_feature_data(scenario, unique_features, include_geometry=True)
    missing = [feature for feature in unique_features if feature not in rows]
    if missing:
        return {
            "status": "error",
            "message": (
                "Parcels not found in this scenario's canvas: "
                f"{', '.join(missing[:10])}."
            ),
            "http_status": 404,
        }

    # Lexicographic over the string ids — ids are not necessarily integers — so
    # the survivor is deterministic for a given selection.
    survivor = sorted(unique_features)[0]

    union_geojson = _merge_union_geojson(quoted_view, unique_features)
    if union_geojson is None:
        return {
            "status": "error",
            "message": "No geometry found for the selected parcels.",
            "http_status": 404,
        }

    with transaction.atomic():
        batch_id = uuid.uuid4().hex
        ParcelGeometryEdit.objects.create(
            scenario=scenario,
            parcel_id=survivor,
            geometry=_geojson_geometry(union_geojson),
            values=_allocate_merge(rows, survivor, survivor),
            source_parcel_ids=sorted(unique_features),
            operation=ParcelGeometryEdit.Operation.MERGE,
            batch_id=batch_id,
            created_by=user,
        )

        # The survivor keeps its own id, so paint already on it would mask the
        # values the merge just computed for it — and those values already
        # include that paint, read out of the canvas view. Drop the overrides
        # and log them as clears in the same batch, so the undo that restores
        # the source parcels restores the survivor's paint with them.
        survivor_paint = list(
            PaintedCanvas.objects.filter(scenario=scenario, feature_id=survivor).values(
                "column_name", "painted_value", "painted_text_value"
            )
        )
        if survivor_paint:
            PaintEvent.objects.bulk_create(
                [
                    PaintEvent(
                        scenario=scenario,
                        feature_id=survivor,
                        column_name=row["column_name"],
                        old_value=row["painted_value"],
                        old_text_value=row["painted_text_value"],
                        operation_type="clear",
                        batch_id=batch_id,
                        painted_by=user,
                    )
                    for row in survivor_paint
                ]
            )
            PaintedCanvas.objects.filter(
                scenario=scenario, feature_id=survivor
            ).delete()

        PaintEvent.objects.create(
            scenario=scenario,
            feature_id=survivor,
            column_name="geometry",
            operation_type="merge",
            batch_id=batch_id,
            painted_by=user,
        )

        purge_scenario_canvas_tiles(scenario)

    return {
        "status": "ok",
        "merged_count": 1,
        "painted_features": [survivor],
        "painted_features_total": 1,
        "batch_id": batch_id,
    }


# ─── Helpers ─────────────────────────────────────────────────────


_PAINT_CONSTRAINT_RESULT: list[ConstraintResult | None] = [None]
"""Last constraint result, cached for warning collection (mutable container for in-module mutation)."""


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


def _quote_qualified_table(schema: str, table: str) -> str:
    """Quote a ``schema``/``table`` pair for safe interpolation into raw SQL.

    Needed because scenario slugs (and therefore canvas view names, e.g.
    ``scenario_martin-auto-refresh_canvas``) can contain hyphens, which
    Postgres parses as a minus operator in an unquoted identifier.
    """
    return f"{connection.ops.quote_name(schema)}.{connection.ops.quote_name(table)}"


def _fetch_feature_data(base_table: str, feature_ids: list[str]) -> dict[str, dict]:
    """Fetch base canvas data for given feature IDs.

    Returns a dict mapping feature_id → row dict (with string keys).
    Uses parameterized query to avoid SQL injection.
    """
    if not feature_ids:
        return {}

    schema, _, table = base_table.rpartition(".")
    quoted_table = _quote_qualified_table(schema or "public", table)
    placeholders = ", ".join("%s" for _ in feature_ids)
    query = (
        f"SELECT id, area_gross, area_parcel, built_form_key FROM {quoted_table} "  # noqa: S608
        f"WHERE CAST(id AS text) IN ({placeholders})"
    )

    with connection.cursor() as cursor:
        cursor.execute(query, feature_ids)
        col_names = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

    return {str(row[0]): dict(zip(col_names, row, strict=True)) for row in rows}


def _json_scalar(value: Any) -> Any:
    """Coerce one fetched base-canvas value into something JSON-serializable.

    ``numeric`` columns — which SQLMesh-declared bases use for areas, densities
    and the DU totals — arrive from psycopg as ``Decimal``, which ``JSONField``
    refuses to serialize.
    """
    return float(value) if isinstance(value, Decimal) else value


def _fetch_canvas_feature_data(
    scenario: Scenario, feature_ids: list[str], *, include_geometry: bool = False
) -> dict[str, dict]:
    """Fetch current column values for *feature_ids* from the scenario's canvas view.

    Reads from the per-scenario canvas view (base canvas UNION any parcel
    geometry edits, COALESCEd with any PaintedCanvas overlay) rather than the
    raw base table, so density matching, ``built_form_key`` lookups and the
    grid/merge allocation all reflect what is already in effect for this
    scenario.

    With *include_geometry*, every column the base canvas exposes comes back —
    a geometry edit row has to carry all of them — plus ``geometry_geojson``
    and ``area_m2``, the parcel's true geodesic area and the denominator the
    grid's area shares divide by. ``geometry`` itself is not selected: only its
    GeoJSON form is used, and a parcel's EWKB hex is orders of magnitude larger
    than the rest of the row.
    """
    if not feature_ids:
        return {}

    schema, table = scenario.base_layer_source()
    quoted_view = _quote_qualified_table(schema, table)
    placeholders = ", ".join("%s" for _ in feature_ids)

    if include_geometry:
        columns = [
            column
            for column in _fetch_base_columns(scenario.workspace.base_table)[2]
            if column not in ("parcel_id", "geometry")
        ]
        selected = ", ".join(["parcel_id", *columns])
        extra = (
            "ST_AsGeoJSON(geometry) AS geometry_geojson, "
            "ST_Area(geometry::geography) AS area_m2"
        )
    else:
        selected = ", ".join(
            [
                "parcel_id",
                "du",
                "emp",
                "area_gross",
                "area_parcel",
                "built_form_key",
                "land_development_category",
                *(f"emp_{sector}" for sector in EMPLOYMENT_SECTORS),
            ]
        )
        extra = ""

    projected = f"{selected}, {extra}" if extra else selected
    query = (
        f"SELECT {projected} "  # noqa: S608 — quoted_view is a quoted identifier pair
        f"FROM {quoted_view} WHERE CAST(parcel_id AS text) IN ({placeholders})"
    )

    with connection.cursor() as cursor:
        cursor.execute(query, feature_ids)
        col_names = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

    return {
        str(row[0]): {
            column: _json_scalar(value)
            for column, value in zip(col_names, row, strict=True)
        }
        for row in rows
    }


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

        purge_scenario_canvas_tiles(scenario)

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
