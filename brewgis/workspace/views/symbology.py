"""Symbology editor views for BrewGIS.

Provides htmx-based endpoints for editing, previewing, and auto-generating
symbology configurations for layers.
"""

from __future__ import annotations

import json

from django.contrib.auth.decorators import user_passes_test
from django.db import transaction
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils.html import format_html
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from brewgis.workspace.analysis.layer_registry import _get_table_columns
from brewgis.workspace.models import Layer
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import StyleClass
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.palettes import get_all_names
from brewgis.workspace.palettes import preview_swatches
from brewgis.workspace.symbology.auto import auto_generate_symbology
from brewgis.workspace.symbology.generator import generate_maplibre_style
from brewgis.workspace.symbology.legend import generate_legend
from brewgis.workspace.views.panels import is_panel_request

_GEOMETRY_DATA_TYPES = {"geometry", "geography", "USER-DEFINED"}


def _resolve_scenario(layer: Layer, data: dict[str, str]) -> Scenario | None:
    """Resolve the active scenario (if any) from a GET/POST payload.

    Lets symbology auto-generation/preview compute breaks against a
    scenario's painted-aware canvas view instead of the raw base table (see
    ``resolve_symbology_source``). Returns ``None`` if no ``scenario`` value
    is present or it doesn't belong to *layer*'s workspace.
    """
    scenario_id = data.get("scenario")
    if not scenario_id:
        return None
    return Scenario.objects.filter(pk=scenario_id, workspace=layer.workspace).first()


def _advanced_open(post_data: dict[str, str]) -> bool:
    """Read the Advanced section's open/closed state from POST data."""
    return post_data.get("advanced_open") == "1"


def _column_choices(layer: Layer) -> list[str]:
    """Return candidate column names for the "color by" dropdown.

    Always the full set of non-geometry columns, regardless of the
    currently-selected symbology Type — the user picks whichever column
    they want to style by and whichever Type makes sense for it, rather
    than the dropdown pre-filtering columns based on Type.
    """
    schema = layer.db_schema or layer.workspace.db_schema
    columns = _get_table_columns(schema, layer.db_table)
    return [
        c["column_name"] for c in columns if c["data_type"] not in _GEOMETRY_DATA_TYPES
    ]


def _resolve_context_classes(config: SymbologyConfig) -> list[StyleClass]:
    """Return the classes to render for *config*.

    Prefers ``preview_style_classes`` (set by ``auto_generate_symbology``'s
    ``commit=False`` mode) over querying the database, since a preview
    config's saved classes — if any — belong to the pre-preview state.
    """
    preview_classes = getattr(config, "preview_style_classes", None)
    if preview_classes is not None:
        return preview_classes
    return list(config.classes.all().order_by("sort_order")) if config.pk else []


def _build_context(
    layer: Layer,
    config: SymbologyConfig | None = None,
    *,
    advanced_open: bool = False,
    scenario: Scenario | None = None,
) -> dict:
    """Build shared template context for the symbology editor.

    ``advanced_open`` echoes back whether the Advanced section was expanded
    when the request was made (see the panel's ``advanced_open`` hidden
    field) — the server, not client-side DOM state, is the source of truth
    for this so it survives a full panel re-render regardless of swap style.

    ``scenario``, if given, is echoed back into a hidden form field so every
    subsequent htmx request from the panel (preview/auto-generate/save)
    keeps computing breaks against that scenario's painted-aware canvas view.
    """
    if config is None:
        try:
            config = layer.symbology
        except SymbologyConfig.DoesNotExist:
            config = SymbologyConfig(layer=layer)

    # Defensive: normalize in-memory so a palette_name saved with the wrong
    # case (e.g. by an older/external caller) still matches the (lowercase)
    # registry instead of rendering as an unrecognized, unselected palette.
    if config.palette_name:
        config.palette_name = config.palette_name.lower()

    classes = _resolve_context_classes(config)
    swatches = preview_swatches()

    return {
        "layer": layer,
        "config": config,
        "classes": classes,
        "palette_names": get_all_names(),
        "palette_options": sorted(swatches.items()),
        "selected_palette_swatches": swatches.get(config.palette_name, []),
        "palettes_json": swatches,
        "geometry_types": ["fill", "line", "circle"],
        "column_choices": _column_choices(layer),
        "advanced_open": advanced_open,
        "scenario": scenario,
    }


@user_passes_test(lambda u: u.is_authenticated)
@require_http_methods(["GET", "POST"])
def edit_symbology(request: HttpRequest, layer_pk: int) -> HttpResponse:
    """Edit symbology for a layer (GET = form, POST = save)."""
    layer = get_object_or_404(Layer, pk=layer_pk)
    config, _created = SymbologyConfig.objects.get_or_create(layer=layer)

    if request.method == "POST":
        return _save_symbology(request, layer, config)

    scenario = _resolve_scenario(layer, request.GET)
    context = _build_context(layer, config, scenario=scenario)

    if is_panel_request(request):
        return render(request, "workspace/symbology/_editor_panel.html", context)

    return render(request, "workspace/symbology/editor.html", context)


