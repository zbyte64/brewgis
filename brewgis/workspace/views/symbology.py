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
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from brewgis.workspace.models import Layer
from brewgis.workspace.models import StyleClass
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.palettes import PALETTES
from brewgis.workspace.palettes import get_all_names
from brewgis.workspace.symbology.auto import auto_generate_symbology
from brewgis.workspace.symbology.generator import generate_maplibre_style
from brewgis.workspace.symbology.legend import generate_legend
from brewgis.workspace.views.panels import is_panel_request


def _build_context(
    layer: Layer,
    config: SymbologyConfig | None = None,
) -> dict:
    """Build shared template context for the symbology editor."""
    if config is None:
        try:
            config = layer.symbology
        except SymbologyConfig.DoesNotExist:
            config = SymbologyConfig(layer=layer)

    classes = list(config.classes.all().order_by("sort_order")) if config.pk else []

    return {
        "layer": layer,
        "config": config,
        "classes": classes,
        "palette_names": get_all_names(),
        "palettes_json": json.dumps(PALETTES),
        "geometry_types": ["fill", "line", "circle"],
    }


@user_passes_test(lambda u: u.is_authenticated)
@require_http_methods(["GET", "POST"])
def edit_symbology(request: HttpRequest, layer_pk: int) -> HttpResponse:
    """Edit symbology for a layer (GET = form, POST = save)."""
    layer = get_object_or_404(Layer, pk=layer_pk)
    config, _created = SymbologyConfig.objects.get_or_create(layer=layer)

    if request.method == "POST":
        return _save_symbology(request, layer, config)

    context = _build_context(layer, config)

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
    config.palette_name = post_data.get("palette_name", "")
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
        context = _build_context(layer, config)
        response = render(request, "workspace/symbology/_editor_panel.html", context)
        style = generate_maplibre_style(config)
        response["HX-Trigger"] = json.dumps(
            {
                "layer-style-changed": {
                    "layerKey": layer.table_name,
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
                "layerKey": layer.table_name,
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
    attribute_column = request.POST.get("attribute_column") or None
    palette_name = request.POST.get("palette_name") or None
    num_classes = int(request.POST.get("num_classes", "5"))
    classification_method = request.POST.get("classification_method") or None

    try:
        with transaction.atomic():
            auto_generate_symbology(
                layer,
                attribute_column=attribute_column,
                palette_name=palette_name,
                num_classes=num_classes,
                classification_method=classification_method,
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
        context = _build_context(layer, config)
        response = render(request, "workspace/symbology/_editor_panel.html", context)
        style = generate_maplibre_style(config)
        response["HX-Trigger"] = json.dumps(
            {
                "layer-style-changed": {
                    "layerKey": layer.table_name,
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
