"""Panel-aware view wrappers for the map-centric shell.

These views return partial HTML suitable for injecting into
the right panel, bottom sheet, or left sidebar of the
WYSIWYG map shell. They delegate to existing views and
force ``panel=1`` rendering.
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING

from django.contrib.auth.decorators import user_passes_test
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

from brewgis.workspace.models import Basemap
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import ScenarioReport
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema
from brewgis.workspace.services.canvas_view_manager import build_paintable_column_meta
from brewgis.workspace.services.filter_compiler import FilterCompiler
from brewgis.workspace.views.basemaps import _get_selected_basemap_id
from brewgis.workspace.views.workspace_detail import build_catalog_context

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http import HttpResponse

_NON_DISPLAY_PROPERTIES = frozenset({"geometry", "uf_is_painted"})


def is_panel_request(request: HttpRequest) -> bool:
    """Detect whether the request is for a panel fragment.

    Returns ``True`` when the request came from htmx (``HX-Request`` header)
    or carries the ``?panel=1`` query parameter.
    """
    return (
        request.GET.get("panel") == "1" or request.headers.get("HX-Request") == "true"
    )


# ---------------------------------------------------------------------------
# Left-sidebar panel endpoints
# ---------------------------------------------------------------------------


@user_passes_test(lambda u: u.is_authenticated)
def panel_layer_list(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Return the layer list panel content for the left sidebar."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)

    # Check for active scenario (passed via query param when on workspace map)
    scenario: Scenario | None = None
    scenario_id = request.GET.get("scenario")
    if scenario_id:
        scenario = get_object_or_404(Scenario, pk=int(scenario_id), workspace=workspace)

    context: dict[str, object] = {
        "workspace": workspace,
        "scenario": scenario,
        "is_public_view": False,
    }

    # Pre-fetch symbology configs for inline legend swatches
    layer_configs: dict[int, SymbologyConfig] = {}
    for layer in workspace.layers.all():
        with contextlib.suppress(SymbologyConfig.DoesNotExist):
            layer_configs[layer.pk] = layer.symbology
    context["layer_configs"] = layer_configs

    # Pre-compute swatch colors for quick rendering (avoid template ORM access)
    swatch_colors: dict[int, str] = {}
    for layer in workspace.layers.all():
        cfg = layer_configs.get(layer.pk)
        if cfg:
            swatch_colors[layer.pk] = cfg.default_color or "#e0e0e0"
        else:
            swatch_colors[layer.pk] = "#e0e0e0"
    context["swatch_colors"] = swatch_colors

    # Pre-compute active filter expressions for map auto-apply
    active_maplibre_filters: dict[str, list | None] = {}
    for layer in workspace.layers.all():
        active_filters = layer.filters.filter(is_active=True)
        if active_filters:
            compiler = FilterCompiler()
            combined = {
                "type": "group",
                "operator": "AND",
                "children": [f.filter_json for f in active_filters],
            }
            active_maplibre_filters[layer.db_table] = compiler.compile_to_maplibre(
                combined
            )
        else:
            active_maplibre_filters[layer.db_table] = None
    context["active_maplibre_filters"] = active_maplibre_filters
    return render(
        request,
        "workspace/partials/_layer_list_panel.html",
        context,
    )


@user_passes_test(lambda u: u.is_authenticated)
def panel_data_catalog(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Return data catalog content for the left sidebar.

    Uses the same curated DataSourceCategory/DataSource catalog as the
    workspace hub page's Data Catalog card, via the shared
    ``build_catalog_context`` helper, so the two surfaces stay consistent.
    """
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    context = build_catalog_context(workspace)
    context["in_map_panel"] = True
    return render(
        request,
        "workspace/partials/_catalog_panel.html",
        context,
    )


@user_passes_test(lambda u: u.is_authenticated)
def panel_import_center(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Return import center content for the left sidebar."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    context: dict[str, object] = {
        "workspace": workspace,
    }
    return render(
        request,
        "workspace/partials/_import_panel.html",
        context,
    )