def _apply_form_data(
    config: SymbologyConfig,
    post_data: dict[str, str],
) -> None:
    """Apply POST form data to a SymbologyConfig without saving.

    Shared between ``_save_symbology`` and ``preview_symbology_for_map``
    so both use the same field parsing.
    """
    config.symbology_type = post_data.get("symbology_type", "single")
    config.attribute_column = post_data.get("attribute_column", "")
    config.default_color = post_data.get("default_color", "#888888")
    config.default_opacity = float(post_data.get("default_opacity", "0.7"))
    config.palette_name = post_data.get("palette_name", "").lower()
    config.reverse_palette = post_data.get("reverse_palette") == "on"
    config.num_classes = int(post_data.get("num_classes", "5"))
    config.classification_method = post_data.get("classification_method", "quantile")
    config.null_handling = post_data.get("null_handling", "gray")
    config.null_color = post_data.get("null_color", "")
    config.zero_transparent = post_data.get("zero_transparent") == "on"
    config.auto_generated = False

    stroke_color = post_data.get("stroke_color", "")
    if stroke_color:
        config.stroke_color = stroke_color
    config.stroke_width = float(post_data.get("stroke_width", "1.0"))
    config.line_width = float(post_data.get("line_width", "1.0"))
    config.circle_radius = float(post_data.get("circle_radius", "4.0"))
    config.min_zoom = float(post_data.get("min_zoom", "0.0"))
    config.max_zoom = float(post_data.get("max_zoom", "22.0"))


def _legend_oob_html(
    request: HttpRequest, layer: Layer, config: SymbologyConfig
) -> str:
    """Render out-of-band swaps that refresh this layer's row in the Layers panel.

    The Layers panel's swatch dot and expandable legend are only populated
    when that panel is (re)fetched, so without this, a symbology save leaves
    them showing the pre-edit colors/classes until the panel is closed and
    reopened.
    """
    swatch_color = config.default_color or "#e0e0e0"
    legend_html = render_to_string(
        "workspace/symbology/legend_partial.html",
        {"legend": generate_legend(config)},
        request=request,
    )
    swatch = format_html(
        '<span id="legend-swatch-{}" hx-swap-oob="true" class="legend-swatch-inline" '
        'style="background-color: {}; width: 10px; height: 10px; '
        'display: inline-block; border-radius: 2px; vertical-align: middle"></span>',
        layer.pk,
        swatch_color,
    )
    legend_wrapper = format_html(
        '<div id="legend-{}" hx-swap-oob="true" class="ps-2">{}</div>',
        layer.pk,
        legend_html,
    )
    return swatch + legend_wrapper


def _save_symbology(
    request: HttpRequest,
    layer: Layer,
    config: SymbologyConfig,
) -> HttpResponse:
    """Save symbology config from POST data."""
    _apply_form_data(config, request.POST)
    config.save()

    # Update style classes from POST
    labels = request.POST.getlist("class_label[]")
    colors = request.POST.getlist("class_color[]")
    min_vals = request.POST.getlist("class_min[]")
    max_vals = request.POST.getlist("class_max[]")

    config.classes.all().delete()
    for i, label in enumerate(labels):
        if not label.strip():
            continue
        color = colors[i] if i < len(colors) else config.default_color
        min_v = float(min_vals[i]) if i < len(min_vals) and min_vals[i] else None
        max_v = float(max_vals[i]) if i < len(max_vals) and max_vals[i] else None
        StyleClass.objects.create(
            symbology=config,
            label=label,
            color=color,
            min_value=min_v,
            max_value=max_v,
            sort_order=i,
        )

    if is_panel_request(request):
        # Stay in panel — return updated editor + trigger map refresh
        scenario = _resolve_scenario(layer, request.POST)
        context = _build_context(
            layer,
            config,
            advanced_open=_advanced_open(request.POST),
            scenario=scenario,
        )
        response = render(request, "workspace/symbology/_editor_panel.html", context)
        response.write(_legend_oob_html(request, layer, config))
        style = generate_maplibre_style(config)
        response["HX-Trigger"] = json.dumps(
            {
                "layer-style-changed": {
                    "layerKey": layer.key,
                    "layerPk": layer.pk,
                    "style": style,
                },
                "show-toast": f"Symbology saved for {layer.name}",
            }
        )
        return response

    return HttpResponseRedirect(f"/workspace/{layer.workspace.pk}/map/")


