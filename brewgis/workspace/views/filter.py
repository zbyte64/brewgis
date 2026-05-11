"""Filter views for BrewGIS — expression-tree filter CRUD via htmx."""

from __future__ import annotations

import json
from typing import Any

from django.contrib.auth.decorators import user_passes_test
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from brewgis.workspace.models import Layer, LayerFilter


def _filter_list_context(layer: Layer) -> dict[str, Any]:
    """Build shared context for filter list partial."""
    return {
        "layer": layer,
        "filters": layer.filters.all(),
    }


def _active_filters_for_layer(layer: Layer) -> list[LayerFilter]:
    """Return active filters for a layer."""
    return list(layer.filters.filter(is_active=True))


@user_passes_test(lambda u: u.is_authenticated)
@require_GET
def layer_filter_list(request: HttpRequest, layer_pk: int) -> HttpResponse:
    """Return filter list partial for a layer."""
    layer = get_object_or_404(Layer, pk=layer_pk)
    context = _filter_list_context(layer)
    return render(request, "workspace/filter/list.html", context)


@user_passes_test(lambda u: u.is_authenticated)
@require_http_methods(["GET", "POST"])
def layer_filter_create(request: HttpRequest, layer_pk: int) -> HttpResponse:
    """Create a new filter for a layer (GET=form, POST=create)."""
    layer = get_object_or_404(Layer, pk=layer_pk)
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            return render(
                request,
                "workspace/filter/editor.html",
                {"layer": layer, "error": "Filter name is required."},
            )
        raw_json = request.POST.get("filter_json", "{}")
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as e:
            return render(
                request,
                "workspace/filter/editor.html",
                {"layer": layer, "filter": None, "error": f"Invalid filter JSON: {e}"},
            )
        flt = LayerFilter.objects.create(
            layer=layer,
            name=name,
            filter_json=parsed,
        )
        # Render the list partial with the new filter included
        context = _filter_list_context(layer)
        return render(request, "workspace/filter/list.html", context)
    # GET — return empty editor
    return render(
        request,
        "workspace/filter/editor.html",
        {"layer": layer, "filter": None},
    )


@user_passes_test(lambda u: u.is_authenticated)
@require_http_methods(["GET", "POST"])
def layer_filter_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Edit an existing filter (GET=form, POST=update)."""
    flt = get_object_or_404(LayerFilter, pk=pk)
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            return render(
                request,
                "workspace/filter/editor.html",
                {
                    "layer": flt.layer,
                    "filter": flt,
                    "error": "Filter name is required.",
                },
            )
        raw_json = request.POST.get("filter_json", "{}")
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as e:
            return render(
                request,
                "workspace/filter/editor.html",
                {
                    "layer": flt.layer,
                    "filter": flt,
                    "error": f"Invalid filter JSON: {e}",
                },
            )
        flt.name = name
        flt.filter_json = parsed
        flt.save()
        context = _filter_list_context(flt.layer)
        return render(request, "workspace/filter/list.html", context)
    # GET — return editor with existing data
    return render(
        request,
        "workspace/filter/editor.html",
        {"layer": flt.layer, "filter": flt},
    )


@require_POST
@user_passes_test(lambda u: u.is_authenticated)
def layer_filter_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Delete a filter and return the list partial."""
    flt = get_object_or_404(LayerFilter, pk=pk)
    layer = flt.layer
    flt.delete()
    context = _filter_list_context(layer)
    return render(request, "workspace/filter/list.html", context)


@require_POST
@user_passes_test(lambda u: u.is_authenticated)
def layer_filter_toggle(request: HttpRequest, pk: int) -> HttpResponse:
    """Toggle the active state of a filter."""
    flt = get_object_or_404(LayerFilter, pk=pk)
    flt.is_active = not flt.is_active
    flt.save()
    context = _filter_list_context(flt.layer)
    return render(request, "workspace/filter/list.html", context)


@user_passes_test(lambda u: u.is_authenticated)
@require_GET
def layer_filter_preview(request: HttpRequest, pk: int) -> JsonResponse:
    """Return a JSON preview of how many features this filter matches.

    For now, returns the filter expression for client-side evaluation.
    Server-side count queries can be added when a specific source table
    is linked to the layer.
    """
    flt = get_object_or_404(LayerFilter, pk=pk)
    return JsonResponse(
        {
            "id": flt.pk,
            "name": flt.name,
            "is_active": flt.is_active,
            "filter_json": flt.filter_json,
            "expression": _human_readable_expression(flt.filter_json),
        }
    )


def _human_readable_expression(filter_json: dict) -> str:
    """Convert a filter expression tree to a human-readable string."""
    if not filter_json or not isinstance(filter_json, dict):
        return "(empty filter)"
    filter_type = filter_json.get("type", "")
    if filter_type == "group":
        operator = filter_json.get("operator", "AND")
        children = filter_json.get("children", [])
        parts = [_human_readable_expression(c) for c in children if c]
        if not parts:
            return "(empty group)"
        return f"({f' {operator} '.join(parts)})"
    if filter_type == "column":
        field = filter_json.get("field", "?")
        op = filter_json.get("operator", "?")
        value = filter_json.get("value", "")
        op_display = {
            "eq": "=",
            "neq": "!=",
            "gt": ">",
            "gte": ">=",
            "lt": "<",
            "lte": "<=",
            "contains": "contains",
            "is_null": "is null",
            "is_not_null": "is not null",
        }
        display_op = op_display.get(op, op)
        if op in ("is_null", "is_not_null"):
            return f"{field} {display_op}"
        return f"{field} {display_op} {value}"
    if filter_type == "geometry":
        geo_type = filter_json.get("geometry_type", "?")
        return f"[geometry: {geo_type}]"
    if filter_type == "join":
        join_layer = filter_json.get("join_layer", "?")
        return f"[join: {join_layer}]"
    return f"[{filter_type}]"