@user_passes_test(lambda u: u.is_authenticated)
def panel_analysis_launch(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Return analysis launch content for the left sidebar."""
    from brewgis.workspace.views.analysis import AnalysisLaunchView

    view = AnalysisLaunchView.as_view()
    return view(request, workspace_pk=workspace_pk)


@user_passes_test(lambda u: u.is_authenticated)
def panel_basemap_picker(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Return the basemap picker content for the left sidebar."""
    get_object_or_404(Workspace, pk=workspace_pk)
    basemaps = Basemap.objects.all().order_by("sort_order")
    context: dict[str, object] = {
        "basemaps": basemaps,
        "workspace_pk": workspace_pk,
        "selected_basemap_id": _get_selected_basemap_id(request, workspace_pk),
    }
    return render(
        request,
        "workspace/partials/_basemap_picker.html",
        context,
    )


@user_passes_test(lambda u: u.is_authenticated)
def panel_report_list(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Return report list content for the left sidebar."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    reports = ScenarioReport.objects.filter(workspace=workspace)
    context: dict[str, object] = {
        "workspace": workspace,
        "reports": reports,
    }
    return render(
        request,
        "workspace/partials/_report_list_panel.html",
        context,
    )


@user_passes_test(lambda u: u.is_authenticated)
@require_POST
def panel_feature_inspect(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Return the feature-inspect panel for a clicked map feature.

    Accepts a JSON body of ``{"feature_id": ..., "properties": {...}}`` —
    the properties come straight from the already-decoded vector tile
    (``queryRenderedFeatures``), since the canvas view's own ``SELECT``
    already exposes every base + painted column, so no extra DB round trip
    is needed just to display them. Editing is only offered when a
    scenario is active, since that's the only context with a non-destructive
    write path (:func:`brewgis.workspace.views.paint.paint_features`) —
    there is nowhere to write an edit against the raw, immutable base table.
    """
    workspace = get_object_or_404(Workspace, pk=workspace_pk)

    scenario: Scenario | None = None
    scenario_pk = request.GET.get("scenario")
    if scenario_pk:
        scenario = get_object_or_404(Scenario, pk=scenario_pk, workspace=workspace)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON body."}, status=400
        )

    feature_id = body.get("feature_id")
    properties: dict[str, object] = body.get("properties") or {}
    if not feature_id:
        return JsonResponse(
            {"status": "error", "message": "feature_id is required."}, status=400
        )

    paintable_labels = {c["name"]: c["label"] for c in build_paintable_column_meta()}
    column_order = list(BaseCanvasSchema.COLUMN_NAMES)

    def _sort_key(name: str) -> tuple[int, str]:
        try:
            return (column_order.index(name), name)
        except ValueError:
            return (len(column_order), name)

    editable_rows: list[dict[str, object]] = []
    static_rows: list[dict[str, object]] = []
    for name in sorted(
        (k for k in properties if k not in _NON_DISPLAY_PROPERTIES), key=_sort_key
    ):
        value = properties[name]
        if name in paintable_labels:
            editable_rows.append(
                {"name": name, "label": paintable_labels[name], "value": value}
            )
        else:
            col_def = BaseCanvasSchema.get(name)
            static_rows.append(
                {
                    "name": name,
                    "label": col_def.label if col_def else name,
                    "value": value,
                }
            )

    context: dict[str, object] = {
        "workspace_pk": workspace_pk,
        "feature_id": feature_id,
        "editable_rows": editable_rows,
        "static_rows": static_rows,
        "editable": scenario is not None,
        "is_painted": bool(properties.get("uf_is_painted")),
    }
    if scenario is not None:
        context["paint_url"] = reverse(
            "workspace:paint_features", args=[workspace_pk, scenario.pk]
        )

    return render(
        request,
        "workspace/partials/_feature_inspect_panel.html",
        context,
    )