@require_POST
def preview_symbology_for_map(request: HttpRequest, layer_pk: int) -> HttpResponse:
    """Return style preview for live in-map preview."""
    layer = get_object_or_404(Layer, pk=layer_pk)
    config, _created = SymbologyConfig.objects.get_or_create(layer=layer)
    _apply_form_data(config, request.POST)
    style = generate_maplibre_style(config)
    response = HttpResponse()
    response["HX-Trigger"] = json.dumps(
        {
            "layer-style-preview": {
                "layerKey": layer.key,
                "paint": style.get("paint", {}),
                "layerName": layer.name,
            }
        }
    )
    return response


@require_POST
def preview_classify(request: HttpRequest, layer_pk: int) -> HttpResponse:
    """Live-preview a reclassification (new column/palette/class count/method).

    Unlike ``auto_generate``, this never writes to the database — it's what
    the editor panel's Column/Palette/Classes/Classification inputs use so
    the user can see the effect of a change before deciding to Save. The
    computed classes are only persisted if the user then submits the form.
    """
    layer = get_object_or_404(Layer, pk=layer_pk)
    scenario = _resolve_scenario(layer, request.POST)
    attribute_column = request.POST.get("attribute_column") or None
    palette_name = request.POST.get("palette_name") or None
    num_classes = int(request.POST.get("num_classes", "5"))
    classification_method = request.POST.get("classification_method") or None
    reverse_palette = request.POST.get("reverse_palette") == "on"

    try:
        config = auto_generate_symbology(
            layer,
            attribute_column=attribute_column,
            palette_name=palette_name,
            num_classes=num_classes,
            classification_method=classification_method,
            reverse_palette=reverse_palette,
            commit=False,
            scenario=scenario,
        )
    except Exception:
        # Non-fatal — table may not exist or have no data for this column
        config, _created = SymbologyConfig.objects.get_or_create(layer=layer)
        _apply_form_data(config, request.POST)
        config.preview_style_classes = _resolve_context_classes(config)

    context = _build_context(
        layer, config, advanced_open=_advanced_open(request.POST), scenario=scenario
    )
    response = render(request, "workspace/symbology/_editor_panel.html", context)
    classes = _resolve_context_classes(config)
    style = generate_maplibre_style(config, classes=classes)
    response["HX-Trigger"] = json.dumps(
        {
            "layer-style-preview": {
                "layerKey": layer.key,
                "paint": style.get("paint", {}),
                "layerName": layer.name,
            }
        }
    )
    return response


@require_POST
def auto_generate(request: HttpRequest, layer_pk: int) -> HttpResponse:
    """Re-run auto-generation for a layer and redirect to the editor."""
    layer = get_object_or_404(Layer, pk=layer_pk)
    scenario = _resolve_scenario(layer, request.POST)
    attribute_column = request.POST.get("attribute_column") or None
    palette_name = request.POST.get("palette_name") or None
    num_classes = int(request.POST.get("num_classes", "5"))
    classification_method = request.POST.get("classification_method") or None
    reverse_palette = request.POST.get("reverse_palette") == "on"

    try:
        with transaction.atomic():
            auto_generate_symbology(
                layer,
                attribute_column=attribute_column,
                palette_name=palette_name,
                num_classes=num_classes,
                classification_method=classification_method,
                reverse_palette=reverse_palette,
                scenario=scenario,
            )
    except Exception:
        # Non-fatal - table may not exist or have no data
        pass

    if is_panel_request(request):
        # Stay in panel — return updated editor + trigger map refresh
        try:
            config = layer.symbology
        except SymbologyConfig.DoesNotExist:
            config = SymbologyConfig(layer=layer)
        context = _build_context(
            layer, config, advanced_open=_advanced_open(request.POST), scenario=scenario
        )
        response = render(request, "workspace/symbology/_editor_panel.html", context)
        response.write(_legend_oob_html(request, layer, config))
        style = generate_maplibre_style(config)
        response["HX-Trigger"] = json.dumps(
            {
                "layer-style-changed": {
                    "layerKey": layer.key,
                    "layerPk": layer.pk,
                    "style": style,
                },
                "show-toast": f"Symbology auto-generated for {layer.name}",
            }
        )
        return response

    return HttpResponseRedirect(f"/symbology/{layer.pk}/edit/")


@require_GET
def preview_symbology(request: HttpRequest, layer_pk: int) -> JsonResponse:
    """Return generated MapLibre style JSON for a layer's symbology."""
    layer = get_object_or_404(Layer, pk=layer_pk)
    try:
        config = layer.symbology
    except SymbologyConfig.DoesNotExist:
        return JsonResponse({"paint": {}, "layout": {}})

    style = generate_maplibre_style(config)
    return JsonResponse(style)


@require_GET
@user_passes_test(lambda u: u.is_authenticated)
def layer_legend(request: HttpRequest, layer_pk: int) -> HttpResponse:
    """Return legend HTML partial for a layer's symbology."""
    config = get_object_or_404(SymbologyConfig, layer__pk=layer_pk)
    legend = generate_legend(config)
    return render(
        request, "workspace/symbology/legend_partial.html", {"legend": legend}
    )
